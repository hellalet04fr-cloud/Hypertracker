#!/usr/bin/env python3
"""
Prepare la vue REPUTATION : les leaderboards HyperTracker, avec les metriques natives
de HyperTracker et rien d'autre.

Pourquoi aucun score de notre modele ici. Mesure sur les 463 adresses de leaderboard :
387 n'ont AUCUN trade clos exploitable et 4 seulement en ont plus de 30. Ce sont des
positions tenues longtemps, jamais ramenees a plat dans la fenetre observable — notre
modele compte des allers-retours clos, il ne peut structurellement pas les mesurer.

Et quand il y parvient, les deux mesures se contredisent : un wallet classe 21e chez
HyperTracker avec 75 M$ de PnL de vie affiche -34 $ sur nos cycles clos recents. Ce
n'est pas une contradiction a arbitrer, ce sont deux grandeurs differentes — PnL de
compte contre performance par trade clos.

On affiche donc les chiffres de HyperTracker, attribues a HyperTracker.

    python app/prepare_reputation.py
"""
from __future__ import annotations

import glob
import json
import os

D = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
CHAMPS = ("pnlAllTime", "pnlPercentAllTime", "pnlDay", "pnlWeek", "pnlMonth",
          "volumeAllTime", "volumeMonth", "perpEquity", "openValue", "age",
          "bias", "exposureRatio")


def main() -> int:
    import pyarrow.parquet as pq

    # UNIQUEMENT les leaderboards perp-pnl. Les tableaux « all-pnl » n'ont que deux
    # champs remplis et leur PnL agrege le spot : un detenteur de tokens y affiche
    # 70 milliards, ce qui n'est pas comparable a une performance de trading. Les
    # perp-pnl portent le jeu complet et coherent, et correspondent a notre perimetre.
    best: dict[str, dict] = {}
    for f in glob.glob(os.path.join(D, "leaderboards_perp-pnl_*", "**", "*.parquet"),
                       recursive=True):
        try:
            lignes = pq.read_table(f).to_pylist()
        except Exception:
            continue
        for r in lignes:
            a = str(r.get("address", "")).lower()
            if len(a) != 42 or set(a[2:]) == {"0"}:      # exclut la pseudo-adresse TWAP
                continue
            d = best.setdefault(a, {"a": a, "rangs": {}, "n_boards": 0,
                                    "_src_rang": 10 ** 9})
            cle = str(r.get("_rankBy"))
            rg = r.get("_rank")
            if rg is not None:
                d["rangs"][cle] = min(int(rg), d["rangs"].get(cle, 10 ** 9))
            # une seule ligne fournit TOUTES les metriques : celle du meilleur rang.
            # Melanger le rang d'un tableau avec les chiffres d'un autre produirait
            # des lignes incoherentes.
            complet = r.get("volumeAllTime") is not None
            if complet and rg is not None and int(rg) < d["_src_rang"]:
                d["_src_rang"] = int(rg)
                for k in CHAMPS:
                    v = r.get(k)
                    d[k] = str(v)[:10] if k == "age" else (float(v) if v is not None else None)

    # notre modele a-t-il pu dire quelque chose sur ce wallet ?
    p = os.path.join(D, "classement_reputation.json")
    notre = {}
    if os.path.exists(p):
        notre = {w["a"]: w for w in json.load(open(p))["wallets"]}
    ser = {}
    p2 = os.path.join(D, "series_reputation.json")
    if os.path.exists(p2):
        ser = {a: len(v) for a, v in json.load(open(p2)).items()}

    out = []
    for a, d in best.items():
        d["meilleur_rang"] = min(d["rangs"].values()) if d["rangs"] else None
        d["n_boards"] = len(d["rangs"])
        d["rang_alltime"] = d["rangs"].get("pnlAllTime")
        d["rang_mois"] = d["rangs"].get("pnlMonth")
        d["rang_semaine"] = d["rangs"].get("pnlWeek")
        d["rang_jour"] = d["rangs"].get("pnlDay")
        d.pop("rangs", None); d.pop("_src_rang", None)
        n = notre.get(a)
        d["notre_score"] = round(n["score"], 1) if n else None
        d["notre_sr"] = round(n["sr"], 3) if n else None
        d["notre_n"] = ser.get(a, 0)
        out.append(d)

    out = [w for w in out if w["meilleur_rang"] is not None]
    out.sort(key=lambda w: w["meilleur_rang"])
    meta = {
        "n": len(out),
        "mesurables": sum(1 for w in out if w["notre_score"] is not None),
        "sans_trade_clos": sum(1 for w in out if w["notre_n"] == 0),
        "source": "leaderboards HyperTracker collectes le 2026-08-22",
    }
    json.dump({"meta": meta, "wallets": out},
              open(os.path.join(D, "reputation_data.json"), "w"), separators=(",", ":"))
    print(f"{len(out)} wallets de leaderboard")
    print(f"  mesurables par notre modele : {meta['mesurables']}")
    print(f"  sans aucun trade clos       : {meta['sans_trade_clos']}")
    print(f"persiste -> reputation_data.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
