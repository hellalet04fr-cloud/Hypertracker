#!/usr/bin/env python3
"""
Calcul du classement des wallets — Bayes hierarchique empirique.

REPRIS A L'IDENTIQUE du script qui a produit `classement_wallets.json` en
production. Aucune formule, aucun seuil, aucune convention n'est modifiee ; le
seul changement est que ce calcul vit desormais DANS le depot, condition
necessaire pour qu'un cycle quotidien puisse le rejouer sans main humaine.

Rappel de ce que sont les trois grandeurs produites, qu'il ne faut pas
confondre :

  score      100 * Phi(post / tau) — position sur l'echelle de population.
  ic         intervalle de credibilite a 95 % autour de ce score.
  confiance  QUALITE DES DONNEES : nombre de criteres satisfaits sur trois.
             Ce n'est pas une probabilite. Les trois criteres reprennent des
             seuils DEJA declares ailleurs dans le projet, aucun n'est nouveau.

    python -m ht.classement
"""
from __future__ import annotations

import json
import math
import os

from .scoring import (MIN_TRADES, apriori, concentration, drawdown, phi,
                      se_sharpe, sharpe)

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")

# Criteres de QUALITE DES DONNEES. Aucun n'est invente pour l'occasion :
#   150   -> ht.oos : trois blocs hors echantillon de MIN_PAR_BLOC = 50
#   0.40  -> ht.final_gate.MAX_PART_MEILLEUR_TRADE (seuil scelle)
#   130.0 -> ht.screening.MIN_JOURS (critere de candidature pre-enregistre)
MIN_TRADES_FIABLE = 150
MAX_CONC = 0.40
MIN_JOURS = 130.0

NIVEAUX = ["faible", "faible", "moyenne", "elevee"]


def base_depuis_series(series: dict) -> dict:
    """Metriques par wallet, pour ceux qui atteignent le plancher de trades."""
    base = {}
    for a, v in series.items():
        v = sorted(v, key=lambda x: x["close"])
        r = [t["pnl"] - t["fee"] for t in v]
        if len(r) < MIN_TRADES:
            continue
        sr, se = sharpe(r), se_sharpe(r)
        if sr is None or se is None or se <= 0:
            continue
        jours = (v[-1]["close"] - v[0]["close"]) / 86400000
        base[a] = {"sr": sr, "se": se, "n": len(r), "jours": jours,
                   "dd": drawdown(r), "conc": concentration(r), "pnl": sum(r)}
    return base


def classer(base: dict) -> dict:
    """Retrecissement bayesien puis ordonnancement. Modifie `base` sur place.

    L'A PRIORI EST REESTIME SUR LA POPULATION PASSEE, exactement comme dans le
    calcul d'origine : m est la mediane des Sharpe observes et tau^2 leur
    dispersion robuste DEBARRASSEE du bruit d'estimation. Le reestimer est la
    definition meme de la methode — ce qui serait fautif, et que le projet
    s'interdit ailleurs, serait de le reestimer sur une sous-population de
    gagnants, ce qui retrecirait tout le monde vers une moyenne de gagnants.
    """
    srs = [b["sr"] for b in base.values()]
    ses = [b["se"] for b in base.values()]
    m, tau2 = apriori(srs, ses)
    tau = math.sqrt(tau2)

    for b in base.values():
        post = (tau2 * b["sr"] + b["se"] ** 2 * m) / (tau2 + b["se"] ** 2)
        psd = math.sqrt((tau2 * b["se"] ** 2) / (tau2 + b["se"] ** 2))
        b["post"], b["psd"] = post, psd
        b["p_comp"] = phi(post / psd)
        b["score"] = 100 * phi(post / tau)
        b["ic"] = (100 * phi((post - 1.96 * psd) / tau),
                   100 * phi((post + 1.96 * psd) / tau))
        crit = [b["n"] >= MIN_TRADES_FIABLE,
                b["conc"] is not None and b["conc"] <= MAX_CONC,
                b["jours"] >= MIN_JOURS]
        b["n_crit"] = sum(crit)
        b["qualite"] = sum(crit)
        b["confiance"] = NIVEAUX[sum(crit)]

    ordre = sorted(base, key=lambda a: -base[a]["score"])
    return {"n": len(base), "m": m, "tau": tau, "ordre": ordre}


def calculer(series: dict) -> dict:
    """Document de classement complet, pret a etre persiste."""
    base = base_depuis_series(series)
    if not base:
        return {"n": 0, "m": 0.0, "tau": 0.0, "classement": []}
    r = classer(base)
    return {"n": r["n"], "m": r["m"], "tau": r["tau"],
            "classement": [{"a": a, **base[a]} for a in r["ordre"]]}


def reporter_p_cal(doc: dict, ancien: dict | None) -> dict:
    """Reporte la PROBABILITE CALIBREE depuis le classement precedent.

    BLOCAGE REEL, ASSUME. Le recalibrage isotonique a bien ete ajuste (ECE
    0.1402 -> 0.0647, verdict LEVE), mais SEULS SES INDICATEURS ont ete
    persistes : le modele lui-meme — les noeuds de la fonction isotonique — n'est
    nulle part sur disque. On ne peut donc pas calibrer un wallet qui n'etait pas
    dans le lot d'origine.

    Deux issues seulement, et une seule est permise :

      - reajuster l'isotonique sur la population du jour. C'est une DECISION
        SCIENTIFIQUE : la calibration a ete pre-enregistree avec un decoupage
        precis (74 en ajustement, 84 en test) et scellee. La rejouer sur d'autres
        donnees change l'objet calibre. INTERDIT sans autorisation explicite.

      - reporter les valeurs deja calculees pour les wallets connus, et laisser
        les nouveaux SANS probabilite calibree. C'est ce qui est fait ici.

    Un wallet sans `p_cal` n'a pas une probabilite de zero : il n'en a pas. Le
    champ vaut None et s'affiche N/D. Le rapport quotidien compte ces wallets et
    les signale, pour que le blocage reste visible au lieu de se dissoudre.
    """
    connus = {}
    if ancien:
        connus = {w["a"]: w.get("p_cal") for w in ancien.get("classement", [])}
    sans = 0
    for w in doc["classement"]:
        w["p_brut"] = w["p_comp"]
        p = connus.get(w["a"])
        w["p_cal"] = p
        if p is None:
            sans += 1
    doc["sans_p_cal"] = sans
    doc["metrique_concentration"] = "part absolue = max|r| / somme|r|, bornee [0,1]"
    doc["probabilite"] = ("calibree par isotonique, ECE 0.0647 sur bloc test ; "
                          "non disponible pour les wallets apparus depuis")
    return doc


def main() -> int:
    src = os.path.join(DATA, "series_wallets.json")
    out = os.path.join(DATA, "classement_wallets.json")
    series = json.load(open(src))
    ancien = json.load(open(out)) if os.path.exists(out) else None
    doc = reporter_p_cal(calculer(series), ancien)
    json.dump(doc, open(out, "w"), indent=1)
    print(f"{doc['n']} wallets classes | a priori m={doc['m']:+.4f} tau={doc['tau']:.4f}")
    if doc["sans_p_cal"]:
        print(f"  ATTENTION {doc['sans_p_cal']} wallet(s) sans probabilite calibree "
              f"(recalibrage non rejouable sans autorisation)")
    print(f"persiste -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
