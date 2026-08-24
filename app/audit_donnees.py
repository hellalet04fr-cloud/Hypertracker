#!/usr/bin/env python3
"""
Audit d'AUTHENTICITE de l'application : chaque valeur affichee remonte-t-elle a une
source reelle ?

L'audit ne fait pas confiance au pipeline : il RECALCULE independamment depuis les
fichiers bruts et compare. Les tolerances sont alignees sur la precision d'arrondi
reellement declaree par la preparation — une tolerance plus serree que l'arrondi
produirait des faux positifs, ce qui est arrive au premier passage et a fait perdre
du temps a chercher une anomalie inexistante.

Il a trouve un defaut reel : le sous-echantillonnage des courbes n'incluait pas le
dernier trade, si bien que 39 wallets sur 231 affichaient une courbe se terminant
ailleurs que sur leur PnL total — pendant que la legende, juste en dessous, donnait
le bon chiffre.

    python -m app.audit_donnees        # depuis la racine du depot
"""
from __future__ import annotations

import json
import os
import re
import statistics as st

D = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
APP = os.environ.get("HT_APP_OUT", os.path.join(D, "app.html"))

# Precision d'arrondi declaree par app/prepare_donnees.py, champ par champ.
PRECISION = {"score": .05, "sr": .00005, "post": .00005, "n": 0, "jours": .5,
             "pnl": .005, "dd": .005, "conc": .0005}

# Valeurs citees en EXEMPLE dans la specification produit. Elles ne doivent jamais
# apparaitre dans le gabarit : ce serait le signe qu'un chiffre d'illustration a fuite
# a la place d'une donnee mesuree.
EXEMPLES = ["94.2", "184", "42.8K", "428", "68 %", "91 %"]


def main() -> int:
    html = open(APP, encoding="utf8").read()
    A = json.load(open(os.path.join(D, "app_data.json")))
    CL = {w["a"]: w for w in
          json.load(open(os.path.join(D, "classement_wallets.json")))["classement"]}
    SER = json.load(open(os.path.join(D, "series_wallets.json")))

    # on isole le GABARIT du bloc de donnees : chercher un nombre dans les donnees
    # n'a aucun sens, il s'y trouve forcement.
    i = html.index("const DB = ")
    gabarit = html[:i] + html[html.index("};", i) + 2:]

    r: dict[str, int] = {}
    r["exemples du brief en dur"] = sum(1 for x in EXEMPLES if x in gabarit)
    r["nombres codes en dur"] = len(re.findall(r'>\s*([+-]?\$?\d[\d.,]{1,8})\s*<', gabarit))

    # --- statistiques derivees : recalcul integral depuis les series brutes
    e = 0
    for w in A["wallets"]:
        tr = sorted(SER.get(w["a"], []), key=lambda t: t["close"])
        if not tr:
            continue
        v = [t["pnl"] - t["fee"] for t in tr]
        g = [x for x in v if x > 0]
        p = [x for x in v if x < 0]
        ref = {
            "n": len(v),
            "win": round(len(g) / len(v) * 100, 1),
            "best": round(max(v), 2),
            "pire": round(min(v), 2),
            "vol": round(st.pstdev(v), 2) if len(v) > 1 else None,
            "pf": round(sum(g) / sum(abs(x) for x in p), 2) if p else None,
            "duree_h": round(st.median([(t["close"] - t["open"]) / 3.6e6 for t in tr]), 1),
        }
        for k, ok in ref.items():
            if (ok is None) != (w[k] is None) or (ok is not None and abs(ok - w[k]) > 0.011):
                e += 1
    r["stats recalculees en ecart"] = e

    r["champs modele en ecart"] = sum(
        1 for w in A["wallets"] for k, tol in PRECISION.items()
        if abs(w[k] - CL[w["a"]][k]) > tol + 1e-9)

    # --- la courbe doit se terminer sur le PnL REEL du wallet
    r["courbes mal terminees"] = sum(
        1 for w in A["wallets"] if w["eq"] and
        abs(w["eq"][-1][1] - round(sum(t["pnl"] - t["fee"] for t in SER[w["a"]]), 2)) > 0.02)

    r["histogrammes incoherents"] = sum(
        1 for w in A["wallets"] if w.get("hist") and sum(w["hist"]["b"]) != w["n"])
    r["sparklines hors bornes"] = sum(
        1 for w in A["wallets"] for x in (w.get("sp") or []) if x < 0 or x > 1)

    # --- les champs indisponibles doivent rester N/A, jamais combles
    for lab, marq in (("ROI force a N/A", '<div class="k">ROI</div><div class="v">${NA}'),
                      ("Long/Short force a N/A", '<div class="k">Long / Short</div><div class="v">${NA}')):
        r[lab.lower()] = 0 if marq in html else 1

    print("AUDIT D'AUTHENTICITE — chaque compteur doit valoir ZERO")
    print("=" * 56)
    for k, v in r.items():
        print(f"  {'OK ' if v == 0 else '!! '}{k:<34}{v:>4}")
    print("=" * 56)
    bon = all(v == 0 for v in r.values())
    print("VERDICT :", "AUCUNE DONNEE FICTIVE" if bon else "ANOMALIE — ne pas publier")
    return 0 if bon else 1


if __name__ == "__main__":
    raise SystemExit(main())
