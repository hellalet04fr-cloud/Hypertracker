"""
Tests de ht/calibration.py. Aucun reseau.

Series `fixture_*` a verite terrain connue : c'est indispensable ici, puisque mesurer
une erreur de calibration exige de connaitre la vraie probabilite generatrice. Aucune
sortie ne decrit un modele reel : aucune issue binaire etiquetee n'a encore ete
collectee (closed_trades jamais observe).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import InsufficientData  # noqa: E402
import ht.calibration as cal  # noqa: E402


# =========================================================================== fixtures
def fixture_parfait(n=3000, seed=1):
    """Modele PARFAITEMENT calibre : p tire uniformement, y ~ Bernoulli(p)."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.95, n)
    y = (rng.uniform(0, 1, n) < p).astype(float)
    return y, p


def fixture_surconfiant(n=3000, seed=2, force=2.5):
    """Meme verite, mais les probabilites sont poussees vers 0 et 1 : le modele
    annonce 90 % la ou la frequence reelle est 70 %."""
    rng = np.random.default_rng(seed)
    p_vrai = rng.uniform(0.05, 0.95, n)
    y = (rng.uniform(0, 1, n) < p_vrai).astype(float)
    logit = np.log(p_vrai / (1 - p_vrai)) * force
    return y, 1.0 / (1.0 + np.exp(-logit))


def fixture_sans_pouvoir(n=3000, seed=3, taux=0.4):
    """Predit toujours le taux de base : bien calibre, resolution nulle."""
    rng = np.random.default_rng(seed)
    y = (rng.uniform(0, 1, n) < taux).astype(float)
    return y, np.full(n, taux)


# =========================================================================== validation
def test_refuse_cible_non_binaire():
    with pytest.raises(InsufficientData) as e:
        cal.brier_score([0, 1, 2], [0.1, 0.2, 0.3])
    assert "binaire" in str(e.value)


def test_refuse_probabilite_hors_bornes():
    with pytest.raises(InsufficientData) as e:
        cal.brier_score([0, 1], [0.5, 1.4])
    assert "hors [0,1]" in str(e.value)


def test_refuse_tailles_incompatibles():
    with pytest.raises(InsufficientData):
        cal.brier_score([0, 1, 1], [0.5, 0.5])


def test_refuse_non_fini():
    with pytest.raises(InsufficientData):
        cal.brier_score([0, 1], [0.5, np.nan])


def test_refuse_echantillon_trop_petit_pour_ece():
    y, p = fixture_parfait(20)
    with pytest.raises(InsufficientData) as e:
        cal.expected_calibration_error(y, p)
    assert "observations" in str(e.value)


# =========================================================================== Brier
def test_brier_valeurs_connues():
    assert cal.brier_score([1.0], [1.0]) == pytest.approx(0.0)
    assert cal.brier_score([0.0], [1.0]) == pytest.approx(1.0)
    assert cal.brier_score([1.0, 0.0], [0.5, 0.5]) == pytest.approx(0.25)


def test_decomposition_respecte_identite():
    y, p = fixture_parfait()
    d = cal.brier_decomposition(y, p, n_bacs=10)
    # brier = fiabilite - resolution + incertitude, a l'erreur de binning pres
    assert d.brier == pytest.approx(d.fiabilite - d.resolution + d.incertitude, abs=5e-3)


def test_modele_calibre_a_faible_fiabilite():
    y, p = fixture_parfait()
    d = cal.brier_decomposition(y, p)
    assert d.fiabilite < 0.01


def test_modele_sans_pouvoir_a_resolution_quasi_nulle():
    y, p = fixture_sans_pouvoir()
    d = cal.brier_decomposition(y, p)
    assert d.resolution < 1e-6
    assert d.incertitude == pytest.approx(y.mean() * (1 - y.mean()))


# =========================================================================== ECE
def test_ece_proche_de_zero_si_calibre():
    y, p = fixture_parfait()
    assert cal.expected_calibration_error(y, p) < 0.03


def test_surconfiance_detectee():
    y, p = fixture_surconfiant()
    assert cal.expected_calibration_error(y, p) > 0.05


def test_binning_par_quantiles_remplit_les_bacs():
    """Avec des probabilites tres concentrees, un binning a largeur egale laisserait
    presque tous les bacs vides. Par quantiles, chaque bac est peuple."""
    rng = np.random.default_rng(9)
    p = rng.normal(0.5, 0.005, 2000).clip(0.001, 0.999)
    y = (rng.uniform(0, 1, 2000) < p).astype(float)
    c = cal.courbe_fiabilite(y, p, n_bacs=10)
    assert c.n_bacs_effectifs >= 8
    assert c.effectifs.min() >= cal.MIN_PAR_BAC


def test_courbe_effectifs_totalisent_l_echantillon():
    y, p = fixture_parfait(1000)
    c = cal.courbe_fiabilite(y, p, n_bacs=10)
    assert int(c.effectifs.sum()) == 1000
    assert len(c.p_moyen) == len(c.frequence_observee) == c.n_bacs_effectifs


# =========================================================================== recalibrage
def test_isotonique_ameliore_la_calibration():
    y_fit, p_fit = fixture_surconfiant(3000, seed=11)
    y_ev, p_ev = fixture_surconfiant(3000, seed=12)
    avant = cal.expected_calibration_error(y_ev, p_ev)
    iso = cal.Isotonique().fit(y_fit, p_fit)
    apres = cal.expected_calibration_error(y_ev, iso.predict(p_ev))
    assert apres < avant


def test_platt_ameliore_la_calibration():
    y_fit, p_fit = fixture_surconfiant(3000, seed=13)
    y_ev, p_ev = fixture_surconfiant(3000, seed=14)
    avant = cal.expected_calibration_error(y_ev, p_ev)
    pl = cal.Platt().fit(y_fit, p_fit)
    apres = cal.expected_calibration_error(y_ev, pl.predict(p_ev))
    assert apres < avant


def test_isotonique_est_monotone():
    y, p = fixture_surconfiant(2000, seed=15)
    iso = cal.Isotonique().fit(y, p)
    grille = np.linspace(0.01, 0.99, 200)
    sortie = iso.predict(grille)
    assert np.all(np.diff(sortie) >= -1e-12)


def test_sorties_restent_dans_zero_un():
    y, p = fixture_surconfiant(1000, seed=16)
    for m in (cal.Isotonique().fit(y, p), cal.Platt().fit(y, p)):
        s = m.predict(np.linspace(0.0, 1.0, 101))
        assert np.all((s >= 0.0) & (s <= 1.0))


def test_refuse_evaluation_sur_le_jeu_d_ajustement():
    """La fuite silencieuse la plus courante en calibration."""
    y, p = fixture_surconfiant(1000, seed=17)
    iso = cal.Isotonique().fit(y, p)
    with pytest.raises(InsufficientData) as e:
        iso.verifier_jeu_distinct(y, p)
    assert "jeu d'ajustement" in str(e.value)
    # un jeu distinct passe
    y2, p2 = fixture_surconfiant(1000, seed=18)
    iso.verifier_jeu_distinct(y2, p2)


def test_platt_exige_les_deux_classes():
    n = 200
    with pytest.raises(InsufficientData) as e:
        cal.Platt().fit(np.ones(n), np.full(n, 0.7))
    assert "deux classes" in str(e.value)


def test_predict_avant_fit_refuse():
    with pytest.raises(InsufficientData):
        cal.Isotonique().predict([0.5])
    with pytest.raises(InsufficientData):
        cal.Platt().predict([0.5])


# =========================================================================== overfit
def test_degradation_dans_le_bruit_non_alertee():
    r = cal.overfit_report(0.200, 0.205, n_oos=100, n_configs_tried=1)
    assert not r.surapprentissage_probable


def test_degradation_franche_alertee():
    r = cal.overfit_report(0.10, 0.40, n_oos=1000, n_configs_tried=1)
    assert r.surapprentissage_probable
    assert r.degradation == pytest.approx(0.30)


def test_seuil_s_eleve_avec_le_nombre_de_configs():
    peu = cal.overfit_report(0.2, 0.25, n_oos=500, n_configs_tried=1)
    beaucoup = cal.overfit_report(0.2, 0.25, n_oos=500, n_configs_tried=10000)
    assert beaucoup.bruit_attendu > peu.bruit_attendu


def test_sens_de_la_metrique_respecte():
    """Avec une metrique ou plus haut est mieux (ex. AUC), la degradation s'inverse."""
    r = cal.overfit_report(0.90, 0.60, n_oos=1000, n_configs_tried=1, plus_bas_est_mieux=False)
    assert r.degradation == pytest.approx(0.30)
    assert r.surapprentissage_probable


def test_metrique_non_finie_refusee():
    with pytest.raises(InsufficientData):
        cal.overfit_report(float("nan"), 0.3, n_oos=100, n_configs_tried=1)


# =========================================================================== derive
def test_psi_faible_sur_meme_distribution():
    rng = np.random.default_rng(21)
    d = cal.population_stability_index(rng.normal(0, 1, 5000), rng.normal(0, 1, 5000))
    assert d.psi < 0.1
    assert d.verdict == "stable"


def test_psi_eleve_sur_distribution_decalee():
    rng = np.random.default_rng(22)
    d = cal.population_stability_index(rng.normal(0, 1, 5000), rng.normal(1.5, 1, 5000))
    assert d.psi > 0.25
    assert d.verdict == "significative"
    assert d.ks > 0.3


def test_ks_borne_entre_zero_et_un():
    rng = np.random.default_rng(23)
    d = cal.population_stability_index(rng.normal(0, 1, 500), rng.normal(0.3, 1, 500))
    assert 0.0 <= d.ks <= 1.0


def test_derive_refuse_echantillon_court():
    with pytest.raises(InsufficientData):
        cal.population_stability_index(np.arange(10.0), np.arange(10.0))


def test_derive_refuse_reference_constante():
    with pytest.raises(InsufficientData) as e:
        cal.population_stability_index(np.full(200, 3.0), np.random.default_rng(1).normal(0, 1, 200))
    assert "concentree" in str(e.value)
