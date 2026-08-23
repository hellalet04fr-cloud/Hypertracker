"""
Probability Engine — fondation.

Ce module ne contient AUCUN modele entrainé. Il fournit l'infrastructure d'estimation
sur laquelle les modeles futurs se brancheront :

  1. Estimation bayesienne d'une proportion (Beta-Binomial) avec prior EXPLICITE.
  2. Retrecissement hierarchique vers la cohorte (prior empirique estime sur l'ensemble
     des groupes, puis chaque groupe est tire vers ce prior a proportion de son bruit).
  3. Estimation frequentiste (intervalle de Wilson) pour comparaison contradictoire.
  4. Un protocole ProbabilityModel(fit, predict_proba, describe) et un temoin obligatoire
     BaselineRate qui predit le taux de base de la cohorte. Tout modele qui ne bat pas
     ce temoin est inutile : c'est la seule facon de detecter un modele qui ne fait que
     reapprendre la frequence marginale.

Principes non negociables appliques ici :

  - Aucune valeur par defaut ne remplace une donnee manquante. Une statistique qui ne
    peut pas etre calculee leve InsufficientData avec un message precis. Il n'y a nulle
    part de `return 0.0`, de moyenne inventee ni de NaN silencieux.
  - Toute fonction qui produit une variable pour un modele prend `asof: datetime` et ne
    lit aucune observation dont knowable_at > asof (rempart contre la fuite de futur).
  - Aucune colonne listee dans Source.post_hoc n'est utilisable pour une variable
    point-in-time : `assert_not_post_hoc` le verifie a l'execution.
  - Un estimateur ne rend JAMAIS un point seul : ProportionEstimate porte toujours son
    intervalle, sa taille d'echantillon et sa methode. Un point nu est un mensonge sur
    l'incertitude.

Biais connus, mesures, et propages dans chaque ModelCard produite ici :
  - Filtre de survie : les cohortes de performance excluent les wallets inactifs. Un
    wallet ruine qui arrete de trader disparait de l'echantillon.
  - Appartenance de cohorte retro-attribuee : recalculee toutes les 3-4 h sur le PnL
    all-time, donc a figer a l'ingestion sous peine de fuite.
  - Leaderboards sans parametre as-of : selection mecanique des survivants.
  - Rupture structurelle au 2026-09-02 sur les prix de liquidation : toute variable de
    distance a la liquidation est non stationnaire de part et d'autre de cette date.
  - Les executions TWAP sont attribuees a une pseudo-adresse de 64 hex (pas une adresse
    EVM valide) : exclue de toute agregation par wallet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
from scipy import optimize
from scipy.special import betaln
from scipy.stats import beta as beta_dist
from scipy.stats import norm as norm_dist

from ht.schema import SOURCES, InsufficientData, knowable_at_for, require

# --------------------------------------------------------------------------- constantes

#: Pseudo-adresse portant les executions TWAP (64 hex, pas une adresse EVM valide).
#: A exclure de toute agregation par wallet : ce n'est pas un trader.
TWAP_PSEUDO_ADDRESS = "0x" + "0" * 64

#: Rupture structurelle documentee sur les prix de liquidation.
LIQUIDATION_REGIME_BREAK = "2026-09-02"

#: Plancher de taille d'echantillon pour une estimation DIRECTE (sans prior informatif).
#: Choix de politique, explicite et surchargeable — ce n'est pas une donnee estimee.
#: En dessous, l'estimateur refuse plutot que de rendre un chiffre que personne ne
#: devrait utiliser.
MIN_TRIALS_DIRECT = 30

#: Nombre minimal de groupes pour identifier un prior de cohorte par Bayes empirique.
MIN_GROUPS_FOR_COHORT_PRIOR = 20

#: Nombre minimal d'essais cumules sur la cohorte entiere.
MIN_TOTAL_TRIALS_FOR_COHORT_PRIOR = 400

#: Biais structurels a rappeler sur toute carte de modele issue de ces donnees.
KNOWN_BIASES: tuple[str, ...] = (
    "survie: les cohortes de performance excluent les wallets inactifs (volume 30j nul "
    "ET aucune position ouverte); un wallet ruine qui arrete de trader disparait",
    "retro-attribution: l'appartenance aux cohortes est recalculee toutes les 3-4h sur "
    "le PnL all-time; la relire a posteriori fuite le futur, elle doit etre figee a "
    "l'ingestion",
    "leaderboards sans as-of: ils selectionnent mecaniquement les survivants",
    f"rupture de regime au {LIQUIDATION_REGIME_BREAK} sur les prix de liquidation "
    "(statiques avant, evolutifs apres): toute distance a la liquidation est non "
    "stationnaire de part et d'autre",
    f"TWAP: les executions attribuees a {TWAP_PSEUDO_ADDRESS} ne sont pas un wallet et "
    "sont exclues de toute agregation par adresse",
)


# --------------------------------------------------------------------------- garde post-hoc
def assert_not_post_hoc(source: str, columns: Iterable[str]) -> None:
    """
    Refuse l'usage d'une colonne contaminee par le futur pour une variable point-in-time.

    Regle 3 du contrat : une colonne listee dans Source.post_hoc n'est connue qu'apres
    coup (ex. `partial` sur closed_trades), l'employer comme predicteur fabrique une
    performance impossible a reproduire en direct.
    """
    src = SOURCES.get(source)
    require(src is not None, f"source inconnue '{source}': absente de schema.SOURCES")
    faute = sorted(set(columns) & set(src.post_hoc))
    if faute:
        raise InsufficientData(
            f"colonnes post-hoc interdites en point-in-time sur '{source}': {faute}. "
            f"Elles ne sont pas connues a knowable_at, seulement apres coup."
        )


def _check_asof(asof: datetime) -> datetime:
    if not isinstance(asof, datetime):
        raise TypeError("asof doit etre un datetime timezone-aware (UTC)")
    if asof.tzinfo is None:
        raise ValueError("asof doit etre timezone-aware (UTC): un asof naif est ambigu "
                         "et rend la borne anti-fuite inverifiable")
    return asof


# --------------------------------------------------------------------------- observations
@dataclass(frozen=True)
class Observation:
    """
    Un essai binaire attribue a un groupe (typiquement un wallet), horodate sur les
    trois horloges du contrat.

    `knowable_at` est l'instant a partir duquel l'API aurait pu servir ce fait. Il est
    derive de `source` + `valid_time` via schema.knowable_at_for lorsqu'il n'est pas
    fourni : ne jamais le laisser egal a valid_time, ce serait supposer une latence de
    publication nulle et donc fuiter.
    """
    group_id: str
    success: bool
    valid_time: datetime
    source: str
    knowable_at: datetime | None = None

    def __post_init__(self):
        if self.valid_time.tzinfo is None:
            raise ValueError(f"valid_time naif pour le groupe {self.group_id!r}: "
                             "toutes les horloges doivent etre UTC-aware")
        if self.source not in SOURCES:
            raise ValueError(f"source '{self.source}' absente de schema.SOURCES")
        if self.knowable_at is None:
            object.__setattr__(self, "knowable_at", knowable_at_for(self.source, self.valid_time))
        elif self.knowable_at.tzinfo is None:
            raise ValueError(f"knowable_at naif pour le groupe {self.group_id!r}")
        if self.knowable_at < self.valid_time:
            raise ValueError(
                f"knowable_at < valid_time pour le groupe {self.group_id!r}: un fait ne "
                "peut pas etre publiable avant d'etre vrai"
            )
        object.__setattr__(self, "success", bool(self.success))


@dataclass(frozen=True)
class AsofReport:
    """Trace de ce que le filtre as-of a retire. Rendue avec les donnees, jamais tue."""
    asof: datetime
    n_input: int
    n_kept: int
    n_future_dropped: int
    n_twap_dropped: int

    def __str__(self) -> str:
        return (f"as-of {self.asof.isoformat()}: {self.n_kept}/{self.n_input} retenues, "
                f"{self.n_future_dropped} futures exclues, {self.n_twap_dropped} TWAP exclues")


def observations_asof(
    observations: Sequence[Observation],
    *,
    asof: datetime,
    exclude_twap: bool = True,
) -> tuple[list[Observation], AsofReport]:
    """
    Ne conserve que les observations dont knowable_at <= asof, et retire par defaut la
    pseudo-adresse TWAP.

    C'est le seul point de passage autorise vers les estimateurs : toute variable de
    modele doit traverser ce filtre.
    """
    _check_asof(asof)
    kept: list[Observation] = []
    n_future = n_twap = 0
    for o in observations:
        if exclude_twap and o.group_id == TWAP_PSEUDO_ADDRESS:
            n_twap += 1
            continue
        if o.knowable_at > asof:
            n_future += 1
            continue
        kept.append(o)
    return kept, AsofReport(asof=asof, n_input=len(observations), n_kept=len(kept),
                            n_future_dropped=n_future, n_twap_dropped=n_twap)


def counts_by_group(observations: Sequence[Observation]) -> dict[str, tuple[int, int]]:
    """Agrege en {group_id: (succes, essais)}. N'invente aucun groupe absent."""
    agg: dict[str, list[int]] = {}
    for o in observations:
        cell = agg.setdefault(o.group_id, [0, 0])
        cell[0] += int(o.success)
        cell[1] += 1
    return {g: (k, n) for g, (k, n) in agg.items()}


# --------------------------------------------------------------------------- prior
@dataclass(frozen=True)
class BetaPrior:
    """
    Prior Beta(alpha, beta) sur une proportion, avec sa justification OBLIGATOIRE.

    Un prior sans justification ecrite est un parametre libre deguise : le champ
    `justification` est requis et non vide pour que la source du prior (croyance
    explicite, Bayes empirique sur une cohorte, reglage documente) reste auditable.
    """
    alpha: float
    beta: float
    justification: str
    source: str = "explicite"     # "explicite" | "bayes_empirique"
    n_groups: int | None = None   # renseigne si estime sur une cohorte
    n_trials: int | None = None

    def __post_init__(self):
        if not (self.alpha > 0 and self.beta > 0):
            raise ValueError(f"prior Beta invalide: alpha={self.alpha}, beta={self.beta} "
                             "(les deux doivent etre > 0)")
        if not math.isfinite(self.alpha) or not math.isfinite(self.beta):
            raise ValueError("prior Beta non fini")
        if not self.justification.strip():
            raise ValueError("un prior sans justification ecrite est interdit: "
                             "documenter d'ou viennent alpha et beta")

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def strength(self) -> float:
        """Poids du prior en essais equivalents (alpha + beta)."""
        return self.alpha + self.beta

    @classmethod
    def uniform(cls, justification: str = "prior uniforme Beta(1,1): aucune croyance "
                                          "prealable sur la proportion") -> "BetaPrior":
        return cls(alpha=1.0, beta=1.0, justification=justification)

    @classmethod
    def jeffreys(cls, justification: str = "prior de Jeffreys Beta(0.5,0.5): "
                                           "non informatif invariant par reparametrage") -> "BetaPrior":
        return cls(alpha=0.5, beta=0.5, justification=justification)

    @classmethod
    def from_mean_strength(cls, mean: float, strength: float, justification: str,
                           **kw) -> "BetaPrior":
        """Prior exprime comme (taux attendu, nombre d'essais equivalents)."""
        if not (0.0 < mean < 1.0):
            raise ValueError(f"moyenne de prior hors (0,1): {mean}")
        if strength <= 0:
            raise ValueError(f"force de prior non positive: {strength}")
        return cls(alpha=mean * strength, beta=(1.0 - mean) * strength,
                   justification=justification, **kw)


# --------------------------------------------------------------------------- estimation
@dataclass(frozen=True)
class ProportionEstimate:
    """
    Resultat d'une estimation de proportion. Porte TOUJOURS son intervalle.

    `shrinkage_to_prior` est le poids effectif du prior dans la moyenne posterieure
    (0 = les donnees decident seules, 1 = le prior decide seul). Sur petit echantillon
    il doit etre proche de 1 : c'est la signature d'un chiffre a ne pas sur-interpreter.
    """
    mean: float
    lower: float
    upper: float
    level: float
    successes: int
    trials: int
    method: str
    interval_kind: str
    asof: datetime
    prior: BetaPrior | None = None
    shrinkage_to_prior: float | None = None
    group_id: str | None = None

    def __post_init__(self):
        for nom, v in (("mean", self.mean), ("lower", self.lower), ("upper", self.upper)):
            if not math.isfinite(v):
                raise ValueError(f"{nom} non fini dans ProportionEstimate")
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{nom}={v} hors [0,1]")
        if self.lower > self.upper:
            raise ValueError(f"intervalle inverse: [{self.lower}, {self.upper}]")
        if not (0.0 < self.level < 1.0):
            raise ValueError(f"niveau de confiance hors (0,1): {self.level}")

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def __str__(self) -> str:
        return (f"{self.mean:.4f} [{self.lower:.4f}, {self.upper:.4f}] "
                f"({self.level:.0%} {self.interval_kind}, k={self.successes}/n={self.trials}, "
                f"{self.method})")


def _validate_counts(successes: int, trials: int) -> tuple[int, int]:
    if not isinstance(successes, (int, np.integer)) or not isinstance(trials, (int, np.integer)):
        raise TypeError("successes et trials doivent etre des entiers (comptages reels, "
                        "pas des estimations)")
    successes, trials = int(successes), int(trials)
    if trials < 0 or successes < 0:
        raise ValueError(f"comptages negatifs: k={successes}, n={trials}")
    if successes > trials:
        raise ValueError(f"k={successes} > n={trials}: comptages incoherents")
    return successes, trials


def _beta_hdi(a: float, b: float, level: float) -> tuple[float, float]:
    """Intervalle de plus haute densite pour Beta(a,b). Degenere en unilateral si a<=1 ou b<=1."""
    tail = 1.0 - level
    if a <= 1.0 and b <= 1.0:
        # densite en U : la region de plus haute densite est disjointe, l'intervalle
        # equi-caudal est le seul resume honnete d'un seul segment.
        return float(beta_dist.ppf(tail / 2.0, a, b)), float(beta_dist.ppf(1.0 - tail / 2.0, a, b))
    if a <= 1.0:
        return 0.0, float(beta_dist.ppf(level, a, b))
    if b <= 1.0:
        return float(beta_dist.ppf(tail, a, b)), 1.0

    def largeur(q: float) -> float:
        return float(beta_dist.ppf(q + level, a, b) - beta_dist.ppf(q, a, b))

    res = optimize.minimize_scalar(largeur, bounds=(1e-12, tail - 1e-12), method="bounded",
                                   options={"xatol": 1e-10})
    q = float(res.x)
    return float(beta_dist.ppf(q, a, b)), float(beta_dist.ppf(q + level, a, b))


def beta_binomial_proportion(
    successes: int,
    trials: int,
    *,
    prior: BetaPrior,
    asof: datetime,
    level: float = 0.90,
    interval: str = "equal_tailed",
    min_trials: int = 0,
    group_id: str | None = None,
) -> ProportionEstimate:
    """
    Posterieure Beta(alpha+k, beta+n-k) et son intervalle de credibilite.

    `min_trials` est un plancher explicite : en dessous, InsufficientData. Il vaut 0 par
    defaut ICI parce qu'un prior informatif rend l'estimation legitime meme a n petit —
    l'intervalle s'elargit alors de lui-meme et `shrinkage_to_prior` tend vers 1. Les
    appelants qui n'ont pas de prior credible doivent passer min_trials=MIN_TRIALS_DIRECT.

    Ne retourne jamais un point seul : l'intervalle fait partie du resultat.
    """
    _check_asof(asof)
    successes, trials = _validate_counts(successes, trials)
    if not (0.0 < level < 1.0):
        raise ValueError(f"niveau hors (0,1): {level}")
    if interval not in ("equal_tailed", "hdi"):
        raise ValueError(f"type d'intervalle inconnu: {interval!r}")
    require(
        trials >= min_trials,
        "echantillon insuffisant pour estimer une proportion"
        + (f" sur le groupe {group_id!r}" if group_id else "")
        + f": n={trials} < plancher={min_trials}. Aucune valeur par defaut ne sera "
          "substituee; collecter davantage d'essais ou fournir un prior de cohorte.",
    )

    a = prior.alpha + successes
    b = prior.beta + (trials - successes)
    mean = a / (a + b)
    if interval == "hdi":
        lo, hi = _beta_hdi(a, b, level)
    else:
        tail = (1.0 - level) / 2.0
        lo = float(beta_dist.ppf(tail, a, b))
        hi = float(beta_dist.ppf(1.0 - tail, a, b))
    lo = min(max(lo, 0.0), 1.0)
    hi = min(max(hi, 0.0), 1.0)
    poids_prior = prior.strength / (prior.strength + trials)
    return ProportionEstimate(
        mean=float(mean), lower=lo, upper=hi, level=level,
        successes=successes, trials=trials,
        method="beta_binomial" if trials > 0 else "beta_binomial_prior_seul",
        interval_kind=interval, asof=asof, prior=prior,
        shrinkage_to_prior=float(poids_prior), group_id=group_id,
    )


def wilson_proportion(
    successes: int,
    trials: int,
    *,
    asof: datetime,
    level: float = 0.90,
    min_trials: int = MIN_TRIALS_DIRECT,
    group_id: str | None = None,
) -> ProportionEstimate:
    """
    Estimateur frequentiste : point = k/n, intervalle de score de Wilson.

    Sert de contre-expertise a la version bayesienne. Il ne rend AUCUN service sans
    donnees : n=0 (ou n < min_trials) leve InsufficientData plutot que de renvoyer 0.0.
    L'intervalle de Wilson est prefere a Wald parce que Wald donne [0,0] a k=0 — un
    intervalle de largeur nulle qui pretend une certitude absurde.
    """
    _check_asof(asof)
    successes, trials = _validate_counts(successes, trials)
    if not (0.0 < level < 1.0):
        raise ValueError(f"niveau hors (0,1): {level}")
    require(
        trials >= max(min_trials, 1),
        "echantillon insuffisant pour un intervalle de Wilson"
        + (f" sur le groupe {group_id!r}" if group_id else "")
        + f": n={trials} < plancher={max(min_trials, 1)}. Sans prior, une proportion "
          "n'est pas estimable a cette taille.",
    )
    z = float(norm_dist.ppf(1.0 - (1.0 - level) / 2.0))
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    demi = (z / denom) * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return ProportionEstimate(
        mean=float(p), lower=float(max(0.0, centre - demi)), upper=float(min(1.0, centre + demi)),
        level=level, successes=successes, trials=trials, method="wilson",
        interval_kind="score", asof=asof, prior=None, shrinkage_to_prior=0.0,
        group_id=group_id,
    )


# --------------------------------------------------------------------------- prior de cohorte
def _log_marginal_beta_binomial(params: np.ndarray, k: np.ndarray, n: np.ndarray) -> float:
    """-log vraisemblance marginale Beta-Binomiale, parametree en log pour rester positif."""
    a, b = float(np.exp(params[0])), float(np.exp(params[1]))
    if not (math.isfinite(a) and math.isfinite(b)) or a <= 0 or b <= 0:
        return float("inf")
    ll = np.sum(betaln(a + k, b + n - k) - betaln(a, b))
    return float(-ll) if math.isfinite(ll) else float("inf")


def _moments_prior(k: np.ndarray, n: np.ndarray) -> tuple[float, float, float]:
    """
    Estimateur des moments (DerSimonian-Laird) : separe la dispersion inter-groupes de
    la variance d'echantillonnage binomiale. Retourne (alpha, beta, tau2).
    Leve InsufficientData si la dispersion inter-groupes n'est pas identifiable.
    """
    N = float(n.sum())
    m = float(k.sum() / N)
    require(0.0 < m < 1.0,
            f"taux de base degenere sur la cohorte (m={m}): tous les essais sont des "
            "succes ou tous des echecs, aucune dispersion estimable")
    p = k / n
    w = n / (m * (1.0 - m))
    p_w = float(np.sum(w * p) / np.sum(w))
    Q = float(np.sum(w * (p - p_w) ** 2))
    G = len(n)
    denom = float(np.sum(w) - np.sum(w ** 2) / np.sum(w))
    require(denom > 0, "cohorte degeneree: un seul groupe porte tout le poids")
    tau2 = (Q - (G - 1)) / denom
    require(
        tau2 > 0,
        f"dispersion inter-groupes non identifiable (tau2 estime = {tau2:.3e} <= 0): "
        f"Q={Q:.2f} pour G-1={G - 1} degres de liberte. Les groupes sont indistinguables "
        "d'un taux commun a cette taille d'echantillon; fournir un prior explicite ou "
        "collecter plus d'essais par groupe.",
    )
    var_max = m * (1.0 - m)
    require(tau2 < var_max,
            f"dispersion estimee (tau2={tau2:.4f}) >= variance maximale d'une Bernoulli "
            f"de moyenne {m:.4f} ({var_max:.4f}): aucune Beta ne peut representer cela")
    nu = var_max / tau2 - 1.0
    return m * nu, (1.0 - m) * nu, tau2


def fit_cohort_prior(
    counts: Mapping[str, tuple[int, int]] | Sequence[tuple[int, int]],
    *,
    asof: datetime,
    method: str = "mml",
    min_groups: int = MIN_GROUPS_FOR_COHORT_PRIOR,
    min_total_trials: int = MIN_TOTAL_TRIALS_FOR_COHORT_PRIOR,
) -> BetaPrior:
    """
    Bayes empirique : estime le prior Beta commun a une cohorte de groupes.

    C'est ce prior qui produit le retrecissement hierarchique — un wallet avec 5 essais
    sera tire vers le comportement de sa cohorte, un wallet avec 5000 essais ne le sera
    presque pas. Sans cela, un wallet a 3/3 ressort a 100% de reussite, ce qui est la
    definition meme du surapprentissage sur echantillon minuscule.

    method="mml"     : maximum de vraisemblance marginale Beta-Binomiale (par defaut).
    method="moments" : estimateur des moments DerSimonian-Laird (plus rapide, plus fragile).

    Refuse (InsufficientData) si la cohorte est trop petite ou si la dispersion
    inter-groupes n'est pas identifiable. Aucun prior par defaut n'est fabrique.
    """
    _check_asof(asof)
    paires = list(counts.values()) if isinstance(counts, Mapping) else list(counts)
    require(len(paires) > 0, "cohorte vide: aucun groupe fourni pour estimer un prior")
    ks, ns = [], []
    for kk, nn in paires:
        kk, nn = _validate_counts(kk, nn)
        if nn == 0:
            continue          # un groupe sans essai n'apporte aucune information
        ks.append(kk)
        ns.append(nn)
    k = np.asarray(ks, dtype=float)
    n = np.asarray(ns, dtype=float)
    require(
        len(n) >= min_groups,
        f"cohorte insuffisante pour un prior empirique: {len(n)} groupes avec au moins "
        f"un essai < plancher={min_groups}",
    )
    require(
        float(n.sum()) >= min_total_trials,
        f"cohorte insuffisante pour un prior empirique: {int(n.sum())} essais cumules "
        f"< plancher={min_total_trials}",
    )
    total_k = float(k.sum())
    require(
        0 < total_k < float(n.sum()),
        f"cohorte degeneree: {int(total_k)} succes sur {int(n.sum())} essais. Un taux de "
        "base a 0 ou 1 ne permet aucune estimation de dispersion.",
    )

    a0, b0, tau2 = _moments_prior(k, n)
    if method == "moments":
        a, b = a0, b0
        detail = f"moments (DerSimonian-Laird), tau2={tau2:.5f}"
    elif method == "mml":
        x0 = np.array([math.log(a0), math.log(b0)])
        res = optimize.minimize(_log_marginal_beta_binomial, x0, args=(k, n),
                                method="Nelder-Mead",
                                options={"xatol": 1e-8, "fatol": 1e-10, "maxiter": 4000})
        require(res.success and np.all(np.isfinite(res.x)),
                f"la vraisemblance marginale Beta-Binomiale n'a pas converge "
                f"({getattr(res, 'message', 'sans message')}); ne pas fabriquer de prior")
        a, b = float(np.exp(res.x[0])), float(np.exp(res.x[1]))
        require(math.isfinite(a) and math.isfinite(b) and a > 0 and b > 0,
                "prior estime non fini: refus de le publier")
        detail = f"maximum de vraisemblance marginale, depart moments tau2={tau2:.5f}"
    else:
        raise ValueError(f"methode de prior inconnue: {method!r} (attendu 'mml' ou 'moments')")

    return BetaPrior(
        alpha=a, beta=b, source="bayes_empirique",
        n_groups=int(len(n)), n_trials=int(n.sum()),
        justification=(
            f"prior de cohorte estime par Bayes empirique ({detail}) sur {len(n)} groupes "
            f"et {int(n.sum())} essais, tous connaissables au plus tard le "
            f"{asof.isoformat()}. Attention: ce prior herite du filtre de survie de la "
            f"cohorte (les groupes inactifs en sont absents)."
        ),
    )


# --------------------------------------------------------------------------- protocole
@dataclass(frozen=True)
class ModelCard:
    """Carte d'identite d'un modele : ce qu'il predit, sur quoi, et ce qui le limite."""
    name: str
    kind: str
    target: str
    trained_asof: datetime | None
    n_observations: int
    n_groups: int
    prior: BetaPrior | None
    level: float
    assumptions: tuple[str, ...] = ()
    biases: tuple[str, ...] = KNOWN_BIASES
    post_hoc_columns_used: tuple[str, ...] = ()

    def __str__(self) -> str:
        entraine = self.trained_asof.isoformat() if self.trained_asof else "NON ENTRAINE"
        return (f"{self.name} [{self.kind}] cible={self.target} asof={entraine} "
                f"n={self.n_observations} groupes={self.n_groups}")


@runtime_checkable
class ProbabilityModel(Protocol):
    """
    Contrat minimal de tout modele de probabilite du moteur.

    - `fit` prend un asof et ne doit consommer aucune observation dont knowable_at > asof.
    - `predict_proba` prend un asof et rend une ProportionEstimate par cle : jamais un
      float nu, pour que l'incertitude voyage avec la prediction.
    - `describe` rend une ModelCard, y compris les biais connus du jeu de donnees.

    Tout modele candidat doit etre compare a BaselineRate : s'il ne bat pas le taux de
    base de la cohorte (Brier ou log-score), il n'apporte rien et ne doit pas etre deploye.
    """

    def fit(self, observations: Sequence[Observation], *, asof: datetime) -> "ProbabilityModel": ...

    def predict_proba(self, keys: Sequence[str], *, asof: datetime) -> list[ProportionEstimate]: ...

    def describe(self) -> ModelCard: ...


# --------------------------------------------------------------------------- modeles
@dataclass
class BaselineRate:
    """
    Temoin obligatoire : predit le taux de base de la cohorte, identique pour toute cle.

    Ce modele ignore volontairement toute information specifique au groupe. Il n'existe
    que pour repondre a la question « le modele complique apporte-t-il quelque chose ? ».
    Un modele qui n'ameliore pas son Brier n'a appris que la frequence marginale.

    L'estimation elle-meme est bayesienne (Beta-Binomial) : le taux de base sort avec
    son intervalle de credibilite, pas comme un point.
    """
    prior: BetaPrior = field(
        default_factory=lambda: BetaPrior.jeffreys(
            "prior de Jeffreys Beta(0.5,0.5) sur le taux de base de la cohorte: choix "
            "non informatif assume, la cohorte agregee porte assez d'essais pour que le "
            "prior ne pese quasiment rien"
        )
    )
    level: float = 0.90
    min_trials: int = MIN_TRIALS_DIRECT
    target: str = "evenement binaire non specifie"
    _estimate: ProportionEstimate | None = field(default=None, init=False, repr=False)
    _asof: datetime | None = field(default=None, init=False, repr=False)
    _n_groups: int = field(default=0, init=False, repr=False)
    _report: AsofReport | None = field(default=None, init=False, repr=False)

    def fit(self, observations: Sequence[Observation], *, asof: datetime) -> "BaselineRate":
        _check_asof(asof)
        retenues, rapport = observations_asof(observations, asof=asof)
        require(
            len(retenues) > 0,
            f"aucune observation connaissable au {asof.isoformat()} "
            f"({rapport}): le taux de base ne peut pas etre estime",
        )
        k = sum(1 for o in retenues if o.success)
        n = len(retenues)
        self._estimate = beta_binomial_proportion(
            k, n, prior=self.prior, asof=asof, level=self.level, min_trials=self.min_trials,
            group_id=None,
        )
        self._asof = asof
        self._n_groups = len({o.group_id for o in retenues})
        self._report = rapport
        return self

    @property
    def base_rate(self) -> ProportionEstimate:
        require(self._estimate is not None, "BaselineRate non entraine: appeler fit(asof=...)")
        return self._estimate

    @property
    def asof_report(self) -> AsofReport:
        require(self._report is not None, "BaselineRate non entraine: appeler fit(asof=...)")
        return self._report

    def predict_proba(self, keys: Sequence[str], *, asof: datetime) -> list[ProportionEstimate]:
        _check_asof(asof)
        require(self._estimate is not None, "BaselineRate non entraine: appeler fit(asof=...)")
        require(
            asof >= self._asof,
            f"prediction demandee au {asof.isoformat()} avec un modele ajuste au "
            f"{self._asof.isoformat()}: predire dans le passe du modele est une fuite",
        )
        return [replace(self._estimate, group_id=str(cle)) for cle in keys]

    def describe(self) -> ModelCard:
        return ModelCard(
            name="BaselineRate", kind="temoin", target=self.target,
            trained_asof=self._asof,
            n_observations=self._estimate.trials if self._estimate else 0,
            n_groups=self._n_groups, prior=self.prior, level=self.level,
            assumptions=(
                "taux de base unique et stationnaire sur la fenetre d'ajustement",
                "les essais sont echangeables entre groupes (hypothese volontairement "
                "fausse: c'est le temoin, pas un modele)",
            ),
        )


@dataclass
class HierarchicalProportion:
    """
    Estimation par groupe avec retrecissement hierarchique vers la cohorte.

    Le prior est soit fourni explicitement, soit estime par Bayes empirique sur la
    cohorte elle-meme (fit_cohort_prior). Chaque groupe recoit ensuite une posterieure
    Beta(alpha+k_i, beta+n_i-k_i) : le poids du prior vaut (alpha+beta)/(alpha+beta+n_i),
    donc un petit echantillon est massivement ramene vers la cohorte.

    C'est le mecanisme anti-surapprentissage exige : un wallet ne peut pas etre declare
    excellent sur trois trades. Le PnL seul ne suffit jamais — ce module ne fournit que
    la brique « proportion » (win rate, taux de survie, taux de succes d'un signal); le
    ranking qui la consomme doit y ajouter persistance, drawdown, taille d'echantillon
    et stabilite.
    """
    prior: BetaPrior | None = None
    level: float = 0.90
    interval: str = "equal_tailed"
    min_trials_per_group: int = 5
    allow_prior_only: bool = False
    prior_method: str = "mml"
    target: str = "evenement binaire non specifie"
    _counts: dict[str, tuple[int, int]] = field(default_factory=dict, init=False, repr=False)
    _prior_fitted: BetaPrior | None = field(default=None, init=False, repr=False)
    _asof: datetime | None = field(default=None, init=False, repr=False)
    _report: AsofReport | None = field(default=None, init=False, repr=False)

    def fit(self, observations: Sequence[Observation], *, asof: datetime) -> "HierarchicalProportion":
        _check_asof(asof)
        retenues, rapport = observations_asof(observations, asof=asof)
        require(len(retenues) > 0,
                f"aucune observation connaissable au {asof.isoformat()} ({rapport})")
        self._counts = counts_by_group(retenues)
        self._prior_fitted = self.prior or fit_cohort_prior(
            self._counts, asof=asof, method=self.prior_method
        )
        self._asof = asof
        self._report = rapport
        return self

    @property
    def cohort_prior(self) -> BetaPrior:
        require(self._prior_fitted is not None,
                "HierarchicalProportion non entraine: appeler fit(asof=...)")
        return self._prior_fitted

    @property
    def asof_report(self) -> AsofReport:
        require(self._report is not None,
                "HierarchicalProportion non entraine: appeler fit(asof=...)")
        return self._report

    def predict_proba(self, keys: Sequence[str], *, asof: datetime) -> list[ProportionEstimate]:
        _check_asof(asof)
        require(self._prior_fitted is not None,
                "HierarchicalProportion non entraine: appeler fit(asof=...)")
        require(
            asof >= self._asof,
            f"prediction au {asof.isoformat()} avec un modele ajuste au "
            f"{self._asof.isoformat()}: predire dans le passe du modele est une fuite",
        )
        sorties: list[ProportionEstimate] = []
        for cle in keys:
            cle = str(cle)
            if cle == TWAP_PSEUDO_ADDRESS:
                raise InsufficientData(
                    f"{TWAP_PSEUDO_ADDRESS} est la pseudo-adresse des executions TWAP, "
                    "pas un wallet: aucune probabilite ne lui est attribuable"
                )
            # Groupe absent = zero essai. Ce n'est PAS une valeur par defaut : c'est le
            # prior de cohorte assume, et il est refuse sauf demande explicite.
            k, n = self._counts.get(cle, (0, 0))
            if n < self.min_trials_per_group and not self.allow_prior_only:
                raise InsufficientData(
                    f"groupe {cle!r}: n={n} essais connaissables au {asof.isoformat()}, "
                    f"plancher={self.min_trials_per_group}. Refus d'estimer; passer "
                    "allow_prior_only=True pour obtenir explicitement la seule cohorte."
                )
            sorties.append(beta_binomial_proportion(
                k, n, prior=self._prior_fitted, asof=asof, level=self.level,
                interval=self.interval, min_trials=0, group_id=cle,
            ))
        return sorties

    def describe(self) -> ModelCard:
        n_obs = sum(n for _, n in self._counts.values())
        return ModelCard(
            name="HierarchicalProportion", kind="bayesien hierarchique", target=self.target,
            trained_asof=self._asof, n_observations=int(n_obs), n_groups=len(self._counts),
            prior=self._prior_fitted, level=self.level,
            assumptions=(
                "les taux par groupe sont tires d'une meme loi Beta de cohorte "
                "(echangeabilite entre groupes)",
                "les essais d'un groupe sont conditionnellement independants et de meme "
                "probabilite sur la fenetre — faux en cas de rupture de regime",
                "aucun retour d'information: la cohorte ne doit pas avoir ete constituee "
                "a partir du resultat qu'on estime",
            ),
        )


# --------------------------------------------------------------------------- scores
@dataclass(frozen=True)
class Scorecard:
    """Comparaison contradictoire d'un modele au temoin. Sans elle, aucun deploiement."""
    n: int
    brier_model: float
    brier_baseline: float
    log_model: float
    log_baseline: float

    @property
    def brier_skill(self) -> float:
        """Skill score de Brier : > 0 signifie que le modele bat le temoin."""
        return 1.0 - self.brier_model / self.brier_baseline

    @property
    def beats_baseline(self) -> bool:
        return self.brier_model < self.brier_baseline and self.log_model < self.log_baseline

    def __str__(self) -> str:
        verdict = "BAT le temoin" if self.beats_baseline else "NE BAT PAS le temoin"
        return (f"n={self.n} brier={self.brier_model:.5f} vs temoin {self.brier_baseline:.5f} "
                f"(skill={self.brier_skill:+.4f}), log={self.log_model:.5f} vs "
                f"{self.log_baseline:.5f} -> {verdict}")


def _as_probs(p: Sequence[float] | Sequence[ProportionEstimate]) -> np.ndarray:
    vals = [x.mean if isinstance(x, ProportionEstimate) else float(x) for x in p]
    arr = np.asarray(vals, dtype=float)
    if arr.size and (not np.all(np.isfinite(arr)) or arr.min() < 0 or arr.max() > 1):
        raise ValueError("probabilites hors [0,1] ou non finies")
    return arr


def brier_score(probs, outcomes: Sequence[bool]) -> float:
    """Erreur quadratique moyenne. Refuse un echantillon vide plutot que de rendre 0.0."""
    p = _as_probs(probs)
    y = np.asarray([bool(o) for o in outcomes], dtype=float)
    require(p.size > 0, "aucune prediction a scorer: le score de Brier n'est pas defini "
                        "sur un echantillon vide")
    require(p.size == y.size, f"tailles incompatibles: {p.size} predictions, {y.size} issues")
    return float(np.mean((p - y) ** 2))


def log_score(probs, outcomes: Sequence[bool]) -> float:
    """Log-perte moyenne. Une prediction a 0 ou 1 exacte est refusee (perte infinie)."""
    p = _as_probs(probs)
    y = np.asarray([bool(o) for o in outcomes], dtype=float)
    require(p.size > 0, "aucune prediction a scorer: la log-perte n'est pas definie "
                        "sur un echantillon vide")
    require(p.size == y.size, f"tailles incompatibles: {p.size} predictions, {y.size} issues")
    if np.any((p <= 0.0) | (p >= 1.0)):
        raise ValueError("probabilite exactement 0 ou 1: log-perte infinie. Utiliser un "
                         "estimateur bayesien avec prior propre plutot que de tronquer.")
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def compare_to_baseline(model_probs, baseline_probs, outcomes: Sequence[bool]) -> Scorecard:
    """
    Verdict de deploiement : un modele qui ne bat pas le taux de base est inutile.

    Les deux jeux de probabilites doivent porter sur les MEMES evenements, dans le meme
    ordre, produits au meme asof — sans quoi la comparaison ne veut rien dire.
    """
    bm = brier_score(model_probs, outcomes)
    bb = brier_score(baseline_probs, outcomes)
    require(bb > 0.0,
            "le temoin a un Brier nul (issues parfaitement predites par le taux de base): "
            "le skill score n'est pas defini, l'echantillon est degenere")
    return Scorecard(n=len(list(outcomes)), brier_model=bm, brier_baseline=bb,
                     log_model=log_score(model_probs, outcomes),
                     log_baseline=log_score(baseline_probs, outcomes))
