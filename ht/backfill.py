#!/usr/bin/env python3
"""
Backfill de l'archive de snapshots d'ordres HyperTracker (2026-01-19 -> 2026-03-12).

Propriétés :
  - grille = fonction pure de (borne, fin) : une panne de N heures ne crée pas de trou,
    elle laisse N*12 créneaux `pending` que le tick suivant draine.
  - reprise : tout l'état vit dans un ledger SQLite ; relancer le process reprend où il s'est arrêté.
  - déduplication : clé d'idempotence = le créneau ; le sha256 du corps LZ4 est enregistré et
    un même sha sur deux créneaux différents est signalé (service figé).
  - intégrité : le JSON doit parser, le nombre d'ordres doit dépasser un plancher, et
    `snapshotTime` du premier ordre doit correspondre au créneau demandé.
  - sans perte : tous les actifs, tous les champs. Parquet trié + zstd-19.
  - budget : le débit s'adapte au 429 observé (retry_after), le tier n'a pas besoin d'être connu.
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, hashlib, threading, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

import lz4.frame
import pyarrow as pa
import pyarrow.parquet as pq

API = "https://ht-api.coinmarketman.com"
FLOOR = datetime(2026, 1, 19, 11, 5, tzinfo=timezone.utc)
CEIL = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)      # premier créneau absent, mesuré
STEP = timedelta(minutes=5)
MIN_ORDERS = 50_000                                           # plancher d'intégrité

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
PARQ = os.path.join(DATA, "orders_5m")
LEDGER = os.path.join(DATA, "ledger.db")
WORKERS = int(os.environ.get("HT_WORKERS", "3"))

def _token() -> str:
    """Lu à l'usage, pas à l'import : le module doit rester importable et testable
    sans secret, et une rotation du jeton doit pouvoir être reprise sans redémarrer."""
    t = os.environ.get("HYPERTRACKER_API_TOKEN") or os.environ.get("HT_TOKEN")
    if not t:
        raise RuntimeError("HYPERTRACKER_API_TOKEN is missing.")
    return t

_lock = threading.Lock()
_pace = {"delay": 0.0, "429": 0, "calls": 0}


# --------------------------------------------------------------------------- ledger
def db():
    c = sqlite3.connect(LEDGER, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=FULL")
    return c


def init():
    os.makedirs(PARQ, exist_ok=True)
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS slots(
            slot TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER DEFAULT 0,
            sha256 TEXT, orders INTEGER, lz4_bytes INTEGER, parquet_bytes INTEGER,
            path TEXT, ingest_time TEXT, knowable_at TEXT, error TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_state ON slots(state)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_sha ON slots(sha256)")
        # matérialisation de la grille : idempotent, rejouable
        t, rows = FLOOR, []
        while t < CEIL:
            rows.append((t.strftime("%Y-%m-%dT%H:%M:%S+00:00"),))
            t += STEP
        c.executemany("INSERT OR IGNORE INTO slots(slot,state) VALUES(?, 'pending')", rows)
    return len(rows)


# --------------------------------------------------------------------------- http
def _req(url, auth):
    h = {"accept": "application/json"}
    if auth:
        h["Authorization"] = f"Bearer {_token()}"
    return urllib.request.Request(url, headers=h)


def fetch(url, auth=False, timeout=300):
    """Retourne (status, bytes, retry_after)."""
    try:
        with urllib.request.urlopen(_req(url, auth), timeout=timeout) as r:
            return r.status, r.read(), None
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        ra = e.headers.get("retry-after") if e.headers else None
        return e.code, body, ra
    except Exception as e:
        return 0, str(e).encode(), None


class QuotaExhausted(Exception):
    """Quota JOURNALIER atteint : aucun réessai ne peut aboutir avant demain."""


MAX_429_RETRIES = 5


def paced(url, auth):
    """
    Appel API respectant le rythme observé.

    Deux 429 très différents, qu'il faut distinguer sous peine de boucler à l'infini :
      - débit dépassé (req/min)  -> attendre `retry_after` et réessayer, borné.
      - quota JOURNALIER épuisé  -> le corps porte {"limit":N,"current":N,"plan":"FREE"} :
        aucun réessai ne peut aboutir aujourd'hui. On lève QuotaExhausted, qui arrête
        proprement tout le run. Le ledger garantit la reprise exacte demain.
    """
    for attempt in range(MAX_429_RETRIES):
        with _lock:
            d = _pace["delay"]
            _pace["calls"] += 1
        if d:
            time.sleep(d)
        st, body, ra = fetch(url, auth)
        if st == 429:
            info = {}
            try:
                info = json.loads(body)
            except Exception:
                pass
            msg = str(info.get("message", ""))
            daily = ("daily limit" in msg.lower()) or (
                isinstance(info.get("limit"), int)
                and info.get("current") is not None
                and int(info["current"]) >= int(info["limit"])
            )
            if daily:
                raise QuotaExhausted(
                    f"quota journalier atteint: {info.get('current')}/{info.get('limit')} "
                    f"(plan {info.get('plan')})"
                )
            wait = 2.0
            try:
                wait = float(ra) if ra else float(info.get("retry_after", 2))
            except Exception:
                pass
            with _lock:
                _pace["429"] += 1
                _pace["delay"] = min(5.0, max(_pace["delay"] * 1.5, 0.25))
            time.sleep(min(60.0, wait))
            continue
        # décroissance lente du délai quand ça passe
        if st == 200:
            with _lock:
                if _pace["delay"] > 0:
                    _pace["delay"] = max(0.0, _pace["delay"] - 0.01)
        return st, body
    # 429 de débit répétés sans jamais aboutir : on rend la main, le créneau reste dû.
    return 429, b'{"message":"rate limited after retries"}'


# --------------------------------------------------------------------------- traitement
KEYS_CONST = ()  # aucun champ n'est supprimé : conservation intégrale


def to_parquet(orders, path):
    keys, cols = list(orders[0].keys()), {}
    for k in keys:
        col = []
        for o in orders:
            v = o.get(k)
            col.append(json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v)
        try:
            cols[k] = pa.array(col)
        except Exception:
            cols[k] = pa.array([None if x is None else str(x) for x in col])
    t = pa.table([cols[k] for k in keys], names=keys)
    # le tri (coin, address, limitPx) améliore le dictionnaire : 2,71x mesuré
    t = t.sort_by([("coin", "ascending"), ("address", "ascending"), ("limitPx", "ascending")])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    pq.write_table(t, tmp, compression="zstd", compression_level=19, use_dictionary=True)
    os.replace(tmp, path)          # atomique sur NTFS
    return os.path.getsize(path)


def do_slot(slot: str):
    ingest = datetime.now(timezone.utc).isoformat()
    try:
        st, body = paced(f"{API}/api/external/orders/5m-snapshots/{urllib.parse.quote(slot, safe='')}/download", True)
    except QuotaExhausted as e:
        # Le créneau reste `pending` : rien n'est consommé, rien n'est perdu.
        return slot, "__quota__", None, str(e)
    if st != 200:
        msg = body[:200].decode("utf8", "replace")
        state = "absent" if st == 404 else "deferred"
        return slot, state, None, f"HTTP {st}: {msg}"
    try:
        url = json.loads(body)["downloadUrl"]
    except Exception as e:
        return slot, "deferred", None, f"URL introuvable: {e}"

    st2, comp, _ = fetch(url, auth=False)          # S3 : hors quota API
    if st2 != 200 or not comp:
        return slot, "deferred", None, f"S3 HTTP {st2}"

    sha = hashlib.sha256(comp).hexdigest()
    try:
        raw = lz4.frame.decompress(comp)
        orders = json.loads(raw)
    except Exception as e:
        return slot, "quarantine", None, f"decompression/parse: {e}"

    if not isinstance(orders, list) or len(orders) < MIN_ORDERS:
        return slot, "quarantine", None, f"plancher d'integrite: {len(orders) if isinstance(orders,list) else 'non-liste'} ordres"

    # cohérence du créneau : snapshotTime doit correspondre à ce qu'on a demandé
    want = int(datetime.fromisoformat(slot).timestamp() * 1000)
    got = orders[0].get("snapshotTime")
    if got is not None and abs(int(got) - want) > 300_000:
        return slot, "quarantine", None, f"creneau incoherent: demande {want}, recu {got}"

    d = datetime.fromisoformat(slot)
    path = os.path.join(PARQ, f"dt={d:%Y-%m-%d}", f"snapshot-{d:%H%M}.parquet")
    psize = to_parquet(orders, path)

    meta = {"sha256": sha, "orders": len(orders), "lz4": len(comp), "parquet": psize,
            "path": path, "ingest": ingest,
            # knowable_at : le fait était obtenable au plus tôt au créneau lui-même ;
            # la latence réelle de publication n'est mesurable que sur le flux courant.
            "knowable": slot}
    return slot, "done", meta, None


def record(slot, state, meta, err):
    with _lock, db() as c:
        if meta:
            dup = c.execute("SELECT slot FROM slots WHERE sha256=? AND slot<>?", (meta["sha256"], slot)).fetchone()
            if dup:
                err = f"sha identique au creneau {dup[0]} (service fige ?)"
                state = "quarantine"
        c.execute("""UPDATE slots SET state=?, attempts=attempts+1, sha256=?, orders=?, lz4_bytes=?,
                     parquet_bytes=?, path=?, ingest_time=?, knowable_at=?, error=?  WHERE slot=?""",
                  (state, meta and meta["sha256"], meta and meta["orders"], meta and meta["lz4"],
                   meta and meta["parquet"], meta and meta["path"], meta and meta["ingest"],
                   meta and meta["knowable"], err, slot))


def pending(limit=400):
    """
    Creneaux a traiter, PRIORITAIRES d'abord.

    La table `slots_prioritaires` sert a rendre un sous-ensemble contigu utile avant
    le reste. Un creneau isole ne debloque rien ; c'est la CONTIGUITE qui compte —
    quarante points d'affilee autorisent un walk-forward, quarante points disperses
    n'autorisent rien. L'ordre par defaut, purement chronologique, ne connait pas
    cette contrainte.
    """
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS slots_prioritaires(
            slot TEXT PRIMARY KEY, motif TEXT, ajoute_le TEXT)""")
        pri = [r[0] for r in c.execute(
            "SELECT s.slot FROM slots s JOIN slots_prioritaires p ON p.slot = s.slot "
            "WHERE s.state IN ('pending','deferred') AND s.attempts < 6 "
            "ORDER BY s.slot LIMIT ?", (limit,)).fetchall()]
        if len(pri) >= limit:
            return pri
        reste = [r[0] for r in c.execute(
            "SELECT s.slot FROM slots s "
            "LEFT JOIN slots_prioritaires p ON p.slot = s.slot "
            "WHERE p.slot IS NULL AND s.state IN ('pending','deferred') "
            "AND s.attempts < 6 ORDER BY s.slot LIMIT ?", (limit - len(pri),)).fetchall()]
        return pri + reste


def stats():
    with db() as c:
        s = dict(c.execute("SELECT state, COUNT(*) FROM slots GROUP BY state").fetchall())
        agg = c.execute("SELECT COUNT(*), SUM(parquet_bytes), SUM(orders) FROM slots WHERE state='done'").fetchone()
    return s, agg


def main():
    total = init()
    t0 = time.time()
    print(f"grille: {total} creneaux | data={DATA} | workers={WORKERS}", flush=True)
    done_now = 0
    while True:
        batch = pending()
        if not batch:
            break
        quota_hit = None
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for slot, state, meta, err in ex.map(do_slot, batch):
                if state == "__quota__":
                    # STOP propre et définitif pour la journée : le créneau reste `pending`,
                    # aucun état n'est écrit, la reprise de demain est exacte.
                    quota_hit = err
                    continue
                record(slot, state, meta, err)
                if state == "done":
                    done_now += 1
                if done_now and done_now % 25 == 0:
                    s, agg = stats()
                    el = time.time() - t0
                    gb = (agg[1] or 0) / 1e9
                    rate = done_now / el * 3600
                    left = (s.get("pending", 0) + s.get("deferred", 0))
                    print(f"[{el/60:6.1f} min] done={s.get('done',0)} pending={left} "
                          f"quarantine={s.get('quarantine',0)} absent={s.get('absent',0)} | "
                          f"{gb:.2f} Go | {rate:.0f}/h | eta {left/max(rate,1):.1f} h | "
                          f"429={_pace['429']} delay={_pace['delay']:.2f}s", flush=True)
        if quota_hit:
            s, agg = stats()
            print(f"ARRET QUOTA: {quota_hit}", flush=True)
            print(f"etat conserve: {json.dumps(s)} | {agg[0]} snapshots | {(agg[1] or 0)/1e9:.2f} Go", flush=True)
            print("reprise exacte au prochain lancement (rien n'est perdu).", flush=True)
            return 3
    s, agg = stats()
    print(f"FIN: {json.dumps(s)} | {agg[0]} snapshots | {(agg[1] or 0)/1e9:.2f} Go | {agg[2] or 0:,} ordres", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
