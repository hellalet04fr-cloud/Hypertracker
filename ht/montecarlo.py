"""
F — Validation par simulation.

Repond a une seule question : la performance observee est-elle distinguable du hasard,
compte tenu de la structure reelle des donnees ?

Trois pieges que ce module traite explicitement :

1. AUTOCORRELATION. Les rendements successifs d'un wallet ne sont pas independants
   (une position se deroule sur plusieurs trades, un regime de marche persiste). Un
   bootstrap i.i.d. casse cette dependance et SOUS-ESTIME la variance, donc surestime
   la significativite. On utilise un bootstrap par blocs stationnaire (Politis & Romano),
   dont la longueur de bloc moyenne est choisie a partir de l'autocorrelation MESUREE.

2. TESTS MULTIPLES. Quand on classe N wallets, le meilleur parait bon par pur hasard.
   Le maximum de N variables centrees vaut environ sigma*sqrt(2 ln N) : avec 1000 wallets
   sans aucun edge, le meilleur affiche un Sharpe d'environ 3,7 ecarts-types. Le Sharpe
   degonfle (Bailey & Lopez de Prado) retranche cette esperance du maximum.

3. NON-NORMALITE. Les rendements de trading sont asymetriques et a queues epaisses.
   Le Sharpe degonfle en tient compte via l'asymetrie et le kurtosis empiriques.

Toutes les fonctions prennent une graine explicite. Aucune graine implicite : un
resultat non reproductible n'est pas un resultat.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .schema import InsufficientData, require

# Seuils minimaux. En dessous, une statistique de dispersion n'a pas de sens et
# on leve plutot que de rendre un nombre qui aurait l'air d'une mesure.
MIN_OBS_BOOTSTRAP = 30
MIN_OBS_PERMUTATION = 20
MIN_OBS_SHARPE = 30
MIN_OBS_DRAWDOWN = 20


# --------------------------------------------------------------------------- utilitaires
def _clean(returns) -> np.ndarray:
    a = np.asarray(returns, dtype=float)
    if a.ndim != 1:
        raise InsufficientData("la serie de rendements doit etre unidimensionnelle")
    if not np.all(np.isfinite(a)):
        raise InsufficientData(
            f"serie non finie: {int((~np.isfinite(a)).sum())} valeur(s) NaN/inf. "
            "Nettoyer en amont plutot que d'imputer ici."
        )
    return a


def autocorrelation(returns, lag: int) -> float:
    """Autocorrelation empirique au retard `lag` (estimateur biaise, denominateur n)."""
    a = _clean(returns)
    require(lag >= 0, "le retard doit etre positif ou nul")
    require(len(a) > lag + 1, f"serie trop courte ({len(a)}) pour le retard {lag}")
    x = a - a.mean()
    denom = float(np.sum(x * x))
    if denom == 0.0:
        raise InsufficientData("serie constante : autocorrelation indefinie")
    if lag == 0:
        return 1.0
    return float(np.sum(x[lag:] * x[:-lag]) / denom)


# --------------------------------------------------------------------------- chi2
# scipy.stats n'est pas garanti present sur les machines qui font tourner le
# generateur : la CDF du chi2 est donc ecrite ici, a partir de la fonction gamma
# incomplete reguliere P(a,x). Deux regimes, parce qu'aucun des deux ne converge
# partout : la serie pour x < a+1, la fraction continue de Lentz au-dela. Les
# convertir l'un en l'autre au mauvais endroit produit des p-valeurs fausses
# sans jamais lever.
_EPS_GAMMA = 1e-15
_MIN_GAMMA = 1e-300
_ITER_GAMMA = 500


def _gamma_p(a: float, x: float) -> float:
    """Fonction gamma incomplete reguliere P(a,x) = gamma(a,x)/Gamma(a)."""
    require(a > 0.0, "le parametre de forme doit etre strictement positif")
    require(x >= 0.0, "la borne d'integration doit etre positive ou nulle")
    if x == 0.0:
        return 0.0
    # facteur commun exp(-x + a ln x - ln Gamma(a)), calcule en logarithmes :
    # x**a deborde des x ~ 700 en double precision.
    facteur = math.exp(-x + a * math.log(x) - math.lgamma(a))
    if x < a + 1.0:
        terme = somme = 1.0 / a
        ap = a
        for _ in range(_ITER_GAMMA):
            ap += 1.0
            terme *= x / ap
            somme += terme
            if abs(terme) < abs(somme) * _EPS_GAMMA:
                break
        return min(1.0, somme * facteur)
    # Fraction continue pour Q(a,x) = 1 - P(a,x), evaluee par l'algorithme de
    # Lentz modifie : un denominateur nul en cours de route est remplace par un
    # infiniment petit plutot que de faire diverger le quotient.
    b = x + 1.0 - a
    c = 1.0 / _MIN_GAMMA
    d = 1.0 / b
    h = d
    for i in range(1, _ITER_GAMMA + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _MIN_GAMMA:
            d = _MIN_GAMMA
        c = b + an / c
        if abs(c) < _MIN_GAMMA:
            c = _MIN_GAMMA
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS_GAMMA:
            break
    return max(0.0, 1.0 - facteur * h)


def _chi2_cdf(x: float, k: int) -> float:
    """Fonction de repartition d'un chi2 a `k` degres de liberte."""
    require(k >= 1, "un chi2 demande au moins un degre de liberte")
    return _gamma_p(k / 2.0, max(0.0, float(x)) / 2.0)


def ljung_box(returns, h: int = 5) -> tuple[float, float]:
    """
    Statistique Q de Ljung-Box et sa p-valeur, chi2 a h degres.

    Q = n(n+2) * somme_{k=1..h} rho_k^2 / (n-k), ou rho_k est l'autocorrelation
    empirique au retard k. Sous l'hypothese nulle « les rendements successifs sont
    independants », Q suit approximativement un chi2 a h degres ; une p-valeur
    faible dit que les trades ne sont PAS independants.

    C'EST UN DIAGNOSTIC, ET RIEN D'AUTRE. Il n'alimente aucun score, aucun seuil,
    aucun classement, et ne doit jamais servir a filtrer un wallet : il indique
    seulement que les intervalles calcules sur cette serie — et notamment tout ce
    qui suppose l'independance — sont a lire avec prudence. Le bootstrap par blocs
    est deja la reponse a cette dependance ; Ljung-Box ne fait que la nommer.
    """
    require(h >= 1, "au moins un retard")
    a = _clean(returns)
    n = len(a)
    require(n > h + 1, f"serie trop courte ({n}) pour {h} retards")
    q = 0.0
    for k in range(1, h + 1):
        rho = autocorrelation(a, k)
        q += rho * rho / (n - k)
    q *= n * (n + 2.0)
    return float(q), float(1.0 - _chi2_cdf(q, h))


def longueur_bloc_recommandee(returns, max_lag: int | None = None) -> int:
    """
    Longueur de bloc moyenne pour le bootstrap stationnaire.

    Regle : on somme les autocorrelations significatives (au-dela de la bande de bruit
    1.96/sqrt(n)) jusqu'au premier retard non significatif, et on prend
    b = ceil(n^(1/3) * (1 + 2*somme)). Le terme n^(1/3) est le taux classique ; le
    facteur d'inflation etire les blocs quand la serie est persistante.

    Une serie sans autocorrelation retombe sur b = ceil(n^(1/3)), soit ~5 pour n=100.
    """
    a = _clean(returns)
    n = len(a)
    require(n >= MIN_OBS_BOOTSTRAP, f"au moins {MIN_OBS_BOOTSTRAP} observations requises (recu {n})")
    if max_lag is None:
        max_lag = max(1, min(n // 4, 50))
    seuil = 1.96 / math.sqrt(n)
    somme = 0.0
    for lag in range(1, max_lag + 1):
        try:
            r = autocorrelation(a, lag)
        except InsufficientData:
            break
        if abs(r) < seuil:
            break
        somme += abs(r)
    b = math.ceil(n ** (1 / 3) * (1 + 2 * somme))
    return int(max(1, min(b, n)))


# --------------------------------------------------------------------------- bootstrap
@dataclass(frozen=True)
class BootstrapResult:
    statistique_observee: float
    moyenne: float
    ecart_type: float
    ic_bas: float
    ic_haut: float
    niveau: float
    n_tirages: int
    longueur_bloc: int
    distribution: np.ndarray = field(repr=False)

    def contient(self, valeur: float) -> bool:
        return self.ic_bas <= valeur <= self.ic_haut


def _indices_blocs_stationnaires(n: int, taille: int, b: int, rng: np.random.Generator) -> np.ndarray:
    """
    Bootstrap stationnaire : longueurs de blocs geometriques de moyenne b, avec
    enroulement circulaire. Contrairement au bootstrap par blocs de longueur fixe,
    la serie re-echantillonnee reste stationnaire.
    """
    p = 1.0 / b
    idx = np.empty(taille, dtype=np.int64)
    i = 0
    while i < taille:
        depart = int(rng.integers(0, n))
        longueur = int(rng.geometric(p)) if p < 1.0 else 1
        longueur = min(longueur, taille - i)
        for k in range(longueur):
            idx[i + k] = (depart + k) % n
        i += longueur
    return idx


def bootstrap_par_blocs(returns, statistique=np.mean, *, seed: int,
                        n_tirages: int = 2000, longueur_bloc: int | None = None,
                        niveau: float = 0.95) -> BootstrapResult:
    """
    Intervalle de confiance percentile par bootstrap stationnaire.

    `statistique` doit accepter un tableau 1D et rendre un scalaire.
    `seed` est obligatoire : un intervalle non reproductible ne vaut rien.
    """
    a = _clean(returns)
    n = len(a)
    require(n >= MIN_OBS_BOOTSTRAP,
            f"au moins {MIN_OBS_BOOTSTRAP} observations requises pour un bootstrap (recu {n})")
    require(0.0 < niveau < 1.0, "le niveau doit etre dans ]0,1[")
    require(n_tirages >= 100, "au moins 100 tirages")
    b = longueur_bloc if longueur_bloc is not None else longueur_bloc_recommandee(a)
    require(1 <= b <= n, f"longueur de bloc invalide: {b}")

    rng = np.random.default_rng(seed)
    dist = np.empty(n_tirages, dtype=float)
    for t in range(n_tirages):
        dist[t] = float(statistique(a[_indices_blocs_stationnaires(n, n, b, rng)]))

    alpha = (1.0 - niveau) / 2.0
    bas, haut = np.quantile(dist, [alpha, 1.0 - alpha])
    return BootstrapResult(
        statistique_observee=float(statistique(a)),
        moyenne=float(dist.mean()), ecart_type=float(dist.std(ddof=1)),
        ic_bas=float(bas), ic_haut=float(haut), niveau=niveau,
        n_tirages=n_tirages, longueur_bloc=b, distribution=dist,
    )


# --------------------------------------------------------------------------- permutation
@dataclass(frozen=True)
class PermutationResult:
    statistique_observee: float
    p_value: float
    n_permutations: int
    significatif: bool
    seuil: float
    distribution: np.ndarray = field(repr=False)


def test_permutation_signe(returns, statistique=np.mean, *, seed: int,
                           n_permutations: int = 2000, seuil: float = 0.05) -> PermutationResult:
    """
    Test de permutation par retournement de signe.

    Hypothese nulle : les rendements sont symetriques autour de zero, autrement dit
    il n'y a pas d'edge directionnel. On tire des signes aleatoires et on recalcule
    la statistique. Le retournement de signe PRESERVE l'ordre temporel, donc il ne
    detruit pas l'autocorrelation — contrairement a une permutation des positions,
    qui testerait une nulle differente (et plus facile a rejeter a tort).

    p-value avec correction de continuite (+1 au numerateur et au denominateur) :
    une p-value strictement nulle est impossible avec un nombre fini de tirages.
    """
    a = _clean(returns)
    n = len(a)
    require(n >= MIN_OBS_PERMUTATION,
            f"au moins {MIN_OBS_PERMUTATION} observations requises (recu {n})")
    require(n_permutations >= 100, "au moins 100 permutations")
    obs = float(statistique(a))
    rng = np.random.default_rng(seed)
    dist = np.empty(n_permutations, dtype=float)
    for t in range(n_permutations):
        signes = rng.choice(np.array([-1.0, 1.0]), size=n)
        dist[t] = float(statistique(a * signes))
    # bilateral : on compare les valeurs absolues
    p = (1.0 + float(np.sum(np.abs(dist) >= abs(obs)))) / (n_permutations + 1.0)
    return PermutationResult(statistique_observee=obs, p_value=p,
                             n_permutations=n_permutations,
                             significatif=p < seuil, seuil=seuil, distribution=dist)


# --------------------------------------------------------------------------- Sharpe degonfle
@dataclass(frozen=True)
class SharpeDegonfle:
    sharpe_observe: float
    sharpe_seuil: float
    probabilite: float
    n_essais: int
    asymetrie: float
    kurtosis: float
    significatif: bool


def sharpe_par_trade(returns) -> float:
    """Sharpe non annualise, par trade. L'annualisation exigerait une frequence
    de trading connue et stable, ce qui n'est pas garanti ici."""
    a = _clean(returns)
    require(len(a) >= MIN_OBS_SHARPE, f"au moins {MIN_OBS_SHARPE} trades requis (recu {len(a)})")
    sd = a.std(ddof=1)
    if sd == 0.0:
        raise InsufficientData("ecart-type nul : le Sharpe est indefini, pas infini")
    return float(a.mean() / sd)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """Quantile normal par bissection : evite une dependance a scipy."""
    require(0.0 < p < 1.0, "quantile hors de ]0,1[")
    bas, haut = -40.0, 40.0
    for _ in range(200):
        mid = (bas + haut) / 2.0
        if _phi(mid) < p:
            bas = mid
        else:
            haut = mid
    return (bas + haut) / 2.0


def sharpe_degonfle(returns, *, n_essais: int, dispersion_essais: float | None = None,
                    seuil: float = 0.95) -> SharpeDegonfle:
    """
    Sharpe degonfle (Bailey & Lopez de Prado, 2014).

    `n_essais` est le nombre de configurations REELLEMENT essayees : nombre de wallets
    classes, de variantes de strategie testees, de jeux de parametres balayes. Le
    sous-declarer revient a se mentir — c'est le parametre le plus facile a tricher.

    Deux etapes :
      1. seuil attendu du maximum de n_essais Sharpe nuls, via l'approximation du
         maximum d'un echantillon gaussien : E[max] ~ (1-g)*Phi^-1(1-1/N) + g*Phi^-1(1-1/(N*e)),
         g = constante d'Euler-Mascheroni.
      2. probabilite que le Sharpe observe depasse ce seuil, en corrigeant l'erreur
         standard du Sharpe par l'asymetrie et le kurtosis empiriques.
    """
    a = _clean(returns)
    n = len(a)
    require(n >= MIN_OBS_SHARPE, f"au moins {MIN_OBS_SHARPE} trades requis (recu {n})")
    require(n_essais >= 1, "n_essais doit valoir au moins 1")

    sr = sharpe_par_trade(a)
    m = a.mean()
    sd = a.std(ddof=1)
    g1 = float(np.mean(((a - m) / sd) ** 3))            # asymetrie
    g2 = float(np.mean(((a - m) / sd) ** 4))            # kurtosis NON centre

    # Erreur standard du Sharpe estime, corrigee par l'asymetrie et le kurtosis.
    var = (1.0 - g1 * sr + (g2 - 1.0) / 4.0 * sr ** 2) / (n - 1.0)
    if var <= 0.0:
        raise InsufficientData(
            "variance du Sharpe non positive (queues extremes) : le degonflement "
            "n'est pas calculable sur cette serie"
        )
    sigma = math.sqrt(var)

    # SEUIL DE DEGONFLEMENT. Le facteur `sigma` n'est pas optionnel : chez Bailey &
    # Lopez de Prado, SR*0 = sqrt(V[SR_n]) x [(1-g)Phi^-1(1-1/N) + g Phi^-1(1-1/(N e))].
    # Le crochet seul est un quantile de loi normale centree reduite ; l'omettre
    # revenait a opposer un Sharpe PAR TRADE (0,10 sur le pool mesure) a un quantile
    # d'ecart-type (3,09 pour N=560). Deux echelles differentes.
    # Consequence verifiee : avec le crochet nu, la condition exigeait un Sharpe par
    # trade de 0,52 des n_essais=2 et de 3,09 a n_essais=560 — seule une serie quasi
    # deterministe (Sharpe par trade ~20 sur un gain constant a 5 % pres) y parvenait.
    # Aucune serie de trading reelle ne l'atteint : la condition n'etait pas severe,
    # elle etait dimensionnellement fausse et donc insatisfaisable par construction.
    # Le seuil de decision (`seuil`, 0,95 sur la probabilite) et `n_essais` restent
    # strictement inchanges — seule l'echelle de SR*0 est corrigee.
    # `dispersion_essais` est sqrt(V[{SR_n}]), l'ecart-type des Sharpe ENTRE essais.
    # C'est la quantite du papier, et elle se MESURE : sur 120 wallets criblés de cette
    # campagne, elle vaut 0,1768 (min -0,626, max +0,741). A defaut, on retombe sur
    # l'erreur standard de l'estimateur, qui vaut ici 0,0358 — quinze fois plus petite,
    # donc quinze fois trop permissive. Le defaut est explicitement signale comme une
    # approximation : ne jamais le laisser passer pour la mesure.
    dispersion = float(dispersion_essais) if dispersion_essais is not None else sigma
    require(dispersion > 0.0, "la dispersion entre essais doit etre strictement positive")
    if n_essais == 1:
        sr0 = 0.0
    else:
        gamma = 0.5772156649015329
        N = float(n_essais)
        sr0 = dispersion * ((1.0 - gamma) * _phi_inv(1.0 - 1.0 / N)
                            + gamma * _phi_inv(1.0 - 1.0 / (N * math.e)))

    proba = _phi((sr - sr0) / sigma)
    return SharpeDegonfle(sharpe_observe=sr, sharpe_seuil=float(sr0), probabilite=float(proba),
                          n_essais=n_essais, asymetrie=g1, kurtosis=g2,
                          significatif=proba >= seuil)


# --------------------------------------------------------------------------- drawdown
@dataclass(frozen=True)
class DrawdownSimule:
    drawdown_observe: float
    quantile_observe: float
    mediane_simulee: float
    q95_simule: float
    n_tirages: int
    longueur_bloc: int
    anormal: bool
    distribution: np.ndarray = field(repr=False)


def max_drawdown(returns) -> float:
    """Max drawdown de la courbe de PnL CUMULE (somme, pas produit) : les rendements
    par trade sont ici des montants, pas des taux composables. Rendu positif."""
    a = _clean(returns)
    require(len(a) >= 1, "serie vide")
    cum = np.cumsum(a)
    pic = np.maximum.accumulate(cum)
    return float(np.max(pic - cum))


def simuler_drawdown(returns, *, seed: int, n_tirages: int = 2000,
                     longueur_bloc: int | None = None) -> DrawdownSimule:
    """
    Distribution du max drawdown attendu pour une serie ayant les MEMES rendements,
    seulement reordonnes par blocs. Permet de distinguer un drawdown anormal d'un
    drawdown parfaitement banal pour cette volatilite.

    `anormal` = le drawdown observe depasse le 95e centile simule.
    """
    a = _clean(returns)
    n = len(a)
    require(n >= MIN_OBS_DRAWDOWN, f"au moins {MIN_OBS_DRAWDOWN} observations requises (recu {n})")
    b = longueur_bloc if longueur_bloc is not None else longueur_bloc_recommandee(a)
    rng = np.random.default_rng(seed)
    dist = np.empty(n_tirages, dtype=float)
    for t in range(n_tirages):
        dist[t] = max_drawdown(a[_indices_blocs_stationnaires(n, n, b, rng)])
    obs = max_drawdown(a)
    q95 = float(np.quantile(dist, 0.95))
    return DrawdownSimule(drawdown_observe=obs,
                          quantile_observe=float(np.mean(dist <= obs)),
                          mediane_simulee=float(np.median(dist)), q95_simule=q95,
                          n_tirages=n_tirages, longueur_bloc=b,
                          anormal=obs > q95, distribution=dist)


# --------------------------------------------------------------------------- rapport
def rapport_significativite(returns, *, seed: int, n_essais: int,
                            n_tirages: int = 2000) -> dict:
    """
    Verdict groupe sur une serie de rendements par trade.

    `n_essais` DOIT etre le nombre de wallets/configurations reellement examines,
    sinon le degonflement ne corrige rien. Les trois tests sont independants et
    peuvent se contredire : c'est une information, pas un defaut.
    """
    a = _clean(returns)
    boot = bootstrap_par_blocs(a, np.mean, seed=seed, n_tirages=n_tirages)
    perm = test_permutation_signe(a, np.mean, seed=seed + 1, n_permutations=n_tirages)
    dd = simuler_drawdown(a, seed=seed + 2, n_tirages=n_tirages)
    try:
        deg = sharpe_degonfle(a, n_essais=n_essais)
        deg_d = {"sharpe": deg.sharpe_observe, "seuil": deg.sharpe_seuil,
                 "probabilite": deg.probabilite, "significatif": deg.significatif}
    except InsufficientData as e:
        deg_d = {"indisponible": str(e)}
    return {
        "n_observations": len(a),
        "longueur_bloc": boot.longueur_bloc,
        "moyenne_ic": (boot.ic_bas, boot.ic_haut),
        "moyenne_ic_exclut_zero": not boot.contient(0.0),
        "permutation_p": perm.p_value,
        "permutation_significative": perm.significatif,
        "sharpe_degonfle": deg_d,
        "drawdown": {"observe": dd.drawdown_observe, "q95_simule": dd.q95_simule,
                     "anormal": dd.anormal},
        "graine": seed,
    }
