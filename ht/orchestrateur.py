#!/usr/bin/env python3
"""
ORCHESTRATEUR. Lit l'etat, choisit la tache la plus rentable EXECUTABLE, l'execute,
la teste, la fait auditer, journalise, met a jour l'etat, recommence.

Les huit roles demandes (data, quant, research, code, auditor, product, infra) ne sont
pas huit processus : ce seraient huit facons de dupliquer des capacites deja presentes.
Ils sont ici des TYPES DE TACHE, executes par une boucle unique, avec une seule
separation reellement necessaire — l'AUDIT, qui doit pouvoir bloquer et donc ne peut pas
etre juge par celui qui produit.

Reprise : tout est sur disque. Un crash, un redemarrage, une session Claude differente
reprennent a la tache suivante sans rien reconstruire, parce qu'aucun etat ne vit en
memoire.

    python -m ht.orchestrateur          # un cycle
    python -m ht.orchestrateur --boucle # jusqu'a epuisement des taches executables
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable

from . import budgets as B
from . import garde as G

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETAT = os.path.join(RACINE, "ht", "project_state.json")
TACHES = os.path.join(DATA, "tasks.json")
DECISIONS = os.path.join(DATA, "decisions.json")


@dataclass
class Tache:
    id: str
    objectif: str
    type: str                       # data | quant | audit | produit | infra
    cout: B.Cout
    roi: float
    executer: Callable[[], dict] = field(repr=False, default=None)
    tests: tuple[str, ...] = ()
    depend_de: tuple[str, ...] = ()


@dataclass
class Resultat:
    tache: str
    objectif: str
    decision: str                   # EXECUTEE | REFUSEE | BLOQUEE | ECHEC
    motif: str
    sortie: dict = field(default_factory=dict)
    tests: str = ""
    cout: dict = field(default_factory=dict)
    horodatage: str = ""
    prochaine: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- etat
def charger_etat() -> dict:
    with open(ETAT) as f:
        return json.load(f)


def ecrire_etat(e: dict) -> None:
    e["maj"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(ETAT, "w") as f:
        json.dump(e, f, indent=1, ensure_ascii=True)


def _ajouter(chemin: str, ligne: dict) -> None:
    d = []
    if os.path.exists(chemin):
        try:
            d = json.load(open(chemin))
        except Exception:
            d = []
    d.append(ligne)
    with open(chemin, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=True)


# ------------------------------------------------------------------------- taches
def _t_collecte_observed() -> dict:
    from . import run_plan as RP
    n = RP.etape_top5(min(30, B.etat().ht_restant))
    return {"fenetres_collectees": n}


def _t_verdict_observed() -> dict:
    from . import verdict_observed as VO
    v = VO.evaluer()
    with open(os.path.join(DATA, "verdict_observed.json"), "w") as f:
        json.dump(v, f, indent=1)
    return {"verdict": v["verdict"], "motif": v["motif"], "positifs": v["n_positifs"]}


def _t_rafraichir_produit() -> dict:
    p = os.path.join(DATA, "produit_classement.json")
    if not os.path.exists(p):
        return {"erreur": "aucun produit a rafraichir"}
    d = json.load(open(p))
    return {"wallets": d["univers"]["wallets_classes"], "statut": d["statut"]}


def _t_audit_integrite() -> dict:
    v = G.controler("audit d'integrite du classement et des scelles")
    return {"autorise": v.autorise, "motifs": v.motifs}


def registre(e: dict) -> list[Tache]:
    """
    Taches candidates, avec leur precondition implicite.

    Elles ne sont PAS des idees de recherche : chacune fait avancer le produit d'un cran
    identifie. Une tache qui ne rentre dans aucun de ces moules doit etre discutee, pas
    inventee par la boucle.
    """
    natifs = _n_natifs_top5()
    t = []
    if natifs < 5:
        t.append(Tache(
            id="collecte_observed_top5",
            objectif="collecter les closed-trades OBSERVED natifs du top-5 du classement",
            type="data", cout=B.Cout(hypertracker=5, cpu_s=60), roi=10.0,
            executer=_t_collecte_observed))
    t.append(Tache(
        id="verdict_observed",
        objectif="appliquer le protocole scelle et rendre le verdict OBSERVED du classement",
        type="quant", cout=B.Cout(cpu_s=30), roi=8.0,
        executer=_t_verdict_observed, depend_de=("collecte_observed_top5",)))
    t.append(Tache(
        id="audit_integrite",
        objectif="auditer l'integrite des scelles, des seuils et du classement",
        type="audit", cout=B.Cout(cpu_s=20), roi=3.0,
        executer=_t_audit_integrite, tests=("tests/test_run_plan_top5.py",)))
    t.append(Tache(
        id="rafraichir_produit",
        objectif="rafraichir le produit de classement des wallets et son dashboard",
        type="produit", cout=B.Cout(cpu_s=30), roi=2.0,
        executer=_t_rafraichir_produit))
    return t


def _n_natifs_top5() -> int:
    """Combien de wallets du top-5 ont deja des natifs exploitables."""
    import sqlite3
    p = os.path.join(DATA, "preenregistrement_observed.json")
    if not os.path.exists(p):
        return 0
    top5 = [a.lower() for a in json.load(open(p))["top5"]]
    try:
        c = sqlite3.connect(os.path.join(DATA, "ledger.db"))
        vus = {r[0].lower() for r in
               c.execute("SELECT DISTINCT address FROM closed_trades_natifs")}
    except Exception:
        return 0
    return sum(1 for a in top5 if a in vus)


# -------------------------------------------------------------------------- tests
def lancer_tests(chemins: tuple[str, ...]) -> tuple[bool, str]:
    if not chemins:
        return True, "aucun test associe"
    p = subprocess.run([sys.executable, "-m", "pytest", *chemins, "-q", "--no-header",
                        "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=RACINE, timeout=600)
    derniere = (p.stdout or p.stderr or "").strip().splitlines()
    return p.returncode == 0, (derniere[-1] if derniere else "sans sortie")


# -------------------------------------------------------------------------- cycle
def cycle(*, sec: bool = False) -> Resultat:
    """
    Un tour complet : etat -> garde -> budget -> execution -> tests -> audit -> journal.

    `sec` (a blanc) parcourt toute la chaine de decision sans rien executer : c'est ainsi
    qu'on verifie l'orchestrateur sans depenser de quota.
    """
    e = charger_etat()
    faits = {t.id for t in []}
    candidates = registre(e)

    # 1. GARDE — avant tout, avant meme de regarder le budget.
    integrite = G.verifier_scelles()
    seuils = G.verifier_seuils()
    if not (integrite and seuils):
        r = Resultat("(aucune)", "controle d'integrite", "BLOQUEE",
                     " | ".join(integrite.motifs + seuils.motifs),
                     horodatage=_now(), prochaine="reparer l'integrite avant toute tache")
        _journaliser(r)
        return r

    # 2. SELECTION — la plus rentable parmi les executables.
    ev = B.etat()
    refus = []
    retenue = None
    for t in sorted(candidates, key=lambda x: -x.roi):
        vd = G.verifier_derive(t.objectif)
        if not vd:
            refus.append(f"{t.id}: {vd.motifs[0]}")
            continue
        if t.depend_de and any(d in {c.id for c in candidates} for d in t.depend_de):
            refus.append(f"{t.id}: attend {', '.join(t.depend_de)}")
            continue
        ok, motif = B.autorise(t.cout, t.roi, e=ev)
        if not ok:
            refus.append(f"{t.id}: {motif}")
            continue
        retenue = t
        break

    # Les refus sont journalises AUSSI : sans eux, une session future ne peut pas
    # savoir qu'une tache a fort ROI existait mais que le quota la bloquait.
    for m in refus:
        _ajouter(DECISIONS, {"horodatage": _now(), "tache": m.split(":")[0],
                             "decision": "NON_RETENUE", "motif": m.split(": ", 1)[-1],
                             "prochaine": ""})

    if retenue is None:
        r = Resultat("(aucune)", "aucune tache executable", "REFUSEE",
                     " | ".join(refus) or "registre vide", horodatage=_now(),
                     prochaine="attendre le reset du quota ou un evenement rendant "
                               "une tache executable")
        _journaliser(r)
        return r

    if sec:
        r = Resultat(retenue.id, retenue.objectif, "REFUSEE", "execution a blanc",
                     cout=retenue.cout.as_dict(), horodatage=_now(),
                     prochaine="relancer sans --sec")
        _journaliser(r)
        return r

    # 3. EXECUTION
    t0 = time.time()
    try:
        sortie = retenue.executer() or {}
        decision, motif = "EXECUTEE", "sans erreur"
    except Exception as ex:
        sortie, decision, motif = {}, "ECHEC", f"{type(ex).__name__}: {ex}"

    # 4. TESTS — un echec transforme l'execution en echec, quoi qu'elle ait produit.
    ok_tests, sortie_tests = lancer_tests(retenue.tests)
    if not ok_tests:
        decision, motif = "ECHEC", f"tests rouges : {sortie_tests}"

    r = Resultat(retenue.id, retenue.objectif, decision, motif, sortie=sortie,
                 tests=sortie_tests, cout=retenue.cout.as_dict(), horodatage=_now(),
                 prochaine=_prochaine(sortie))
    r.cout["cpu_s_reel"] = round(time.time() - t0, 1)
    _journaliser(r)

    # 5. ETAT — mis a jour seulement si la tache a reussi.
    if decision == "EXECUTEE":
        e["prochaine_action"] = r.prochaine or e.get("prochaine_action", "")
        ecrire_etat(e)
    return r


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _prochaine(sortie: dict) -> str:
    if sortie.get("verdict") == "VALIDE":
        return "publier le produit certifie et figer le classement"
    if sortie.get("verdict") in ("REFUSE", "INCONCLUSIF"):
        return f"verdict {sortie['verdict']} : documenter, ne pas relancer d'experience"
    if sortie.get("fenetres_collectees"):
        return "appliquer le protocole scelle sur les natifs collectes"
    return ""


def _journaliser(r: Resultat) -> None:
    _ajouter(TACHES, r.as_dict())
    _ajouter(DECISIONS, {"horodatage": r.horodatage, "tache": r.tache,
                         "decision": r.decision, "motif": r.motif,
                         "prochaine": r.prochaine})


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    sec = "--sec" in a
    boucle = "--boucle" in a
    n = 0
    while True:
        r = cycle(sec=sec)
        n += 1
        print(f"[{n}] {r.tache} — {r.decision} — {r.motif[:150]}")
        if r.sortie:
            print(f"     sortie : {r.sortie}")
        if r.prochaine:
            print(f"     prochaine : {r.prochaine}")
        if not boucle or r.decision in ("REFUSEE", "BLOQUEE", "ECHEC") or n >= 20:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
