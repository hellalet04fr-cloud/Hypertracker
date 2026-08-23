#!/usr/bin/env python3
"""
Moteur de variables (feature engine) point-in-time.

Principe directeur : une variable calculee « a asof » doit etre IMMUABLE. Ce qu'on
savait le 19 janvier a 11h31 sur l'etat du monde a 11h31 doit etre exactement ce
qu'on recalculera le 19 fevrier pour ce meme instant. Toute difference est une fuite
de futur, et une fuite de futur transforme un backtest en fiction.

Trois barrieres, dans cet ordre :

  1. BARRIERE DE CHARGEMENT — AsOfView est le SEUL point du module qui coupe les
     donnees. Elle expose `pit()` (coupe a asof, sur knowable_at) et `rows_at_run_time()`
     (aucune coupe : la fuite volontaire, reservee aux specs de controle). Les colonnes
     listees dans Source.post_hoc sont physiquement retirees de la table au chargement :
     meme un spec malveillant ne peut pas les atteindre.

  2. BARRIERE DECLARATIVE — FeatureSpec.requires est valide a la construction contre
     Source.columns et contre Source.post_hoc. Le contexte passe a la fonction ne
     projette QUE les colonnes declarees.

  3. BARRIERE EMPIRIQUE — leak_check() rejoue le vecteur a asof depuis deux points
     d'observation (asof, puis asof + 30 jours) et exige l'EGALITE STRICTE. C'est un
     replay differentiel : contrairement a un test de monotonie, il attrape aussi bien
     le spec qui oublie la coupe que la valeur revisee apres coup.

Regle non negociable : aucune valeur par defaut ne remplace une donnee absente. Une
fonction de variable qui ne peut pas calculer leve InsufficientData avec un message
precis. La ligne d'entite concernee est marquee incomplete et EXCLUE du jeu
d'entrainement — jamais imputee, jamais mise a zero.

Biais traites explicitement ici :
  - pseudo-adresse TWAP (64 hexa nuls, pas une adresse EVM) exclue de toute agregation
    par wallet, au chargement ET a la construction du vecteur ;
  - revisions : pour une meme cle, la version la PLUS ANCIENNEMENT ingeree est retenue,
    ce qui rend la lecture insensible aux corrections posterieures ; le nombre de
    revisions ignorees est compte et consultable, jamais silencieux ;
  - sources DOCUMENTED : la presence reelle de chaque colonne requise est verifiee a
    l'execution, la doc s'etant deja revelee fausse.

Ce module ne calcule aucune variable de distance a la liquidation : la rupture
structurelle du 2026-09-02 sur les prix de liquidation rend ces variables non
stationnaires de part et d'autre de la coupure. Elles devront porter un indicateur
de regime explicite avant d'entrer ici.
"""
from __future__ import annotations

import glob
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .schema import (
    DOCUMENTED,
    SOURCES,
    InsufficientData,
    Source,
    knowable_at_for,
    require,
)

__all__ = [
    "FeatureSpec", "FeatureContext", "AsOfView", "Loader", "ParquetLoader",
    "InMemoryLoader", "LeakDetected", "LeakReport", "REGISTRY", "register",
    "feature", "registered", "clear_registry", "build", "training_set",
    "leak_check", "leak_check_all", "discover_entities", "install_builtin_specs",
    "TWAP_PSEUDO_ADDRESS", "ENTITY_COLUMN", "HT_DATA_ROOT", "DEFAULT_LEAK_HORIZON",
]

# --------------------------------------------------------------------------- constantes
HT_DATA_ROOT = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")

# Les executions TWAP sont attribuees a une pseudo-adresse de 64 hexa nuls : ce n'est
# pas une adresse EVM (20 octets = 40 hexa), c'est un fourre-tout d'exchange. L'agreger
# comme un wallet fabriquerait le plus gros « trader » de la plateforme.
TWAP_PSEUDO_ADDRESS = "0x" + "0" * 64

# Colonne portant l'identifiant d'entite, par source.
ENTITY_COLUMN: dict[str, str] = {
    "orders_5m": "address",
    "wallets": "address",
    "fills": "address",
    "closed_trades": "address",
    "leaderboards": "address",
    "segments": "id",
}

DEFAULT_LEAK_HORIZON = timedelta(days=30)

_ARROW_DTYPES: dict[str, pa.DataType] = {
    "float64": pa.float64(),
    "int64": pa.int64(),
    "bool": pa.bool_(),
    "string": pa.string(),
}

# Colonnes techniques ajoutees par le chargeur.
KNOWABLE_AT = "_knowable_at"
INGEST_TIME = "_ingest_time"


class LeakDetected(Exception):
    """Le replay differentiel a produit deux vecteurs differents pour le meme asof.
    La variable concernee est inutilisable : elle depend de l'instant ou on la calcule."""


# --------------------------------------------------------------------------- utilitaires temps
def _is_zero_address(value: Any) -> bool:
    """Vrai pour la pseudo-adresse TWAP (et toute variante entierement nulle)."""
    if not isinstance(value, str):
        return False
    body = value[2:] if value[:2].lower() == "0x" else value
    return len(body) > 0 and set(body) <= {"0"}


def _to_utc(value: Any, *, field_name: str) -> datetime:
    """Normalise un instant. Aucune tolerance : une valeur qu'on ne sait pas lire
    est une donnee absente, pas une occasion d'inventer un fuseau."""
    if value is None:
        raise InsufficientData(f"{field_name} absent : instant non determinable")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise InsufficientData(f"{field_name} naif : fuseau inconnu, refus de supposer UTC")
        return value.astimezone(timezone.utc)
    if isinstance(value, bool):
        raise InsufficientData(f"{field_name} booleen : instant non determinable")
    if isinstance(value, (int, float)):
        v = float(value)
        if v >= 1e14:          # microsecondes depuis epoch
            return datetime.fromtimestamp(v / 1e6, timezone.utc)
        if v >= 1e11:          # millisecondes
            return datetime.fromtimestamp(v / 1e3, timezone.utc)
        if v >= 1e9:           # secondes
            return datetime.fromtimestamp(v, timezone.utc)
        raise InsufficientData(
            f"{field_name}={value!r} anterieur a 2001 en toute unite plausible : "
            "epoch non identifiable, refus de deviner"
        )
    if isinstance(value, str):
        s = value.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InsufficientData(f"{field_name}={value!r} illisible en ISO-8601 ({exc})") from None
        if dt.tzinfo is None:
            raise InsufficientData(f"{field_name}={value!r} sans fuseau : refus de supposer UTC")
        return dt.astimezone(timezone.utc)
    raise InsufficientData(f"{field_name} de type {type(value).__name__} : instant non determinable")


def _require_aware(dt: datetime, label: str) -> datetime:
    if not isinstance(dt, datetime):
        raise TypeError(f"{label} doit etre un datetime, recu {type(dt).__name__}")
    if dt.tzinfo is None:
        raise ValueError(f"{label} doit etre timezone-aware (UTC)")
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- specification
@dataclass(frozen=True)
class FeatureSpec:
    """Declaration d'une variable.

    name     : identifiant unique dans le registre, et nom de colonne en sortie.
    source   : nom d'une Source du contrat (ht.schema.SOURCES).
    fn       : fn(ctx: FeatureContext, entity: str) -> valeur. Doit LEVER InsufficientData
               si la donnee reelle manque. Retourner None, NaN ou une valeur par defaut
               est une faute : build() le refusera.
    requires : colonnes de la source effectivement lues. Validees contre Source.columns
               et interdites d'intersection avec Source.post_hoc.
    dtype    : type arrow de la colonne produite.
    """
    name: str
    source: str
    fn: Callable[["FeatureContext", str], Any]
    requires: tuple[str, ...]
    dtype: str = "float64"
    description: str = ""

    def __post_init__(self):
        if not self.name or not isinstance(self.name, str):
            raise ValueError("FeatureSpec.name doit etre une chaine non vide")
        if self.source not in SOURCES:
            raise ValueError(
                f"{self.name}: source inconnue {self.source!r} ; "
                f"sources du contrat : {sorted(SOURCES)}"
            )
        if not callable(self.fn):
            raise ValueError(f"{self.name}: fn n'est pas appelable")
        if self.dtype not in _ARROW_DTYPES:
            raise ValueError(f"{self.name}: dtype {self.dtype!r} inconnu ; {sorted(_ARROW_DTYPES)}")
        if not isinstance(self.requires, tuple):
            object.__setattr__(self, "requires", tuple(self.requires))
        if not self.requires:
            raise ValueError(f"{self.name}: requires vide — une variable declare ce qu'elle lit")

        src = SOURCES[self.source]
        inconnues = [c for c in self.requires if c not in src.columns]
        if inconnues:
            raise ValueError(
                f"{self.name}: colonnes absentes du contrat {self.source} : {inconnues}"
            )
        interdites = sorted(set(self.requires) & set(src.post_hoc))
        if interdites:
            raise ValueError(
                f"{self.name}: colonnes post_hoc interdites en point-in-time : {interdites} "
                f"(source {self.source}). Ces champs sont contamines par le futur."
            )

    @property
    def src(self) -> Source:
        return SOURCES[self.source]

    @property
    def entity_column(self) -> str:
        col = ENTITY_COLUMN.get(self.source)
        if col is None:
            raise ValueError(f"aucune colonne d'entite connue pour la source {self.source}")
        return col


# --------------------------------------------------------------------------- registre
REGISTRY: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec, *, replace: bool = False) -> FeatureSpec:
    if spec.name in REGISTRY and not replace:
        raise ValueError(f"variable deja enregistree : {spec.name!r}")
    REGISTRY[spec.name] = spec
    return spec


def feature(name: str, source: str, requires: Sequence[str], *,
            dtype: str = "float64", description: str = "", replace: bool = False):
    """Decorateur d'enregistrement declaratif."""
    def deco(fn):
        register(FeatureSpec(name=name, source=source, fn=fn,
                             requires=tuple(requires), dtype=dtype,
                             description=description), replace=replace)
        return fn
    return deco


def registered(*names: str) -> tuple[FeatureSpec, ...]:
    """Recupere des specs par nom. Sans argument : tout le registre, ordre d'insertion."""
    if not names:
        return tuple(REGISTRY.values())
    manquants = [n for n in names if n not in REGISTRY]
    if manquants:
        raise KeyError(f"variables non enregistrees : {manquants}")
    return tuple(REGISTRY[n] for n in names)


def clear_registry() -> None:
    REGISTRY.clear()


# --------------------------------------------------------------------------- chargeurs
class Loader:
    """Interface de chargement. Un chargeur renvoie TOUT ce qu'il possede, sans
    aucune coupe temporelle : la coupe est la responsabilite exclusive d'AsOfView,
    pour qu'elle soit auditables en un seul endroit."""

    def load(self, source: Source, columns: tuple[str, ...]) -> pa.Table:
        raise NotImplementedError

    def describe(self) -> str:
        return type(self).__name__


def _knowable_column(table: pa.Table, source: Source, lag_s: float | None) -> pa.Array:
    """Calcule knowable_at pour chaque ligne a partir de la colonne valid_time.
    Chemin rapide vectorise pour les epochs entiers, repli python sinon."""
    if source.valid_time is None:
        raise InsufficientData(
            f"source {source.name} sans colonne valid_time : instant de connaissance "
            "indeterminable, aucune variable point-in-time possible"
        )
    if source.valid_time not in table.column_names:
        raise InsufficientData(
            f"source {source.name} : colonne valid_time {source.valid_time!r} absente "
            "des fichiers reels"
        )
    col = table[source.valid_time]
    if len(col) == 0:
        return pa.array([], type=pa.timestamp("us", tz="UTC"))

    lag = timedelta(seconds=lag_s) if lag_s is not None else (
        knowable_at_for(source.name, datetime(2000, 1, 1, tzinfo=timezone.utc))
        - datetime(2000, 1, 1, tzinfo=timezone.utc)
    )

    if pa.types.is_integer(col.type):
        premiere = col.drop_null()
        if len(premiere) == 0:
            raise InsufficientData(
                f"source {source.name} : colonne {source.valid_time} entierement nulle"
            )
        echantillon = float(premiere[0].as_py())
        if echantillon >= 1e14:
            unite = "us"
        elif echantillon >= 1e11:
            unite = "ms"
        elif echantillon >= 1e9:
            unite = "s"
        else:
            raise InsufficientData(
                f"source {source.name} : {source.valid_time}={echantillon!r} anterieur a 2001 "
                "en toute unite plausible, epoch non identifiable"
            )
        ts = col.cast(pa.timestamp(unite, tz="UTC")).cast(pa.timestamp("us", tz="UTC"))
        return pc.add(ts, pa.scalar(int(lag.total_seconds() * 1e6), type=pa.duration("us")))

    valeurs = col.to_pylist()
    return pa.array(
        [None if v is None else _to_utc(v, field_name=f"{source.name}.{source.valid_time}") + lag
         for v in valeurs],
        type=pa.timestamp("us", tz="UTC"),
    )


_ZERO_VARIANTES = pa.array(["0x" + "0" * 64, "0" * 64, "0x" + "0" * 40, "0" * 40], type=pa.string())


def _cast_horodatage(arr, label: str):
    if isinstance(arr, pa.ChunkedArray):
        arr = arr.combine_chunks()
    if pa.types.is_timestamp(arr.type) and arr.type.tz is None:
        raise InsufficientData(f"{label} sans fuseau : refus de supposer UTC")
    return arr.cast(pa.timestamp("us", tz="UTC"))


def _normalise(table: pa.Table, source: Source, columns: tuple[str, ...],
               lag_s: float | None, ingest_default: datetime | None) -> pa.Table:
    """Projette les colonnes utiles, ajoute _knowable_at / _ingest_time, retire les
    colonnes post_hoc et les lignes de la pseudo-adresse TWAP.

    Les colonnes de cle metier (Source.key) sont chargees meme si aucun spec ne les
    demande : sans elles, la deduplication des revisions serait faite sur une cle
    partielle, ce qui ecraserait des lignes distinctes. Elles restent invisibles pour
    les fonctions de variables, qui ne voient que leur `requires`.
    """
    voulues: list[str] = []
    for c in (*columns, *source.key, source.valid_time, ENTITY_COLUMN.get(source.name)):
        if c and c in table.column_names and c not in voulues:
            voulues.append(c)

    # BARRIERE 1 : les colonnes contaminees par le futur ne quittent jamais le disque.
    voulues = [c for c in voulues if c not in source.post_hoc]

    if KNOWABLE_AT in table.column_names:
        knowable = _cast_horodatage(table[KNOWABLE_AT], f"{source.name}.{KNOWABLE_AT}")
    else:
        knowable = _knowable_column(table, source, lag_s)
        if isinstance(knowable, pa.ChunkedArray):
            knowable = knowable.combine_chunks()

    if INGEST_TIME in table.column_names:
        ingest = _cast_horodatage(table[INGEST_TIME], f"{source.name}.{INGEST_TIME}")
    elif ingest_default is not None:
        ingest = pa.array([ingest_default] * table.num_rows, type=pa.timestamp("us", tz="UTC"))
    else:
        # Faute d'estampille de provenance, on prend l'instant de connaissance : c'est
        # une borne inferieure verifiable, pas une valeur inventee. Elle ne sert qu'a
        # departager les revisions, jamais a couper un backtest.
        ingest = knowable

    out = table.select(voulues)
    out = out.append_column(KNOWABLE_AT, knowable)
    out = out.append_column(INGEST_TIME, ingest)

    ent = ENTITY_COLUMN.get(source.name)
    if ent and ent in out.column_names and pa.types.is_string(out.schema.field(ent).type):
        col = out[ent]
        masque = pc.and_(pc.is_valid(col), pc.invert(pc.is_in(col, value_set=_ZERO_VARIANTES)))
        if pc.sum(pc.cast(masque, pa.int64())).as_py() != out.num_rows:
            out = out.filter(masque)
    return out


@dataclass
class ParquetLoader:
    """Lit les parquets deposes par le collecteur : <root>/<source>/dt=*/*.parquet.

    L'instant d'ingestion vient du mtime du fichier : c'est une metadonnee de
    provenance reelle, pas une valeur fabriquee. Elle sert uniquement a departager
    deux versions d'une meme cle, conformement au contrat qui reserve ingest_time a
    la provenance et a l'audit.
    """
    root: str = HT_DATA_ROOT
    lags: Mapping[str, float] | None = None
    _cache: dict = field(default_factory=dict, repr=False)

    def files(self, source: Source) -> list[str]:
        base = os.path.join(self.root, source.name)
        motifs = [os.path.join(base, "dt=*", "*.parquet"), os.path.join(base, "*.parquet")]
        vus: list[str] = []
        for m in motifs:
            for f in sorted(glob.glob(m)):
                if f not in vus:
                    vus.append(f)
        return vus

    def describe(self) -> str:
        return f"ParquetLoader(root={self.root!r})"

    def load(self, source: Source, columns: tuple[str, ...]) -> pa.Table:
        cle = (source.name, tuple(sorted(columns)))
        if cle in self._cache:
            return self._cache[cle]
        # Reutilise une table deja lue qui couvre au moins les colonnes demandees :
        # relire 2 M de lignes une fois par variable serait une perte seche.
        couvrant = [t for (n, c), t in list(self._cache.items())
                    if n == source.name and set(columns) <= set(c)]
        if couvrant:
            self._cache[cle] = couvrant[0]
            return couvrant[0]

        fichiers = self.files(source)
        if not fichiers:
            raise InsufficientData(
                f"aucun parquet pour la source {source.name} sous {self.root} : "
                "cette surface n'a pas encore ete collectee"
            )

        lag = (self.lags or {}).get(source.name)
        morceaux: list[pa.Table] = []
        for f in fichiers:
            pf = pq.ParquetFile(f)
            presentes = set(pf.schema_arrow.names)
            besoin = {c for c in columns} | {source.valid_time}
            ent = ENTITY_COLUMN.get(source.name)
            if ent:
                besoin.add(ent)
            besoin.discard(None)
            manquantes = sorted(besoin - presentes)
            if manquantes:
                statut = "annoncees par la doc mais " if source.status == DOCUMENTED else ""
                raise InsufficientData(
                    f"{f}: colonnes {statut}absentes du flux reel : {manquantes}"
                )
            # Cles metier au mieux : leur absence n'est pas bloquante, elle desactive
            # seulement la deduplication des revisions (signalee par AsOfView).
            besoin |= {c for c in source.key if c in presentes}
            t = pf.read(columns=sorted(besoin))
            ingest = datetime.fromtimestamp(os.path.getmtime(f), timezone.utc)
            morceaux.append(_normalise(t, source, tuple(columns), lag, ingest))

        table = pa.concat_tables(morceaux, promote_options="permissive")
        self._cache[cle] = table
        return table


@dataclass
class InMemoryLoader:
    """Chargeur de fixtures. Les tables passees ici ne sont JAMAIS des donnees reelles :
    toute sortie qui en decoule doit etre presentee comme telle."""
    tables: Mapping[str, Any]
    lags: Mapping[str, float] | None = None
    _cache: dict = field(default_factory=dict, repr=False)

    def describe(self) -> str:
        return f"InMemoryLoader(fixtures={sorted(self.tables)})"

    def load(self, source: Source, columns: tuple[str, ...]) -> pa.Table:
        cle = (source.name, tuple(sorted(columns)))
        if cle in self._cache:
            return self._cache[cle]
        brut = self.tables.get(source.name)
        if brut is None:
            raise InsufficientData(
                f"fixture absente pour la source {source.name} : rien a calculer"
            )
        table = brut if isinstance(brut, pa.Table) else pa.Table.from_pylist(list(brut))
        besoin = {c for c in columns}
        manquantes = sorted(besoin - set(table.column_names))
        if manquantes:
            statut = "annoncees par la doc mais " if source.status == DOCUMENTED else ""
            raise InsufficientData(
                f"fixture {source.name} : colonnes {statut}absentes : {manquantes}"
            )
        out = _normalise(table, source, tuple(columns), (self.lags or {}).get(source.name), None)
        self._cache[cle] = out
        return out


# --------------------------------------------------------------------------- vue as-of
@dataclass
class AsOfView:
    """SEUL point de coupe temporelle du module.

    asof    : instant du backtest. Aucune ligne dont knowable_at > asof n'est visible
              par le chemin honnete.
    vantage : instant depuis lequel on execute le calcul. Il ne doit JAMAIS influencer
              une variable honnete — c'est precisement ce que leak_check verifie en le
              deplacant de 30 jours.
    """
    loader: Loader
    asof: datetime
    vantage: datetime | None = None
    entities: tuple[str, ...] | None = None
    revisions_ignorees: int = field(default=0, init=False)
    cles_partielles: tuple[str, ...] = field(default=(), init=False)
    _tables: dict = field(default_factory=dict, repr=False, init=False)
    _index: dict = field(default_factory=dict, repr=False, init=False)
    _alias: dict = field(default_factory=dict, repr=False, init=False)

    def __post_init__(self):
        self.asof = _require_aware(self.asof, "asof")
        self.vantage = self.asof if self.vantage is None else _require_aware(self.vantage, "vantage")
        if self.vantage < self.asof:
            raise ValueError("vantage anterieur a asof : on ne calcule pas avant d'observer")
        if self.entities is not None:
            self.entities = tuple(self.entities)

    # -- chargement + deduplication des revisions ---------------------------------
    def _resout(self, source: Source, columns: tuple[str, ...]) -> tuple:
        """Cle de cache : reutilise une table deja materialisee qui couvre les colonnes."""
        cle = (source.name, tuple(sorted(columns)))
        if cle in self._alias:
            return self._alias[cle]
        for (nom, cols) in list(self._tables):
            if nom == source.name and set(columns) <= set(cols):
                self._alias[cle] = (nom, cols)
                return (nom, cols)
        self._alias[cle] = cle
        return cle

    def prime(self, source: Source, columns: tuple[str, ...]) -> None:
        """Materialise en une lecture l'union des colonnes dont on aura besoin."""
        self._table(source, tuple(columns))

    def _table(self, source: Source, columns: tuple[str, ...]) -> pa.Table:
        cle = self._resout(source, columns)
        if cle in self._tables:
            return self._tables[cle]
        table = self.loader.load(source, tuple(columns))

        ent = ENTITY_COLUMN.get(source.name)
        if self.entities is not None and ent and ent in table.column_names:
            masque = pc.is_in(table[ent], value_set=pa.array(self.entities, type=pa.string()))
            table = table.filter(masque)

        table = self._deduplique(table, source)
        cle = (source.name, tuple(sorted(table.column_names)))
        self._alias[(source.name, tuple(sorted(columns)))] = cle
        self._tables[cle] = table
        self._index.pop(cle, None)
        return table

    def _deduplique(self, table: pa.Table, source: Source) -> pa.Table:
        """Pour une meme cle metier, retient la version la PLUS ANCIENNEMENT ingeree.

        Une correction publiee apres coup ne peut donc pas modifier une variable deja
        calculee : c'est ce qui rend la lecture insensible au point d'observation. Les
        versions ecartees sont comptees (revisions_ignorees), jamais tues.

        Si la cle metier n'est pas integralement presente, la deduplication est
        DESACTIVEE (dedupliquer sur une cle partielle ecraserait des lignes distinctes)
        et la source est signalee dans `cles_partielles`.
        """
        cles = [c for c in source.key if c in table.column_names]
        if len(cles) != len(source.key):
            if source.name not in self.cles_partielles:
                self.cles_partielles = self.cles_partielles + (source.name,)
            return table
        if not cles or table.num_rows == 0:
            return table
        colonnes = [table[c].to_pylist() for c in cles]
        ingest = table[INGEST_TIME].to_pylist()
        premier: dict[tuple, tuple[Any, int]] = {}
        for i in range(table.num_rows):
            k = tuple(col[i] for col in colonnes)
            prec = premier.get(k)
            if prec is None or (ingest[i] is not None and prec[0] is not None and ingest[i] < prec[0]):
                premier[k] = (ingest[i], i)
        if len(premier) == table.num_rows:
            return table
        self.revisions_ignorees += table.num_rows - len(premier)
        garde = sorted(idx for _, idx in premier.values())
        return table.take(pa.array(garde, type=pa.int64()))

    def _entity_index(self, source: Source, columns: tuple[str, ...]) -> dict[str, list[int]]:
        """
        Index entite -> positions de lignes, mis en cache PAR SOURCE et non par
        (source, colonnes).

        Justification, verifiee empiriquement sur les 2 160 522 lignes reelles : le
        chargeur ne fait que PROJETER des colonnes, il ne filtre ni ne reordonne. Le
        nombre de lignes et la colonne d'entite sont donc identiques quel que soit le
        `requires` de la spec. Sans cette mise en commun, chaque spec au `requires`
        distinct rescanne la totalite de la table — huit specs coutaient huit scans.

        Le garde-fou ci-dessous rend l'hypothese verifiable a l'execution : si un
        futur chargeur venait a filtrer, le decompte differerait et on echoue au lieu
        de prendre des positions de lignes fausses pour argent comptant.
        """
        table = self._table(source, columns)
        cle = source.name
        cache = self._index.get(cle)
        if cache is not None:
            idx, n_attendu = cache
            if n_attendu != table.num_rows:
                raise InsufficientData(
                    f"index d'entites incoherent pour {source.name} : construit sur "
                    f"{n_attendu} lignes, table courante a {table.num_rows}. Le chargeur "
                    "ne projette plus seulement des colonnes ; l'index par source n'est "
                    "plus valide."
                )
            return idx
        ent = ENTITY_COLUMN.get(source.name)
        idx: dict[str, list[int]] = {}
        if ent and ent in table.column_names:
            for i, v in enumerate(table[ent].to_pylist()):
                if v is not None:
                    idx.setdefault(v, []).append(i)
        self._index[cle] = (idx, table.num_rows)
        return idx

    # -- accesseurs ---------------------------------------------------------------
    def _slice(self, source: Source, columns: tuple[str, ...], entity: str | None,
               borne: datetime) -> pa.Table:
        table = self._table(source, columns)
        if entity is not None:
            lignes = self._entity_index(source, columns).get(entity, [])
            if not lignes:
                return table.slice(0, 0)
            table = table.take(pa.array(lignes, type=pa.int64()))
        if table.num_rows == 0:
            return table
        masque = pc.less_equal(table[KNOWABLE_AT], pa.scalar(borne, type=pa.timestamp("us", tz="UTC")))
        return table.filter(masque)

    def pit(self, source: Source, columns: tuple[str, ...], entity: str | None = None) -> pa.Table:
        """Chemin honnete : coupe stricte sur knowable_at <= asof."""
        return self._slice(source, columns, entity, self.asof)

    def at_run_time(self, source: Source, columns: tuple[str, ...],
                    entity: str | None = None) -> pa.Table:
        """FUITE DE FUTUR ASSUMEE. Renvoie la table telle qu'elle apparait a l'instant
        d'execution (vantage), sans aucune coupe a asof. N'existe que pour ecrire des
        specs de controle et demontrer que leak_check les attrape. Toute variable qui
        passe par ici echouera au replay differentiel — c'est voulu."""
        return self._slice(source, columns, entity, self.vantage)


# --------------------------------------------------------------------------- contexte
class FeatureContext:
    """Vue restreinte offerte a une fonction de variable : une seule source, uniquement
    les colonnes declarees dans requires, uniquement les lignes connaissables a asof.
    Trace au passage le knowable_at maximal effectivement touche."""

    def __init__(self, view: AsOfView, spec: FeatureSpec, entity: str):
        self._view = view
        self._spec = spec
        self._entity = entity
        self._touched_max: datetime | None = None
        self._rows_touched = 0

    # -- metadonnees
    @property
    def asof(self) -> datetime:
        return self._view.asof

    @property
    def entity(self) -> str:
        return self._entity

    @property
    def spec(self) -> FeatureSpec:
        return self._spec

    @property
    def knowable_at_max(self) -> datetime | None:
        return self._touched_max

    @property
    def rows_touched(self) -> int:
        return self._rows_touched

    # -- acces aux donnees
    def _projette(self, table: pa.Table) -> pa.Table:
        """BARRIERE 2 : la fonction ne voit QUE les colonnes qu'elle a declarees
        (plus l'instant de connaissance). Une colonne non declaree — donc non validee
        contre post_hoc — est inatteignable, meme si le chargeur l'a lue."""
        garde = [c for c in self._spec.requires if c in table.column_names]
        manquantes = [c for c in self._spec.requires if c not in table.column_names]
        if manquantes:
            statut = "annoncees par la doc mais " if self._spec.src.status == DOCUMENTED else ""
            raise InsufficientData(
                f"{self._spec.name}: colonnes {statut}absentes des donnees reelles "
                f"({self._spec.source}) : {manquantes}"
            )
        return table.select(garde + [KNOWABLE_AT])

    def _trace(self, table: pa.Table) -> list[dict]:
        table = self._projette(table)
        self._rows_touched += table.num_rows
        if table.num_rows:
            mx = pc.max(table[KNOWABLE_AT]).as_py()
            if mx is not None:
                mx = mx if mx.tzinfo else mx.replace(tzinfo=timezone.utc)
                if self._touched_max is None or mx > self._touched_max:
                    self._touched_max = mx
        return table.to_pylist()

    def rows(self) -> list[dict]:
        """Lignes de l'entite, connaissables a asof, projetees sur requires.
        Peut etre vide : c'est a la fonction de lever InsufficientData si c'est le cas."""
        return self._trace(self._view.pit(self._spec.src, self._spec.requires, self._entity))

    def arrow(self) -> pa.Table:
        t = self._projette(self._view.pit(self._spec.src, self._spec.requires, self._entity))
        self._rows_touched += t.num_rows
        if t.num_rows:
            mx = pc.max(t[KNOWABLE_AT]).as_py()
            if mx is not None:
                mx = mx if mx.tzinfo else mx.replace(tzinfo=timezone.utc)
                if self._touched_max is None or mx > self._touched_max:
                    self._touched_max = mx
        return t

    def snapshots(self) -> list[tuple[datetime, list[dict]]]:
        """Lignes regroupees par instant de connaissance, du plus ancien au plus recent."""
        groupes: dict[datetime, list[dict]] = {}
        for r in self.rows():
            k = r.get(KNOWABLE_AT)
            if k is None:
                continue
            k = k if k.tzinfo else k.replace(tzinfo=timezone.utc)
            groupes.setdefault(k, []).append(r)
        return sorted(groupes.items(), key=lambda kv: kv[0])

    def latest_snapshot(self) -> tuple[datetime, list[dict]]:
        snaps = self.snapshots()
        require(bool(snaps),
                f"{self._spec.name}[{self._entity}] : aucune ligne de {self._spec.source} "
                f"connaissable au {self.asof.isoformat()}")
        return snaps[-1]

    def rows_at_run_time(self) -> list[dict]:
        """FUITE DE FUTUR ASSUMEE — voir AsOfView.at_run_time. Reserve aux specs de
        controle destines a faire echouer leak_check."""
        t = self._view.at_run_time(self._spec.src, self._spec.requires, self._entity)
        return self._trace(t)


# --------------------------------------------------------------------------- validation des valeurs
def _valide_valeur(spec: FeatureSpec, entity: str, v: Any) -> Any:
    if v is None:
        raise InsufficientData(
            f"{spec.name}[{entity}] : la fonction a retourne None. Une variable "
            "indisponible doit LEVER InsufficientData, pas renvoyer un trou."
        )
    if spec.dtype in ("float64", "int64"):
        if isinstance(v, bool):
            raise InsufficientData(f"{spec.name}[{entity}] : booleen recu pour un dtype {spec.dtype}")
        if not isinstance(v, (int, float)):
            raise InsufficientData(
                f"{spec.name}[{entity}] : type {type(v).__name__} incompatible avec {spec.dtype}"
            )
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            raise InsufficientData(
                f"{spec.name}[{entity}] : valeur non finie ({v!r}). Un NaN silencieux "
                "est une donnee manquante deguisee."
            )
        return int(v) if spec.dtype == "int64" else f
    if spec.dtype == "bool":
        if not isinstance(v, bool):
            raise InsufficientData(f"{spec.name}[{entity}] : type {type(v).__name__} incompatible avec bool")
        return v
    if not isinstance(v, str):
        raise InsufficientData(f"{spec.name}[{entity}] : type {type(v).__name__} incompatible avec string")
    return v


# --------------------------------------------------------------------------- construction
def build(asof: datetime,
          entities: Iterable[str],
          specs: Sequence[FeatureSpec] | None = None,
          *,
          loader: Loader | None = None,
          vantage: datetime | None = None,
          view: AsOfView | None = None) -> pa.Table:
    """Assemble le vecteur de variables : une ligne par entite.

    Colonnes de sortie : entity, <une par spec>, asof, knowable_at_max, complete, missing.

    Une entite dont au moins une variable requise manque est marquee complete=False, ses
    variables absentes restent NULLES (jamais imputees) et la raison exacte est portee
    par la colonne missing. Utiliser training_set() pour obtenir le sous-ensemble
    exploitable — l'exclusion est explicite, jamais implicite.
    """
    asof = _require_aware(asof, "asof")
    entites = list(dict.fromkeys(entities))
    if not entites:
        raise InsufficientData("build : aucune entite demandee")

    specs = tuple(specs) if specs is not None else registered()
    if not specs:
        raise InsufficientData("build : aucun spec fourni ni enregistre")
    doublons = {s.name for s in specs if [x.name for x in specs].count(s.name) > 1}
    if doublons:
        raise ValueError(f"noms de variables en double : {sorted(doublons)}")

    if view is None:
        if loader is None:
            loader = ParquetLoader()
        view = AsOfView(loader=loader, asof=asof, vantage=vantage, entities=tuple(entites))
    else:
        if view.asof != asof:
            raise ValueError("build : la vue fournie ne porte pas le meme asof")

    colonnes: dict[str, list[Any]] = {s.name: [] for s in specs}
    knowable_max: list[datetime | None] = []
    complet: list[bool] = []
    manquant: list[str | None] = []

    for ent in entites:
        raisons: list[str] = []
        kmax: datetime | None = None

        if _is_zero_address(ent):
            # Biais connu : la pseudo-adresse TWAP agrege les executions de tout
            # l'exchange. La traiter comme un wallet fabriquerait un faux geant.
            for s in specs:
                colonnes[s.name].append(None)
            raisons.append("entite=pseudo-adresse TWAP (64 hexa nuls) : exclue de toute "
                           "agregation par wallet")
            knowable_max.append(None)
            complet.append(False)
            manquant.append(" | ".join(raisons))
            continue

        for s in specs:
            ctx = FeatureContext(view, s, ent)
            try:
                valeur = _valide_valeur(s, ent, s.fn(ctx, ent))
            except InsufficientData as exc:
                colonnes[s.name].append(None)
                raisons.append(f"{s.name}: {exc}")
            else:
                colonnes[s.name].append(valeur)
            if ctx.knowable_at_max is not None and (kmax is None or ctx.knowable_at_max > kmax):
                kmax = ctx.knowable_at_max

        knowable_max.append(kmax)
        complet.append(not raisons)
        manquant.append(None if not raisons else " | ".join(raisons))

    arrays = [pa.array(entites, type=pa.string())]
    noms = ["entity"]
    for s in specs:
        arrays.append(pa.array(colonnes[s.name], type=_ARROW_DTYPES[s.dtype]))
        noms.append(s.name)
    arrays += [
        pa.array([asof] * len(entites), type=pa.timestamp("us", tz="UTC")),
        pa.array(knowable_max, type=pa.timestamp("us", tz="UTC")),
        pa.array(complet, type=pa.bool_()),
        pa.array(manquant, type=pa.string()),
    ]
    noms += ["asof", "knowable_at_max", "complete", "missing"]

    table = pa.table(arrays, names=noms)
    return table.replace_schema_metadata({
        "asof": asof.isoformat(),
        "vantage": view.vantage.isoformat(),
        "loader": view.loader.describe(),
        "specs": ",".join(s.name for s in specs),
        "revisions_ignorees": str(view.revisions_ignorees),
    })


def training_set(table: pa.Table, *, drop_flags: bool = True) -> pa.Table:
    """Sous-ensemble exploitable : uniquement les lignes completes.

    Leve InsufficientData si aucune ligne ne survit — un jeu d'entrainement vide est
    une information, pas un cas limite a ignorer.
    """
    if "complete" not in table.column_names:
        raise ValueError("table sans colonne 'complete' : ce n'est pas une sortie de build()")
    garde = table.filter(pc.equal(table["complete"], pa.scalar(True)))
    if garde.num_rows == 0:
        raisons = [m for m in table["missing"].to_pylist() if m][:3]
        raise InsufficientData(
            f"aucune ligne complete sur {table.num_rows} entites. Exemples de causes : {raisons}"
        )
    if drop_flags:
        garde = garde.drop_columns(["complete", "missing"])
    return garde


# --------------------------------------------------------------------------- replay differentiel
@dataclass(frozen=True)
class LeakReport:
    spec: str
    asof: datetime
    vantage: datetime
    entites_comparees: int
    ecarts: tuple[dict, ...]

    @property
    def ok(self) -> bool:
        return not self.ecarts

    def __str__(self) -> str:
        if self.ok:
            return (f"leak_check OK — {self.spec} identique a {self.asof.isoformat()} "
                    f"vu de {self.asof.isoformat()} et de {self.vantage.isoformat()} "
                    f"({self.entites_comparees} entites)")
        d = self.ecarts[0]
        return (f"FUITE — {self.spec} : {len(self.ecarts)} ecart(s) sur "
                f"{self.entites_comparees} entites. Premier : entite={d['entity']} "
                f"champ={d['champ']} a_asof={d['a_asof']!r} a_vantage={d['a_vantage']!r}")


def _cellules(table: pa.Table, spec: FeatureSpec) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ents = table["entity"].to_pylist()
    val = table[spec.name].to_pylist()
    kmax = table["knowable_at_max"].to_pylist()
    comp = table["complete"].to_pylist()
    miss = table["missing"].to_pylist()
    for i, e in enumerate(ents):
        out[e] = {"valeur": val[i], "knowable_at_max": kmax[i],
                  "complete": comp[i], "missing": miss[i]}
    return out


def _strictement_egal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and math.isnan(a):
            return False        # un NaN n'est jamais egal a lui-meme : on le traite en ecart
        return a == b
    return a == b


def leak_check(spec: FeatureSpec,
               asof: datetime,
               entities: Iterable[str] | None = None,
               *,
               loader: Loader | None = None,
               horizon: timedelta = DEFAULT_LEAK_HORIZON,
               strict: bool = True,
               max_entities: int = 200,
               compare_missing: bool = True) -> LeakReport:
    """Replay differentiel.

    Reconstruit le vecteur de `spec` POUR LE MEME asof depuis deux points d'observation :
    d'abord vantage=asof, puis vantage=asof+horizon (30 jours par defaut). Exige
    l'EGALITE STRICTE de la valeur, du knowable_at_max, du drapeau complete et de la
    raison d'incompletude.

    Pourquoi pas un simple test de monotonie : une valeur revisee apres coup peut tres
    bien rester dans les memes bornes tout en changeant. Seule la comparaison bit a bit
    de deux reconstructions attrape ce cas.

    Leve InsufficientData si aucune entite n'est evaluable aux deux vantages : un
    verdict « pas de fuite » tire d'un echantillon vide serait un mensonge.
    """
    if horizon <= timedelta(0):
        raise ValueError("horizon de leak_check doit etre strictement positif")
    asof = _require_aware(asof, "asof")
    if loader is None:
        loader = ParquetLoader()

    if entities is None:
        entites = discover_entities(spec.source, asof, loader=loader, limit=max_entities)
    else:
        entites = list(dict.fromkeys(entities))[:max_entities]
    if not entites:
        raise InsufficientData(
            f"leak_check({spec.name}) : aucune entite presente dans {spec.source} "
            f"au {asof.isoformat()} — verification impossible, verdict refuse"
        )

    t1 = build(asof, entites, [spec], loader=loader, vantage=asof)
    t2 = build(asof, entites, [spec], loader=loader, vantage=asof + horizon)

    c1, c2 = _cellules(t1, spec), _cellules(t2, spec)
    champs = ["valeur", "knowable_at_max", "complete"] + (["missing"] if compare_missing else [])

    ecarts: list[dict] = []
    evaluables = 0
    for e in entites:
        a, b = c1.get(e), c2.get(e)
        if a is None or b is None:
            ecarts.append({"entity": e, "champ": "presence",
                           "a_asof": a is not None, "a_vantage": b is not None})
            continue
        if a["valeur"] is not None or b["valeur"] is not None:
            evaluables += 1
        for ch in champs:
            if not _strictement_egal(a[ch], b[ch]):
                ecarts.append({"entity": e, "champ": ch,
                               "a_asof": a[ch], "a_vantage": b[ch]})

    if evaluables == 0 and not ecarts:
        raisons = [v["missing"] for v in c1.values() if v["missing"]][:3]
        raise InsufficientData(
            f"leak_check({spec.name}) : aucune valeur produite sur {len(entites)} entites "
            f"aux deux points d'observation — impossible de conclure. Causes : {raisons}"
        )

    rapport = LeakReport(spec=spec.name, asof=asof, vantage=asof + horizon,
                         entites_comparees=len(entites), ecarts=tuple(ecarts))
    if strict and not rapport.ok:
        raise LeakDetected(str(rapport))
    return rapport


def leak_check_all(specs: Sequence[FeatureSpec],
                   asof: datetime,
                   entities: Iterable[str] | None = None,
                   **kw) -> dict[str, LeakReport]:
    """Passe tous les specs au replay differentiel. strict=False force par defaut pour
    obtenir le tableau complet plutot que de s'arreter au premier coupable."""
    kw.setdefault("strict", False)
    ents = None if entities is None else list(entities)
    return {s.name: leak_check(s, asof, ents, **kw) for s in specs}


def discover_entities(source_name: str, asof: datetime, *,
                      loader: Loader | None = None, limit: int = 200) -> list[str]:
    """Entites presentes dans une source a asof — decouverte elle aussi bornee par la
    coupe point-in-time, sinon la seule liste des entites fuiterait deja le futur."""
    asof = _require_aware(asof, "asof")
    src = SOURCES.get(source_name)
    if src is None:
        raise ValueError(f"source inconnue : {source_name!r}")
    ent = ENTITY_COLUMN.get(source_name)
    if ent is None:
        raise ValueError(f"aucune colonne d'entite connue pour {source_name}")
    if loader is None:
        loader = ParquetLoader()
    vue = AsOfView(loader=loader, asof=asof)
    table = vue.pit(src, (ent,), None)
    vus: list[str] = []
    for v in table[ent].to_pylist():
        if v is not None and v not in vus:
            vus.append(v)
            if len(vus) >= limit:
                break
    return vus


# ===========================================================================
# Variables de reference sur orders_5m (seule surface reellement collectee)
# ===========================================================================
def _notional(r: dict) -> float | None:
    px, sz = r.get("limitPx"), r.get("sz")
    if px is None or sz is None:
        return None
    try:
        v = float(px) * float(sz)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _carnet(ctx: FeatureContext) -> tuple[datetime, list[dict]]:
    """Dernier carnet d'ordres connaissable a asof, ordres ouverts non declencheurs."""
    k, lignes = ctx.latest_snapshot()
    ouverts = [r for r in lignes if r.get("status") == "open" and not r.get("isTrigger")]
    require(bool(ouverts),
            f"{ctx.spec.name}[{ctx.entity}] : aucun ordre ouvert non declencheur dans le "
            f"carnet du {k.isoformat()} (les ordres declencheurs ont limitPx=0, les "
            "compter fabriquerait un notionnel nul)")
    return k, ouverts


def f_open_orders_count(ctx: FeatureContext, entity: str) -> int:
    _, lignes = ctx.latest_snapshot()
    oids = {r.get("oid") for r in lignes if r.get("status") == "open" and r.get("oid") is not None}
    require(bool(oids),
            f"open_orders_count[{entity}] : aucun oid exploitable dans le dernier carnet")
    return len(oids)


def f_open_notional_usd(ctx: FeatureContext, entity: str) -> float:
    _, ouverts = _carnet(ctx)
    vals = [n for n in (_notional(r) for r in ouverts) if n is not None and n > 0]
    require(bool(vals),
            f"open_notional_usd[{entity}] : limitPx ou sz absents/nuls sur tous les ordres "
            "ouverts — notionnel non calculable")
    return float(sum(vals))


def f_side_imbalance(ctx: FeatureContext, entity: str) -> float:
    """(notionnel achat - notionnel vente) / notionnel total, dans [-1, 1]."""
    _, ouverts = _carnet(ctx)
    achat = sell = 0.0
    for r in ouverts:
        n = _notional(r)
        if n is None or n <= 0:
            continue
        side = r.get("side")
        if side == "B":
            achat += n
        elif side == "A":
            sell += n
    total = achat + sell
    require(total > 0,
            f"side_imbalance[{entity}] : notionnel total nul ou side inconnu — "
            "desequilibre non defini")
    return (achat - sell) / total


def f_coin_concentration(ctx: FeatureContext, entity: str) -> float:
    """Herfindahl du notionnel par actif : 1 = mono-actif, ~1/n = disperse."""
    _, ouverts = _carnet(ctx)
    par_coin: dict[str, float] = {}
    for r in ouverts:
        n = _notional(r)
        c = r.get("coin")
        if n is None or n <= 0 or c is None:
            continue
        par_coin[c] = par_coin.get(c, 0.0) + n
    total = sum(par_coin.values())
    require(total > 0,
            f"coin_concentration[{entity}] : aucun notionnel positif rattachable a un actif")
    return float(sum((v / total) ** 2 for v in par_coin.values()))


def f_distinct_coins(ctx: FeatureContext, entity: str) -> int:
    _, lignes = ctx.latest_snapshot()
    coins = {r.get("coin") for r in lignes if r.get("status") == "open" and r.get("coin")}
    require(bool(coins), f"distinct_coins[{entity}] : aucun actif identifiable")
    return len(coins)


def f_reduce_only_share(ctx: FeatureContext, entity: str) -> float:
    """Part des ordres marques reduceOnly : proxy de posture defensive."""
    _, lignes = ctx.latest_snapshot()
    ouverts = [r for r in lignes if r.get("status") == "open"]
    require(bool(ouverts), f"reduce_only_share[{entity}] : aucun ordre ouvert")
    connus = [r for r in ouverts if r.get("reduceOnly") is not None]
    require(len(connus) == len(ouverts),
            f"reduce_only_share[{entity}] : reduceOnly absent sur "
            f"{len(ouverts) - len(connus)} ordre(s) — part non calculable sans imputation")
    return sum(1 for r in connus if r["reduceOnly"]) / len(connus)


def f_order_churn(ctx: FeatureContext, entity: str) -> float:
    """Rotation du carnet entre les deux derniers instants connaissables :
    |difference symetrique des oid| / |union|. Exige DEUX carnets reels."""
    snaps = ctx.snapshots()
    require(len(snaps) >= 2,
            f"order_churn[{entity}] : {len(snaps)} carnet(s) connaissable(s) au "
            f"{ctx.asof.isoformat()}, il en faut 2 pour mesurer une rotation")
    avant = {r.get("oid") for r in snaps[-2][1] if r.get("oid") is not None}
    apres = {r.get("oid") for r in snaps[-1][1] if r.get("oid") is not None}
    union = avant | apres
    require(bool(union), f"order_churn[{entity}] : aucun oid dans les deux derniers carnets")
    return len(avant ^ apres) / len(union)


def f_book_lifespan_ratio(ctx: FeatureContext, entity: str) -> float:
    """Part des oid presents dans TOUS les carnets connaissables : ordres dormants.
    Exige au moins deux carnets, sinon la mesure vaut trivialement 1."""
    snaps = ctx.snapshots()
    require(len(snaps) >= 2,
            f"book_lifespan_ratio[{entity}] : {len(snaps)} carnet(s), il en faut 2")
    ensembles = [{r.get("oid") for r in lignes if r.get("oid") is not None} for _, lignes in snaps]
    union = set().union(*ensembles)
    require(bool(union), f"book_lifespan_ratio[{entity}] : aucun oid exploitable")
    persistants = set.intersection(*ensembles)
    return len(persistants) / len(union)


_BUILTINS: tuple[tuple[str, Callable, tuple[str, ...], str, str], ...] = (
    ("orders5m.open_orders_count", f_open_orders_count,
     ("address", "oid", "status", "snapshotTime"), "int64",
     "Nombre d'ordres ouverts distincts dans le dernier carnet connaissable."),
    ("orders5m.open_notional_usd", f_open_notional_usd,
     ("address", "limitPx", "sz", "status", "isTrigger", "snapshotTime"), "float64",
     "Somme limitPx*sz des ordres ouverts non declencheurs."),
    ("orders5m.side_imbalance", f_side_imbalance,
     ("address", "limitPx", "sz", "side", "status", "isTrigger", "snapshotTime"), "float64",
     "Desequilibre achat/vente en notionnel, dans [-1, 1]."),
    ("orders5m.coin_concentration", f_coin_concentration,
     ("address", "limitPx", "sz", "coin", "status", "isTrigger", "snapshotTime"), "float64",
     "Herfindahl du notionnel par actif."),
    ("orders5m.distinct_coins", f_distinct_coins,
     ("address", "coin", "status", "snapshotTime"), "int64",
     "Nombre d'actifs distincts au carnet."),
    ("orders5m.reduce_only_share", f_reduce_only_share,
     ("address", "reduceOnly", "status", "snapshotTime"), "float64",
     "Part des ordres reduceOnly."),
    ("orders5m.order_churn", f_order_churn,
     ("address", "oid", "snapshotTime"), "float64",
     "Rotation des oid entre les deux derniers carnets."),
    ("orders5m.book_lifespan_ratio", f_book_lifespan_ratio,
     ("address", "oid", "snapshotTime"), "float64",
     "Part des oid presents dans tous les carnets connaissables."),
)


def install_builtin_specs(*, replace: bool = True) -> tuple[FeatureSpec, ...]:
    """Enregistre les variables de reference. Idempotent par defaut.

    Toutes portent sur orders_5m : c'est la seule surface reellement collectee a ce
    jour. Aucune variable de performance (PnL, drawdown, win rate, persistance) n'est
    definie ici tant que closed_trades / fills / wallets n'ont pas ete captures — les
    ecrire maintenant reviendrait a livrer du code dont la sortie ne peut pas exister.
    """
    out = []
    for nom, fn, req, dtype, desc in _BUILTINS:
        out.append(register(FeatureSpec(name=nom, source="orders_5m", fn=fn,
                                        requires=req, dtype=dtype, description=desc),
                            replace=replace))
    return tuple(out)


install_builtin_specs()
