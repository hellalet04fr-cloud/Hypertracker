#!/usr/bin/env python3
"""
Installe, verifie ou retire la tache planifiee « hypertracker-morning ».

08:00 EUROPE/PARIS, ET NON UN DECALAGE FIXE. Le planificateur de taches Windows
declenche a l'heure LOCALE de la machine. Cette machine est reglee sur
Europe/Paris, donc la tache suit d'elle-meme le passage heure d'ete / heure
d'hiver : ecrire « 06:00 UTC » aurait fonctionne six mois par an et se serait
decale d'une heure les six autres, sans rien signaler.

Le module VERIFIE cette hypothese avant d'installer : si l'horloge locale ne
coincide pas avec Europe/Paris, il refuse et le dit, au lieu de poser une tache
qui se declencherait a la mauvaise heure.

    python -m ht.planifier --installer
    python -m ht.planifier --etat
    python -m ht.planifier --retirer
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

NOM = "hypertracker-morning"
HEURE = "08:00"
ZONE = "Europe/Paris"


def coherence_horaire() -> tuple[bool, str]:
    """L'heure locale de la machine est-elle bien celle d'Europe/Paris ?"""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:                                   # pragma: no cover
        return False, "module zoneinfo indisponible"
    paris = datetime.now(ZoneInfo(ZONE))
    local = datetime.now().astimezone()
    if paris.utcoffset() != local.utcoffset():
        return False, (f"l'horloge locale ({local.tzname()}, {local.utcoffset()}) "
                       f"ne coincide pas avec {ZONE} ({paris.tzname()}, "
                       f"{paris.utcoffset()}) : la tache se declencherait a "
                       f"{HEURE} locale, pas a {HEURE} a Paris")
    return True, (f"horloge locale alignee sur {ZONE} "
                  f"({local.tzname()}, decalage {local.utcoffset()})")


def commande() -> str:
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    journal = os.path.join(os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data"),
                           "matin.log")
    return (f'cmd /c cd /d "{racine}" && '
            f'"{sys.executable}" -m ht.matin >> "{journal}" 2>&1')


def _schtasks(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          encoding="utf8", errors="replace")


def installer(force: bool = False) -> int:
    ok, motif = coherence_horaire()
    print(f"  fuseau : {motif}")
    if not ok and not force:
        print("  REFUS : corriger le fuseau de la machine, ou passer --force en "
              "connaissance de cause.")
        return 2
    r = _schtasks(["/Create", "/TN", NOM, "/SC", "DAILY", "/ST", HEURE,
                   "/TR", commande(), "/F", "/RL", "LIMITED"])
    print((r.stdout or r.stderr).strip())
    if r.returncode != 0:
        print("  ECHEC de l'installation.")
        return r.returncode
    print(f"  tache « {NOM} » installee — tous les jours a {HEURE} ({ZONE})")
    return 0


def etat() -> int:
    r = _schtasks(["/Query", "/TN", NOM, "/V", "/FO", "LIST"])
    if r.returncode != 0:
        print(f"  tache « {NOM} » absente")
        return 1
    garder = ("Nom de la tâche", "TaskName", "Prochaine", "Next Run",
              "Dernière", "Last Run", "État", "Status", "Résultat", "Last Result")
    for ligne in (r.stdout or "").splitlines():
        if any(ligne.strip().startswith(g) for g in garder):
            print("  " + ligne.strip())
    ok, motif = coherence_horaire()
    print(f"  fuseau : {motif}")
    return 0


def retirer() -> int:
    r = _schtasks(["/Delete", "/TN", NOM, "/F"])
    print((r.stdout or r.stderr).strip())
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tache planifiee HyperTracker")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--installer", action="store_true")
    g.add_argument("--etat", action="store_true")
    g.add_argument("--retirer", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="installer malgre un fuseau non aligne sur Europe/Paris")
    a = ap.parse_args(argv)
    if a.installer:
        return installer(a.force)
    if a.etat:
        return etat()
    return retirer()


if __name__ == "__main__":
    raise SystemExit(main())
