#!/usr/bin/env python3
"""
ORCHESTRATEUR. Analyse l'etat, planifie depuis les verrous, arbitre, execute, teste,
audite, journalise, recommence.

Les huit roles demandes (data, quant, research, code, auditor, product, infra) ne sont
pas huit processus : ce seraient huit facons de dupliquer des capacites deja presentes.
Ils sont des TYPES DE TACHE executes par une boucle unique, avec une seule separation
reellement necessaire — l'AUDIT, qui doit pouvoir bloquer et ne peut donc pas etre juge
par celui qui produit.

Trois protections contre l'emballement, parce qu'un systeme autonome se trompe vite :

  BOUCLE      une tache qui echoue deux fois pour le MEME motif est marquee BLOQUEE et
              n'est plus proposee. Reessayer un troisieme fois ne serait pas de la
              tenacite, seulement du gaspillage.
  STAGNATION  plusieurs cycles consecutifs sans progres arretent la boucle avec un
              diagnostic, au lieu de consommer des tokens indefiniment.
  FRONTIERE   un verrou sans patron de tache connu produit un diagnostic, jamais une
              tache improvisee. C'est la limite assumee de l'autonomie.

Reprise : rien ne vit en memoire. Un crash, un redemarrage ou une session differente
repartent du disque.

    python -m ht.orchestrateur           # un cycle
    python -m ht.orchestrateur --boucle  # jusqu'a blocage, stagnation ou epuisement
    python -m ht.orchestrateur --sec     # a blanc : decide sans rien executer
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from . import budgets as B
from . import garde as G
from . import planificateur as P

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETAT = os.path.join(RACINE, "ht", "project_state.json")
TACHES = os.path.join(DATA, "tasks.json")
DECISIONS = os.path.join(DATA, "decisions.json")
CYCLES = os.path.join(DATA, "cycles.json")

ECHECS_AVANT_BLOCAGE = 2        # deux fois le meme motif suffisent a conclure
CYCLES_SANS_PROGRES_MAX = 3


@dataclass
class Resultat:
    tache: str
    objectif: str
    decision: str                   # EXECUTEE | REFUSEE | BLOQUEE | ECHEC | STAGNATION
    motif: str
    raison: str = ""
    sortie: dict = field(default_factory=dict)
    tests: str = ""
    audit: str = ""
    cout: dict = field(default_factory=dict)
    etat_avant: str = ""
    etat_apres: str = ""
    horodatage: str = ""
    prochaine: str = ""
    blocage: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def journal(self, n: int) -> str:
        l = [f"CYCLE            {n}",
             f"OBJECTIF         {self.objectif}",
             f"TACHE CHOISIE    {self.tache}",
             f"RAISON           {self.raison or '—'}",
             f"COUT             {self.cout or '—'}",
             f"RESULTAT         {self.decision} — {self.motif[:120]}",
             f"TESTS            {self.tests or '—'}",
             f"AUDIT            {self.audit or '—'}",
             f"ETAT AVANT       {self.etat_avant or '—'}",
             f"ETAT APRES       {self.etat_apres or '—'}",
             f"PROCHAINE TACHE  {self.prochaine or '—'}"]
        if self.blocage:
            l.append(f"BLOCAGE          {self.blocage}")
        return "\n".join(l)


# --------------------------------------------------------------------------- etat
def charger_etat() -> dict:
    with open(ETAT) as f:
        return json.load(f)


def ecrire_etat(e: dict) -> None:
    e["maj"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(ETAT, "w") as f:
        json.dump(e, f, indent=1, ensure_ascii=True)


def _lire(chemin: str) -> list:
    if not os.path.exists(chemin):
        return []
    try:
        return json.load(open(chemin))
    except Exception:
        return []


def _ajouter(chemin: str, ligne: dict) -> None:
    d = _lire(chemin)
    d.append(ligne)
    with open(chemin, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=True)


def _empreinte_etat(e: dict) -> str:
    """Resume court de l'etat, pour rendre le progres visible d'un cycle a l'autre."""
    ouverts = [v.get("id") for v in e.get("verrous", [])
               if "FERME" not in str(v.get("statut", "")).upper()]
    return f"{e.get('progression_pct', '?')}% | verrous ouverts: {', '.join(ouverts) or 'aucun'}"


# ------------------------------------------------------------------------- boucles
def taches_bloquees() -> dict[str, str]:
    """
    Taches ayant echoue ECHECS_AVANT_BLOCAGE fois pour le meme motif.

    Le motif est normalise sur ses premiers mots : deux echecs identiques a un
    horodatage pres doivent compter comme deux echecs identiques.
    """
    compte: dict[tuple[str, str], int] = {}
    for d in _lire(DECISIONS):
        if d.get("decision") not in ("ECHEC", "BLOQUEE"):
            continue
        cle = (d.get("tache", ""), " ".join(str(d.get("motif", "")).split()[:6]))
        compte[cle] = compte.get(cle, 0) + 1
    return {t: m for (t, m), n in compte.items() if n >= ECHECS_AVANT_BLOCAGE}


def stagnation() -> bool:
    """
    Plusieurs cycles consecutifs sans CHANGEMENT D'ETAT.

    Le progres ne se mesure pas au succes d'execution. Une tache perenne qui reussit
    a chaque tour sans rien deplacer produit des cycles verts et zero avancement :
    mesure reelle, la boucle a tourne 20 fois sur le meme audit avant que ce critere
    ne soit corrige. Ce qui compte est l'empreinte de l'etat avant et apres.
    """
    recents = _lire(CYCLES)[-CYCLES_SANS_PROGRES_MAX:]
    if len(recents) < CYCLES_SANS_PROGRES_MAX:
        return False
    return all(c.get("etat_avant") == c.get("etat_apres") for c in recents)


# ---------------------------------------------------------------------- executeurs
def _t_collecte_observed() -> dict:
    from . import run_plan as RP
    return {"fenetres_collectees": RP.etape_top5(min(30, B.etat().ht_restant))}


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
    v = G.controler("audit d'integrite du classement de wallets et des scelles")
    return {"autorise": v.autorise, "motifs": v.motifs}


def _t_isoler_crash() -> dict:
    """Reproduit le crash natif dans un sous-processus isole et en garde la trace.
    Un acces violation tue l'interpreteur : il ne peut donc pas etre attrape en
    Python, seulement observe depuis l'exterieur."""
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/test_elite.py",
                        "-q", "--no-header", "-p", "no:cacheprovider", "-x"],
                       capture_output=True, text=True, cwd=RACINE, timeout=300)
    s = (p.stdout or "") + (p.stderr or "")
    lignes = [l for l in s.splitlines()
              if "Windows fatal" in l or ".py\", line" in l or "in " in l][:12]
    chemin = os.path.join(DATA, "diagnostic_crash_behavior.txt")
    with open(chemin, "w", encoding="utf8") as f:
        f.write(s)
    return {"code_retour": p.returncode, "trace": lignes[:6], "rapport": chemin}


def _t_deleguer(consigne: str = "", objectif: str = "") -> dict:
    """Confie a Claude Code une tache demandant du jugement. Les gardes s'appliquent
    au prompt AVANT envoi et a la sortie APRES : la delegation n'est pas un
    contournement de l'anti-derive, elle passe par lui deux fois."""
    from . import delegation as D
    d = D.deleguer(objectif or consigne, consigne)
    return {"delegue": True, "accepte": d.accepte, "motif": d.motif,
            "duree_s": d.duree_s, "extrait": (d.sortie or "")[:400]}


EXECUTEURS = {
    "_t_deleguer": _t_deleguer,
    "_t_collecte_observed": _t_collecte_observed,
    "_t_verdict_observed": _t_verdict_observed,
    "_t_rafraichir_produit": _t_rafraichir_produit,
    "_t_audit_integrite": _t_audit_integrite,
    "_t_isoler_crash": _t_isoler_crash,
}

# L'audit ne lance PAS tests/test_autonomie.py : ce fichier execute des cycles, qui
# relanceraient pytest sur lui-meme. On lui associe les tests du chemin produit, qui
# sont ceux dont la rupture invaliderait reellement l'audit.
TESTS_PAR_TACHE = {
    "audit_integrite": ("tests/test_gate.py", "tests/test_final_gate.py"),
    "collecte_observed_top5": ("tests/test_run_plan_top5.py",),
    "verdict_observed": ("tests/test_run_plan_top5.py",),
}


# -------------------------------------------------------------------------- tests
def lancer_tests(chemins: tuple[str, ...]) -> tuple[bool, str]:
    if not chemins:
        return True, "aucun test associe"
    p = subprocess.run([sys.executable, "-m", "pytest", *chemins, "-q", "--no-header",
                        "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=RACINE, timeout=900)
    lignes = (p.stdout or p.stderr or "").strip().splitlines()
    return p.returncode == 0, (lignes[-1] if lignes else "sans sortie")


# -------------------------------------------------------------------------- cycle
def cycle(*, sec: bool = False, ignorer_stagnation: bool = False) -> Resultat:
    e = charger_etat()
    avant = _empreinte_etat(e)

    # 1. GARDE — avant le budget, avant la selection.
    integrite, seuils = G.verifier_scelles(), G.verifier_seuils()
    if not (integrite and seuils):
        r = Resultat("(aucune)", "controle d'integrite", "BLOQUEE",
                     " | ".join(integrite.motifs + seuils.motifs),
                     audit="integrite ROMPUE", etat_avant=avant, etat_apres=avant,
                     horodatage=_now(),
                     prochaine="reparer l'integrite avant toute autre tache",
                     blocage="sceau ou seuil modifie")
        _journaliser(r)
        return r

    # 2. STAGNATION — arrete la BOUCLE, pas une invocation deliberee.
    # Une garde sans porte de sortie transformerait un blocage passager en blocage
    # definitif : apres correction de la cause, le systeme doit pouvoir retenter.
    if stagnation() and not ignorer_stagnation:
        r = Resultat("(aucune)", "diagnostic de stagnation", "STAGNATION",
                     f"{CYCLES_SANS_PROGRES_MAX} cycles consecutifs sans changement d'etat",
                     etat_avant=avant, etat_apres=avant, horodatage=_now(),
                     prochaine="intervention humaine ou attente d'un evenement externe",
                     blocage=_diagnostic_stagnation())
        _journaliser(r)
        return r

    # 3. PLANIFICATION — depuis les verrous, jamais improvisee.
    cands, diags = P.planifier(e)
    # La frontiere de l'autonomie se deplace ici : un verrou sans patron connu ne
    # reste plus un simple diagnostic, il devient une tache DELEGUEE. Claude
    # l'instruit et propose un patron ; il ne l'execute pas de sa propre initiative.
    cands.extend(P.deleguer_diagnostics(diags))
    P.journaliser_plan(cands, diags)
    bloquees = taches_bloquees()

    # 4. ARBITRAGE
    ev = B.etat()
    refus, retenue = list(diags), None
    ids = {c.id for c in cands}
    for c in sorted(cands, key=lambda x: -x.roi):
        if c.id in bloquees:
            refus.append(f"{c.id}: BLOQUEE — {bloquees[c.id]}")
            continue
        vd = G.verifier_derive(c.objectif)
        if not vd:
            refus.append(f"{c.id}: {vd.motifs[0]}")
            continue
        if c.executeur not in EXECUTEURS:
            refus.append(f"{c.id}: aucun executeur lie — a instruire manuellement")
            continue
        if any(d in ids and d not in bloquees for d in c.depend_de):
            refus.append(f"{c.id}: attend {', '.join(c.depend_de)}")
            continue
        ok, motif = B.autorise(c.cout, c.roi, e=ev)
        if not ok:
            refus.append(f"{c.id}: {motif}")
            continue
        retenue = c
        break

    for m in refus:
        _ajouter(DECISIONS, {"horodatage": _now(), "tache": m.split(":")[0],
                             "decision": "NON_RETENUE",
                             "motif": m.split(": ", 1)[-1], "prochaine": ""})

    if retenue is None:
        r = Resultat("(aucune)", "aucune tache executable", "REFUSEE",
                     " | ".join(refus) or "aucun candidat",
                     etat_avant=avant, etat_apres=avant, horodatage=_now(),
                     prochaine="attendre le reset du quota ou un evenement declencheur")
        _journaliser(r)
        return r

    if sec:
        r = Resultat(retenue.id, retenue.objectif, "REFUSEE", "execution a blanc",
                     raison=retenue.raison, cout=retenue.cout.as_dict(),
                     etat_avant=avant, etat_apres=avant, horodatage=_now(),
                     prochaine="relancer sans --sec")
        _journaliser(r)
        return r

    # 5. EXECUTION
    t0 = time.time()
    try:
        fn = EXECUTEURS[retenue.executeur]
        sortie = (fn(consigne=retenue.raison, objectif=retenue.objectif)
                  if retenue.executeur == "_t_deleguer" else fn()) or {}
        decision, motif = "EXECUTEE", "sans erreur"
    except Exception as ex:
        sortie, decision, motif = {}, "ECHEC", f"{type(ex).__name__}: {ex}"

    # 6. TESTS — un echec transforme l'execution en echec, quoi qu'elle ait produit.
    ok_tests, sortie_tests = lancer_tests(TESTS_PAR_TACHE.get(retenue.id, ()))
    if not ok_tests:
        decision, motif = "ECHEC", f"tests rouges : {sortie_tests}"

    # 7. AUDIT — independant de l'execution.
    a = G.controler(retenue.objectif)
    if not a:
        decision, motif = "ECHEC", f"audit refuse : {a.motifs[0]}"

    r = Resultat(retenue.id, retenue.objectif, decision, motif, raison=retenue.raison,
                 sortie=sortie, tests=sortie_tests, audit=a.resume()[:80],
                 cout=dict(retenue.cout.as_dict(), cpu_s_reel=round(time.time() - t0, 1)),
                 etat_avant=avant, horodatage=_now(), prochaine=_prochaine(sortie))

    if decision == "EXECUTEE":
        e["prochaine_action"] = r.prochaine or e.get("prochaine_action", "")
        ecrire_etat(e)
    r.etat_apres = _empreinte_etat(charger_etat())
    _journaliser(r)
    return r


def _diagnostic_stagnation() -> str:
    """Nommer ce qui a tourne sans effet : un diagnostic doit designer, pas resumer."""
    recents = _lire(CYCLES)[-CYCLES_SANS_PROGRES_MAX:]
    taches = [c.get("tache", "?") for c in recents]
    etat = recents[-1].get("etat_apres", "?") if recents else "?"
    return (f"taches sans effet : {', '.join(taches)} | etat inchange : {etat} | "
            f"aucune tache du registre ne peut deplacer cet etat sans une ressource "
            f"actuellement indisponible")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _prochaine(sortie: dict) -> str:
    v = sortie.get("verdict")
    if v == "VALIDE":
        return "publier le classement certifie et figer le produit"
    if v in ("REFUSE", "INCONCLUSIF"):
        return f"verdict {v} : documenter, ne relancer aucune experience"
    if sortie.get("fenetres_collectees"):
        return "appliquer le protocole scelle sur les natifs collectes"
    return ""


def _journaliser(r: Resultat) -> None:
    _ajouter(TACHES, r.as_dict())
    _ajouter(CYCLES, {"horodatage": r.horodatage, "tache": r.tache,
                      "decision": r.decision, "motif": r.motif,
                      "etat_avant": r.etat_avant, "etat_apres": r.etat_apres})
    _ajouter(DECISIONS, {"horodatage": r.horodatage, "tache": r.tache,
                         "decision": r.decision, "motif": r.motif,
                         "prochaine": r.prochaine})


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    sec, boucle = "--sec" in a, "--boucle" in a
    n = 0
    while True:
        # le premier tour est toujours tente : c'est la porte de sortie de la
        # garde anti-stagnation. Les suivants la respectent.
        r = cycle(sec=sec, ignorer_stagnation=(n == 0))
        n += 1
        print(r.journal(n))
        print("-" * 72)
        if not boucle or r.decision in ("REFUSEE", "BLOQUEE", "STAGNATION") or n >= 20:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
