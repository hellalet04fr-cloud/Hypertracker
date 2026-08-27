#!/usr/bin/env python3
"""
Decouverte quotidienne de wallets candidats.

ZERO REQUETE HYPERTRACKER. Les deux sources sont deja sur disque et n'ont aucun
cout : les instantanes de carnet d'ordres (`orders_5m`) et les classements
HyperTracker deja collectes (`leaderboards_*`). La decouverte ne consomme donc
jamais le quota, ce qui est la condition pour qu'elle puisse tourner tous les
matins sans arbitrage.

LA DECOUVERTE EST INDEPENDANTE DU CLASSEMENT. Elle ne regarde ni les scores ni
les rangs : un wallet absent du Top 20 doit pouvoir devenir candidat demain, et
un wallet jamais vu doit pouvoir entrer sans qu'on lui demande d'abord d'etre
bon. Selectionner les candidats sur la performance fabriquerait un classement de
survivants — c'est exactement le biais que la selection par hachage evite.

Chaque decouverte porte sa PROVENANCE et sa DATE. Ce sont des faits : ils ne
sont jamais reecrits si le wallet est revu par une autre source.
"""
from __future__ import annotations

import glob
import os

from . import registre as R

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
LONGUEUR_ADRESSE = 42

# Pseudo-adresse des ordres TWAP du protocole : ce n'est pas un wallet.
PSEUDO = {"0x" + "0" * 40}


def _valide(a: str) -> bool:
    a = a.lower()
    return (len(a) == LONGUEUR_ADRESSE and a.startswith("0x")
            and a not in PSEUDO and set(a[2:]) != {"0"})


def depuis_carnets(limite: int | None = None) -> set[str]:
    """Adresses vues dans les instantanes de carnet d'ordres.

    C'est la population NON BIAISEE : y figurer signifie avoir un ordre au
    carnet, pas avoir gagne. Lecture DuckDB directe sur les Parquet ; a 16,5 M de
    lignes, un `select distinct` coute quelques secondes et zero requete reseau.
    """
    import duckdb
    fichiers = glob.glob(os.path.join(DATA, "orders_5m", "**", "*.parquet"), recursive=True)
    if not fichiers:
        return set()
    con = duckdb.connect()
    tmp = os.path.join(DATA, "duckdb_tmp")
    os.makedirs(tmp, exist_ok=True)
    con.execute("set temp_directory=?", [tmp])
    con.execute("set preserve_insertion_order=false")
    liste = "[" + ",".join("'" + f.replace("'", "''") + "'" for f in fichiers) + "]"
    q = (f"select distinct lower(address) a from read_parquet({liste}) "
         f"where address is not null and length(address) = {LONGUEUR_ADRESSE}")
    if limite:
        q += f" limit {int(limite)}"
    return {r[0] for r in con.execute(q).fetchall() if _valide(r[0])}


def depuis_leaderboards() -> set[str]:
    """Adresses des classements HyperTracker deja telecharges.

    Population BIAISEE PAR SURVIE, et declaree comme telle : on n'y voit que ceux
    qui ont gagne et qui tradent encore. Elle sert a decouvrir, pas a mesurer —
    la qualification qui suit applique les memes criteres a tout le monde.
    """
    import pyarrow.parquet as pq
    out: set[str] = set()
    for f in glob.glob(os.path.join(DATA, "leaderboards_*", "**", "*.parquet"),
                       recursive=True):
        try:
            t = pq.read_table(f, columns=["address"])
        except Exception:
            continue
        for a in t.column("address").to_pylist():
            a = str(a or "").lower()
            if _valide(a):
                out.add(a)
    return out


SOURCES = {
    "carnet": depuis_carnets,
    "leaderboard": depuis_leaderboards,
}


def decouvrir(c, *, sources: tuple[str, ...] = ("carnet", "leaderboard"),
              limite_carnet: int | None = None, dry_run: bool = False) -> dict:
    """Ajoute les adresses inconnues en DISCOVERY. Retourne le bilan par source.

    La deduplication est double : au sein du lot, et contre le registre. Un
    wallet deja connu n'est pas retouche — ni sa provenance, ni sa date de
    premiere vue, qui sont des faits historiques.
    """
    bilan = {"nouveaux": 0, "deja_connus": 0, "par_source": {}, "erreurs": {}}
    vus: set[str] = set()
    for nom in sources:
        try:
            trouvees = SOURCES[nom]() if nom != "carnet" else depuis_carnets(limite_carnet)
        except Exception as e:                      # source indisponible : on le dit
            bilan["erreurs"][nom] = f"{type(e).__name__}: {e}"
            bilan["par_source"][nom] = 0
            continue
        neufs = 0
        for a in sorted(trouvees):
            if a in vus:
                continue
            vus.add(a)
            if dry_run:
                if R.wallet(c, a) is None:
                    neufs += 1
                else:
                    bilan["deja_connus"] += 1
            elif R.enregistrer_decouverte(c, a, nom):
                neufs += 1
            else:
                bilan["deja_connus"] += 1
        bilan["par_source"][nom] = neufs
        bilan["nouveaux"] += neufs
    if not dry_run:
        c.commit()
    return bilan
