#!/usr/bin/env python3
"""
Score les wallets des LEADERBOARDS HyperTracker avec le modele scelle.

Les 231 wallets du classement viennent des carnets d'ordres, tires par hash : une
population volontairement non biaisee. Les leaderboards sont une population DISJOINTE
— recoupement mesure : 0 sur 231 — et ils portent le signal que l'utilisateur appelle
« reputation » : rang HyperTracker, PnL, volume, anciennete du compte.

BIAIS DE SURVIE, declare. La regle de selection scellee avait ecarte les leaderboards
pour cette raison exacte : on n'y voit que ceux qui ont gagne ET qui tradent encore.
Les scores produits ici sont donc valables pour COMPARER ces wallets entre eux et pour
les suivre, mais la population n'est pas representative.

A PRIORI NON RECALCULE. On applique m et tau estimes sur la population non biaisee.
Reestimer l'a priori sur des gagnants les retrecirait vers une moyenne de gagnants et
gonflerait tout le monde — c'est exactement l'erreur que le retrecissement doit eviter.

    python app/collecter_reputation.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

D = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
PERP = lambda co: ":" not in co and "/" not in co
MIN_TRADES = 30


def reputation() -> dict:
    """Meilleur rang et metriques HyperTracker par adresse, tous leaderboards confondus."""
    import pyarrow.parquet as pq
    out: dict[str, dict] = {}
    for f in glob.glob(os.path.join(D, "leaderboards_*", "**", "*.parquet"), recursive=True):
        try:
            t = pq.read_table(f).to_pylist()
        except Exception:
            continue
        for r in t:
            a = str(r.get("address", "")).lower()
            if len(a) != 42:
                continue
            d = out.setdefault(a, {"rangs": {}, "pnl_all": None, "pnl_pct": None,
                                   "vol_all": None, "equity": None, "age": None})
            cle = f"{r.get('_endpoint')}/{r.get('_rankBy')}"
            rg = r.get("_rank")
            if rg is not None:
                d["rangs"][cle] = min(int(rg), d["rangs"].get(cle, 10**9))
            for k, src in (("pnl_all", "pnlAllTime"), ("pnl_pct", "pnlPercentAllTime"),
                           ("vol_all", "volumeAllTime"), ("equity", "perpEquity")):
                v = r.get(src)
                if v is not None and d[k] is None:
                    d[k] = float(v)
            if d["age"] is None and r.get("age"):
                d["age"] = str(r["age"])[:10]
    for a, d in out.items():
        d["meilleur_rang"] = min(d["rangs"].values()) if d["rangs"] else None
        d["n_leaderboards"] = len(d["rangs"])
    return out


def main() -> int:
    import ht.hl_public as HL
    import ht.reconstruct as R

    rep = reputation()
    adr = sorted(rep)
    print(f"adresses de leaderboard : {len(adr)}")

    cache = os.path.join(D, "series_reputation.json")
    series = json.load(open(cache)) if os.path.exists(cache) else {}
    print(f"deja en cache : {len(series)}")

    t0 = time.time()
    for i, a in enumerate(adr):
        if a in series:
            continue
        try:
            rec = R.reconstruire_wallet(a, [f for f in HL.user_fills(a) if PERP(f["coin"])])
            series[a] = [{"pnl": x.realizedPnlUsd, "fee": x.feeUsd, "open": x.openTime,
                          "close": x.closeTime, "coin": x.coin}
                         for x in rec.trades if not x.tronque and not x.position_ouverte]
        except Exception:
            series[a] = []
        if (i + 1) % 40 == 0:
            json.dump(series, open(cache, "w"), separators=(",", ":"))
            print(f"  {i+1}/{len(adr)} | {HL.STATS.requetes} req | "
                  f"{time.time()-t0:.0f}s", flush=True)
    json.dump(series, open(cache, "w"), separators=(",", ":"))
    print(f"collecte terminee : {HL.STATS.requetes} requetes Hyperliquid, 0 HyperTracker")

    # --- a priori SCELLE, repris de la population non biaisee
    CL = json.load(open(os.path.join(D, "classement_wallets.json")))
    m, tau = CL["m"], CL["tau"]
    tau2 = tau ** 2
    print(f"a priori applique (non recalcule) : m={m:+.4f} tau={tau:.4f}")

    def sharpe(r):
        sd = st.pstdev(r)
        return (st.mean(r) / sd) if sd > 0 and len(r) > 1 else None

    def se(r):
        n = len(r)
        if n < 3:
            return None
        mm, sd = st.mean(r), st.pstdev(r)
        if sd <= 0:
            return None
        sr = mm / sd
        g3 = sum(((x - mm) / sd) ** 3 for x in r) / n
        g4 = sum(((x - mm) / sd) ** 4 for x in r) / n
        v = (1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) / (n - 1)
        return math.sqrt(v) if v > 0 else None

    phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    out = []
    for a, tr in series.items():
        if len(tr) < MIN_TRADES:
            continue
        tr = sorted(tr, key=lambda t: t["close"])
        r = [t["pnl"] - t["fee"] for t in tr]
        sr, s = sharpe(r), se(r)
        if sr is None or s is None or s <= 0:
            continue
        post = (tau2 * sr + s ** 2 * m) / (tau2 + s ** 2)
        out.append({"a": a, "sr": sr, "se": s, "post": post,
                    "score": 100 * phi(post / tau), "n": len(r),
                    "pnl": sum(r), **{k: v for k, v in rep[a].items() if k != "rangs"}})
    out.sort(key=lambda w: -w["score"])
    json.dump({"m": m, "tau": tau, "n": len(out), "wallets": out},
              open(os.path.join(D, "classement_reputation.json"), "w"), indent=1)
    print(f"\n{len(out)} wallets de leaderboard scores (>= {MIN_TRADES} trades)")
    print(f"persiste -> classement_reputation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
