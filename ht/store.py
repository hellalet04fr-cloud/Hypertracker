"""
Couche d'accès unique au lac Parquet — lecture *as-of* stricte.

Principe : aucun moteur en aval ne lit un fichier Parquet directement. Tout passe par
`open_lake()`, qui expose des relations duckdb déjà bornées sur `knowable_at <= asof`.
C'est le seul endroit du projet où l'on décide « cette ligne était-elle connaissable ? ».

Trois invariants tenus ici, et nulle part ailleurs :

1. Aucune valeur par défaut ne remplace une donnée absente. Une source absente du disque
   n'est pas un lac vide : `as_of()` lève `InsufficientData` avec le chemin cherché.
   Une ligne dont le `valid_time` est NULL n'est pas datée à `epoch` : elle est écartée
   et comptée (`null_valid_time_count`), parce qu'une ligne non datable n'est jamais
   connaissable.
2. `knowable_at` = `valid_time` + latence de publication de `schema.knowable_at_for`.
   La latence n'est pas recopiée ici : elle est *mesurée* sur `knowable_at_for` à
   l'ouverture, pour qu'un changement du contrat se propage sans édition de ce fichier.
   Si le Parquet porte déjà une colonne `knowable_at`, elle fait foi (l'ingestion sait
   mieux que le défaut prudent).
3. La pseudo-adresse TWAP est retirée de toute relation portant une colonne `address`.
   Le nombre de lignes retirées reste interrogeable (`twap_excluded_count`) : un biais
   qu'on mesure, pas un biais qu'on cache.

Ce module ne calcule aucune statistique. Il ne fait que borner et compter.
"""
from __future__ import annotations

import os
import glob as _glob
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from ht.schema import (
    SOURCES,
    Source,
    InsufficientData,
    knowable_at_for,
    require,
    utcnow,
)

# --------------------------------------------------------------------------- constantes

#: Les exécutions TWAP sont attribuées à cette pseudo-adresse (0x + 64 zéros hex).
#: Ce n'est PAS une adresse EVM valide (une vraie fait 40 hex). L'agréger par wallet
#: fabriquerait un « trader » géant qui n'existe pas. Exclusion systématique.
TWAP_PSEUDO_ADDRESS = "0x" + "0" * 64

#: Racine du lac. Surchargeable par variable d'environnement pour les tests et le runtime.
DEFAULT_LAKE_ROOT = Path(os.environ.get("HT_LAKE_ROOT", str(Path.home() / "ht_data")))

#: Bornes de plausibilité d'un instant du lac. Hors de cet intervalle, on refuse de
#: deviner l'unité d'un timestamp numérique plutôt que de dater une ligne à l'an 1970.
_PLAUSIBLE_MIN = datetime(2020, 1, 1, tzinfo=timezone.utc)
_PLAUSIBLE_FUTURE_MARGIN = timedelta(days=7)

#: Types duckdb considérés comme un instant déjà typé.
_TS_TYPES = {"TIMESTAMP WITH TIME ZONE", "TIMESTAMP_TZ", "TIMESTAMP", "DATE",
             "TIMESTAMP_S", "TIMESTAMP_MS", "TIMESTAMP_NS"}
_NUMERIC_TYPES = {"BIGINT", "INTEGER", "HUGEINT", "UBIGINT", "UINTEGER",
                  "DOUBLE", "FLOAT", "DECIMAL"}


# --------------------------------------------------------------------------- couverture

@dataclass(frozen=True)
class Coverage:
    """
    Ce que le lac contient réellement pour une source. Un moteur en aval s'en sert pour
    REFUSER de calculer (« 8 snapshots sur 40 minutes ne font pas une série temporelle »),
    jamais pour extrapoler.
    """
    source: str
    min_valid_time: datetime
    max_valid_time: datetime
    n_rows: int
    n_partitions: int              # nombre de fichiers Parquet distincts (unité de collecte)
    n_hive_partitions: int | None  # nombre de valeurs distinctes de la clé de partitionnement (dt=...)
    null_valid_time_count: int     # lignes non datables, donc jamais connaissables
    twap_rows: int                 # lignes attribuées à la pseudo-adresse TWAP, exclues partout

    @property
    def span(self) -> timedelta:
        return self.max_valid_time - self.min_valid_time

    def as_tuple(self) -> tuple[datetime, datetime, int, int]:
        """Forme courte du contrat : (min_valid_time, max_valid_time, n_rows, n_partitions)."""
        return (self.min_valid_time, self.max_valid_time, self.n_rows, self.n_partitions)


# --------------------------------------------------------------------------- vue interne

@dataclass
class _SourceView:
    source: Source
    view: str
    files: tuple[str, ...]
    columns: dict[str, str]          # nom -> type duckdb
    vt_expr: str | None = None       # expression SQL -> TIMESTAMPTZ (valid_time)
    ka_expr: str | None = None       # expression SQL -> TIMESTAMPTZ (knowable_at)
    lag_s: float | None = None       # latence appliquée, None si knowable_at natif
    resolved: bool = False


def _sql_str(value: str) -> str:
    """Littéral SQL simple-quote échappé."""
    return "'" + value.replace("'", "''") + "'"


def _ts_literal(moment: datetime) -> str:
    return f"TIMESTAMPTZ {_sql_str(moment.astimezone(timezone.utc).isoformat())}"


def _publication_lag_s(source_name: str) -> float:
    """
    Latence de publication *mesurée* sur schema.knowable_at_for, pour ne pas dupliquer
    la table des défauts. Si le contrat change, ce module suit sans être modifié.
    """
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lag = (knowable_at_for(source_name, base) - base).total_seconds()
    require(lag >= 0.0,
            f"latence de publication negative pour '{source_name}' ({lag}s) : "
            "knowable_at_for est incoherent, un backtest fuiterait le futur")
    return lag


# --------------------------------------------------------------------------- le lac

class Lake:
    """
    Connexion duckdb + une vue par source réellement présente sur disque.

    Une source absente ne casse rien : `available()` renvoie False et toute tentative
    de lecture lève `InsufficientData` en nommant le répertoire attendu.
    """

    def __init__(self, root: Path, connection: duckdb.DuckDBPyConnection | None = None):
        self.root = Path(root)
        self.con = connection if connection is not None else duckdb.connect(":memory:")
        # Sans cela, l'affichage et les casts TIMESTAMPTZ dependraient du fuseau de la
        # machine : une meme requete donnerait deux bornes as-of selon le poste.
        self.con.execute("SET TimeZone='UTC'")
        _require_pytz()
        self._views: dict[str, _SourceView] = {}
        self._register_all()

    # ---------------------------------------------------------------- découverte

    def _files_for(self, name: str) -> tuple[str, ...]:
        base = self.root / name
        if not base.is_dir():
            return ()
        pattern = str(base / "**" / "*.parquet").replace("\\", "/")
        return tuple(sorted(p.replace("\\", "/") for p in _glob.glob(pattern, recursive=True)))

    def _register_all(self) -> None:
        for name in SOURCES:
            files = self._files_for(name)
            if not files:
                continue
            view = f"lake_{name}"
            pattern = str(self.root / name / "**" / "*.parquet").replace("\\", "/")
            # union_by_name : les snapshots d'une meme source peuvent avoir gagne une
            # colonne en cours de route ; on ne veut ni planter ni tronquer.
            # filename : provenance ligne a ligne, indispensable pour auditer une valeur.
            self.con.execute(
                f"CREATE OR REPLACE VIEW {view} AS "
                f"SELECT * FROM read_parquet({_sql_str(pattern)}, "
                f"hive_partitioning=true, union_by_name=true, filename=true)"
            )
            cols = {r[0]: r[1] for r in self.con.execute(f"DESCRIBE {view}").fetchall()}
            self._views[name] = _SourceView(
                source=SOURCES[name], view=view, files=files, columns=cols
            )

    def refresh(self) -> None:
        """Re-scanne le disque. À appeler après une collecte, sans rouvrir la connexion."""
        for v in self._views.values():
            self.con.execute(f"DROP VIEW IF EXISTS {v.view}")
        self._views.clear()
        self._register_all()

    # ---------------------------------------------------------------- introspection

    @staticmethod
    def _known(source: str) -> Source:
        if source not in SOURCES:
            raise ValueError(
                f"source inconnue : {source!r}. Sources du contrat : {sorted(SOURCES)}"
            )
        return SOURCES[source]

    def available(self, source: str) -> bool:
        """True si au moins un fichier Parquet de cette source est sur disque."""
        self._known(source)
        return source in self._views

    def sources_available(self) -> tuple[str, ...]:
        return tuple(sorted(self._views))

    def sources_missing(self) -> tuple[str, ...]:
        return tuple(sorted(n for n in SOURCES if n not in self._views))

    def files(self, source: str) -> tuple[str, ...]:
        self._require_available(source)
        return self._views[source].files

    def columns(self, source: str) -> tuple[str, ...]:
        """Colonnes réellement présentes sur disque (pas celles annoncées par le contrat)."""
        self._require_available(source)
        return tuple(self._views[source].columns)

    def missing_columns(self, source: str) -> tuple[str, ...]:
        """
        Colonnes du contrat absentes du disque. Une source DOCUMENTED peut mentir :
        c'est déjà arrivé. Un moteur vérifie ceci avant de lire un champ.
        """
        self._require_available(source)
        present = set(self._views[source].columns)
        return tuple(c for c in SOURCES[source].columns if c not in present)

    def check_columns(self, source: str, needed) -> None:
        """Lève InsufficientData si une colonne requise manque physiquement."""
        self._require_available(source)
        present = set(self._views[source].columns)
        absent = [c for c in needed if c not in present]
        require(not absent,
                f"colonnes absentes du lac pour '{source}' : {absent}. "
                f"Presentes : {sorted(present)}")

    def _require_available(self, source: str) -> _SourceView:
        self._known(source)
        if source not in self._views:
            raise InsufficientData(
                f"source '{source}' absente du lac : aucun fichier "
                f"{self.root / source}/**/*.parquet. Rien n'a encore ete collecte pour "
                f"cette source ; aucun calcul ne peut la remplacer."
            )
        return self._views[source]

    # ---------------------------------------------------------------- axe temporel

    def _resolve_time(self, source: str) -> _SourceView:
        """
        Détermine, une fois pour toutes, comment lire l'instant d'une source.
        Toute ambiguïté (unité epoch indécidable, texte non parsable, colonne vide)
        est une erreur, jamais une supposition.
        """
        sv = self._require_available(source)
        if sv.resolved:
            return sv

        cols = sv.columns

        # 1) knowable_at natif : l'ingestion a mesure la latence, elle prime sur le defaut.
        if "knowable_at" in cols:
            sv.ka_expr = self._to_timestamptz(sv, "knowable_at")
            sv.lag_s = None
        # 2) sinon on le derive du valid_time du contrat.
        vt_col = sv.source.valid_time
        require(vt_col is not None,
                f"source '{source}' n'a pas de colonne valid_time au contrat : "
                "impossible de la borner as-of, donc impossible de l'utiliser en amont "
                "d'un modele")
        require(vt_col in cols,
                f"colonne valid_time '{vt_col}' absente du lac pour '{source}'. "
                f"Colonnes presentes : {sorted(cols)}")
        sv.vt_expr = self._to_timestamptz(sv, vt_col)

        if sv.ka_expr is None:
            lag = _publication_lag_s(source)
            sv.lag_s = lag
            micros = int(round(lag * 1_000_000))
            sv.ka_expr = f"({sv.vt_expr} + to_microseconds({micros}))"

        # Une source dont AUCUNE ligne n'est datable n'est pas une source vide : c'est
        # une source cassee. On le dit, on ne date pas a epoch.
        n_total, n_dated = self.con.execute(
            f"SELECT count(*), count({sv.vt_expr}) FROM {sv.view}"
        ).fetchone()
        require(n_total > 0, f"source '{source}' presente sur disque mais vide (0 ligne)")
        require(n_dated > 0,
                f"source '{source}' : les {n_total} lignes ont un valid_time "
                f"('{vt_col}') NULL ou non convertible. Aucune n'est datable, donc "
                "aucune n'est connaissable.")

        # Plausibilite : refuse de servir des instants hors du domaine du projet plutot
        # que de laisser un backtest tourner sur des dates de 1970.
        lo, hi = self.con.execute(
            f"SELECT min({sv.vt_expr}), max({sv.vt_expr}) FROM {sv.view}"
        ).fetchone()
        upper = utcnow() + _PLAUSIBLE_FUTURE_MARGIN
        require(lo >= _PLAUSIBLE_MIN and hi <= upper,
                f"source '{source}' : valid_time hors bornes plausibles "
                f"[{_PLAUSIBLE_MIN.isoformat()}, {upper.isoformat()}] -> "
                f"[{lo}, {hi}]. Unite epoch mal interpretee ou donnees corrompues.")

        sv.resolved = True
        return sv

    def _to_timestamptz(self, sv: _SourceView, col: str) -> str:
        """
        Expression SQL convertissant `col` en TIMESTAMPTZ UTC.
        L'unite d'un epoch numerique est DEDUITE des valeurs reelles, pas supposee ;
        si les valeurs s'etalent sur deux unites possibles, on refuse.
        """
        dtype = sv.columns[col].upper()
        q = f'"{col}"'

        if dtype.startswith("TIMESTAMP WITH TIME ZONE") or dtype in ("TIMESTAMPTZ", "TIMESTAMP_TZ"):
            return q
        if dtype.startswith("TIMESTAMP") or dtype == "DATE":
            # Instant naif : le lac est en UTC par convention d'ingestion.
            return f"({q} AT TIME ZONE 'UTC')"
        if dtype == "VARCHAR":
            bad = self.con.execute(
                f"SELECT count(*) FROM {sv.view} "
                f"WHERE {q} IS NOT NULL AND TRY_CAST({q} AS TIMESTAMPTZ) IS NULL"
            ).fetchone()[0]
            require(bad == 0,
                    f"colonne '{col}' de '{sv.source.name}' : {bad} valeurs texte non "
                    "convertibles en instant. Aucune date de repli ne sera inventee.")
            return f"CAST({q} AS TIMESTAMPTZ)"
        if any(dtype.startswith(t) for t in _NUMERIC_TYPES):
            lo, hi = self.con.execute(
                f"SELECT min(CAST({q} AS DOUBLE)), max(CAST({q} AS DOUBLE)) FROM {sv.view}"
            ).fetchone()
            require(lo is not None,
                    f"colonne '{col}' de '{sv.source.name}' entierement NULL : "
                    "aucune ligne n'est datable.")
            u_lo, u_hi = _epoch_unit(lo, col, sv.source.name), _epoch_unit(hi, col, sv.source.name)
            require(u_lo == u_hi,
                    f"colonne '{col}' de '{sv.source.name}' : unites epoch melangees "
                    f"({u_lo} pour min={lo}, {u_hi} pour max={hi}). Indecidable, on refuse.")
            return f"to_timestamp(CAST({q} AS DOUBLE) / {float(u_lo)})"

        raise InsufficientData(
            f"colonne '{col}' de '{sv.source.name}' de type {dtype} : "
            "impossible d'en faire un instant sans supposition."
        )

    # ---------------------------------------------------------------- lecture as-of

    def raw(self, source: str) -> duckdb.DuckDBPyRelation:
        """
        Relation NON bornee, TWAP inclus. Reservee a l'audit et a la mesure de biais.
        Ne jamais la donner a un moteur de variables : elle contient le futur.
        """
        sv = self._require_available(source)
        return self.con.sql(f"SELECT * FROM {sv.view}")

    def _address_filter(self, sv: _SourceView) -> str:
        if "address" not in sv.columns:
            return ""
        return (f" AND (\"address\" IS NULL OR lower(CAST(\"address\" AS VARCHAR)) "
                f"<> {_sql_str(TWAP_PSEUDO_ADDRESS)})")

    def as_of(self, source: str, asof: datetime,
              columns: tuple[str, ...] | None = None) -> duckdb.DuckDBPyRelation:
        """
        Relation bornee : uniquement les lignes dont `knowable_at <= asof`.

        Deux colonnes sont ajoutees : `valid_time` et `knowable_at` (TIMESTAMPTZ UTC),
        pour qu'un moteur en aval puisse re-verifier lui-meme l'absence de fuite.
        La pseudo-adresse TWAP est exclue. Les lignes non datables sont exclues.
        """
        _require_aware(asof)
        sv = self._resolve_time(source)
        if columns is not None:
            self.check_columns(source, columns)
            forbidden = sorted(set(columns) & set(sv.source.post_hoc))
            require(not forbidden,
                    f"colonnes post-hoc demandees sur '{source}' : {forbidden}. "
                    "Ces champs sont contamines par le futur (contrat schema.Source.post_hoc) "
                    "et ne peuvent pas servir a une variable point-in-time.")
            projection = ", ".join(f'"{c}"' for c in columns)
        else:
            projection = "*"

        vt = sv.vt_expr if sv.vt_expr else sv.ka_expr
        return self.con.sql(
            f"SELECT {projection}, {vt} AS valid_time, {sv.ka_expr} AS knowable_at "
            f"FROM {sv.view} "
            f"WHERE {vt} IS NOT NULL AND {sv.ka_expr} <= {_ts_literal(asof)}"
            f"{self._address_filter(sv)}"
        )

    def select_asof(self, source: str, columns, asof: datetime) -> duckdb.DuckDBPyRelation:
        """as_of restreint a une projection, avec refus explicite des colonnes post-hoc."""
        return self.as_of(source, asof, columns=tuple(columns))

    # ------- raccourcis nommes (une source absente leve, elle ne renvoie pas du vide)

    def orders_asof(self, asof: datetime) -> duckdb.DuckDBPyRelation:
        return self.as_of("orders_5m", asof)

    def wallets_asof(self, asof: datetime) -> duckdb.DuckDBPyRelation:
        return self.as_of("wallets", asof)

    def segments_asof(self, asof: datetime) -> duckdb.DuckDBPyRelation:
        return self.as_of("segments", asof)

    def closed_trades_asof(self, asof: datetime) -> duckdb.DuckDBPyRelation:
        return self.as_of("closed_trades", asof)

    def fills_asof(self, asof: datetime) -> duckdb.DuckDBPyRelation:
        return self.as_of("fills", asof)

    def leaderboards_asof(self, asof: datetime) -> duckdb.DuckDBPyRelation:
        """
        Attention : les leaderboards n'ont aucun parametre as-of cote API. Le filtre
        applique ici porte sur l'instant de CAPTURE, pas sur un classement historique.
        Le contenu reste une selection de survivants ; ce module ne peut pas corriger ca.
        """
        return self.as_of("leaderboards", asof)

    # ---------------------------------------------------------------- couverture

    def coverage(self, source: str) -> Coverage:
        """
        Etendue reelle des donnees (TWAP exclu, lignes non datables exclues du min/max).
        Leve InsufficientData si la source est absente ou vide.
        """
        sv = self._resolve_time(source)
        addr = self._address_filter(sv)
        where = f"WHERE 1=1{addr}" if addr else ""
        row = self.con.execute(
            f"SELECT min({sv.vt_expr}), max({sv.vt_expr}), count(*), "
            f"count(DISTINCT filename), count(*) - count({sv.vt_expr}) "
            f"FROM {sv.view} {where}"
        ).fetchone()
        lo, hi, n_rows, n_files, n_null = row
        require(n_rows > 0,
                f"source '{source}' : 0 ligne exploitable apres exclusion TWAP")
        require(lo is not None and hi is not None,
                f"source '{source}' : aucune ligne datable, couverture indefinissable")

        hive = None
        for cand in ("dt", "date", "day"):
            if cand in sv.columns and cand not in sv.source.columns:
                hive = self.con.execute(
                    f"SELECT count(DISTINCT \"{cand}\") FROM {sv.view}"
                ).fetchone()[0]
                break

        return Coverage(
            source=source, min_valid_time=lo, max_valid_time=hi, n_rows=n_rows,
            n_partitions=n_files, n_hive_partitions=hive,
            null_valid_time_count=n_null, twap_rows=self.twap_excluded_count(source),
        )

    def coverage_asof(self, source: str, asof: datetime) -> Coverage:
        """Couverture de ce qui etait connaissable a `asof`. Sert a refuser un calcul
        dont la fenetre d'apprentissage n'existait pas encore."""
        _require_aware(asof)
        rel = self.as_of(source, asof)
        lo, hi, n_rows, n_files = rel.aggregate(
            "min(valid_time), max(valid_time), count(*), count(DISTINCT filename)"
        ).fetchone()
        require(n_rows > 0,
                f"source '{source}' : rien n'etait connaissable a {asof.isoformat()} "
                f"(premiere ligne connaissable : {self.first_knowable_at(source).isoformat()})")
        return Coverage(source=source, min_valid_time=lo, max_valid_time=hi, n_rows=n_rows,
                        n_partitions=n_files, n_hive_partitions=None,
                        null_valid_time_count=0, twap_rows=0)

    def first_knowable_at(self, source: str) -> datetime:
        sv = self._resolve_time(source)
        v = self.con.execute(f"SELECT min({sv.ka_expr}) FROM {sv.view}").fetchone()[0]
        require(v is not None, f"source '{source}' : aucun knowable_at calculable")
        return v

    def last_knowable_at(self, source: str) -> datetime:
        sv = self._resolve_time(source)
        v = self.con.execute(f"SELECT max({sv.ka_expr}) FROM {sv.view}").fetchone()[0]
        require(v is not None, f"source '{source}' : aucun knowable_at calculable")
        return v

    def publication_lag_s(self, source: str) -> float | None:
        """Latence appliquee (None si le lac porte un knowable_at natif)."""
        return self._resolve_time(source).lag_s

    def twap_excluded_count(self, source: str) -> int:
        """Nombre de lignes retirees a cause de la pseudo-adresse TWAP. Biais mesure."""
        sv = self._require_available(source)
        if "address" not in sv.columns:
            return 0
        return self.con.execute(
            f"SELECT count(*) FROM {sv.view} WHERE lower(CAST(\"address\" AS VARCHAR)) = "
            f"{_sql_str(TWAP_PSEUDO_ADDRESS)}"
        ).fetchone()[0]

    def require_coverage(self, source: str, *, min_rows: int = 1,
                         min_span: timedelta | None = None,
                         min_partitions: int = 1,
                         asof: datetime | None = None) -> Coverage:
        """
        Garde-fou d'entree pour tout moteur : leve InsufficientData tant que le lac ne
        porte pas de quoi calculer. A appeler AVANT le premier calcul, pas apres.
        """
        cov = self.coverage_asof(source, asof) if asof is not None else self.coverage(source)
        require(cov.n_rows >= min_rows,
                f"'{source}' : {cov.n_rows} lignes < {min_rows} requises")
        require(cov.n_partitions >= min_partitions,
                f"'{source}' : {cov.n_partitions} partitions < {min_partitions} requises")
        if min_span is not None:
            require(cov.span >= min_span,
                    f"'{source}' : couverture de {cov.span} < {min_span} requise "
                    f"({cov.min_valid_time.isoformat()} -> {cov.max_valid_time.isoformat()}). "
                    "Trop court pour etre une serie temporelle.")
        return cov

    # ---------------------------------------------------------------- cycle de vie

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Lake":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return (f"<Lake root={self.root} presentes={list(self.sources_available())} "
                f"absentes={list(self.sources_missing())}>")


# --------------------------------------------------------------------------- helpers

def _epoch_unit(value: float, col: str, source: str) -> float:
    """
    Diviseur ramenant un epoch numerique en secondes. Deduit de l'ordre de grandeur,
    et seulement dans des plages non ambigues pour l'epoque du projet (>= 2020).
    """
    v = abs(float(value))
    if 1.5e9 <= v < 1e11:
        return 1.0            # secondes
    if 1.5e12 <= v < 1e14:
        return 1e3            # millisecondes
    if 1.5e15 <= v < 1e17:
        return 1e6            # microsecondes
    if 1.5e18 <= v < 1e20:
        return 1e9            # nanosecondes
    raise InsufficientData(
        f"colonne '{col}' de '{source}' : valeur epoch {value!r} d'unite indecidable. "
        "Aucune unite par defaut ne sera supposee."
    )


def _require_pytz() -> None:
    """
    duckdb ne sait convertir un TIMESTAMP WITH TIME ZONE en datetime Python *aware*
    que si pytz est installe. Sans lui, les instants remonteraient naifs et le
    contrat schema.Clocks (tz-aware obligatoire) serait viole en silence.
    On echoue tot, avec la commande a taper.
    """
    try:
        import pytz  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depend de l'environnement
        raise InsufficientData(
            "pytz est requis : duckdb en a besoin pour rendre des instants "
            "timezone-aware. Installer avec `python -m pip install pytz`."
        ) from exc


def _require_aware(asof: datetime) -> None:
    if not isinstance(asof, datetime):
        raise ValueError(f"asof doit etre un datetime, recu {type(asof).__name__}")
    if asof.tzinfo is None or asof.tzinfo.utcoffset(asof) is None:
        raise ValueError(
            "asof doit etre timezone-aware (UTC). Un instant naif rend la borne as-of "
            "dependante du fuseau de la machine : c'est une fuite de futur potentielle."
        )


def open_lake(root: str | Path | None = None) -> Lake:
    """
    Ouvre le lac et cree une vue duckdb par source presente sur disque.
    Ne leve jamais parce qu'une source manque : c'est `available()` qui le dit,
    et `as_of()` qui refuse de servir du vide.
    """
    return Lake(Path(root) if root is not None else DEFAULT_LAKE_ROOT)
