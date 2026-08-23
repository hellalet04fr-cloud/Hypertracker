"""
G — Calibration et detection de surapprentissage.

Un modele peut trier correctement (bonne AUC) et mentir sur ses probabilites : dire
"80 %" quand la frequence reelle est 55 %. Pour un moteur de probabilites, c'est
disqualifiant — on ne peut pas dimensionner un risque sur une probabilite fausse.

Choix explicites :
  - BINNING PAR QUANTILES, jamais a largeur egale. Les probabilites predites sont
    concentrees (souvent proche du taux de base) : des bacs a largeur egale laissent
    la plupart vides et l'ECE resultante est dominee par deux ou trois bacs, ce qui
    la rend a la fois instable et flatteuse.
  - RECALIBRAGE AJUSTE SUR UN JEU DEDIE. Ajuster l'isotonique sur le test est une
    fuite : le module REFUSE de le faire (verification d'identite des tableaux).
  - Le score de Brier est decompose (fiabilite / resolution / incertitude) parce que
    le score seul confond deux defauts opposes : mal calibre, et sans pouvoir
    discriminant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .schema import InsufficientData, require

MIN_OBS_CALIBRATION = 50
MIN_PAR_BAC = 5


# --------------------------------------------------------------------------- utilitaires
def _valider(y_true, y_prob) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_prob, dtype=float)
    require(y.ndim == 1 and p.ndim == 1, "y_true et y_prob doivent etre unidimensionnels")
    require(len(y) == len(p), f"tailles incompatibles: {len(y)} vs {len(p)}")
    require(len(y) > 0, "echantillon vide")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(p))):
        raise InsufficientData("valeurs non finies : nettoyer en amont, ne pas imputer ici")
    uniques = set(np.unique(y).tolist())
    require(uniques <= {0.0, 1.0}, f"y_true doit etre binaire 0/1, trouve {sorted(uniques)[:5]}")
    require(bool(np.all((p >= 0.0) & (p <= 1.0))),
            f"probabilites hors [0,1]: min={p.min():.4g} max={p.max():.4g}")
    return y, p


# --------------------------------------------------------------------------- Brier
@dataclass(frozen=True)
class BrierDecomposition:
    brier: float
    fiabilite: float          # plus bas = mieux (ecart calibration)
    resolution: float         # plus haut = mieux (pouvoir discriminant)
    incertitude: float        # propriete des donnees, pas du modele
    n_bacs: int

    def verifie_identite(self, tol: float = 1e-8) -> bool:
        """brier = fiabilite - resolution + incertitude (a l'erreur de binning pres)."""
        return abs(self.brier - (self.fiabilite - self.resolution + self.incertitude)) < tol


def brier_score(y_true, y_prob) -> float:
    y, p = _valider(y_true, y_prob)
    return float(np.mean((p - y) ** 2))


def _bords_quantiles(p: np.ndarray, n_bacs: int) -> np.ndarray:
    """Bords par quantiles, dedupliques : des probabilites tres concentrees peuvent
    produire des quantiles identiques, auquel cas le nombre de bacs diminue et c'est
    signale plutot que masque."""
    qs = np.linspace(0.0, 1.0, n_bacs + 1)
    bords = np.unique(np.quantile(p, qs))
    bords[0] = min(bords[0], 0.0) - 1e-12
    bords[-1] = max(bords[-1], 1.0) + 1e-12
    return bords


def _affecter_bacs(p: np.ndarray, n_bacs: int) -> tuple[np.ndarray, int]:
    bords = _bords_quantiles(p, n_bacs)
    idx = np.clip(np.digitize(p, bords[1:-1], right=False), 0, len(bords) - 2)
    return idx, len(bords) - 1


def brier_decomposition(y_true, y_prob, n_bacs: int = 10) -> BrierDecomposition:
    """Decomposition de Murphy. Le binning est par quantiles (voir docstring du module)."""
    y, p = _valider(y_true, y_prob)
    require(len(y) >= MIN_OBS_CALIBRATION,
            f"au moins {MIN_OBS_CALIBRATION} observations requises (recu {len(y)})")
    idx, k = _affecter_bacs(p, n_bacs)
    n = len(y)
    ybar = float(y.mean())
    fiab = res = 0.0
    for b in range(k):
        m = idx == b
        nb = int(m.sum())
        if nb == 0:
            continue
        pbar = float(p[m].mean())
        obar = float(y[m].mean())
        fiab += nb * (pbar - obar) ** 2
        res += nb * (obar - ybar) ** 2
    fiab /= n
    res /= n
    inc = ybar * (1.0 - ybar)
    return BrierDecomposition(brier=brier_score(y, p), fiabilite=fiab,
                              resolution=res, incertitude=inc, n_bacs=k)


# --------------------------------------------------------------------------- ECE
@dataclass(frozen=True)
class CourbeFiabilite:
    p_moyen: np.ndarray
    frequence_observee: np.ndarray
    effectifs: np.ndarray
    ece: float
    mce: float
    n_bacs_effectifs: int
    bacs_sous_peuples: int


def courbe_fiabilite(y_true, y_prob, n_bacs: int = 10) -> CourbeFiabilite:
    """
    Diagramme de fiabilite sous forme tabulaire, plus ECE et MCE.

    ECE = somme ponderee des ecarts |p_moyen - frequence| par bac.
    MCE = pire ecart sur un bac ayant au moins MIN_PAR_BAC observations : un bac
          a 2 elements donne un ecart de pur bruit qui gonflerait le MCE.
    """
    y, p = _valider(y_true, y_prob)
    require(len(y) >= MIN_OBS_CALIBRATION,
            f"au moins {MIN_OBS_CALIBRATION} observations requises (recu {len(y)})")
    idx, k = _affecter_bacs(p, n_bacs)
    n = len(y)
    pm, fo, eff = [], [], []
    ece = 0.0
    mce = 0.0
    sous_peuples = 0
    for b in range(k):
        m = idx == b
        nb = int(m.sum())
        if nb == 0:
            continue
        pbar = float(p[m].mean())
        obar = float(y[m].mean())
        pm.append(pbar)
        fo.append(obar)
        eff.append(nb)
        ece += nb / n * abs(pbar - obar)
        if nb >= MIN_PAR_BAC:
            mce = max(mce, abs(pbar - obar))
        else:
            sous_peuples += 1
    return CourbeFiabilite(np.array(pm), np.array(fo), np.array(eff, dtype=int),
                           float(ece), float(mce), len(pm), sous_peuples)


def expected_calibration_error(y_true, y_prob, n_bacs: int = 10) -> float:
    return courbe_fiabilite(y_true, y_prob, n_bacs).ece


def ece_hors_echantillon(y_true, y_prob, *, classification: str,
                         jeu_ajustement=None, n_bacs: int = 10) -> float:
    """
    ECE publiable, c'est-a-dire mesuree hors echantillon sur des donnees OBSERVEES.

    Trois refus, chacun suffisant :
      - `classification` different de OBSERVED : une ECE calculee sur des issues
        reconstruites mesure la calibration face a NOTRE reconstruction, pas face au
        marche. La publier reviendrait a certifier une probabilite avec la meme
        source qui l'a produite.
      - jeu d'evaluation identique au jeu d'ajustement : fuite classique.
      - echantillon sous le plancher.

    C'est cette valeur, et elle seule, que `ht.signaux` doit recevoir : sans elle, le
    moteur refuse d'emettre une direction.
    """
    from .schema import OBSERVED

    if classification != OBSERVED:
        raise InsufficientData(
            f"ECE non publiable sur des donnees {classification!r} : une erreur de "
            f"calibration n'a de sens que confrontee a des issues OBSERVED. "
            "Les donnees DERIVED servent au developpement, pas a certifier une probabilite."
        )
    if jeu_ajustement is not None:
        y_fit, p_fit = jeu_ajustement
        _valider(y_fit, p_fit)
        y, p = _valider(y_true, y_prob)
        emp_a = (len(y_fit), float(np.sum(y_fit)), float(np.sum(p_fit)))
        emp_b = (len(y), float(np.sum(y)), float(np.sum(p)))
        if emp_a == emp_b:
            raise InsufficientData(
                "ECE evaluee sur le jeu d'ajustement : resultat sans valeur. "
                "Utiliser un jeu hors echantillon distinct."
            )
    return expected_calibration_error(y_true, y_prob, n_bacs)


# --------------------------------------------------------------------------- recalibrage
class _Recalibrateur:
    """Base commune : memorise l'identite du jeu d'ajustement pour interdire de
    l'appliquer a lui-meme lors d'une evaluation."""

    def __init__(self):
        self._empreinte_fit: tuple | None = None

    def _memoriser(self, y, p):
        self._empreinte_fit = (len(y), float(np.sum(y)), float(np.sum(p)), float(np.sum(p * p)))

    def verifier_jeu_distinct(self, y_true, y_prob):
        """Leve si on evalue sur exactement le jeu d'ajustement — la fuite la plus
        courante et la plus silencieuse en calibration."""
        y, p = _valider(y_true, y_prob)
        emp = (len(y), float(np.sum(y)), float(np.sum(p)), float(np.sum(p * p)))
        if self._empreinte_fit is not None and emp == self._empreinte_fit:
            raise InsufficientData(
                "evaluation sur le jeu d'ajustement du recalibrage : resultat sans valeur. "
                "Utiliser un jeu de calibration distinct du train ET du test."
            )


class Isotonique(_Recalibrateur):
    """
    Regression isotone par PAVA (pool adjacent violators). Non parametrique : elle
    n'impose aucune forme, seulement la monotonie. Plus souple que Platt, mais elle
    surapprend sur petit echantillon — d'ou le plancher MIN_OBS_CALIBRATION.
    """

    def __init__(self):
        super().__init__()
        self.x_: np.ndarray | None = None
        self.y_: np.ndarray | None = None

    def fit(self, y_true, y_prob) -> "Isotonique":
        y, p = _valider(y_true, y_prob)
        require(len(y) >= MIN_OBS_CALIBRATION,
                f"isotonique: au moins {MIN_OBS_CALIBRATION} observations (recu {len(y)})")
        ordre = np.argsort(p, kind="mergesort")
        xs, ys = p[ordre], y[ordre]
        valeurs = list(ys.astype(float))
        poids = [1.0] * len(ys)
        i = 0
        while i < len(valeurs) - 1:
            if valeurs[i] <= valeurs[i + 1]:
                i += 1
                continue
            w = poids[i] + poids[i + 1]
            v = (valeurs[i] * poids[i] + valeurs[i + 1] * poids[i + 1]) / w
            valeurs[i:i + 2] = [v]
            poids[i:i + 2] = [w]
            while i > 0 and valeurs[i - 1] > valeurs[i]:
                w2 = poids[i - 1] + poids[i]
                v2 = (valeurs[i - 1] * poids[i - 1] + valeurs[i] * poids[i]) / w2
                valeurs[i - 1:i + 1] = [v2]
                poids[i - 1:i + 1] = [w2]
                i -= 1
        # re-expansion des blocs vers le support
        ajuste = np.empty(len(ys), dtype=float)
        pos = 0
        for v, w in zip(valeurs, poids):
            n = int(round(w))
            ajuste[pos:pos + n] = v
            pos += n
        self.x_, self.y_ = xs, ajuste
        self._memoriser(y, p)
        return self

    def predict(self, y_prob) -> np.ndarray:
        require(self.x_ is not None, "isotonique non ajustee")
        p = np.asarray(y_prob, dtype=float)
        require(bool(np.all((p >= 0.0) & (p <= 1.0))), "probabilites hors [0,1]")
        return np.clip(np.interp(p, self.x_, self.y_), 0.0, 1.0)


class Platt(_Recalibrateur):
    """
    Recalibrage de Platt : regression logistique a une variable sur le logit predit.
    Parametrique (2 parametres), donc robuste sur petit echantillon, mais incapable
    de corriger une distorsion non sigmoidale.
    """

    def __init__(self, max_iter: int = 200, tol: float = 1e-9):
        super().__init__()
        self.a_ = 1.0
        self.b_ = 0.0
        self.max_iter = max_iter
        self.tol = tol
        self._ajuste = False

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        eps = 1e-12
        p = np.clip(p, eps, 1.0 - eps)
        return np.log(p / (1.0 - p))

    @staticmethod
    def _sigmoide(z: np.ndarray) -> np.ndarray:
        """Sigmoide numeriquement stable : exp(-z) deborde des que z < -709.
        On traite separement les deux signes pour ne jamais exponentier un grand positif."""
        z = np.asarray(z, dtype=float)
        out = np.empty_like(z)
        pos = z >= 0
        out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
        e = np.exp(z[~pos])
        out[~pos] = e / (1.0 + e)
        return out

    def fit(self, y_true, y_prob) -> "Platt":
        y, p = _valider(y_true, y_prob)
        require(len(y) >= MIN_OBS_CALIBRATION,
                f"platt: au moins {MIN_OBS_CALIBRATION} observations (recu {len(y)})")
        require(0 < y.sum() < len(y), "platt: il faut les deux classes dans le jeu d'ajustement")
        x = self._logit(p)
        a, b = 1.0, 0.0
        for _ in range(self.max_iter):
            q = self._sigmoide(a * x + b)
            w = np.maximum(q * (1.0 - q), 1e-12)
            r = y - q
            g = np.array([float(np.sum(r * x)), float(np.sum(r))])
            h = np.array([[float(np.sum(w * x * x)), float(np.sum(w * x))],
                          [float(np.sum(w * x)), float(np.sum(w))]])
            try:
                pas = np.linalg.solve(h, g)
            except np.linalg.LinAlgError:
                raise InsufficientData("platt: hessienne singuliere, ajustement impossible")
            a += float(pas[0])
            b += float(pas[1])
            if float(np.max(np.abs(pas))) < self.tol:
                break
        self.a_, self.b_, self._ajuste = a, b, True
        self._memoriser(y, p)
        return self

    def predict(self, y_prob) -> np.ndarray:
        require(self._ajuste, "platt non ajuste")
        p = np.asarray(y_prob, dtype=float)
        require(bool(np.all((p >= 0.0) & (p <= 1.0))), "probabilites hors [0,1]")
        return self._sigmoide(self.a_ * self._logit(p) + self.b_)


# --------------------------------------------------------------------------- surapprentissage
@dataclass(frozen=True)
class RapportOverfit:
    metrique_train: float
    metrique_oos: float
    degradation: float
    bruit_attendu: float
    n_configs: int
    seuil_alerte: float
    surapprentissage_probable: bool
    commentaire: str


def overfit_report(train_metric: float, oos_metric: float, *, n_oos: int,
                   n_configs_tried: int, plus_bas_est_mieux: bool = True) -> RapportOverfit:
    """
    Compare la performance en apprentissage et hors echantillon.

    Une degradation n'est pas en soi une preuve de surapprentissage : elle peut n'etre
    que du bruit d'echantillonnage. On la compare donc a une echelle de bruit
    approximative, 1/sqrt(n_oos), amplifiee par sqrt(2*ln(n_configs)) — l'esperance du
    maximum de n_configs tirages, exactement le meme argument que pour le Sharpe
    degonfle : plus on essaie de configurations, plus le meilleur train est optimiste.
    """
    require(n_oos >= 1, "n_oos doit valoir au moins 1")
    require(n_configs_tried >= 1, "n_configs_tried doit valoir au moins 1")
    for nom, v in (("train_metric", train_metric), ("oos_metric", oos_metric)):
        if not math.isfinite(v):
            raise InsufficientData(f"{nom} non finie")
    degradation = (oos_metric - train_metric) if plus_bas_est_mieux else (train_metric - oos_metric)
    bruit = 1.0 / math.sqrt(n_oos)
    if n_configs_tried > 1:
        bruit *= math.sqrt(2.0 * math.log(n_configs_tried))
    probable = degradation > bruit
    if probable:
        com = (f"degradation {degradation:.4g} au-dela du bruit attendu {bruit:.4g} "
               f"pour {n_configs_tried} configuration(s) essayee(s)")
    elif degradation <= 0:
        com = "pas de degradation hors echantillon"
    else:
        com = f"degradation {degradation:.4g} compatible avec le bruit ({bruit:.4g})"
    return RapportOverfit(float(train_metric), float(oos_metric), float(degradation),
                          float(bruit), int(n_configs_tried), float(bruit), probable, com)


# --------------------------------------------------------------------------- derive
@dataclass(frozen=True)
class Derive:
    psi: float
    ks: float
    n_reference: int
    n_courant: int
    n_bacs: int
    verdict: str


def population_stability_index(reference, courant, n_bacs: int = 10) -> Derive:
    """
    PSI et statistique de Kolmogorov-Smirnov entre deux fenetres d'une meme variable.

    Bacs definis par les quantiles de la REFERENCE (pas du courant) : sinon on
    redefinit l'echelle a chaque mesure et la derive devient invisible.
    Lecture usuelle du PSI : < 0,1 stable ; 0,1-0,25 moderee ; > 0,25 significative.
    """
    r = np.asarray(reference, dtype=float)
    c = np.asarray(courant, dtype=float)
    require(r.ndim == 1 and c.ndim == 1, "series unidimensionnelles attendues")
    require(len(r) >= MIN_OBS_CALIBRATION and len(c) >= MIN_OBS_CALIBRATION,
            f"au moins {MIN_OBS_CALIBRATION} observations de chaque cote "
            f"(recu {len(r)} et {len(c)})")
    if not (np.all(np.isfinite(r)) and np.all(np.isfinite(c))):
        raise InsufficientData("valeurs non finies dans les series de derive")

    bords = np.unique(np.quantile(r, np.linspace(0, 1, n_bacs + 1)))
    if len(bords) < 3:
        raise InsufficientData("reference trop concentree : moins de 2 bacs distincts")
    bords[0], bords[-1] = -np.inf, np.inf
    hr, _ = np.histogram(r, bins=bords)
    hc, _ = np.histogram(c, bins=bords)
    pr = hr / hr.sum()
    pc = hc / hc.sum()
    eps = 1e-6                                    # evite log(0) sur un bac vide
    pr = np.clip(pr, eps, None)
    pc = np.clip(pc, eps, None)
    psi = float(np.sum((pc - pr) * np.log(pc / pr)))

    tous = np.sort(np.concatenate([r, c]))
    cr = np.searchsorted(np.sort(r), tous, side="right") / len(r)
    cc = np.searchsorted(np.sort(c), tous, side="right") / len(c)
    ks = float(np.max(np.abs(cr - cc)))

    verdict = "stable" if psi < 0.1 else ("moderee" if psi < 0.25 else "significative")
    return Derive(psi, ks, len(r), len(c), len(bords) - 1, verdict)
