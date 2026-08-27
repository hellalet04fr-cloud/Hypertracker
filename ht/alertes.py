#!/usr/bin/env python3
"""
Alertes du cycle quotidien : ce qui a change et merite d'etre regarde.

TOUT EST DEDUPLIQUE. La cle par defaut est categorie + adresse + jour : un meme
evenement constate deux fois dans la journee ne produit qu'une alerte. Sans
cela, un cycle relance apres incident reemettrait tout ce qu'il avait deja emis,
et la seule facon de lire le rapport serait de ne plus le lire.

AUCUNE ALERTE NE REPOSE SUR LE PnL SEUL. Un wallet n'est jamais signale comme
remarquable parce qu'il a gagne de l'argent : il l'est parce qu'il satisfait les
criteres de qualification existants ET qu'il se place haut au classement. Un gain
spectaculaire sur un seul trade produit une concentration elevee, donc un rejet,
donc aucune alerte.
"""
from __future__ import annotations

from . import registre as R
from .lifecycle import EXCELLENT

NEW_WALLET = "NEW_WALLET"
RANK_UP = "RANK_UP"
RANK_DOWN = "RANK_DOWN"
DRAWDOWN_CHANGE = "DRAWDOWN_CHANGE"
CONFIDENCE_CHANGE = "CONFIDENCE_CHANGE"
CONCENTRATION_CHANGE = "CONCENTRATION_CHANGE"
WALLET_ARCHIVED = "WALLET_ARCHIVED"
DATA_FAILURE = "DATA_FAILURE"
QUOTA_WARNING = "QUOTA_WARNING"
DAILY_COMPLETE = "DAILY_COMPLETE"

# Amplitudes a partir desquelles un changement cesse d'etre du bruit. Ce ne sont
# PAS des seuils scientifiques : ils ne decident d'aucune qualification, d'aucun
# score, d'aucune entree ni sortie du classement. Ils decident uniquement de ce
# qui merite une ligne dans le rapport du matin.
BOND_RANG = 10          # places gagnees ou perdues
# Deplacement minimal de POSITION RELATIVE, en fraction du peloton. Un rang seul
# ne dit rien : quand 9 wallets entrent au classement, tous ceux du dessous
# perdent jusqu'a 9 places sans qu'aucun n'ait decline. Mesure sur le cycle du
# 25 aout : 43 alertes RANK_DOWN pour zero degradation reelle. La position
# relative, elle, ne bouge que si le wallet a reellement change de place DANS le
# peloton — un critere que la simple croissance de la population ne declenche pas.
BOND_POSITION = 0.05
BOND_DRAWDOWN = 0.50    # +50 % de repli maximal
BOND_CONCENTRATION = 0.15  # en valeur absolue de part


def _pct(avant, apres):
    if not avant:
        return None
    return (apres - avant) / abs(avant)


def emettre(c, cycle_id: str, evenements: list[dict]) -> int:
    """Insere les alertes non deja vues aujourd'hui. Retourne le nombre retenu."""
    n = 0
    for e in evenements:
        if R.alerter(c, cycle_id, e["categorie"], e["message"],
                     adresse=e.get("adresse"), cle=e.get("cle"), details=e.get("details")):
            n += 1
    c.commit()
    return n


def comparer(avant: dict, apres: dict, *, nouveaux_rangs: dict,
             n_avant: int | None = None, n_apres: int | None = None) -> list[dict]:
    """Evenements deduits de la comparaison de deux classements.

    `avant` et `apres` sont indexes par adresse et portent les metriques du
    moteur. Aucune grandeur n'est recalculee ici : on lit ce que le moteur a
    produit et on regarde ce qui a bouge.
    """
    ev: list[dict] = []
    n_avant = n_avant or len(avant) or 1
    n_apres = n_apres or len(apres) or 1
    for a, w in apres.items():
        v = avant.get(a)
        rang = nouveaux_rangs.get(a)

        if v is None:
            # NOUVEAU AU CLASSEMENT. Il n'est signale comme remarquable que s'il
            # est excellent au sens de la qualification ET place haut — jamais
            # sur son PnL, jamais sur une seule serie.
            if w.get("classe") == EXCELLENT and rang and rang <= 20:
                ev.append({"categorie": NEW_WALLET, "adresse": a,
                           "message": f"Entree directe au rang {rang} — "
                                      f"{w['n']} trades clos, qualite {w.get('qualite')}/3",
                           "details": {"rang": rang, "score": w.get("score"),
                                       "n": w.get("n"), "qualite": w.get("qualite")}})
            continue

        ancien_rang = v.get("rang")
        if ancien_rang and rang and n_avant and n_apres:
            delta = ancien_rang - rang
            # DEUX conditions, et la seconde fait le travail : le deplacement doit
            # etre sensible en places ET en position relative. Sans la seconde, la
            # seule arrivee de nouveaux wallets suffit a declarer tout le monde en
            # baisse.
            dpos = (ancien_rang / n_avant) - (rang / n_apres)
            if abs(delta) >= BOND_RANG and abs(dpos) >= BOND_POSITION:
                cat = RANK_UP if delta > 0 else RANK_DOWN
                signe = "+" if delta > 0 else ""
                ev.append({"categorie": cat, "adresse": a,
                           "message": f"{ancien_rang}/{n_avant} -> {rang}/{n_apres} "
                                      f"({signe}{delta} places, position "
                                      f"{dpos:+.0%})",
                           "details": {"avant": ancien_rang, "apres": rang,
                                       "n_avant": n_avant, "n_apres": n_apres,
                                       "deplacement_relatif": round(dpos, 4)}})

        d = _pct(v.get("dd"), w.get("dd"))
        if d is not None and d >= BOND_DRAWDOWN:
            ev.append({"categorie": DRAWDOWN_CHANGE, "adresse": a,
                       "message": f"repli maximal {v['dd']:.0f} -> {w['dd']:.0f} USD "
                                  f"({d:+.0%})",
                       "details": {"avant": v.get("dd"), "apres": w.get("dd")}})

        if v.get("confiance") and w.get("confiance") and v["confiance"] != w["confiance"]:
            ev.append({"categorie": CONFIDENCE_CHANGE, "adresse": a,
                       "message": f"qualite des donnees {v['confiance']} -> {w['confiance']}",
                       "details": {"avant": v.get("confiance"), "apres": w.get("confiance")}})

        ca, cb = v.get("conc"), w.get("conc")
        if ca is not None and cb is not None and abs(cb - ca) >= BOND_CONCENTRATION:
            ev.append({"categorie": CONCENTRATION_CHANGE, "adresse": a,
                       "message": f"concentration {ca:.2f} -> {cb:.2f}",
                       "details": {"avant": ca, "apres": cb}})
    return ev
