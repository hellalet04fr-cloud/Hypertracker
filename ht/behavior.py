"""
B — Wallet Behavior Engine.

Variables comportementales par wallet, calculees UNIQUEMENT sur la seule source
reellement collectee a ce jour : les snapshots d'ordres ouverts `orders_5m`
(Parquet, un fichier = un snapshot, `snapshotTime` constant dans le fichier).

Ce module ne produit AUCUN score et AUCUN classement : il produit des variables
brutes accompagnees de leurs denominateurs. Le tri « smart money » est le travail
d'un module aval, qui doit croiser performance, persistance, drawdown, win rate,
TAILLE D'ECHANTILLON et stabilite. Les colonnes `n_*` exposees ici existent pour
qu'aucun classement ne puisse etre construit sans regarder la taille d'echantillon.

Regles tenues par ce module
---------------------------
1. Aucune valeur par defaut a la place d'une donnee manquante.
   - Ce qui est un COMPTAGE reellement observe (n_ordres, n_oid_appariables, ...)
     vaut 0 quand rien n'a ete observe : 0 est ici un fait mesure, pas un bouchon.
   - Ce qui est un TAUX ou une STATISTIQUE vaut NULL (NaN pandas) des que son
     denominateur est nul ou l'echantillon insuffisant. Jamais 0.0, jamais une
     moyenne inventee. Chaque taux est publie a cote de son denominateur, pour que
     l'absence soit lisible et auditable.
   - L'acces scalaire (`variable()`) leve InsufficientData sur un NULL : impossible
     de consommer un trou par inadvertance.
   - Si la fenetre visible a `asof` est vide, ou si la persistance n'a aucune paire
     de snapshots consecutifs, on leve InsufficientData au lieu de renvoyer un
     cadre vide ou des zeros.

2. Point-in-time. Toute fonction prend `asof: datetime` (timezone-aware) et ne lit
   AUCUN snapshot dont `knowable_at > asof`, ou knowable_at = knowable_at_for(
   "orders_5m", snapshotTime). Le filtrage se fait au niveau du FICHIER : comme
   `snapshotTime` est constant dans un fichier (verifie a l'indexation, refus de
   calculer sinon), exclure le fichier exclut exactement les lignes non connaissables.

3. Aucune colonne `post_hoc` n'est lue (ORDERS_5M.post_hoc est vide aujourd'hui ;
   la verification est faite a l'execution, elle protegera si le contrat change).

Biais et limites assumes (a lire avant d'interpreter une sortie)
----------------------------------------------------------------
  - Un `oid` qui disparait entre deux snapshots a ete EXECUTE ou ANNULE : les
    snapshots seuls ne permettent pas de trancher. `taux_persistance` melange donc
    patience et remplissage. Il faudra `fills` pour separer les deux.
  - Grille de 5 minutes : un ordre poste et annule entre deux snapshots est invisible.
    La persistance mesuree est donc une BORNE SUPERIEURE de la patience reelle.
  - Le carnet reconstitue est celui des ordres servis par l'API, pas le carnet
    complet de l'exchange. Le meilleur prix est donc « meilleur prix OBSERVABLE »,
    d'ou le nom des colonnes.
  - Auto-reference du carnet : un wallet seul au sommet servirait de reference a
    lui-meme. Corrige exactement par un leave-one-out par adresse (cf. _SQL_MEILLEUR).
  - Les executions TWAP sont attribuees a la pseudo-adresse 64-hex
    0x0000...0000 (66 caracteres, pas une adresse EVM) : exclue de toute agregation.
  - Rupture structurelle annoncee au 2026-09-02 sur les prix de liquidation : aucune
    variable de ce module n'utilise closestLiq ni une distance a la liquidation,
    donc aucune n'est exposee a cette rupture.
  - Aucun filtre de survie n'est applique ici (contrairement aux cohortes de
    performance amont) : un wallet est present s'il avait des ordres ouverts, point.
    Un wallet sans ordre ouvert est simplement absent, il n'est pas note zero.
"""
from __future__ import annotations

import os
import glob as _glob
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from ht.schema import ORDERS_5M, InsufficientData, knowable_at_for, require

# --------------------------------------------------------------------------- constantes
RACINE_DEFAUT = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
SOUS_DOSSIER = "orders_5m"
PAS_SNAPSHOT = timedelta(minutes=5)          # grille de la source

LONGUEUR_ADRESSE_EVM = 42                    # "0x" + 40 hex
PSEUDO_ADRESSE_TWAP = "0x" + "0" * 64        # 66 caracteres : jamais une adresse EVM
ADRESSES_EXCLUES = (PSEUDO_ADRESSE_TWAP,)

# colonnes strictement necessaires ; toutes OBSERVED dans ORDERS_5M
COLONNES_UTILES = (
    "snapshotTime", "address", "coin", "side", "limitPx", "sz", "origSz", "oid",
    "orderType", "tif", "reduceOnly", "isTrigger", "isPositionTpsl",
)


# --------------------------------------------------------------------------- indexation
@dataclass(frozen=True)
class Snapshot:
    """Un fichier = un snapshot. `valid_time` est l'instant du snapshot amont,
    `knowable_at` le premier instant ou il aurait pu etre servi."""
    chemin: str
    valid_time: datetime
    knowable_at: datetime
    n_lignes: int


@dataclass(frozen=True)
class Fenetre:
    """Fenetre point-in-time reellement lisible a `asof`."""
    asof: datetime
    racine: str
    snapshots: tuple[Snapshot, ...]
    paires_consecutives: tuple[tuple[datetime, datetime], ...]

    @property
    def chemins(self) -> list[str]:
        return [s.chemin for s in self.snapshots]

    @property
    def debut(self) -> datetime:
        return self.snapshots[0].valid_time

    @property
    def fin(self) -> datetime:
        return self.snapshots[-1].valid_time


def _horodatage(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _verifier_colonnes_autorisees(colonnes) -> None:
    """Regle 3 : interdiction stricte de lire une colonne contaminee par le futur."""
    interdites = sorted(set(colonnes) & set(ORDERS_5M.post_hoc))
    if interdites:
        raise ValueError(
            f"colonnes post_hoc interdites pour une variable point-in-time : {interdites}"
        )
    inconnues = sorted(set(colonnes) - set(ORDERS_5M.columns))
    if inconnues:
        raise ValueError(f"colonnes absentes du contrat orders_5m : {inconnues}")


def repertoire_snapshots(racine: str | None = None) -> str:
    return os.path.join(racine or RACINE_DEFAUT, SOUS_DOSSIER)


def _signature(rep: str) -> tuple:
    fichiers = sorted(_glob.glob(os.path.join(rep, "dt=*", "*.parquet")))
    sig = []
    for f in fichiers:
        st = os.stat(f)
        sig.append((f, st.st_size, st.st_mtime_ns))
    return tuple(sig)


_CACHE_INDEX: dict[tuple, tuple[Snapshot, ...]] = {}


def _snapshot_time_du_fichier(chemin: str) -> tuple[int, int]:
    """(snapshotTime, n_lignes). Lit d'abord les statistiques Parquet (pas de scan)
    et verifie que snapshotTime est bien constant dans le fichier : sinon le
    filtrage point-in-time au niveau fichier serait faux, et on refuse de calculer."""
    pf = pq.ParquetFile(chemin)
    md = pf.metadata
    require(md.num_rows > 0, f"snapshot vide : {chemin}")
    noms = pf.schema_arrow.names
    manquantes = sorted(set(COLONNES_UTILES) - set(noms))
    require(not manquantes, f"colonnes absentes de {chemin} : {manquantes}")
    idx = noms.index("snapshotTime")

    mn, mx = None, None
    for g in range(md.num_row_groups):
        st = md.row_group(g).column(idx).statistics
        if st is None or not st.has_min_max:
            mn = mx = None
            break
        mn = st.min if mn is None else min(mn, st.min)
        mx = st.max if mx is None else max(mx, st.max)
    if mn is None:
        valeurs = pq.read_table(chemin, columns=["snapshotTime"]).column(0).to_pylist()
        mn, mx = min(valeurs), max(valeurs)
    require(
        mn == mx,
        f"snapshotTime non constant dans {chemin} ({mn} != {mx}) : le filtrage "
        f"point-in-time par fichier serait faux, refus de calculer.",
    )
    return int(mn), int(md.num_rows)


def indexer_snapshots(racine: str | None = None) -> tuple[Snapshot, ...]:
    """Indexe tous les snapshots presents sur disque, tries par valid_time croissant."""
    _verifier_colonnes_autorisees(COLONNES_UTILES)
    rep = repertoire_snapshots(racine)
    require(os.path.isdir(rep), f"repertoire de snapshots absent : {rep}")
    sig = _signature(rep)
    require(len(sig) > 0, f"aucun fichier Parquet sous {rep}/dt=*/ : rien a calculer")
    cle = (rep,) + sig
    if cle in _CACHE_INDEX:
        return _CACHE_INDEX[cle]

    snaps = []
    for chemin, _, _ in sig:
        ms, n = _snapshot_time_du_fichier(chemin)
        vt = _horodatage(ms)
        snaps.append(Snapshot(chemin, vt, knowable_at_for(ORDERS_5M.name, vt), n))
    snaps.sort(key=lambda s: (s.valid_time, s.chemin))

    vus: dict[datetime, str] = {}
    for s in snaps:
        require(
            s.valid_time not in vus,
            f"deux fichiers portent le meme snapshotTime {s.valid_time.isoformat()} "
            f"({vus.get(s.valid_time)} et {s.chemin}) : doublon a resoudre avant calcul",
        )
        vus[s.valid_time] = s.chemin

    resultat = tuple(snaps)
    _CACHE_INDEX[cle] = resultat
    return resultat


def fenetre_visible(asof: datetime, racine: str | None = None) -> Fenetre:
    """Snapshots dont knowable_at <= asof. Leve InsufficientData si aucun."""
    require(
        isinstance(asof, datetime) and asof.tzinfo is not None,
        "asof doit etre un datetime timezone-aware (UTC)",
    )
    tous = indexer_snapshots(racine)
    vus = tuple(s for s in tous if s.knowable_at <= asof)
    if not vus:
        plus_tot = min(s.knowable_at for s in tous)
        raise InsufficientData(
            f"aucun snapshot orders_5m connaissable a asof={asof.isoformat()} : "
            f"le plus precoce n'est connaissable qu'a {plus_tot.isoformat()} "
            f"({len(tous)} snapshots sur disque)"
        )
    paires = []
    for a, b in zip(vus, vus[1:]):
        if b.valid_time - a.valid_time == PAS_SNAPSHOT:
            paires.append((a.valid_time, b.valid_time))
    return Fenetre(asof, repertoire_snapshots(racine), vus, tuple(paires))


def resume_fenetre(f: Fenetre) -> dict:
    """Provenance minimale a joindre a toute sortie publiee."""
    return {
        "asof": f.asof.isoformat(),
        "racine": f.racine,
        "n_snapshots": len(f.snapshots),
        "n_paires_consecutives": len(f.paires_consecutives),
        "debut": f.debut.isoformat(),
        "fin": f.fin.isoformat(),
        "n_lignes_brutes": sum(s.n_lignes for s in f.snapshots),
    }


# --------------------------------------------------------------------------- SQL
def _litteral_liste(valeurs) -> str:
    return "[" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in valeurs) + "]"


def connexion(f: Fenetre) -> duckdb.DuckDBPyConnection:
    """Connexion DuckDB exposant la vue `ht_ordres`, deja bornee a la fenetre
    point-in-time et deja purgee des pseudo-adresses (TWAP)."""
    _verifier_colonnes_autorisees(COLONNES_UTILES)
    con = duckdb.connect()
    cols = ", ".join(COLONNES_UTILES)
    exclues = ", ".join("'" + a + "'" for a in ADRESSES_EXCLUES)
    con.execute(
        f"""
        create or replace temp view ht_ordres as
        select {cols}
        from read_parquet({_litteral_liste(f.chemins)})
        where address is not null
          and length(address) = {LONGUEUR_ADRESSE_EVM}
          and address not in ({exclues})
        """
    )
    n = con.execute("select count(*) from ht_ordres").fetchone()[0]
    require(
        n > 0,
        f"0 ligne exploitable dans la fenetre {f.debut.isoformat()} -> "
        f"{f.fin.isoformat()} ({len(f.snapshots)} snapshots) apres exclusion des "
        f"pseudo-adresses : rien a calculer",
    )
    return con


def _con(f: Fenetre, con):
    return con if con is not None else connexion(f)


# ---- carnet et meilleurs prix observables, en leave-one-out par adresse ----
# Un wallet ne doit jamais servir de reference a lui-meme. Pour chaque
# (snapshot, coin, cote) on calcule le meilleur prix APRES retrait des ordres de
# l'adresse evaluee. Formulation exacte : les niveaux de prix sont ranges du
# meilleur au pire ; si le meilleur niveau est tenu par au moins 2 adresses, en
# retirer une ne le deplace pas ; s'il est tenu par une seule adresse x, alors pour
# x la reference devient le premier niveau qui n'est pas lui aussi tenu
# exclusivement par x (« niveau de repli »). Si un tel niveau n'existe pas, la
# reference est INCONNUE pour x : ses ordres sont exclus des statistiques, jamais
# remplaces par une valeur de substitution.
_SQL_MEILLEUR = """
with carnet as (
    select snapshotTime, coin, side, address, limitPx, sz, origSz, oid
    from ht_ordres
    where isTrigger = false and limitPx > 0
),
niveaux as (
    select snapshotTime, coin, side, limitPx as px,
           count(distinct address) as n_addr,
           min(address) as seul_addr,
           row_number() over (
               partition by snapshotTime, coin, side
               order by case when side = 'B' then -limitPx else limitPx end
           ) as rang
    from carnet
    group by 1, 2, 3, 4
),
tete as (select * from niveaux where rang = 1),
repli as (
    select n.snapshotTime, n.coin, n.side, min(n.rang) as rang_repli
    from niveaux n
    join tete t on t.snapshotTime = n.snapshotTime and t.coin = n.coin and t.side = n.side
    where t.n_addr = 1 and n.rang > 1
      and not (n.n_addr = 1 and n.seul_addr = t.seul_addr)
    group by 1, 2, 3
),
meilleur as (
    select t.snapshotTime, t.coin, t.side,
           t.px as px_tete,
           case when t.n_addr = 1 then t.seul_addr end as addr_tete,
           nr.px as px_repli
    from tete t
    left join repli r
           on r.snapshotTime = t.snapshotTime and r.coin = t.coin and r.side = t.side
    left join niveaux nr
           on nr.snapshotTime = t.snapshotTime and nr.coin = t.coin
          and nr.side = t.side and nr.rang = r.rang_repli
),
cote as (
    select c.*,
           case when mb.addr_tete = c.address then mb.px_repli else mb.px_tete end
               as bid_hors_soi,
           case when ma.addr_tete = c.address then ma.px_repli else ma.px_tete end
               as ask_hors_soi
    from carnet c
    left join meilleur mb
           on mb.snapshotTime = c.snapshotTime and mb.coin = c.coin and mb.side = 'B'
    left join meilleur ma
           on ma.snapshotTime = c.snapshotTime and ma.coin = c.coin and ma.side = 'A'
),
mesure as (
    select *, (bid_hors_soi + ask_hors_soi) / 2.0 as milieu
    from cote
    where bid_hors_soi is not null and ask_hors_soi is not null
      and bid_hors_soi > 0 and ask_hors_soi > 0
      and ask_hors_soi >= bid_hors_soi
),
ecart as (
    select address, oid, snapshotTime, coin, side, limitPx, milieu,
           10000.0 * (case when side = 'B' then (milieu - limitPx)
                           else (limitPx - milieu) end) / milieu as distance_milieu_bp,
           case when side = 'B' then limitPx >= bid_hors_soi
                                else limitPx <= ask_hors_soi end as au_touche
    from mesure
)
"""


# --------------------------------------------------------------------------- variables
def empreinte_ordres(asof: datetime, racine: str | None = None,
                     fenetre: Fenetre | None = None, con=None) -> pd.DataFrame:
    """Empreinte de types d'ordres par wallet.

    Taux publies avec leur denominateur. `part_alo` / `part_gtc` sont NULL quand le
    wallet n'a que des ordres declencheurs (tif vide cote API) : ne pas y lire 0.0.
    """
    f = fenetre or fenetre_visible(asof, racine)
    c = _con(f, con)
    df = c.execute(
        """
        select address,
               count(*)                                 as n_ordres,
               count(distinct snapshotTime)             as n_snapshots_presents,
               count(distinct oid)                      as n_oid_distincts,
               count(distinct coin)                     as n_coins,
               sum(case when orderType = 'Limit' then 1 else 0 end)   as n_limit,
               sum(case when orderType in ('Stop Market', 'Stop Limit')
                        then 1 else 0 end)                            as n_stop,
               sum(case when orderType in ('Take Profit Market', 'Take Profit Limit')
                        then 1 else 0 end)                            as n_take_profit,
               sum(case when reduceOnly then 1 else 0 end)            as n_reduce_only,
               sum(case when isTrigger then 1 else 0 end)             as n_trigger,
               sum(case when isPositionTpsl then 1 else 0 end)        as n_position_tpsl,
               sum(case when side = 'B' then 1 else 0 end)            as n_achat,
               sum(case when tif is not null and tif <> '' then 1 else 0 end)
                                                                      as n_ordres_avec_tif,
               sum(case when tif = 'Alo' then 1 else 0 end)           as n_alo,
               sum(case when tif = 'Gtc' then 1 else 0 end)           as n_gtc
        from ht_ordres
        group by 1
        """
    ).df()
    n = df["n_ordres"]
    for nom, num in (("part_limit", "n_limit"),
                     ("part_stop", "n_stop"),
                     ("part_take_profit", "n_take_profit"),
                     ("part_reduce_only", "n_reduce_only"),
                     ("part_trigger", "n_trigger"),
                     ("part_position_tpsl", "n_position_tpsl"),
                     ("part_achat", "n_achat")):
        df[nom] = _taux(df[num], n)
    d = df["n_ordres_avec_tif"]
    df["part_alo"] = _taux(df["n_alo"], d)
    df["part_gtc"] = _taux(df["n_gtc"], d)
    return df.set_index("address").sort_index()


def concentration(asof: datetime, racine: str | None = None,
                  fenetre: Fenetre | None = None, con=None) -> pd.DataFrame:
    """Concentration par actif : indice de Herfindahl sur les ordres et sur le notionnel.

    `hhi_*` dans (0, 1] ; 1 = mono-actif. `n_coins_effectif` = 1 / hhi (nombre
    equivalent d'actifs). `hhi_notionnel` est NULL si aucun ordre de carnet chiffrable.
    """
    f = fenetre or fenetre_visible(asof, racine)
    c = _con(f, con)
    df = c.execute(
        """
        with par_coin as (
            select address, coin,
                   count(*) as n,
                   sum(case when isTrigger = false and limitPx > 0
                            then sz * limitPx else 0 end)              as notionnel,
                   sum(case when isTrigger = false and limitPx > 0
                            then 1 else 0 end)                         as n_chiffrable
            from ht_ordres
            group by 1, 2
        ),
        tot as (
            select address, sum(n) as n_tot, sum(notionnel) as notionnel_tot,
                   sum(n_chiffrable) as n_chiffrable_tot, count(*) as n_coins
            from par_coin group by 1
        )
        select t.address, t.n_coins,
               t.n_tot              as n_ordres,
               t.n_chiffrable_tot   as n_ordres_chiffrables_coin,
               t.notionnel_tot      as notionnel_total,
               sum(power(p.n * 1.0 / t.n_tot, 2)) as hhi_ordres,
               case when t.notionnel_tot > 0
                    then sum(power(p.notionnel / t.notionnel_tot, 2)) end as hhi_notionnel,
               max(p.n * 1.0 / t.n_tot)  as part_coin_principal,
               arg_max(p.coin, p.n)      as coin_principal
        from par_coin p join tot t on t.address = p.address
        group by 1, 2, 3, 4, 5
        """
    ).df()
    df["n_coins_effectif"] = _inverse(df["hhi_ordres"])
    df["n_coins_effectif_notionnel"] = _inverse(df["hhi_notionnel"])
    return df.set_index("address").sort_index()


def agressivite_placement(asof: datetime, racine: str | None = None,
                          fenetre: Fenetre | None = None, con=None) -> pd.DataFrame:
    """Agressivite de placement : distance relative du limitPx au milieu du carnet
    observable, en points de base, calculee HORS ordres du wallet evalue.

    distance_milieu_bp > 0 : ordre passif, en retrait du milieu.
    distance_milieu_bp < 0 : ordre place a l'interieur du spread observable.
    `part_au_touche` : part des ordres au moins aussi bons que le meilleur prix
    observable hors soi.
    Toutes ces statistiques sont NULL quand n_ordres_cotables = 0.
    """
    f = fenetre or fenetre_visible(asof, racine)
    c = _con(f, con)
    df = c.execute(
        _SQL_MEILLEUR
        + """
        , base as (
            select address,
                   sum(case when isTrigger = false and limitPx > 0 then 1 else 0 end)
                       as n_ordres_carnet
            from ht_ordres group by 1
        ),
        agg as (
            select address,
                   count(*) as n_ordres_cotables,
                   quantile_cont(distance_milieu_bp, 0.5)  as distance_milieu_bp_mediane,
                   avg(distance_milieu_bp)                 as distance_milieu_bp_moyenne,
                   quantile_cont(distance_milieu_bp, 0.25) as distance_milieu_bp_q1,
                   quantile_cont(distance_milieu_bp, 0.75) as distance_milieu_bp_q3,
                   sum(case when au_touche then 1 else 0 end) as n_au_touche
            from ecart group by 1
        )
        select b.address, b.n_ordres_carnet,
               coalesce(a.n_ordres_cotables, 0) as n_ordres_cotables,
               coalesce(a.n_au_touche, 0)       as n_au_touche,
               a.distance_milieu_bp_mediane, a.distance_milieu_bp_moyenne,
               a.distance_milieu_bp_q1, a.distance_milieu_bp_q3
        from base b left join agg a on a.address = b.address
        """
    ).df()
    df["part_au_touche"] = _taux(df["n_au_touche"], df["n_ordres_cotables"])
    df["couverture_cotation"] = _taux(df["n_ordres_cotables"], df["n_ordres_carnet"])
    df["ecart_interquartile_bp"] = (
        df["distance_milieu_bp_q3"] - df["distance_milieu_bp_q1"]
    )
    return df.set_index("address").sort_index()


def persistance_ordres(asof: datetime, racine: str | None = None,
                       fenetre: Fenetre | None = None, con=None) -> pd.DataFrame:
    """Persistance des `oid` entre snapshots CONSECUTIFS (pas de 5 min exactement).

    Leve InsufficientData si la fenetre visible ne contient aucune paire consecutive :
    la variable n'existe pas sur un snapshot isole, et rien ne peut la remplacer.

    ATTENTION : disparition = execution OU annulation. Sans `fills`, les deux sont
    indistinguables ; `taux_persistance` n'est donc pas un pur indicateur de patience.
    """
    f = fenetre or fenetre_visible(asof, racine)
    require(
        len(f.paires_consecutives) > 0,
        f"persistance impossible : aucune paire de snapshots consecutifs "
        f"(pas de {int(PAS_SNAPSHOT.total_seconds())}s) parmi les {len(f.snapshots)} "
        f"snapshots connaissables a asof={f.asof.isoformat()} "
        f"({f.debut.isoformat()} -> {f.fin.isoformat()})",
    )
    c = _con(f, con)
    paires = ", ".join(
        f"({int(a.timestamp() * 1000)}, {int(b.timestamp() * 1000)})"
        for a, b in f.paires_consecutives
    )
    df = c.execute(
        f"""
        with paires(t0, t1) as (values {paires}),
        appariables as (
            select o.address, o.oid, p.t1
            from ht_ordres o join paires p on o.snapshotTime = p.t0
        ),
        survie as (
            select a.address,
                   count(*)     as n_oid_appariables,
                   count(s.oid) as n_oid_survivants
            from appariables a
            left join ht_ordres s
                   on s.oid = a.oid and s.address = a.address and s.snapshotTime = a.t1
            group by 1
        ),
        base as (select distinct address from ht_ordres)
        select b.address,
               coalesce(s.n_oid_appariables, 0) as n_oid_appariables,
               coalesce(s.n_oid_survivants, 0)  as n_oid_survivants
        from base b left join survie s on s.address = b.address
        """
    ).df()
    df["taux_persistance"] = _taux(df["n_oid_survivants"], df["n_oid_appariables"])
    df["taux_churn"] = 1.0 - df["taux_persistance"]
    df["n_paires_snapshots"] = len(f.paires_consecutives)
    return df.set_index("address").sort_index()


def tailles_ordres(asof: datetime, racine: str | None = None,
                   fenetre: Fenetre | None = None, con=None) -> pd.DataFrame:
    """Taille typique et dispersion, sur les ordres de carnet (hors declencheurs).

    Le notionnel est sz * limitPx. `ecart_type_log_notionnel` exige au moins 2 ordres
    chiffrables (sinon NULL : un ecart-type sur un point n'existe pas, il ne vaut pas 0).
    """
    f = fenetre or fenetre_visible(asof, racine)
    c = _con(f, con)
    df = c.execute(
        """
        with carnet as (
            select address, sz, origSz, limitPx, sz * limitPx as notionnel
            from ht_ordres where isTrigger = false and limitPx > 0 and sz > 0
        ),
        agg as (
            select address,
                   count(*)                       as n_ordres_chiffrables,
                   quantile_cont(notionnel, 0.5)  as notionnel_median,
                   avg(notionnel)                 as notionnel_moyen,
                   quantile_cont(notionnel, 0.25) as notionnel_q1,
                   quantile_cont(notionnel, 0.75) as notionnel_q3,
                   max(notionnel)                 as notionnel_max,
                   quantile_cont(sz, 0.5)         as sz_median,
                   case when count(*) >= 2 then stddev_samp(ln(notionnel)) end
                                                  as ecart_type_log_notionnel,
                   case when count(*) >= 2 and avg(notionnel) > 0
                        then stddev_samp(notionnel) / avg(notionnel) end
                                                  as coef_variation_notionnel,
                   sum(case when sz < origSz then 1 else 0 end) as n_partiellement_remplis
            from carnet group by 1
        ),
        base as (select distinct address from ht_ordres)
        select b.address,
               coalesce(a.n_ordres_chiffrables, 0) as n_ordres_chiffrables,
               a.notionnel_median, a.notionnel_moyen, a.notionnel_q1, a.notionnel_q3,
               a.notionnel_max, a.sz_median, a.ecart_type_log_notionnel,
               a.coef_variation_notionnel,
               coalesce(a.n_partiellement_remplis, 0) as n_partiellement_remplis
        from base b left join agg a on a.address = b.address
        """
    ).df()
    df["part_partiellement_remplis"] = _taux(
        df["n_partiellement_remplis"], df["n_ordres_chiffrables"]
    )
    return df.set_index("address").sort_index()


def profil_comportemental(asof: datetime, racine: str | None = None,
                          fenetre: Fenetre | None = None,
                          min_ordres: int = 1,
                          avec_persistance: bool = True) -> pd.DataFrame:
    """Assemble les cinq blocs en un profil par wallet.

    `min_ordres` ne fabrique aucune valeur : il retire des lignes dont l'echantillon
    est trop maigre. Le module aval DOIT gater sur la taille d'echantillon avant tout
    classement : n_ordres, n_snapshots_presents, n_oid_appariables sont la pour ca.

    `avec_persistance=False` permet de calculer les autres blocs quand la fenetre n'a
    pas encore deux snapshots consecutifs ; le profil renvoye porte alors
    `.attrs["persistance"] = "indisponible: <raison>"` et AUCUNE colonne de
    persistance — jamais des zeros de remplacement.
    """
    f = fenetre or fenetre_visible(asof, racine)
    require(min_ordres >= 1, f"min_ordres doit valoir au moins 1 (recu {min_ordres})")
    c = connexion(f)
    blocs = [
        empreinte_ordres(asof, fenetre=f, con=c),
        concentration(asof, fenetre=f, con=c).drop(columns=["n_ordres", "n_coins"]),
        agressivite_placement(asof, fenetre=f, con=c),
        tailles_ordres(asof, fenetre=f, con=c),
    ]
    if avec_persistance:
        blocs.append(persistance_ordres(asof, fenetre=f, con=c))
        note_persistance = "calculee"
    else:
        try:
            persistance_ordres(asof, fenetre=f, con=c)
        except InsufficientData as e:
            note_persistance = f"indisponible: {e}"
        else:
            note_persistance = "ecartee a la demande de l'appelant"
    profil = blocs[0].join(blocs[1:], how="left")
    profil = profil[profil["n_ordres"] >= min_ordres]
    require(
        len(profil) > 0,
        f"aucun wallet avec au moins {min_ordres} ordres dans la fenetre "
        f"{f.debut.isoformat()} -> {f.fin.isoformat()}",
    )
    profil.attrs.update(resume_fenetre(f))
    profil.attrs["persistance"] = note_persistance
    profil.attrs["source"] = ORDERS_5M.name
    return profil


# --------------------------------------------------------------------------- acces scalaire
def variable(profil: pd.DataFrame, address: str, nom: str) -> float:
    """Lecture d'une variable pour un wallet. Leve InsufficientData si la valeur est
    absente ou NULL : aucun trou ne peut etre consomme comme un zero."""
    require(nom in profil.columns, f"variable inconnue : {nom!r}")
    require(
        address in profil.index,
        f"wallet {address} absent du profil (fenetre {profil.attrs.get('debut')} -> "
        f"{profil.attrs.get('fin')})",
    )
    v = profil.at[address, nom]
    require(
        pd.notna(v),
        f"{nom} non calculable pour {address} : denominateur nul ou echantillon "
        f"insuffisant dans la fenetre {profil.attrs.get('debut')} -> "
        f"{profil.attrs.get('fin')}",
    )
    return float(v)


# --------------------------------------------------------------------------- outils
def _taux(num: pd.Series, den: pd.Series) -> pd.Series:
    """Taux NULL des que le denominateur est nul. Jamais 0.0 par defaut."""
    num = pd.to_numeric(num, errors="raise").astype("float64")
    den = pd.to_numeric(den, errors="raise").astype("float64")
    return (num / den).where(den > 0)


def _inverse(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="raise").astype("float64")
    return (1.0 / s).where(s > 0)
