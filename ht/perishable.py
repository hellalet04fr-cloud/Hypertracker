#!/usr/bin/env python3
"""
Capture des surfaces NON RATTRAPABLES : aucun parametre as-of, aucun endpoint historique.
Ce qui n'est pas capture maintenant est perdu definitivement.

  - leaderboards (all-pnl, perp-pnl) sur les 4 rankBy : classement du jour, non reconstituable
  - /segments : appartenance aux 16 cohortes, recalculee toutes les 3-4 h en amont
  - /wallets : borne par HT_WALLET_CAP. Le balayage complet (296 781 wallets = 594 requetes,
    soit 5,9 jours de quota FREE) est deliberement exclu : les leaderboards donnent
    directement le haut du panier.

Bitemporalite : chaque ligne porte observed_at (instant de capture, horodate cote client).
L'appartenance aux cohortes est FIGEE a la capture — la relire plus tard donnerait une
appartenance retro-attribuee, donc une fuite.

Budget : l'API n'envoie AUCUN en-tete X-RateLimit-* (verifie sur reponse 200). Le compteur
local est donc la seule mesure du reliquat, et HT_BUDGET le plafond dur.
"""
from __future__ import annotations
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

API = "https://ht-api.coinmarketman.com"
DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")

calls = 0
BUDGET = int(os.environ.get("HT_BUDGET", "100"))


class QuotaExhausted(Exception):
    """Quota JOURNALIER atteint : aucun reessai ne peut aboutir avant le reset."""


class BudgetDepasse(Exception):
    """Plafond local atteint : on s'arrete AVANT de depenser plus que prevu."""


def _token() -> str:
    """Lu a l'usage, pas a l'import : le module reste importable et testable sans secret."""
    t = os.environ.get("HYPERTRACKER_API_TOKEN") or os.environ.get("HT_TOKEN")
    if not t:
        raise RuntimeError("HYPERTRACKER_API_TOKEN is missing.")
    return t


def get(path, retries=4):
    """
    Un 429 de DEBIT se reessaie ; un 429 de QUOTA JOURNALIER ne se reessaie JAMAIS —
    sinon chaque endpoint brule `retries` requetes pour rien, soit jusqu'a 40 requetes
    perdues sur une campagne de 10 endpoints.
    """
    global calls
    if calls >= BUDGET:
        raise BudgetDepasse(f"plafond local atteint: {calls}/{BUDGET}")
    for a in range(retries):
        req = urllib.request.Request(
            API + path,
            headers={"Authorization": f"Bearer {_token()}", "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                calls += 1
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                calls += 1
                info = {}
                try:
                    info = json.loads(e.read())
                except Exception:
                    pass
                msg = str(info.get("message", "")).lower()
                daily = "daily limit" in msg or (
                    isinstance(info.get("limit"), int)
                    and info.get("current") is not None
                    and int(info["current"]) >= int(info["limit"])
                )
                if daily:
                    raise QuotaExhausted(
                        f"quota journalier atteint: {info.get('current')}/{info.get('limit')} "
                        f"(plan {info.get('plan')})"
                    ) from None
                ra = e.headers.get("retry-after") if e.headers else None
                time.sleep(min(60, float(ra) if ra else 2 ** a))
                continue
            if 500 <= e.code < 600:
                time.sleep(2 ** a)
                continue
            raise
        except (QuotaExhausted, BudgetDepasse):
            raise
        except Exception:
            time.sleep(2 ** a)
    raise RuntimeError(f"echec apres {retries} tentatives: {path}")


def flat(o, obs, prefix=""):
    """Aplatit un enregistrement en gardant TOUS les champs (imbriques serialises)."""
    row = {}
    for k, v in o.items():
        row[prefix + k] = json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v
    row["observed_at"] = obs
    return row


def write(rows, name, obs):
    if not rows:
        return 0
    keys = sorted({k for r in rows for k in r})
    try:
        cols = {k: pa.array([r.get(k) for r in rows]) for k in keys}
        t = pa.table([cols[k] for k in keys], names=keys)
    except Exception:
        cols = {k: pa.array([None if r.get(k) is None else str(r.get(k)) for r in rows]) for k in keys}
        t = pa.table([cols[k] for k in keys], names=keys)
    d = os.path.join(DATA, name, f"dt={obs[:10]}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{obs[11:19].replace(':', '')}.parquet")
    tmp = p + ".part"
    pq.write_table(t, tmp, compression="zstd", compression_level=19, use_dictionary=True)
    os.replace(tmp, p)
    return os.path.getsize(p)


def unwrap(j):
    """L'API n'a pas d'enveloppe coherente : tableau nu, {status,data} ou {totalCount,items}."""
    if isinstance(j, list):
        return j, None
    if isinstance(j, dict):
        for k in ("items", "data", "results"):
            if isinstance(j.get(k), list):
                return j[k], j.get("totalCount")
    return [], None


def sweep_wallets(obs, page=500, cap=None):
    rows, off, total = [], 0, None
    while True:
        j = get(f"/api/external/wallets?limit={page}&offset={off}")
        items, tc = unwrap(j)
        if tc is not None:
            total = tc
        if not items:
            break
        rows.extend(flat(o, obs) for o in items)
        off += len(items)
        if total and off >= total:
            break
        if cap and off >= cap:
            break
        if len(items) < page:
            break
    return rows, total


def main():
    obs = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cap = int(os.environ.get("HT_WALLET_CAP", "500")) or None
    out = {}
    arret = None                      # renseigne des qu'un quota/budget stoppe la campagne

    # 1. leaderboards — la surface la plus irremplacable
    for ep in ("all-pnl", "perp-pnl"):
        if arret:
            break
        for rank in ("pnlDay", "pnlWeek", "pnlMonth", "pnlAllTime"):
            try:
                j = get(f"/api/external/leaderboards/{ep}?limit=100"
                        f"&rankBy={rank}&orderBy={rank}&order=desc")
                items, _ = unwrap(j)
                rows = [dict(flat(o, obs), _endpoint=ep, _rankBy=rank, _rank=i + 1)
                        for i, o in enumerate(items)]
                out[f"leaderboard/{ep}/{rank}"] = (len(rows),
                                                   write(rows, f"leaderboards_{ep}_{rank}", obs))
            except (QuotaExhausted, BudgetDepasse) as e:
                arret = str(e)
                out[f"leaderboard/{ep}/{rank}"] = ("ARRET", arret[:90])
                break
            except Exception as e:
                out[f"leaderboard/{ep}/{rank}"] = ("ERREUR", str(e)[:80])

    # 2. cohortes — appartenance figee a l'instant de capture
    if not arret:
        try:
            segs, _ = unwrap(get("/api/external/segments"))
            out["segments"] = (len(segs), write([flat(s, obs) for s in segs], "segments", obs))
        except (QuotaExhausted, BudgetDepasse) as e:
            arret = str(e)
            out["segments"] = ("ARRET", arret[:90])
        except Exception as e:
            out["segments"] = ("ERREUR", str(e)[:80])

    # 3. wallets — borne par HT_WALLET_CAP, jamais de balayage complet
    if not arret:
        try:
            rows, total = sweep_wallets(obs, cap=cap)
            out["wallets"] = (len(rows), write(rows, "wallets", obs), f"totalCount={total}")
        except (QuotaExhausted, BudgetDepasse) as e:
            arret = str(e)
            out["wallets"] = ("ARRET", arret[:90])
        except Exception as e:
            out["wallets"] = ("ERREUR", str(e)[:120])

    print(f"observed_at={obs}  requetes={calls}/{BUDGET}")
    for k, v in out.items():
        print(f"  {k:<34} {v}")
    if arret:
        print(f"ARRET NET : {arret}")
        print("aucune requete supplementaire ; relancer apres le reset (reprise exacte).")
    return 3 if arret else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
