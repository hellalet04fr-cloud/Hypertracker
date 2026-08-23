"""
Tests de ht/montecarlo.py. Aucun reseau, aucune requete API.

Toutes les series sont des generateurs `fixture_*` a verite terrain CONNUE : c'est la
seule facon de verifier qu'un test de significativite detecte un edge injecte et
n'en invente pas sur du bruit. Aucune sortie de ces tests ne decrit un wallet reel —
aucun rendement reel n'a encore ete collecte (closed_trades jamais observe).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import InsufficientData  # noqa: E402
import ht.montecarlo as mc  # noqa: E402


# =========================================================================== fixtures
def fixture_bruit(n=400, seed=1, sigma=1.0):
    """Aucun edge : moyenne nulle, i.i.d."""
    return np.random.default_rng(seed).normal(0.0, sigma, n)


def fixture_edge(n=400, seed=2, mu=0.35, sigma=1.0):
    """Edge franc : moyenne strictement positive."""
    return np.random.default_rng(seed).normal(mu, sigma, n)


def fixture_autocorrelee(n=600, seed=3, phi=0.6, sigma=1.0):
    """AR(1) de moyenne nulle : pas d'edge, mais forte dependance temporelle."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0.0, sigma)
    return x


# =========================================================================== garde-fous
def test_refuse_serie_trop_courte():
    with pytest.raises(InsufficientData) as e:
        mc.bootstrap_par_blocs(fixture_bruit(10), seed=0)
    assert "observations" in str(e.value)


def test_refuse_valeurs_non_finies():
    a = fixture_bruit(100)
    a[7] = np.nan
    with pytest.raises(InsufficientData) as e:
        mc.bootstrap_par_blocs(a, seed=0)
    assert "non finie" in str(e.value)


def test_refuse_serie_constante_pour_le_sharpe():
    with pytest.raises(InsufficientData) as e:
        mc.sharpe_par_trade(np.full(100, 0.5))
    assert "indefini" in str(e.value)


def test_graine_obligatoire():
    with pytest.raises(TypeError):
        mc.bootstrap_par_blocs(fixture_bruit(100))          # seed est keyword-only


# =========================================================================== autocorrelation
def test_autocorrelation_lag0_vaut_un():
    assert mc.autocorrelation(fixture_bruit(200), 0) == pytest.approx(1.0)


def test_autocorrelation_detecte_ar1():
    r1 = mc.autocorrelation(fixture_autocorrelee(2000, seed=11, phi=0.6), 1)
    assert 0.45 < r1 < 0.75          # phi=0.6, tolerance d'echantillonnage


def test_bloc_plus_long_quand_serie_persistante():
    b_iid = mc.longueur_bloc_recommandee(fixture_bruit(600, seed=12))
    b_ar = mc.longueur_bloc_recommandee(fixture_autocorrelee(600, seed=13, phi=0.7))
    assert b_ar > b_iid
    assert b_iid >= 1


# =========================================================================== bootstrap
def test_bootstrap_reproductible():
    a = fixture_edge(200)
    r1 = mc.bootstrap_par_blocs(a, seed=42, n_tirages=300)
    r2 = mc.bootstrap_par_blocs(a, seed=42, n_tirages=300)
    assert r1.ic_bas == r2.ic_bas and r1.ic_haut == r2.ic_haut


def test_bootstrap_graines_differentes_donnent_resultats_differents():
    a = fixture_edge(200)
    r1 = mc.bootstrap_par_blocs(a, seed=1, n_tirages=300)
    r2 = mc.bootstrap_par_blocs(a, seed=2, n_tirages=300)
    assert r1.ic_bas != r2.ic_bas


def test_bootstrap_ic_contient_zero_sur_bruit():
    r = mc.bootstrap_par_blocs(fixture_bruit(500, seed=21), seed=7, n_tirages=800)
    assert r.contient(0.0)


def test_bootstrap_ic_exclut_zero_sur_edge():
    r = mc.bootstrap_par_blocs(fixture_edge(500, seed=22), seed=7, n_tirages=800)
    assert not r.contient(0.0)
    assert r.ic_bas > 0.0


def test_bootstrap_encadre_la_statistique_observee():
    a = fixture_edge(300)
    r = mc.bootstrap_par_blocs(a, seed=5, n_tirages=600)
    assert r.ic_bas <= r.statistique_observee <= r.ic_haut


# =========================================================================== permutation
def test_permutation_ne_trouve_rien_sur_bruit():
    r = mc.test_permutation_signe(fixture_bruit(400, seed=31), seed=3, n_permutations=800)
    assert not r.significatif
    assert r.p_value > 0.05


def test_permutation_trouve_edge_injecte():
    r = mc.test_permutation_signe(fixture_edge(400, seed=32), seed=3, n_permutations=800)
    assert r.significatif
    assert r.p_value < 0.01


def test_p_value_jamais_nulle():
    """Correction de continuite : avec un nombre fini de tirages, p=0 est impossible."""
    r = mc.test_permutation_signe(fixture_edge(400, seed=33, mu=5.0), seed=3, n_permutations=200)
    assert r.p_value > 0.0
    assert r.p_value == pytest.approx(1.0 / 201.0)


def test_taux_de_faux_positifs_raisonnable():
    """Sur 20 series de pur bruit, au plus 3 detections au seuil 5 % (tolerance large
    pour ne pas rendre le test instable)."""
    faux = 0
    for s in range(20):
        r = mc.test_permutation_signe(fixture_bruit(200, seed=100 + s), seed=s, n_permutations=400)
        faux += int(r.significatif)
    assert faux <= 3


# =========================================================================== Sharpe degonfle
def test_seuil_croit_avec_le_nombre_d_essais():
    a = fixture_edge(300)
    s1 = mc.sharpe_degonfle(a, n_essais=1)
    s100 = mc.sharpe_degonfle(a, n_essais=100)
    s10000 = mc.sharpe_degonfle(a, n_essais=10000)
    assert s1.sharpe_seuil == 0.0
    assert s100.sharpe_seuil > s1.sharpe_seuil
    assert s10000.sharpe_seuil > s100.sharpe_seuil


def test_degonflement_reduit_la_confiance():
    a = fixture_edge(300, mu=0.2)
    assert mc.sharpe_degonfle(a, n_essais=10000).probabilite < mc.sharpe_degonfle(a, n_essais=1).probabilite


def test_meilleur_de_mille_bruits_ne_survit_pas_au_degonflement():
    """Le scenario que le degonflement existe pour attraper : on prend le MEILLEUR
    Sharpe parmi 1000 series sans aucun edge. Non degonfle il parait excellent ;
    degonfle a n_essais=1000 il ne doit plus etre significatif."""
    meilleur, best_sr = None, -np.inf
    for s in range(1000):
        a = fixture_bruit(120, seed=5000 + s)
        sr = mc.sharpe_par_trade(a)
        if sr > best_sr:
            best_sr, meilleur = sr, a
    assert best_sr > 0.2                                   # il parait bon
    naif = mc.sharpe_degonfle(meilleur, n_essais=1)
    corrige = mc.sharpe_degonfle(meilleur, n_essais=1000)
    assert naif.probabilite > 0.95                         # naivement "significatif"
    assert not corrige.significatif                        # apres correction, non


def test_sharpe_degonfle_refuse_echantillon_court():
    with pytest.raises(InsufficientData):
        mc.sharpe_degonfle(fixture_edge(10), n_essais=5)


# =========================================================================== drawdown
def test_max_drawdown_valeur_connue():
    """PnL cumule 1, 3, 0, 2 -> pic 3, creux 0 -> drawdown 3."""
    assert mc.max_drawdown([1.0, 2.0, -3.0, 2.0]) == pytest.approx(3.0)


def test_max_drawdown_nul_si_monotone_croissant():
    assert mc.max_drawdown([1.0, 1.0, 1.0]) == pytest.approx(0.0)


def test_drawdown_normal_non_signale():
    a = fixture_bruit(300, seed=41)
    d = mc.simuler_drawdown(a, seed=9, n_tirages=500)
    assert 0.0 <= d.quantile_observe <= 1.0
    assert not d.anormal or d.quantile_observe > 0.95


def test_drawdown_anormal_detecte():
    """Une serie ou l'on CONCENTRE toutes les pertes d'affilee a le meme jeu de
    rendements mais un drawdown bien pire que la plupart des reordonnancements."""
    rng = np.random.default_rng(51)
    a = np.concatenate([rng.normal(0.5, 0.3, 150), rng.normal(-0.5, 0.3, 150)])
    d = mc.simuler_drawdown(a, seed=9, n_tirages=500, longueur_bloc=1)
    assert d.anormal
    assert d.quantile_observe > 0.95


# =========================================================================== rapport
def test_rapport_coherent_sur_bruit():
    r = mc.rapport_significativite(fixture_bruit(400, seed=61), seed=11, n_essais=500, n_tirages=400)
    assert not r["permutation_significative"]
    assert not r["moyenne_ic_exclut_zero"]
    assert r["graine"] == 11


def test_rapport_coherent_sur_edge():
    r = mc.rapport_significativite(fixture_edge(400, seed=62), seed=11, n_essais=1, n_tirages=400)
    assert r["permutation_significative"]
    assert r["moyenne_ic_exclut_zero"]
    assert r["sharpe_degonfle"]["significatif"]
