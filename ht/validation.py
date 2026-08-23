#!/usr/bin/env python3
"""
Cadre de validation temporelle stricte (walk-forward / out-of-sample).

Ce module ne calcule aucune performance : il produit et VERIFIE la géométrie
temporelle dans laquelle un modèle a le droit d'être entraîné puis évalué.
Tout ce qui suit part d'un principe unique : un backtest n'est borné que par
`knowable_at` (cf. ht.schema.Clocks), jamais par `valid_time`.

POURQUOI PURGE ET EMBARGO SONT OBLIGATOIRES (et non optionnels)
---------------------------------------------------------------
1) PURGE — un trade ouvert à cheval sur la frontière train/test fuit.
   Une variable observée à t porte une étiquette qui n'est connue qu'à t+h
   (h = horizon de détention : sortie de position, PnL réalisé, liquidation).
   Si la fenêtre d'entraînement se termine à T et que le test commence à T,
   toutes les observations d'entraînement situées dans [T-h, T) ont une
   étiquette qui recouvre le début du test : le modèle apprend, indirectement,
   ce qui se produit pendant la période d'évaluation. La purge est l'intervalle
   vide [train_end, test_start) qui absorbe cet horizon. Elle doit valoir au
   moins la durée de détention maximale des trades étiquetés
   (cf. `check_purge_covers`). Une purge nulle N'EST PAS une purge.

2) EMBARGO — la contamination joue aussi dans l'autre sens. Les observations
   qui suivent immédiatement la fin du test partagent avec lui la même
   micro-structure (ordres encore ouverts, même vague de flux, autocorrélation
   sérielle). Les réinjecter telles quelles dans l'entraînement du pli suivant
   revient à entraîner sur le voisinage immédiat d'un test déjà consommé.
   L'embargo neutralise [test_end, test_end + embargo) dans TOUS les plis
   ultérieurs : c'est `Fold.excluded`.

Le sens des bornes est uniforme : toutes les fenêtres sont semi-ouvertes
[début, fin). Un instant exactement égal à `fin` n'appartient pas à la fenêtre.

BIAIS QUE CE MODULE NE PEUT PAS CORRIGER (il les signale, il ne les répare pas)
------------------------------------------------------------------------------
  - Survie : les cohortes de performance excluent les wallets inactifs. Un
    walk-forward sur un univers déjà filtré reste un walk-forward sur des
    survivants. Aucune purge ne répare une population.
  - Rétro-attribution des cohortes : l'appartenance est recalculée en amont
    toutes les 3-4 h sur le PnL all-time. Seule la valeur figée à l'ingestion
    est utilisable ; `assert_capture_covers` refuse les plis antérieurs à la
    première capture d'une source non reconstituable.
  - Rupture structurelle du 2026-09-02 sur les prix de liquidation : un pli
    qui entraîne avant et teste après évalue un autre régime.
    `folds_crossing` les énumère, `assert_no_crossing` les refuse.
  - Les exécutions TWAP portent la pseudo-adresse 0x000...0 (64 hex) : leur
    exclusion relève de l'agrégation par wallet, en amont de ce module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from .schema import SOURCES, InsufficientData, knowable_at_for, require

ZERO = timedelta(0)

# Sources sans endpoint historique : ce qui n'a pas été capturé est perdu.
# Un pli d'entraînement antérieur à la première capture n'a pas de données.
NON_RECONSTRUCTIBLE = frozenset({"leaderboards", "wallets", "segments"})

# Ruptures structurelles connues, mesurées en amont.
STRUCTURAL_BREAKS: dict[str, datetime] = {
    # Prix de liquidation statiques avant, évolutifs après : toute variable de
    # distance à la liquidation est non stationnaire de part et d'autre.
    "liquidation_px": datetime(2026, 9, 2, tzinfo=timezone.utc),
}


# --------------------------------------------------------------------------- erreurs
class ValidationConfigError(ValueError):
    """Configuration de validation invalide (fenêtres vides, pas incohérent...)."""


class LeakageError(ValidationConfigError):
    """Géométrie fuyante : le train voit, directement ou non, la période de test."""


# --------------------------------------------------------------------------- utilitaires
def _aware(value: datetime, nom: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationConfigError(f"{nom} doit être un datetime, reçu {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationConfigError(f"{nom} doit être timezone-aware (UTC) : {value!r}")
    return value.astimezone(timezone.utc)


def _duree(value: timedelta, nom: str, *, strictement_positive: bool = True) -> timedelta:
    if not isinstance(value, timedelta):
        raise ValidationConfigError(f"{nom} doit être un timedelta, reçu {type(value).__name__}")
    if strictement_positive and value <= ZERO:
        raise LeakageError(
            f"{nom} doit être strictement positif ({value} fourni). "
            "Purge et embargo ne sont pas optionnels : sans eux, une étiquette "
            "ouverte à la frontière train/test fait fuiter le futur."
        )
    if not strictement_positive and value < ZERO:
        raise ValidationConfigError(f"{nom} ne peut pas être négatif ({value})")
    return value


def _chevauche(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    """Intersection non vide de deux intervalles semi-ouverts [a0,a1) et [b0,b1)."""
    return a0 < b1 and b0 < a1


def calendrier(dates: Iterable[datetime]) -> tuple[datetime, ...]:
    """Normalise un calendrier : UTC, trié, dédoublonné. Refuse le vide et le naïf."""
    vals = [_aware(d, "date du calendrier") for d in dates]
    require(len(vals) > 0, "calendrier vide : aucune date fournie, aucun pli constructible")
    return tuple(sorted(set(vals)))


def calendrier_epoch_ms(values: Iterable[int]) -> tuple[datetime, ...]:
    """Calendrier depuis des epochs en millisecondes (format de snapshotTime)."""
    return calendrier(datetime.fromtimestamp(int(v) / 1000.0, tz=timezone.utc) for v in values)


# --------------------------------------------------------------------------- pli
@dataclass(frozen=True)
class Fold:
    """
    Un pli walk-forward. Toutes les fenêtres sont semi-ouvertes [début, fin).

    Disposition sur l'axe du temps :

        [train_start, train_end) | purge | [test_start, test_end) | embargo |
                                 ^ train_asof                     ^ test_asof

    `excluded` liste les zones d'embargo des plis PRECEDENTS qui tombent dans
    cette fenêtre d'entraînement : elles sont retirées du train.

    L'objet refuse d'exister s'il est fuyant : la validation est faite à la
    construction, on ne peut donc pas détenir un pli invalide.
    """
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    purge: timedelta
    embargo: timedelta
    excluded: tuple[tuple[datetime, datetime], ...] = ()
    n_train: int | None = None   # None = calendrier non fourni, jamais « 0 par défaut »
    n_test: int | None = None

    def __post_init__(self):
        s = object.__setattr__
        s(self, "train_start", _aware(self.train_start, "train_start"))
        s(self, "train_end", _aware(self.train_end, "train_end"))
        s(self, "test_start", _aware(self.test_start, "test_start"))
        s(self, "test_end", _aware(self.test_end, "test_end"))
        s(self, "purge", _duree(self.purge, "purge"))
        s(self, "embargo", _duree(self.embargo, "embargo"))
        s(self, "excluded", tuple(
            (_aware(a, "excluded.start"), _aware(b, "excluded.end")) for a, b in self.excluded
        ))
        self._verifier()

    # -- invariants ------------------------------------------------------
    def _verifier(self) -> None:
        if self.train_start >= self.train_end:
            raise ValidationConfigError(
                f"pli {self.index} : fenêtre d'entraînement vide ou inversée "
                f"[{self.train_start}, {self.train_end})"
            )
        if self.test_start >= self.test_end:
            raise ValidationConfigError(
                f"pli {self.index} : fenêtre de test vide ou inversée "
                f"[{self.test_start}, {self.test_end})"
            )
        if self.test_end <= self.train_start:
            raise LeakageError(
                f"pli {self.index} : le test [{self.test_start}, {self.test_end}) PRECEDE "
                f"l'entraînement [{self.train_start}, {self.train_end}). Entraîner sur le futur "
                "de la période évaluée n'est pas un backtest."
            )
        if _chevauche(self.train_start, self.train_end, self.test_start, self.test_end):
            raise LeakageError(
                f"pli {self.index} : chevauchement train [{self.train_start}, {self.train_end}) / "
                f"test [{self.test_start}, {self.test_end}) — les mêmes instants servent à "
                "apprendre et à évaluer."
            )
        ecart = self.test_start - self.train_end
        if ecart < self.purge:
            raise LeakageError(
                f"pli {self.index} : écart train/test = {ecart} < purge = {self.purge}. "
                "Les étiquettes ouvertes à la frontière recouvrent le début du test."
            )
        for a, b in self.excluded:
            if a >= b:
                raise ValidationConfigError(f"pli {self.index} : intervalle exclu inversé [{a}, {b})")
            if not _chevauche(a, b, self.train_start, self.train_end):
                raise ValidationConfigError(
                    f"pli {self.index} : intervalle exclu [{a}, {b}) hors de la fenêtre "
                    "d'entraînement — exclusion sans objet, configuration suspecte."
                )

    # -- horloges --------------------------------------------------------
    @property
    def train_asof(self) -> datetime:
        """Instant d'arrêt des connaissances pour construire les variables du train.
        Toute ligne dont knowable_at > train_asof est interdite."""
        return self.train_end

    @property
    def test_asof(self) -> datetime:
        """Fin de la période évaluée. Aucune variable du pli ne peut la dépasser."""
        return self.test_end

    @property
    def purge_interval(self) -> tuple[datetime, datetime]:
        return (self.train_end, self.test_start)

    @property
    def embargo_interval(self) -> tuple[datetime, datetime]:
        return (self.test_end, self.test_end + self.embargo)

    @property
    def embargo_end(self) -> datetime:
        return self.test_end + self.embargo

    # -- appartenance ----------------------------------------------------
    def in_train(self, t: datetime) -> bool:
        t = _aware(t, "t")
        if not (self.train_start <= t < self.train_end):
            return False
        return not any(a <= t < b for a, b in self.excluded)

    def in_test(self, t: datetime) -> bool:
        t = _aware(t, "t")
        return self.test_start <= t < self.test_end

    def select(self, times: Sequence[datetime], part: str) -> tuple[int, ...]:
        """Indices des instants appartenant à `part` ('train' ou 'test')."""
        if part == "train":
            pred = self.in_train
        elif part == "test":
            pred = self.in_test
        else:
            raise ValidationConfigError("part doit valoir 'train' ou 'test'")
        return tuple(i for i, t in enumerate(times) if pred(t))

    def spans(self, instant: datetime) -> bool:
        """Vrai si `instant` tombe entre le début du train et la fin du test."""
        instant = _aware(instant, "instant")
        return self.train_start <= instant < self.test_end

    # -- garde point-in-time ---------------------------------------------
    def assert_pit(self, knowable_ats: Iterable[datetime], part: str = "train") -> None:
        """Refuse toute ligne connue APRES l'asof du morceau visé."""
        asof = self.train_asof if part == "train" else self.test_asof
        futurs = [_aware(k, "knowable_at") for k in knowable_ats]
        faute = [k for k in futurs if k > asof]
        if faute:
            raise LeakageError(
                f"pli {self.index} ({part}) : {len(faute)} ligne(s) avec knowable_at > asof "
                f"({asof.isoformat()}), la plus tardive à {max(faute).isoformat()}"
            )

    def __str__(self) -> str:
        f = "%Y-%m-%d %H:%M"
        return (f"pli {self.index:>2} | train [{self.train_start:{f}} -> {self.train_end:{f}}) "
                f"n={self.n_train if self.n_train is not None else '?'} | purge {self.purge} | "
                f"test [{self.test_start:{f}} -> {self.test_end:{f}}) "
                f"n={self.n_test if self.n_test is not None else '?'} | embargo {self.embargo}")


# --------------------------------------------------------------------------- couverture
@dataclass(frozen=True)
class Coverage:
    """Couverture REELLE, mesurée sur le calendrier fourni. Aucun champ n'est
    une valeur par défaut : tout est compté sur des dates existantes."""
    n_dates: int
    first_date: datetime
    last_date: datetime
    span: timedelta
    n_slots: int                      # plis géométriquement possibles
    n_folds: int                      # plis retenus (données réellement présentes)
    dropped: tuple[tuple[int, str], ...]
    dates_in_train: int
    dates_in_test: int
    dates_unused: int
    fraction_tested: float
    tested_span: timedelta            # union des fenêtres de test
    unused_tail: timedelta            # queue de calendrier jamais évaluée
    overlapping_tests: bool

    def rapport(self) -> str:
        lignes = [
            f"calendrier      : {self.n_dates} dates, {self.first_date.isoformat()} -> "
            f"{self.last_date.isoformat()} ({self.span})",
            f"plis            : {self.n_folds} retenus / {self.n_slots} géométriquement possibles",
            f"dates en test   : {self.dates_in_test}/{self.n_dates} "
            f"({self.fraction_tested:.1%}), union des tests = {self.tested_span}",
            f"dates en train  : {self.dates_in_train}/{self.n_dates}",
            f"jamais utilisées: {self.dates_unused} (queue non évaluée : {self.unused_tail})",
        ]
        for idx, motif in self.dropped:
            lignes.append(f"  slot {idx} écarté : {motif}")
        if self.overlapping_tests:
            lignes.append("  ATTENTION : fenêtres de test chevauchantes, OOS non indépendants")
        return "\n".join(lignes)


@dataclass(frozen=True)
class WalkForwardParams:
    train_window: timedelta
    test_window: timedelta
    step: timedelta
    purge: timedelta
    embargo: timedelta
    anchored: bool
    min_train: int
    min_test: int
    min_folds: int


@dataclass(frozen=True)
class WalkForwardPlan:
    """Séquence de plis + couverture mesurée. Se comporte comme une liste de plis."""
    folds: tuple[Fold, ...]
    coverage: Coverage
    params: WalkForwardParams

    def __len__(self) -> int:
        return len(self.folds)

    def __iter__(self):
        return iter(self.folds)

    def __getitem__(self, i):
        return self.folds[i]

    def rapport(self) -> str:
        return "\n".join([self.coverage.rapport()] + [str(f) for f in self.folds])


# --------------------------------------------------------------------------- walk-forward
def walk_forward(
    dates: Iterable[datetime],
    train_window: timedelta,
    test_window: timedelta,
    step: timedelta,
    purge: timedelta,
    embargo: timedelta,
    *,
    anchored: bool = False,
    min_train: int = 1,
    min_test: int = 1,
    min_folds: int = 3,
    allow_overlapping_tests: bool = False,
    origin: datetime | None = None,
) -> WalkForwardPlan:
    """
    Construit les plis walk-forward sur le calendrier `dates`.

    `dates` est la liste des instants réellement observés (valid_time des
    snapshots, par exemple). La géométrie est calculée sur l'axe du temps,
    mais un pli n'est retenu que s'il contient de VRAIES dates des deux côtés
    (>= min_train et >= min_test) : on ne fabrique pas un pli vide.

    purge et embargo sont des paramètres positionnels obligatoires et doivent
    être strictement positifs (voir l'en-tête du module).

    Lève InsufficientData si moins de `min_folds` plis sont exploitables, en
    indiquant le nombre réellement possible et le temps manquant.
    """
    cal = calendrier(dates)
    train_window = _duree(train_window, "train_window")
    test_window = _duree(test_window, "test_window")
    step = _duree(step, "step")
    purge = _duree(purge, "purge")
    embargo = _duree(embargo, "embargo")
    if min_train < 1 or min_test < 1:
        raise ValidationConfigError("min_train et min_test doivent valoir au moins 1")
    if min_folds < 1:
        raise ValidationConfigError("min_folds doit valoir au moins 1")
    if test_window > step and not allow_overlapping_tests:
        raise ValidationConfigError(
            f"step ({step}) < test_window ({test_window}) : les fenêtres de test se "
            "chevauchent, les performances OOS ne seraient pas indépendantes. "
            "Passer allow_overlapping_tests=True pour l'assumer explicitement."
        )

    t0 = _aware(origin, "origin") if origin is not None else cal[0]
    horizon = cal[-1]
    if origin is not None and t0 > horizon:
        raise ValidationConfigError(
            f"origin ({t0.isoformat()}) postérieure à la dernière date du calendrier "
            f"({horizon.isoformat()})"
        )

    # Nombre de plis géométriquement possibles : test_end(i) <= horizon.
    # test_end(i) = t0 + train_window + i*step + purge + test_window
    marge = horizon - t0 - train_window - purge - test_window
    n_slots = (marge // step) + 1 if marge >= ZERO else 0

    folds: list[Fold] = []
    dropped: list[tuple[int, str]] = []
    embargos: list[tuple[datetime, datetime]] = []   # zones d'embargo des slots précédents

    for i in range(n_slots):
        if anchored:
            train_start = t0
        else:
            train_start = t0 + i * step
        train_end = t0 + train_window + i * step
        test_start = train_end + purge
        test_end = test_start + test_window

        exclus = tuple(
            (max(a, train_start), min(b, train_end))
            for a, b in embargos
            if _chevauche(a, b, train_start, train_end)
        )
        # Zone d'embargo de CE slot, opposable aux slots suivants (même écarté :
        # le test a été consommé géométriquement, on n'y revient pas).
        embargos.append((test_end, test_end + embargo))

        pli = Fold(
            index=i,
            train_start=train_start, train_end=train_end,
            test_start=test_start, test_end=test_end,
            purge=purge, embargo=embargo, excluded=exclus,
        )
        n_tr = len(pli.select(cal, "train"))
        n_te = len(pli.select(cal, "test"))
        if n_tr < min_train or n_te < min_test:
            dropped.append((i, f"données réelles insuffisantes : {n_tr} date(s) en train "
                               f"(min {min_train}), {n_te} en test (min {min_test})"))
            continue
        folds.append(Fold(
            index=i,
            train_start=train_start, train_end=train_end,
            test_start=test_start, test_end=test_end,
            purge=purge, embargo=embargo, excluded=exclus,
            n_train=n_tr, n_test=n_te,
        ))

    cov = _couverture(cal, folds, dropped, n_slots, t0, horizon, test_window, step)

    if len(folds) < min_folds:
        besoin = t0 + train_window + purge + test_window + (min_folds - 1) * step
        manque = besoin - horizon
        raise InsufficientData(
            f"couverture insuffisante : {len(folds)} pli(s) exploitable(s) sur {n_slots} "
            f"géométriquement possible(s), minimum requis {min_folds}. "
            f"Calendrier {cal[0].isoformat()} -> {horizon.isoformat()} ({horizon - cal[0]}), "
            f"{len(cal)} dates. Il manque {manque} de données pour atteindre le pli n°{min_folds} "
            f"(train {train_window} + purge {purge} + test {test_window}, pas {step})."
        )

    plan = WalkForwardPlan(
        folds=tuple(folds), coverage=cov,
        params=WalkForwardParams(train_window, test_window, step, purge, embargo,
                                 anchored, min_train, min_test, min_folds),
    )
    assert_no_leakage(plan)      # défense en profondeur : re-vérifie tout, pli à pli
    return plan


def _couverture(cal, folds, dropped, n_slots, t0, horizon, test_window, step) -> Coverage:
    en_train = {t for f in folds for t in (cal[i] for i in f.select(cal, "train"))}
    en_test = {t for f in folds for t in (cal[i] for i in f.select(cal, "test"))}
    utilisees = en_train | en_test
    tested_span = _union_duree([(f.test_start, f.test_end) for f in folds])
    fin_tests = max((f.test_end for f in folds), default=None)
    return Coverage(
        n_dates=len(cal), first_date=cal[0], last_date=horizon, span=horizon - cal[0],
        n_slots=n_slots, n_folds=len(folds), dropped=tuple(dropped),
        dates_in_train=len(en_train), dates_in_test=len(en_test),
        dates_unused=len(cal) - len(utilisees),
        fraction_tested=len(en_test) / len(cal),
        tested_span=tested_span,
        unused_tail=(horizon - fin_tests) if fin_tests is not None else (horizon - cal[0]),
        overlapping_tests=test_window > step,
    )


def _union_duree(intervalles: Sequence[tuple[datetime, datetime]]) -> timedelta:
    total = ZERO
    fin_courante: datetime | None = None
    debut_courant: datetime | None = None
    for a, b in sorted(intervalles):
        if fin_courante is None:
            debut_courant, fin_courante = a, b
        elif a <= fin_courante:
            fin_courante = max(fin_courante, b)
        else:
            total += fin_courante - debut_courant
            debut_courant, fin_courante = a, b
    if fin_courante is not None and debut_courant is not None:
        total += fin_courante - debut_courant
    return total


# --------------------------------------------------------------------------- vérifications
def assert_no_leakage(plan: WalkForwardPlan | Iterable[Fold]) -> None:
    """
    Re-vérifie l'absence de fuite indépendamment de la construction :
      - purge respectée et test strictement postérieur au train, pli par pli ;
      - aucune date d'entraînement au-delà du début du test du même pli ;
      - aucune fenêtre d'entraînement empiétant sur la zone d'embargo d'un pli
        antérieur sans l'avoir explicitement exclue.
    """
    folds = list(plan)
    for f in folds:
        if f.train_end + f.purge > f.test_start:
            raise LeakageError(f"pli {f.index} : purge non respectée (train_end + purge > test_start)")
        if f.train_asof > f.test_start:
            raise LeakageError(f"pli {f.index} : train_asof postérieur au début du test")
        if _chevauche(f.train_start, f.train_end, f.test_start, f.test_end):
            raise LeakageError(f"pli {f.index} : train et test se chevauchent")
    for i, f in enumerate(folds):
        for g in folds[:i]:
            ea, eb = g.embargo_interval
            if not _chevauche(ea, eb, f.train_start, f.train_end):
                continue
            couvert = any(a <= max(ea, f.train_start) and min(eb, f.train_end) <= b
                          for a, b in f.excluded)
            if not couvert:
                raise LeakageError(
                    f"pli {f.index} : entraînement sur [{f.train_start}, {f.train_end}) qui "
                    f"empiète sur l'embargo [{ea}, {eb}) du pli {g.index} sans exclusion."
                )


def check_purge_covers(purge: timedelta, max_holding: timedelta) -> None:
    """
    La purge doit absorber l'horizon d'étiquetage : durée de détention maximale
    des trades utilisés comme étiquettes. Sinon un trade ouvert avant train_end
    et fermé après test_start fait fuiter la période de test.
    """
    purge = _duree(purge, "purge")
    max_holding = _duree(max_holding, "max_holding", strictement_positive=False)
    if purge < max_holding:
        raise LeakageError(
            f"purge ({purge}) inférieure à la détention maximale des étiquettes "
            f"({max_holding}) : un trade à cheval sur la frontière train/test fuit."
        )


def folds_crossing(plan: WalkForwardPlan | Iterable[Fold], instant: datetime) -> tuple[int, ...]:
    """Indices des plis dont la portée (train_start -> test_end) contient `instant`."""
    instant = _aware(instant, "instant")
    return tuple(f.index for f in plan if f.spans(instant))


def assert_no_crossing(plan: WalkForwardPlan | Iterable[Fold], instant: datetime,
                       quoi: str = "rupture structurelle") -> None:
    idx = folds_crossing(plan, instant)
    if idx:
        raise ValidationConfigError(
            f"plis {list(idx)} à cheval sur {quoi} du {instant.isoformat()} : "
            "entraînement et test portent sur deux régimes différents."
        )


def assert_capture_covers(plan: WalkForwardPlan | Iterable[Fold], source: str,
                          first_capture_at: datetime) -> None:
    """
    Refuse les plis antérieurs à la première capture d'une source non
    reconstituable (leaderboards, wallets, segments) : aucun endpoint ne permet
    de rejouer ce passé, il n'existe tout simplement pas de données.
    """
    require(source in SOURCES, f"source inconnue : {source}")
    first_capture_at = _aware(first_capture_at, "first_capture_at")
    fautifs = [f.index for f in plan if f.train_start < first_capture_at]
    if fautifs:
        motif = ("source non reconstituable (aucun endpoint historique)"
                 if source in NON_RECONSTRUCTIBLE else "antérieur à la première capture")
        raise InsufficientData(
            f"plis {fautifs} commencent avant la première capture de « {source} » "
            f"({first_capture_at.isoformat()}) — {motif}. Ces plis n'ont pas de données."
        )


# --------------------------------------------------------------------------- point-in-time
def publication_lag(source: str, publication_lag_s: float | None = None) -> timedelta:
    """Latence de publication effective d'une source, via ht.schema.knowable_at_for."""
    require(source in SOURCES, f"source inconnue : {source}")
    ref = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return knowable_at_for(source, ref, publication_lag_s) - ref


def latest_usable_valid_time(source: str, asof: datetime,
                             publication_lag_s: float | None = None) -> datetime:
    """
    Dernier valid_time dont le knowable_at est <= asof. C'est la borne réelle
    d'une variable construite « à la date asof » : elle est toujours en retard
    sur asof de la latence de publication.
    """
    asof = _aware(asof, "asof")
    return asof - publication_lag(source, publication_lag_s)


def pit_mask(source: str, valid_times: Sequence[datetime], asof: datetime,
             publication_lag_s: float | None = None) -> tuple[bool, ...]:
    """Masque des lignes utilisables à `asof` (knowable_at <= asof), source par source."""
    borne = latest_usable_valid_time(source, asof, publication_lag_s)
    return tuple(_aware(v, "valid_time") <= borne for v in valid_times)


def assert_no_future(knowable_ats: Iterable[datetime], asof: datetime, label: str = "") -> None:
    """Garde générique : aucune ligne connue après `asof`."""
    asof = _aware(asof, "asof")
    faute = [_aware(k, "knowable_at") for k in knowable_ats]
    faute = [k for k in faute if k > asof]
    if faute:
        raise LeakageError(
            f"{label or 'jeu'} : {len(faute)} ligne(s) avec knowable_at > asof "
            f"({asof.isoformat()}), la plus tardive à {max(faute).isoformat()}"
        )


def assert_not_post_hoc(source: str, columns: Iterable[str]) -> None:
    """Interdit l'usage d'une colonne contaminée par le futur (Source.post_hoc)."""
    require(source in SOURCES, f"source inconnue : {source}")
    src = SOURCES[source]
    fautives = sorted(set(columns) & set(src.post_hoc))
    if fautives:
        raise LeakageError(
            f"colonnes post-hoc interdites en point-in-time sur « {source} » : {fautives}"
        )
