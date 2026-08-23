#!/usr/bin/env python3
"""
PLANIFICATEUR. Transforme les verrous enregistres en taches candidates.

Le point delicat de l'autonomie est ici. Un planificateur qui inventerait des taches en
texte libre serait exactement le mecanisme de derive qu'on cherche a empecher : c'est
ainsi que le projet a glisse une fois vers la certification d'un signal de trading.

D'ou la regle de construction : **toute tache descend d'un verrou enregistre dans
project_state.json**. Le planificateur ne cree pas de travail, il instruit des verrous.
Un verrou nouveau produit automatiquement ses taches ; un verrou sans patron connu
produit un DIAGNOSTIC, pas une improvisation.

Ce que le planificateur peut faire :   proposer, estimer, prioriser.
Ce qu'il ne peut pas faire :           toucher a l'objectif, aux seuils, aux protocoles
                                       scelles ou aux donnees de reference.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

from . import budgets as B

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")


@dataclass
class Candidate:
    """Une tache proposee, avec tout ce qu'il faut pour l'arbitrer sans la lancer."""
    id: str
    verrou: str
    objectif: str
    raison: str
    type: str
    fichiers: tuple[str, ...]
    depend_de: tuple[str, ...]
    cout: B.Cout
    gain: str
    roi: float
    risque: str
    condition_succes: str
    condition_arret: str
    executeur: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["cout"] = self.cout.as_dict()
        return d


# --------------------------------------------------------------- patrons par verrou
def _p_observed(v: dict) -> list[Candidate]:
    return [
        Candidate(
            id="collecte_observed_top5", verrou=v["id"],
            objectif="collecter les closed-trades OBSERVED natifs du top-5 de wallets",
            raison=v.get("mesure", "aucun natif pour le top-5"),
            type="data",
            fichiers=("ht/run_plan.py", "ledger.db"),
            depend_de=(),
            cout=B.Cout(hypertracker=5, cpu_s=120), roi=10.0,
            gain="debloque la certification du classement",
            risque="consomme la ressource la plus rare ; un 429 arrete le lot sans perte",
            condition_succes="5 wallets du top-5 avec >= 30 trades natifs",
            condition_arret="quota refuse, ou 5/5 deja collectes",
            executeur="_t_collecte_observed"),
        Candidate(
            id="verdict_observed", verrou=v["id"],
            objectif="appliquer le protocole scelle et rendre le verdict OBSERVED",
            raison="le protocole est scelle et n'attend plus que les donnees",
            type="quant",
            fichiers=("ht/verdict_observed.py", "verdict_observed.json"),
            depend_de=("collecte_observed_top5",),
            cout=B.Cout(cpu_s=30), roi=8.0,
            gain="verdict VALIDE / REFUSE / INCONCLUSIF sur le classement",
            risque="aucun : aucune decision n'est prise a l'execution",
            condition_succes="un verdict est rendu et persiste",
            condition_arret="moins de 30 trades natifs pour 3 wallets ou plus",
            executeur="_t_verdict_observed"),
    ]


def _p_granularite(v: dict) -> list[Candidate]:
    return [Candidate(
        id="elargir_base_calibration", verrou=v["id"],
        objectif="elargir la base de calibration du score de confiance des wallets",
        raison=("l'isotonique ajustee sur 74 wallets produit des paliers ; "
                "davantage de wallets a decoupage temporel valide affinerait la courbe"),
        type="quant",
        fichiers=("series_wallets.json", "comparaison_modeles.json"),
        depend_de=(),
        cout=B.Cout(hyperliquid=400, cpu_s=900), roi=2.5,
        gain="probabilite annoncee plus fine, sans toucher au modele",
        risque=("aucun sur le modele : seule la carte de calibration change. "
                "Le protocole scelle impose l'isotonique, sans substitution possible."),
        condition_succes="ECE toujours <= 0.10 avec des paliers plus nombreux",
        condition_arret="ECE degradee au-dela de 0.10 : on garde la carte actuelle",
        executeur="_t_elargir_calibration")]


def _p_crash(v: dict) -> list[Candidate]:
    return [Candidate(
        id="isoler_crash_behavior", verrou=v["id"],
        objectif="isoler le crash natif du module de comportement des wallets",
        raison=v.get("mesure", "acces violation dans behavior.py"),
        type="infra",
        fichiers=("ht/behavior.py", "tests/test_elite.py"),
        depend_de=(),
        cout=B.Cout(cpu_s=180), roi=1.2,
        gain="suite de tests entierement verte, diagnostic reproductible",
        risque="module hors chemin produit : ne pas y consacrer plus d'un cycle",
        condition_succes="crash reproduit dans un test isole, ou cause identifiee",
        condition_arret="deux cycles sans progres : marquer BLOQUE et passer",
        executeur="_t_isoler_crash")]


def _p_echantillon(v: dict) -> list[Candidate]:
    return [Candidate(
        id="elargir_criblage_wallets", verrou=v["id"],
        objectif="elargir le criblage de wallets pour densifier le haut du classement",
        raison=v.get("mesure", "trop peu de wallets qualifies en tete de classement"),
        type="data",
        fichiers=("campagne_journal_v3.json", "series_wallets.json"),
        depend_de=(),
        cout=B.Cout(hyperliquid=2400, cpu_s=1500), roi=3.0,
        gain="plus de candidats qualifies, a priori mieux estime",
        risque="Hyperliquid gratuit mais limite a 30 req/min : compter en heures",
        condition_succes="au moins 50 wallets qualifies supplementaires",
        condition_arret="rendement decroissant : moins de 5 qualifies par vague",
        executeur="_t_elargir_criblage")]


# Un verrou sans patron ne produit PAS de tache : il produit un diagnostic.
PATRONS = {
    "CONFIRMATION_OBSERVED_TOP5": _p_observed,
    "GRANULARITE_PROBABILITE": _p_granularite,
    "CRASH_BEHAVIOR_DUCKDB": _p_crash,
    "TAILLE_ECHANTILLON_INDEPENDANT": _p_echantillon,
    "ECHANTILLON_INSUFFISANT": _p_echantillon,
}

# Taches perennes, rattachees a la sante du produit et non a un verrou.
def _perennes() -> list[Candidate]:
    return [
        Candidate(
            id="audit_integrite", verrou="(perenne)",
            objectif="auditer l'integrite des scelles, seuils et classement de wallets",
            raison="un sceau rompu ou un seuil deplace invalide tout l'aval",
            type="audit",
            fichiers=("ht/garde.py",), depend_de=(),
            cout=B.Cout(cpu_s=30), roi=3.0,
            gain="garantie que rien n'a bouge sous nos pieds",
            risque="aucun",
            condition_succes="12 seuils conformes et 3 sceaux intacts",
            condition_arret="jamais : controle a chaque cycle",
            executeur="_t_audit_integrite"),
        Candidate(
            id="rafraichir_produit", verrou="(perenne)",
            objectif="rafraichir le produit de classement des wallets",
            raison="le dashboard doit refleter l'etat courant",
            type="produit",
            fichiers=("produit_classement.json",), depend_de=(),
            cout=B.Cout(cpu_s=30), roi=2.0,
            gain="livrable a jour",
            risque="aucun",
            condition_succes="produit regenere sans erreur",
            condition_arret="aucun classement disponible",
            executeur="_t_rafraichir_produit"),
    ]


def planifier(etat: dict) -> tuple[list[Candidate], list[str]]:
    """
    Rend (candidates, diagnostics).

    Les candidates descendent des verrous OUVERTS. Les diagnostics signalent les verrous
    pour lesquels aucun patron n'existe — c'est la frontiere de l'autonomie, et elle est
    dite explicitement plutot que comblee par de l'improvisation.
    """
    cands, diags = [], []
    for v in etat.get("verrous", []):
        if "FERME" in str(v.get("statut", "")).upper():
            continue
        p = PATRONS.get(v.get("id", ""))
        if p is None:
            diags.append(f"verrou '{v.get('id')}' sans patron de tache connu : "
                         f"a instruire manuellement, non improvise")
            continue
        cands.extend(p(v))
    cands.extend(_perennes())
    return cands, diags


def deleguer_diagnostics(diags: list[str]) -> list[Candidate]:
    """
    Transforme un verrou sans patron en tache DELEGUEE.

    C'est la ou l'autonomie gagne du terrain sans perdre en surete : plutot que de
    laisser le verrou dormir dans un diagnostic, on demande a Claude de l'instruire
    — constater, mesurer, proposer un patron. La proposition reste une proposition :
    aucun patron n'entre dans PATRONS sans relecture.
    """
    out = []
    for i, d in enumerate(diags):
        verrou = d.split("'")[1] if "'" in d else f"inconnu_{i}"
        out.append(Candidate(
            id=f"instruire_{verrou.lower()}", verrou=verrou,
            objectif=f"instruire le verrou {verrou} du classement de wallets",
            raison=(f"Le verrou {verrou} est enregistre dans project_state.json mais "
                    f"aucun patron de tache ne lui correspond. Constate son etat reel "
                    f"a partir des fichiers du projet, mesure ce qui manque, et propose "
                    f"un patron de tache exploitable. Ne modifie rien."),
            type="research",
            fichiers=("ht/project_state.json", "ht/planificateur.py"),
            depend_de=(),
            cout=B.Cout(cpu_s=600, tokens_k=40), roi=1.5,
            gain="un verrou dormant devient instruit et planifiable",
            risque="delegation a un modele : gardes appliquees au prompt ET a la sortie",
            condition_succes="un patron de tache est propose et argumente",
            condition_arret="deux tentatives sans proposition exploitable",
            executeur="_t_deleguer"))
    return out


def journaliser_plan(cands: list[Candidate], diags: list[str],
                     chemin: str | None = None) -> str:
    p = chemin or os.path.join(DATA, "plan.json")
    with open(p, "w") as f:
        json.dump({"candidates": [c.as_dict() for c in cands],
                   "diagnostics": diags}, f, indent=1, ensure_ascii=True)
    return p
