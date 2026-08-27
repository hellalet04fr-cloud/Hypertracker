#!/usr/bin/env python3
"""
Registre persistant des wallets : etats, historique, alertes, journal de cycle.

TROIS ETATS, ET UNE REGLE QUI NE PLIE PAS

  DISCOVERY  decouvert, pas encore assez documente pour etre classe. Il accumule
             des donnees et sera reexamine.
  RANKED     satisfait les criteres de candidature deja definis par le projet.
             Il apparait dans l'application.
  ARCHIVED   ne les satisfait plus. Il disparait du classement actif.

ARCHIVER N'EST PAS SUPPRIMER. Aucune ligne d'historique n'est jamais effacee ;
un wallet archive conserve ses scores, ses rangs, ses metriques, la raison et la
date de son retrait. Il revient automatiquement en RANKED s'il redevient
qualifie. C'est pour cela que l'historique est une table en append seul et que
rien, dans ce module, ne propose de DELETE.

SQLite plutot que JSON : a plusieurs milliers de wallets, relire et reecrire un
document entier a chaque changement d'etat devient le poste de cout dominant, et
une interruption en cours d'ecriture perd tout le fichier. Ici chaque ecriture
est une transaction, et une reprise apres arret brutal retrouve un etat coherent.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
BASE = os.path.join(DATA, "registre.db")

DISCOVERY = "DISCOVERY"
RANKED = "RANKED"
ARCHIVED = "ARCHIVED"
ETATS = (DISCOVERY, RANKED, ARCHIVED)

_SCHEMA = """
create table if not exists wallets (
    adresse         text primary key,
    statut          text not null,
    source          text not null,
    decouvert_le    integer not null,
    evalue_le       integer,
    maj_le          integer not null,
    watch           integer not null default 0,
    sale            integer not null default 1,   -- a reevaluer
    n_trades        integer,
    score           real,
    rang            integer,
    confiance       text,
    qualite         integer,
    classe          text,                          -- verdict de qualification
    archive_raison  text,
    archive_le      integer
);
create index if not exists idx_wallets_statut on wallets(statut);
create index if not exists idx_wallets_sale   on wallets(sale);

-- APPEND SEUL. Aucune requete de ce module ne supprime d'historique.
create table if not exists historique (
    id        integer primary key autoincrement,
    ts        integer not null,
    adresse   text not null,
    statut    text not null,
    score     real,
    rang      integer,
    confiance text,
    qualite   integer,
    n_trades  integer,
    conc      real,
    dd        real,
    jours     real,
    sr        real,
    raison    text not null
);
create index if not exists idx_hist_adresse on historique(adresse, ts);

create table if not exists alertes (
    id        integer primary key autoincrement,
    ts        integer not null,
    cycle_id  text not null,
    categorie text not null,
    adresse   text,
    cle       text not null unique,   -- deduplication
    message   text not null,
    details   text
);
create index if not exists idx_alertes_ts on alertes(ts);

create table if not exists journal (
    id             integer primary key autoincrement,
    cycle_id       text not null,
    ts             integer not null,
    phase          text not null,
    tache          text not null,
    adresse        text,
    cout_estime    integer default 0,
    cout_reel      integer default 0,
    resultat       text,
    erreur         text,
    decision       text,
    raison         text,
    statut_avant   text,
    statut_apres   text
);
create index if not exists idx_journal_cycle on journal(cycle_id, ts);

create table if not exists cycles (
    cycle_id  text primary key,
    debut     integer not null,
    fin       integer,
    mode      text not null,          -- reel | dry-run
    resultat  text,
    resume    text
);
"""


def maintenant() -> int:
    return int(time.time())


# Colonnes ajoutees apres coup. La migration est ADDITIVE et IDEMPOTENTE : on
# ajoute ce qui manque, on ne recree rien, on ne supprime jamais. Une base
# existante garde donc son historique complet.
_COLONNES_AJOUTEES = (
    # OBSERVED des qu'une donnee native HyperTracker existe pour ce wallet ; sinon
    # DERIVED. Jamais deduit d'autre chose, jamais converti.
    ("wallets", "provenance", "text"),
    ("wallets", "raison_decouverte", "text"),
    ("wallets", "dernier_cycle", "text"),
    ("wallets", "derniere_collecte", "integer"),
    # nombre de retours ARCHIVED -> RANKED : un wallet qui fait le yoyo est une
    # information en soi, et elle se perdrait dans le detail de l'historique.
    ("wallets", "n_retours", "integer"),
    ("wallets", "promu_le", "integer"),
    ("historique", "cycle_id", "text"),
)


def _migrer(c: sqlite3.Connection) -> None:
    for table, colonne, typ in _COLONNES_AJOUTEES:
        existantes = {r[1] for r in c.execute(f"pragma table_info({table})")}
        if colonne not in existantes:
            c.execute(f"alter table {table} add column {colonne} {typ}")
    c.commit()


def connexion(chemin: str | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(chemin or BASE)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=WAL")     # survit a un arret brutal
    c.execute("pragma foreign_keys=ON")
    c.executescript(_SCHEMA)
    _migrer(c)
    return c


# --------------------------------------------------------------------- wallets
def enregistrer_decouverte(c, adresse: str, source: str, *, ts: int | None = None,
                           raison: str = "", provenance: str = "DERIVED",
                           cycle_id: str | None = None) -> bool:
    """Insere un wallet inconnu en DISCOVERY. Retourne True s'il etait nouveau.

    Un wallet deja connu n'est PAS reecrit : sa date de premiere decouverte, sa
    source et sa raison de decouverte sont des FAITS historiques, pas des champs
    a rafraichir. C'est aussi ce qui rend la decouverte idempotente — relancer le
    cycle deux fois ne recree ni ne renomme personne.

    `provenance` vaut DERIVED par defaut : un wallet simplement apercu dans un
    carnet n'a aucune donnee native. Il ne passe a OBSERVED que lorsqu'une donnee
    native existe reellement, et jamais par deduction.
    """
    ts = ts or maintenant()
    cur = c.execute(
        "insert or ignore into wallets (adresse, statut, source, decouvert_le, maj_le,"
        " provenance, raison_decouverte, dernier_cycle)"
        " values (?, ?, ?, ?, ?, ?, ?, ?)",
        (adresse.lower(), DISCOVERY, source, ts, ts, provenance, raison, cycle_id))
    return cur.rowcount > 0


def wallet(c, adresse: str) -> sqlite3.Row | None:
    return c.execute("select * from wallets where adresse = ?", (adresse.lower(),)).fetchone()


def par_statut(c, statut: str) -> list[sqlite3.Row]:
    return c.execute("select * from wallets where statut = ? order by rang is null, rang",
                     (statut,)).fetchall()


def compter(c) -> dict:
    r = {s: 0 for s in ETATS}
    for row in c.execute("select statut, count(*) n from wallets group by statut"):
        r[row["statut"]] = row["n"]
    r["watch"] = c.execute("select count(*) n from wallets where watch = 1").fetchone()["n"]
    r["sales"] = c.execute("select count(*) n from wallets where sale = 1").fetchone()["n"]
    return r


def a_reevaluer(c, limite: int | None = None) -> list[str]:
    """Wallets marques sales, dans l'ordre de PRIORITE defini plus haut.

    Deterministe : meme registre, meme ordre. C'est ce qui rend un cycle
    reproductible et un dry-run fidele a ce que fera le cycle reel.
    """
    q = f"select adresse from wallets where sale = 1 order by {priorite_sql()}"
    if limite:
        q += f" limit {int(limite)}"
    return [r["adresse"] for r in c.execute(q)]


def marquer_sale(c, adresses: Iterable[str], sale: bool = True) -> None:
    c.executemany("update wallets set sale = ?, maj_le = ? where adresse = ?",
                  [(1 if sale else 0, maintenant(), a.lower()) for a in adresses])


def suivre(c, adresse: str, actif: bool = True) -> None:
    c.execute("update wallets set watch = ?, maj_le = ? where adresse = ?",
              (1 if actif else 0, maintenant(), adresse.lower()))


def majw(c, adresse: str, **champs) -> None:
    if not champs:
        return
    champs["maj_le"] = maintenant()
    cols = ", ".join(f"{k} = ?" for k in champs)
    c.execute(f"update wallets set {cols} where adresse = ?",
              (*champs.values(), adresse.lower()))


def transition(c, adresse: str, vers: str, raison: str, *,
               metriques: dict | None = None, ts: int | None = None,
               cycle_id: str | None = None) -> str:
    """Change l'etat d'un wallet ET inscrit la trace. Les deux vont ensemble :
    un changement d'etat sans raison enregistree est un changement qu'on ne
    saura pas expliquer demain. Retourne l'etat precedent."""
    assert vers in ETATS, vers
    ts = ts or maintenant()
    w = wallet(c, adresse)
    avant = w["statut"] if w else None
    if w is None:
        c.execute("insert into wallets (adresse, statut, source, decouvert_le, maj_le)"
                  " values (?, ?, ?, ?, ?)", (adresse.lower(), vers, "transition", ts, ts))
    else:
        champs = {"statut": vers, "maj_le": ts}
        if vers == ARCHIVED:
            champs["archive_raison"] = raison
            champs["archive_le"] = ts
        elif avant == ARCHIVED:
            # Retour au classement : on efface le MOTIF d'archivage, jamais
            # l'historique. Le compteur de retours, lui, s'incremente — un wallet
            # qui entre et sort plusieurs fois raconte quelque chose que le detail
            # de l'historique ne montre pas d'un coup d'oeil.
            champs["archive_raison"] = None
            champs["archive_le"] = None
            champs["n_retours"] = (w["n_retours"] or 0) + 1
        if vers == RANKED and avant != RANKED:
            champs["promu_le"] = ts
        cols = ", ".join(f"{k} = ?" for k in champs)
        c.execute(f"update wallets set {cols} where adresse = ?",
                  (*champs.values(), adresse.lower()))
    inscrire_historique(c, adresse, vers, raison, metriques or {}, ts=ts,
                        cycle_id=cycle_id)
    return avant


# ----------------------------------------------------------------- historique
def inscrire_historique(c, adresse: str, statut: str, raison: str,
                        m: dict, *, ts: int | None = None,
                        cycle_id: str | None = None) -> None:
    c.execute(
        "insert into historique (ts, adresse, statut, score, rang, confiance, qualite,"
        " n_trades, conc, dd, jours, sr, raison, cycle_id)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts or maintenant(), adresse.lower(), statut, m.get("score"), m.get("rang"),
         m.get("confiance"), m.get("qualite"), m.get("n"), m.get("conc"), m.get("dd"),
         m.get("jours"), m.get("sr"), raison, cycle_id))


# Amplitude en dessous de laquelle un score n'a pas « bouge ». L'a priori etant
# reestime a chaque cycle sur la population, tous les scores derivent de quelques
# dix-milliemes meme quand rien n'a change pour le wallet. Sans ce seuil, chaque
# cycle inscrirait une ligne par wallet classe.
EPSILON_SCORE = 0.05


def enregistrer_point(c, adresse: str, statut: str, raison: str, m: dict, *,
                      cycle_id: str | None = None, ts: int | None = None) -> bool:
    """Inscrit un point d'historique SEULEMENT s'il apporte une information.

    L'historique doit rester lisible dans un an. Mesure sur trois cycles : 367
    lignes « maintenu » pour zero changement, soit 195 par cycle et de l'ordre de
    70 000 par an — de quoi noyer les quelques dizaines de transitions qui, elles,
    comptent vraiment.

    Un point est donc ecrit quand, et seulement quand :
      - le statut a change ; ou
      - le rang a change ; ou
      - le score a bouge de plus de EPSILON_SCORE ; ou
      - aucun point n'existe encore pour ce wallet aujourd'hui.

    Le dernier cas garantit une photo quotidienne, donc une courbe continue, sans
    qu'un cycle relance dans la journee n'en ajoute une seconde. Retourne True si
    une ligne a ete ecrite.
    """
    ts = ts or maintenant()
    dernier = c.execute(
        "select ts, statut, rang, score from historique where adresse = ?"
        " order by ts desc limit 1", (adresse.lower(),)).fetchone()
    if dernier is not None:
        meme_jour = (time.strftime("%Y-%m-%d", time.localtime(dernier["ts"]))
                     == time.strftime("%Y-%m-%d", time.localtime(ts)))
        inchange = (dernier["statut"] == statut
                    and dernier["rang"] == m.get("rang")
                    and dernier["score"] is not None and m.get("score") is not None
                    and abs(dernier["score"] - m["score"]) <= EPSILON_SCORE)
        if meme_jour and inchange:
            return False
    inscrire_historique(c, adresse, statut, raison, m, ts=ts, cycle_id=cycle_id)
    return True


# ------------------------------------------------------------------- priorite
# Ordre d'examen, deterministe. IL NE DIT PAS QUI EST MEILLEUR : il dit qui
# regarder ensuite. Aucun score n'y entre — sinon la file d'attente finirait par
# selectionner la population sur la performance, ce que le criblage s'interdit.
PRIORITES = (
    ("wallet suivi manuellement", "watch = 1"),
    ("classe, donc son retrait doit etre vu tot", "statut = 'RANKED'"),
    ("jamais evalue", "evalue_le is null"),
    ("archive, peut requalifier", "statut = 'ARCHIVED'"),
)


def priorite_sql() -> str:
    """Expression d'ordre : les criteres ci-dessus, puis le plus ancien examen."""
    cas = " ".join(f"when {cond} then {i}" for i, (_, cond) in enumerate(PRIORITES))
    return f"case {cas} else {len(PRIORITES)} end, coalesce(evalue_le, 0), decouvert_le"


def historique(c, adresse: str, limite: int = 200) -> list[sqlite3.Row]:
    return c.execute("select * from historique where adresse = ? order by ts desc limit ?",
                     (adresse.lower(), limite)).fetchall()


def dernier_rang(c, adresse: str) -> int | None:
    r = c.execute("select rang from historique where adresse = ? and rang is not null"
                  " order by ts desc limit 1", (adresse.lower(),)).fetchone()
    return r["rang"] if r else None


# --------------------------------------------------------------------- alertes
def alerter(c, cycle_id: str, categorie: str, message: str, *, adresse: str | None = None,
            cle: str | None = None, details: dict | None = None,
            ts: int | None = None) -> bool:
    """Insere une alerte si sa cle n'existe pas deja. Retourne True si insérée.

    La cle de deduplication vaut par defaut categorie + adresse + JOUR : le meme
    evenement, constate deux fois dans la meme journee, ne produit qu'une alerte.
    Sans cela, un cycle relance apres incident en generait autant que de wallets
    deja traites.
    """
    ts = ts or maintenant()
    jour = time.strftime("%Y-%m-%d", time.localtime(ts))
    cle = cle or f"{categorie}|{adresse or '-'}|{jour}"
    cur = c.execute(
        "insert or ignore into alertes (ts, cycle_id, categorie, adresse, cle, message, details)"
        " values (?,?,?,?,?,?,?)",
        (ts, cycle_id, categorie, adresse.lower() if adresse else None, cle, message,
         json.dumps(details, ensure_ascii=False) if details else None))
    return cur.rowcount > 0


def alertes_du_jour(c, jour: str | None = None) -> list[sqlite3.Row]:
    jour = jour or time.strftime("%Y-%m-%d")
    debut = int(time.mktime(time.strptime(jour, "%Y-%m-%d")))
    return c.execute("select * from alertes where ts >= ? order by ts", (debut,)).fetchall()


# ---------------------------------------------------------------- journal/cycle
def ouvrir_cycle(c, cycle_id: str, mode: str) -> None:
    c.execute("insert or replace into cycles (cycle_id, debut, mode) values (?,?,?)",
              (cycle_id, maintenant(), mode))


def fermer_cycle(c, cycle_id: str, resultat: str, resume: str) -> None:
    c.execute("update cycles set fin = ?, resultat = ?, resume = ? where cycle_id = ?",
              (maintenant(), resultat, resume, cycle_id))


def journaliser(c, cycle_id: str, phase: str, tache: str, **kw) -> None:
    c.execute(
        "insert into journal (cycle_id, ts, phase, tache, adresse, cout_estime, cout_reel,"
        " resultat, erreur, decision, raison, statut_avant, statut_apres)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cycle_id, maintenant(), phase, tache, kw.get("adresse"),
         kw.get("cout_estime", 0), kw.get("cout_reel", 0), kw.get("resultat"),
         kw.get("erreur"), kw.get("decision"), kw.get("raison"),
         kw.get("statut_avant"), kw.get("statut_apres")))


def dernier_cycle(c) -> sqlite3.Row | None:
    return c.execute("select * from cycles order by debut desc limit 1").fetchone()
