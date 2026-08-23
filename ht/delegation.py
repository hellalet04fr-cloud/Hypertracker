#!/usr/bin/env python3
"""
DELEGATION a Claude Code en mode headless.

C'est le seul manque reel de l'orchestrateur : il ne sait executer que des fonctions
Python pre-liees. Toute tache demandant du JUGEMENT — diagnostiquer un crash natif,
chercher une source de donnees alternative, instruire un verrou sans patron — etait
refusee avec « aucun executeur lie ». Ce module les rend executables.

Deux gardes, aux deux bouts, et c'est ce qui rend la delegation acceptable :

  AVANT   le prompt passe par ht.garde. Une consigne qui evoque une branche abandonnee
          n'est jamais envoyee. On ne compte pas sur le modele pour refuser : on ne lui
          donne pas l'occasion.
  APRES   le resultat repasse par ht.garde avant d'etre accepte. Un agent qui repartirait
          vers une piste abandonnee voit sa sortie rejetee, pas integree.

Bornes dures : nombre de tours, delai, et budget de tokens declare. Un agent autonome
sans borne de tours est un agent qui peut couter n'importe quoi.

Ce module n'accorde AUCUNE permission d'ecriture par defaut. Une delegation qui doit
modifier le depot doit le demander explicitement, et cela se voit dans le journal.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field, asdict

from . import garde as G

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_TOURS = 12
DELAI_S = 900
JOURNAL = os.path.join(DATA, "delegations.json")

# Consigne systeme commune. Elle repete l'objectif et les interdits parce qu'un agent
# delegue ne partage pas notre historique : il ne sait pas que six experiences ont deja
# ete brulees dans une branche abandonnee.
CADRE = (
    "Tu travailles sur HyperTracker. Objectif UNIQUE du projet : "
    f"{G.OBJECTIF}. "
    "INTERDIT ABSOLU : Liquidity Sweep, recherche d'edge de trading, optimisation "
    "d'execution maker/taker, TP/SL, backtest de strategie. Ces branches sont "
    "definitivement abandonnees. "
    "INTERDIT : modifier un seuil scientifique, un pre-enregistrement scelle, ou "
    "traiter des donnees DERIVED comme OBSERVED. "
    "Si la tache demandee te semble derivee de l'objectif, REFUSE et explique pourquoi. "
    "Rends un compte-rendu court et factuel : ce que tu as constate, ce que tu as fait, "
    "ce qui reste. Pas de reformulation de la consigne."
)


@dataclass
class Delegation:
    tache: str
    objectif: str
    accepte: bool
    motif: str
    sortie: str = ""
    cout_tours: int = 0
    duree_s: float = 0.0
    code_retour: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def disponible() -> bool:
    """Claude Code est-il installe et appelable ?"""
    return shutil.which("claude") is not None


def deleguer(objectif: str, consigne: str, *, max_tours: int = MAX_TOURS,
             delai_s: int = DELAI_S, ecriture: bool = False,
             executeur=None) -> Delegation:
    """
    Confie une tache a Claude Code en headless, sous garde aux deux bouts.

    `ecriture=False` par defaut : la delegation observe et rapporte, elle ne modifie
    pas le depot. Autoriser l'ecriture est une decision qui doit se voir.

    `executeur` permet d'injecter un double dans les tests : aucun appel reel n'est
    necessaire pour verifier que les gardes fonctionnent.
    """
    # --- GARDE AVANT : on ne donne pas au modele l'occasion de deriver
    v = G.verifier_derive(objectif)
    if not v:
        d = Delegation(objectif[:60], objectif, False,
                       f"refuse avant envoi : {v.motifs[0]}")
        _journaliser(d)
        return d

    if executeur is None and not disponible():
        d = Delegation(objectif[:60], objectif, False,
                       "claude introuvable : delegation impossible")
        _journaliser(d)
        return d

    cmd = ["claude", "-p", f"{CADRE}\n\nTACHE : {consigne}",
           "--max-turns", str(max_tours), "--output-format", "text"]
    if not ecriture:
        cmd += ["--permission-mode", "plan"]

    import time
    t0 = time.time()
    try:
        if executeur is not None:
            code, sortie = executeur(cmd)
        else:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=RACINE, timeout=delai_s)
            code, sortie = p.returncode, (p.stdout or p.stderr or "")
    except subprocess.TimeoutExpired:
        d = Delegation(objectif[:60], objectif, False,
                       f"delai de {delai_s}s depasse", duree_s=delai_s)
        _journaliser(d)
        return d
    except Exception as e:
        d = Delegation(objectif[:60], objectif, False, f"{type(e).__name__}: {e}")
        _journaliser(d)
        return d

    duree = round(time.time() - t0, 1)

    # --- GARDE APRES : une sortie qui repart vers l'abandonne n'est pas integree
    vs = G.verifier_derive(sortie[:4000])
    derive = (not vs) and "abandonnee" in (vs.motifs[0] if vs.motifs else "")
    if derive:
        d = Delegation(objectif[:60], objectif, False,
                       f"sortie rejetee : {vs.motifs[0]}", sortie=sortie[:2000],
                       duree_s=duree, code_retour=code)
        _journaliser(d)
        return d

    d = Delegation(objectif[:60], objectif, code == 0,
                   "sans erreur" if code == 0 else f"code de retour {code}",
                   sortie=sortie[:4000], duree_s=duree, code_retour=code)
    _journaliser(d)
    return d


def _journaliser(d: Delegation) -> None:
    lignes = []
    if os.path.exists(JOURNAL):
        try:
            lignes = json.load(open(JOURNAL))
        except Exception:
            lignes = []
    lignes.append(d.as_dict())
    with open(JOURNAL, "w") as f:
        json.dump(lignes, f, indent=1, ensure_ascii=True)
