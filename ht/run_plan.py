#!/usr/bin/env python3
"""
Executeur du plan de collecte deja defini (ht/collect_plan.py).

Concu pour etre lance toutes les 4 heures par le planificateur Windows. La tentative
EST la verification : si le quota est epuise, le premier appel leve QuotaExhausted et
tout s'arrete apres UNE requete — aucun test separe n'est donc necessaire.

Budget : un compteur par jour UTC est persiste dans le ledger. Plusieurs executions
dans la meme journee se partagent les 100 requetes au lieu de les redepenser chacune.

Ordre, du plus irremplacable au plus rattrapable :
  1. perissables  : leaderboards + segments + 1 page wallets   (aucun as-of, perdus sinon)
  2. resumes      : /closed-trades/summary sur les adresses des leaderboards
                    (1 requete = winRate/profitFactor/payoffRatio/expectancy x 6 intervalles)
  3. archive      : backfill des snapshots, bornes FIXES 19 jan -> 12 mars, jamais perissable
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
LEDGER = os.path.join(DATA, "ledger.db")
API = "https://ht-api.coinmarketman.com"
QUOTA_JOUR = int(os.environ.get("HT_BUDGET", "100"))
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- budget
def _db():
    os.makedirs(DATA, exist_ok=True)
    c = sqlite3.connect(LEDGER, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS spend(
        jour TEXT PRIMARY KEY, used INTEGER NOT NULL DEFAULT 0,
        maj TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS summaries(
        address TEXT PRIMARY KEY, observed_at TEXT, payload TEXT)""")
    return c


def _jour() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def depense(n: int = 0) -> int:
    """Incremente et retourne le total depense aujourd'hui (UTC)."""
    j = _jour()
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO spend(jour, used) VALUES(?, 0)", (j,))
        if n:
            c.execute("UPDATE spend SET used = used + ?, maj = ? WHERE jour = ?",
                      (n, datetime.now(timezone.utc).isoformat(), j))
        return c.execute("SELECT used FROM spend WHERE jour = ?", (j,)).fetchone()[0]


def reste() -> int:
    return max(0, QUOTA_JOUR - depense(0))


# --------------------------------------------------------------------------- etapes
def etape_perissables() -> tuple[bool, str]:
    """Delegue a ht.perishable, en lui passant le reliquat comme plafond."""
    budget = reste()
    if budget <= 0:
        return False, "budget du jour deja epuise"
    env = dict(os.environ, HT_BUDGET=str(budget), HT_DATA_ROOT=DATA,
               HT_WALLET_CAP=os.environ.get("HT_WALLET_CAP", "500"))
    p = subprocess.run([sys.executable, os.path.join(RACINE, "ht", "perishable.py")],
                       capture_output=True, text=True, env=env, cwd=RACINE)
    sortie = (p.stdout or "") + (p.stderr or "")
    # ht.perishable imprime "requetes=N/BUDGET" : on recupere N pour le compteur du jour
    n = 0
    for ligne in sortie.splitlines():
        if "requetes=" in ligne:
            try:
                n = int(ligne.split("requetes=")[1].split("/")[0])
            except (ValueError, IndexError):
                pass
    if n:
        depense(n)
    print(sortie.strip())
    return p.returncode == 0, sortie.strip()[-300:]


def adresses_leaderboards() -> list[str]:
    """Union des adresses des leaderboards deja captures, sans requete."""
    import pyarrow.parquet as pq
    from .collect_plan import adresses_depuis_leaderboards

    lignes = []
    for f in glob.glob(os.path.join(DATA, "leaderboards_*", "**", "*.parquet"), recursive=True):
        try:
            lignes.extend(pq.read_table(f).to_pylist())
        except Exception:
            continue
    return adresses_depuis_leaderboards(lignes)


def etape_resumes(adresses: list[str], budget: int) -> int:
    """Un /closed-trades/summary par adresse. Deduplique via la table `summaries` :
    une adresse deja resumee aujourd'hui n'est jamais redemandee."""
    from .perishable import _token

    if budget <= 0 or not adresses:
        return 0
    with _db() as c:
        deja = {r[0] for r in c.execute("SELECT address FROM summaries")}
    a_faire = [a for a in adresses if a not in deja][:budget]
    obtenus = 0
    for a in a_faire:
        url = f"{API}/api/external/closed-trades/summary?address={urllib.parse.quote(a)}&interval=all"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}",
                                                   "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                corps = r.read().decode("utf8", "replace")
            depense(1)
            with _db() as c:
                c.execute("INSERT OR REPLACE INTO summaries VALUES(?,?,?)",
                          (a, datetime.now(timezone.utc).isoformat(), corps))
            obtenus += 1
        except urllib.error.HTTPError as e:
            depense(1)
            if e.code == 429:
                print(f"resumes: arret quota apres {obtenus} obtenu(s)")
                break
            print(f"resumes: {a[:10]}... HTTP {e.code}")
        except Exception as e:
            print(f"resumes: {a[:10]}... {type(e).__name__}")
    return obtenus


def adresses_derivees() -> list[str]:
    """Wallets pour lesquels une reconstruction DERIVED existe deja sur disque.
    Ce sont EUX qu'il faut collecter en natif en priorite : sans recouvrement, la
    validation croisee n'a rien a comparer et le portail restera NOT_READY."""
    import glob
    import pyarrow.parquet as pq

    vus: dict[str, None] = {}
    for f in glob.glob(os.path.join(DATA, "reconstructed_closed_trades", "**", "*.parquet"),
                       recursive=True):
        try:
            for a in pq.read_table(f, columns=["address"])["address"].to_pylist():
                if isinstance(a, str) and len(a) == 42:
                    vus.setdefault(a, None)
        except Exception:
            continue
    return list(vus)


def etape_top5(budget: int) -> int:
    """
    PRIORITE ABSOLUE : confirmer en natif les 5 premiers de classement_wallets.json.

    C'est le dernier verrou scientifique du produit. Tout le reste — resumes, archive,
    perissables — sert l'ancien objectif et peut attendre le lendemain ; ce pas-ci ne le
    peut pas, parce qu'il conditionne le verdict du moteur de classement.

    STRATEGIE LARGE D'ABORD. La documentation expose un parametre `limit` (defaut 100)
    que ce code n'envoyait jamais : chaque requete se contentait donc de 100 trades sur
    une fenetre de 30 jours. Le protocole scelle prevoit explicitement "la fenetre la
    plus large que l'API accepte, determinee par UNE requete de test" — on tente donc
    400 jours avec limit=500, et on ne retombe sur des tranches de 30 jours que si la
    large echoue. Le top-5 passe alors de ~20 requetes a 5.

    Le premier appel SERT DE SONDE : un 429 arrete le lot entier, sans le gaspiller
    requete par requete. Chaque code de reponse est journalise dans `requetes`, ce qui
    rend l'ecart serveur/registre mesurable au lieu d'etre devine.
    """
    from . import quota as Q
    from .perishable import _token

    if Q.epuise():
        print("top5 : le serveur a deja refuse dans cette fenetre — aucune requete tentee.")
        return 0
    chemin = os.path.join(DATA, "classement_wallets.json")
    if not os.path.exists(chemin):
        print("top5 : aucun classement disponible.")
        return 0
    with open(chemin) as f:
        cl = json.load(f)["classement"][:5]

    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    deja = set()
    with _db() as c:
        for a, fen in c.execute("SELECT address, fenetre FROM closed_trades_natifs"):
            deja.add((a.lower(), fen))

    etat = {"obtenus": 0, "large_marche": None}

    def _demander(a, deb, fin, limite):
        """Une requete. Rend (trades, arret) ; arret=True sur 429."""
        fen = f"{iso(deb)}_{iso(fin)}"
        if (a.lower(), fen) in deja:
            return None, False
        url = (f"{API}/api/external/closed-trades?address={urllib.parse.quote(a)}"
               f"&startTime={urllib.parse.quote(iso(deb))}"
               f"&endTime={urllib.parse.quote(iso(fin))}"
               f"&limit={int(limite)}")
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {_token()}",
                          "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                corps = r.read().decode("utf8", "replace")
            depense(1)
            Q.journaliser("closed-trades", a, 200)
            etat["obtenus"] += 1
            with _db() as c:
                c.execute("INSERT OR REPLACE INTO closed_trades_natifs VALUES(?,?,?,?)",
                          (a, fen, datetime.now(timezone.utc).isoformat(), corps))
            deja.add((a.lower(), fen))
            try:
                return json.loads(corps).get("trades", []), False
            except Exception:
                return [], False
        except urllib.error.HTTPError as e:
            depense(1)
            Q.journaliser("closed-trades", a, e.code)
            if e.code == 429:
                print(f"top5 : refus 429 apres {etat['obtenus']} requetes — lot interrompu.")
                return None, True
            print(f"top5 : {a[:10]}... HTTP {e.code}")
            return None, False
        except Exception as e:
            print(f"top5 : {a[:10]}... {type(e).__name__}")
            return None, False

    maintenant = datetime.now(timezone.utc)
    for w in cl:
        a = w["a"]
        if etat["obtenus"] >= budget:
            break
        n_vus = 0

        if etat["large_marche"] is not False:
            tr, arret = _demander(a, maintenant - timedelta(days=400), maintenant, 500)
            if arret:
                return etat["obtenus"]
            if tr is not None:
                n_vus = len(tr)
                if n_vus:
                    # jamais supposer qu'un champ est present : un seul trade sans
                    # closeTime ferait echouer la collecte et couterait la fenetre
                    # de quota entiere.
                    ts = sorted(t["closeTime"] for t in tr if t.get("closeTime"))
                    span = 0
                    try:
                        if len(ts) >= 2:
                            span = (datetime.fromisoformat(ts[-1].replace("Z", "+00:00"))
                                    - datetime.fromisoformat(ts[0].replace("Z", "+00:00"))).days
                    except ValueError:
                        # horodatage malforme : on ne sait pas conclure sur l'etendue,
                        # mais cela ne doit surtout pas interrompre la collecte.
                        span = 0
                    etat["large_marche"] = span > 35
                    print(f"top5 : {a[:10]}... {n_vus} trades sur {span} j "
                          f"(fenetre large {'ACCEPTEE' if etat['large_marche'] else 'plafonnee'})")
                    if etat["large_marche"] and n_vus >= 30:
                        continue

        # repli : tranches de 30 jours, du plus recent au plus ancien
        for k in range(12):
            if etat["obtenus"] >= budget or n_vus >= 30:
                break
            fin_f = maintenant - timedelta(days=30 * k)
            tr, arret = _demander(a, fin_f - timedelta(days=30), fin_f, 500)
            if arret:
                return etat["obtenus"]
            if tr:
                n_vus += len(tr)
        print(f"top5 : {a[:10]}... {n_vus} trades natifs cumules")
    return etat["obtenus"]


def etape_natifs(adresses: list[str], budget: int) -> int:
    """
    Collecte de closed_trades NATIFS, fenetre de 30 jours par requete.

    Ordre volontaire : les wallets deja reconstruits d'abord. Un natif sur un wallet
    inconnu du cote DERIVED alimente le classement mais ne fait pas avancer la
    verification, qui est le vrai verrou.
    """
    from .perishable import _token

    if budget <= 0 or not adresses:
        return 0
    with _db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS closed_trades_natifs(
            address TEXT, fenetre TEXT, observed_at TEXT, payload TEXT,
            PRIMARY KEY(address, fenetre))""")
        c.execute("""CREATE TABLE IF NOT EXISTS fenetres_a_collecter(
            address TEXT, fenetre TEXT, debut TEXT, fin TEXT, n_derived INTEGER,
            PRIMARY KEY(address, fenetre))""")
        deja = {(r[0], r[1]) for r in
                c.execute("SELECT address, fenetre FROM closed_trades_natifs")}
        # Fenetres pre-calculees hors ligne, triees par recouvrement DERIVED decroissant.
        # Sans elles on retomberait sur les 30 derniers jours, qui ne recouvrent RIEN
        # du DERIVED : c'est ce qui a produit 0 paire appariee au premier essai.
        planifiees = [dict(address=r[0], fenetre=r[1], debut=r[2], fin=r[3])
                      for r in c.execute(
                          "SELECT address, fenetre, debut, fin FROM fenetres_a_collecter "
                          "ORDER BY n_derived DESC")]

    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if planifiees:
        cibles = [p for p in planifiees if (p["address"], p["fenetre"]) not in deja]
    else:
        fin = datetime.now(timezone.utc)
        deb = fin - timedelta(days=30)
        cibles = [{"address": a, "debut": iso(deb), "fin": iso(fin),
                   "fenetre": f"{iso(deb)}_{iso(fin)}"}
                  for a in adresses
                  if (a, f"{iso(deb)}_{iso(fin)}") not in deja]

    obtenus = 0
    for p in cibles[:budget]:
        a, fenetre = p["address"], p["fenetre"]
        url = (f"{API}/api/external/closed-trades?address={urllib.parse.quote(a)}"
               f"&startTime={urllib.parse.quote(p['debut'])}"
               f"&endTime={urllib.parse.quote(p['fin'])}")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}",
                                                   "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                corps = r.read().decode("utf8", "replace")
            depense(1)
            with _db() as c:
                c.execute("INSERT OR REPLACE INTO closed_trades_natifs VALUES(?,?,?,?)",
                          (a, fenetre, datetime.now(timezone.utc).isoformat(), corps))
            obtenus += 1
        except urllib.error.HTTPError as e:
            depense(1)
            if e.code == 429:
                print(f"natifs: arret quota apres {obtenus}")
                break
            print(f"natifs: {a[:10]}... HTTP {e.code}")
        except Exception as e:
            print(f"natifs: {a[:10]}... {type(e).__name__}")
    return obtenus


def etape_gate() -> str:
    """
    Enchainement automatique : validation croisee -> ECE -> classement.
    Ne fait AUCUNE requete : il ne fait que constater sur ce qui est deja sur disque.
    """
    from . import gate as G

    natifs: list[dict] = []
    try:
        with _db() as c:
            for (payload,) in c.execute("SELECT payload FROM closed_trades_natifs"):
                try:
                    d = json.loads(payload)
                except Exception:
                    continue
                # Enveloppe reelle constatee : {"trades": [...], "nextCursor": ...}.
                # L'API n'a pas d'enveloppe unique — /segments rend un tableau nu,
                # /wallets {totalCount,items}, /closed-trades {trades,nextCursor}.
                if isinstance(d, list):
                    lignes = d
                else:
                    lignes = next((d[k] for k in ("trades", "items", "data", "results")
                                   if isinstance(d.get(k), list)), [])
                natifs.extend(lignes)
    except Exception:
        pass

    reconstruits: list[dict] = []
    try:
        import glob
        import pyarrow.parquet as pq
        for f in glob.glob(os.path.join(DATA, "reconstructed_closed_trades", "**", "*.parquet"),
                           recursive=True):
            reconstruits.extend(pq.read_table(f).to_pylist())
    except Exception:
        pass

    out = G.executer_si_pret(natifs, reconstruits, None)
    v = out["verdict"]
    print(v.resume())
    print(f"  -> {out['note']}")
    return v.etat


def etape_archive(budget: int) -> int:
    """Backfill des snapshots avec le reliquat. Le ledger garantit la reprise exacte."""
    if budget <= 0:
        return 0
    env = dict(os.environ, HT_DATA_ROOT=DATA, HT_WORKERS=os.environ.get("HT_WORKERS", "3"))
    p = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, r'%s');"
                        "from ht import backfill as b; b.main()" % RACINE],
                       capture_output=True, text=True, env=env, cwd=RACINE, timeout=3 * 3600)
    print((p.stdout or "").strip()[-500:])
    return 0


# --------------------------------------------------------------------------- main
def main() -> int:
    debut = datetime.now(timezone.utc).isoformat(timespec="seconds")
    utilise = depense(0)
    print(f"[{debut}] plan de collecte — depense du jour {utilise}/{QUOTA_JOUR}")

    if reste() <= 0:
        print("budget du jour epuise ; rien a faire.")
        return 0

    # CHEMIN CRITIQUE D'ABORD. Le produit est le classement de wallets ; sa
    # confirmation OBSERVED passe avant tout ce qui sert l'ancien objectif.
    n_top = etape_top5(min(reste(), 30))
    print(f"top-5 : {n_top} fenetres natives collectees")
    if reste() <= 0:
        print("budget epuise apres le top-5.")
        return 0

    ok, _ = etape_perissables()
    if not ok:
        print(f"perissables : arret. depense {depense(0)}/{QUOTA_JOUR}")
        return 3

    adresses = adresses_leaderboards()
    print(f"adresses issues des leaderboards : {len(adresses)}")

    # Les resumes debloquent toute la chaine aval (ranking, validation, Monte-Carlo,
    # calibration) ; l'archive n'est pas perissable. On leur donne donc les deux tiers
    # du reliquat, le reste allant a l'archive pour qu'elle continue d'avancer.
    r = reste()

    # Priorite : les wallets deja reconstruits. Sans recouvrement DERIVED/natif, la
    # validation croisee n'a rien a comparer et le portail reste NOT_READY — c'est
    # le vrai verrou, avant meme le volume de trades.
    # Priorite aux wallets deja reconstruits, PUIS complement par les leaderboards.
    # Sans ce complement, un lac DERIVED vide rendrait `cibles` vide et aucun natif ne
    # serait jamais collecte : le portail resterait NOT_READY indefiniment.
    cibles = adresses_derivees()
    vus = set(adresses)
    communs = [a for a in cibles if a in vus]
    priorite = communs + [a for a in cibles if a not in vus] + \
               [a for a in adresses if a not in set(cibles)]
    n_nat = etape_natifs(priorite, min(len(priorite), max(1, r // 3)))
    print(f"closed_trades natifs obtenus : {n_nat} (dont recouvrement DERIVED prioritaire)")

    part_resumes = (reste() * 2) // 3
    n = etape_resumes(adresses, part_resumes)
    print(f"resumes obtenus : {n}")

    etape_archive(reste())

    # Constat automatique, sans requete : validation croisee -> ECE -> classement.
    print("\n--- portail de verification ---")
    try:
        etat = etape_gate()
    except Exception as e:
        etat = f"erreur: {type(e).__name__}"
        print(f"portail indisponible : {e}")

    # Le verdict OBSERVED suit immediatement la collecte du top-5 : sans ce chainage,
    # les donnees dorment jusqu'a la prochaine session alors que le protocole est deja
    # scelle et n'attend aucune decision. Aucune requete, aucun choix — pure execution.
    print("\n--- verdict OBSERVED du top-5 ---")
    try:
        from . import verdict_observed as VO
        v = VO.evaluer()
        with open(os.path.join(DATA, "verdict_observed.json"), "w") as f:
            json.dump(v, f, indent=1)
        print(f"verdict={v['verdict']} — {v['motif']}")
    except Exception as e:
        print(f"verdict indisponible : {type(e).__name__}: {e}")

    print(f"fin — depense du jour {depense(0)}/{QUOTA_JOUR} | portail={etat}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
