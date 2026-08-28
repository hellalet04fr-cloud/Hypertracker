#!/usr/bin/env python3
"""
LA PORTE UNIQUE. Une commande, un verdict.

Le projet avait cinq controles, chacun excellent et chacun lance a la main —
donc lance rarement, donc inutile la moitie du temps. Ce module les enchaine et
rend UN verdict. Un garde-fou qu'on doit se rappeler d'invoquer n'en est pas un.

    python -m ht.verifier              tout, dans l'ordre du moins cher au plus cher
    python -m ht.verifier --rapide     s'arrete avant les controles navigateur
    python -m ht.verifier --etape garde

ORDRE DELIBERE : du moins cher au plus cher, et ARRET AU PREMIER ECHEC BLOQUANT.
Verifier l'interface quand la garde scientifique est deja tombee ne renseigne
sur rien et coute une minute.

CE QUE CHAQUE ETAPE PROUVE — elles ne se recouvrent pas :

  garde        aucun seuil scelle n'a bouge, aucune branche abandonnee n'est
               rouverte, DERIVED ne certifie pas
  tests        les 410 tests rapides passent
  donnees      les donnees preparees redisent les fichiers bruts (12 compteurs)
  regressions  les defauts confirmes par l'audit du 2026-08-28 ne reviennent pas
  coherence    l'ECRAN affiche ce que le MOTEUR a calcule
  fonctions    les 114 parcours de l'interface repondent

La quatrieme est celle qui manquait le plus : une valeur peut etre juste en base,
la fonctionnalite marcher, et l'ecran montrer autre chose.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
JOURNAL = os.path.join(DATA, "verifications.json")


class Etape:
    """Une verification. `bloquante` decide si l'echec arrete la chaine."""

    def __init__(self, cle, titre, prouve, commande, bloquante=True, navigateur=False):
        self.cle, self.titre, self.prouve = cle, titre, prouve
        self.commande, self.bloquante, self.navigateur = commande, bloquante, navigateur


ETAPES = [
    Etape("garde", "Garde scientifique",
          "seuils scelles, branches abandonnees, provenance",
          [sys.executable, "-c",
           "import ht.garde as G,sys;"
           "v=[G.verifier_derive(G.OBJECTIF),G.verifier_scelles(),G.verifier_seuils()];"
           "[print('  '+m) for x in v for m in x.motifs];"
           "p=G.verifier_provenance('DERIVED','certification');"
           "print('  DERIVED ne certifie pas :', not p.autorise);"
           "sys.exit(0 if all(x.autorise for x in v) and not p.autorise else 1)"]),
    Etape("tests", "Tests rapides",
          "410 tests unitaires et de comportement",
          [sys.executable, "-m", "pytest", "-q"]),
    Etape("donnees", "Authenticite des donnees",
          "12 compteurs a zero : aucune donnee fictive",
          [sys.executable, "-m", "app.audit_donnees"]),
    Etape("regressions", "Regressions de l'audit",
          "les 29 defauts confirmes ne reviennent pas",
          ["node", "tests/regressions.js"], navigateur=True),
    Etape("coherence", "Coherence ecran / moteur",
          "ce qui est affiche egale ce qui a ete calcule",
          ["node", "tests/coherence_ui.js"], navigateur=True),
    Etape("fonctions", "Fonctionnalites",
          "114 parcours exerces dans un navigateur reel",
          ["node", "tests/audit_fonctionnalites.js"], navigateur=True,
          bloquante=False),
]


def _tuer_navigateurs() -> None:
    """Un Edge residuel retient le port de debogage et sert l'ANCIENNE page : le
    controle passerait alors sur une interface qui n'est plus celle du depot."""
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"],
                   capture_output=True, text=True)


def executer(etape: Etape, verbeux: bool = True) -> dict:
    if etape.navigateur:
        _tuer_navigateurs()
        time.sleep(1)
    t0 = time.time()
    r = subprocess.run(etape.commande, cwd=RACINE, capture_output=True,
                       text=True, encoding="utf8", errors="replace")
    duree = time.time() - t0
    sortie = ((r.stdout or "") + (r.stderr or "")).strip()
    ok = r.returncode == 0
    if verbeux:
        marque = "OK  " if ok else ("!!  " if etape.bloquante else "~~  ")
        print(f"  {marque}{etape.titre:<28} {duree:>6.1f}s  {etape.prouve}")
        if not ok:
            for l in sortie.splitlines()[-14:]:
                print("        " + l)
    return {"etape": etape.cle, "titre": etape.titre, "ok": ok,
            "code": r.returncode, "duree_s": round(duree, 1),
            "bloquante": etape.bloquante,
            "sortie": sortie[-2500:]}


def verifier(rapide: bool = False, seulement: str | None = None,
             verbeux: bool = True) -> dict:
    choix = [e for e in ETAPES
             if (not seulement or e.cle == seulement)
             and (not rapide or not e.navigateur)]
    if verbeux:
        print("=" * 72)
        print("VERIFICATION HYPERTRACKER" + ("  (rapide)" if rapide else ""))
        print("=" * 72)
    res, arret = [], None
    for e in choix:
        d = executer(e, verbeux)
        res.append(d)
        if not d["ok"] and e.bloquante:
            arret = e.cle
            if verbeux:
                print(f"\n  ARRET : « {e.titre} » a echoue. Les etapes suivantes ne "
                      f"renseigneraient sur rien.")
            break

    bloquants = [d for d in res if not d["ok"] and d["bloquante"]]
    reserves = [d for d in res if not d["ok"] and not d["bloquante"]]
    verdict = ("CONFORME" if not bloquants and not reserves else
               "CONFORME AVEC RESERVE" if not bloquants else "NON CONFORME")
    bilan = {"horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "verdict": verdict, "arret": arret, "etapes": res,
             "duree_s": round(sum(d["duree_s"] for d in res), 1)}
    try:
        h = json.load(open(JOURNAL, encoding="utf8")) if os.path.exists(JOURNAL) else []
        h.append(bilan)
        with open(JOURNAL, "w", encoding="utf8") as f:
            json.dump(h[-60:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass                      # journaliser ne doit jamais faire echouer la porte
    if verbeux:
        print("=" * 72)
        print(f"VERDICT : {verdict}   ({bilan['duree_s']}s, "
              f"{len(res)} etape(s) sur {len(ETAPES)})")
        if reserves:
            print("  reserve : " + ", ".join(d["titre"] for d in reserves))
        print("=" * 72)
    return bilan


def _modifie() -> bool:
    """Le depot a-t-il change ? Sans cela, le crochet tournerait aussi sur les
    tours de conversation, ou il n'a rien a verifier — 35 secondes pour rien."""
    r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "app", "ht", "tests"],
                       cwd=RACINE, capture_output=True)
    if r.returncode != 0:
        return True
    r = subprocess.run(["git", "status", "--porcelain", "--", "app", "ht", "tests"],
                       cwd=RACINE, capture_output=True, text=True)
    return bool((r.stdout or "").strip())


def hook() -> int:
    """Mode crochet : silencieux quand tout va bien, bruyant quand ca casse.

    Il NE BLOQUE JAMAIS. Un crochet de fin de tour qui bloque peut boucler, et
    surtout : verifier n'est pas decider. Il constate et le dit ; ce qu'on en
    fait reste humain.
    """
    if not _modifie():
        print(json.dumps({"suppressOutput": True}))
        return 0
    b = verifier(rapide=True, verbeux=False)
    if b["verdict"] == "CONFORME":
        msg = f"Vérification : CONFORME ({b['duree_s']}s)"
    else:
        casses = [d["titre"] for d in b["etapes"] if not d["ok"]]
        msg = (f"Vérification : {b['verdict']} — {', '.join(casses)}. "
               f"Détail : python -m ht.verifier --rapide")
    print(json.dumps({"systemMessage": msg, "suppressOutput": True},
                     ensure_ascii=False))
    return 0


def _console_utf8() -> None:
    """La console Windows est en cp1252 : le premier caractere hors table tue le
    rapport au moment ou il compte le plus. On remplace plutot que de mourir."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description="Porte de verification HyperTracker")
    ap.add_argument("--rapide", action="store_true",
                    help="s'arrete avant les controles navigateur")
    ap.add_argument("--etape", choices=[e.cle for e in ETAPES],
                    help="n'executer qu'une etape")
    ap.add_argument("--hook", action="store_true",
                    help="mode crochet : ne verifie que si le depot a change, "
                         "rend un JSON, ne bloque jamais")
    a = ap.parse_args(argv)
    if a.hook:
        return hook()
    b = verifier(rapide=a.rapide, seulement=a.etape)
    return 0 if b["verdict"].startswith("CONFORME") else 1


if __name__ == "__main__":
    raise SystemExit(main())
