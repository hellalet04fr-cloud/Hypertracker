#!/usr/bin/env python3
"""
Suivi REEL du quota HyperTracker.

Le compteur local a diverge du serveur : refus HTTP 429 alors que le registre indiquait
76/100 le 2026-08-23, et 98/100 la veille. Trois plafonds differents observes — 100, 98,
76 — ce qui prouve que le registre ne compte pas ce que le serveur compte.

Ce module ne cherche pas a deviner la regle du serveur. Il enregistre ce qui s'est
REELLEMENT passe, code de reponse par code de reponse, et laisse le 429 faire autorite.
Un compteur qu'on croit exact est plus dangereux qu'un compteur qu'on sait approximatif :
le premier fait lancer des lots entiers dans le vide.

Reset serveur mesure : 03:00 UTC. Les collectes reussies des 22 et 23 aout se situent
toutes entre 03:01 et 03:12, jamais avant.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
LEDGER = os.path.join(DATA, "ledger.db")
HEURE_RESET_UTC = 3          # mesure, pas supposee


def _db():
    os.makedirs(DATA, exist_ok=True)
    c = sqlite3.connect(LEDGER, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS requetes(
        ts TEXT NOT NULL, endpoint TEXT NOT NULL, cible TEXT, code INTEGER)""")
    return c


def fenetre_courante() -> datetime:
    """Debut de la fenetre de quota en cours, cote SERVEUR (dernier 03:00 UTC)."""
    m = datetime.now(timezone.utc)
    d = m.replace(hour=HEURE_RESET_UTC, minute=0, second=0, microsecond=0)
    return d if m >= d else d - timedelta(days=1)


def journaliser(endpoint: str, cible: str | None, code: int) -> None:
    """Enregistre l'issue REELLE d'une requete, succes comme refus."""
    with _db() as c:
        c.execute("INSERT INTO requetes VALUES(?,?,?,?)",
                  (datetime.now(timezone.utc).isoformat(), endpoint, cible, int(code)))


def epuise() -> bool:
    """
    Le serveur a-t-il refuse depuis le dernier reset ?

    C'est le SEUL signal digne de confiance. Tant qu'aucun 429 n'est tombe dans la
    fenetre courante, on tente ; des qu'il tombe, on s'arrete pour de bon.
    """
    d = fenetre_courante().isoformat()
    with _db() as c:
        n = c.execute("SELECT COUNT(*) FROM requetes WHERE ts >= ? AND code = 429",
                      (d,)).fetchone()[0]
    return n > 0


def bilan() -> dict:
    """Ce qui s'est reellement passe dans la fenetre de quota en cours."""
    d = fenetre_courante().isoformat()
    with _db() as c:
        lignes = list(c.execute(
            "SELECT code, COUNT(*) FROM requetes WHERE ts >= ? GROUP BY code", (d,)))
    par_code = {int(k): int(v) for k, v in lignes}
    return {"fenetre_debut": d,
            "reussies": par_code.get(200, 0),
            "refusees_429": par_code.get(429, 0),
            "autres": {k: v for k, v in par_code.items() if k not in (200, 429)},
            "total": sum(par_code.values()),
            "epuise": par_code.get(429, 0) > 0}
