"""
Tests de ht.probability — fondation du Probability Engine.

AUCUN reseau, AUCUNE donnee reelle n'est utilisee ici. Tout ce qui ressemble a des
donnees est produit par des generateurs prefixes `fixture_` : ce sont des simulations
dont la verite terrain est connue, ce qui est la seule facon de tester la calibration
d'un estimateur. Aucun chiffre sorti de ces tests ne decrit le marche reel — les
snapshots orders_5m sont les seules donnees collectees a ce jour et ils ne contiennent
aucune issue binaire etiquetee.

Ce que l'on verifie :
  - convergence de la posterieure vers la vraie proportion quand n grandit ;
  - couverture effective de l'intervalle de credibilite (calibration bayesienne) ;
  - domination du prior sur petit echantillon (anti-surapprentissage) ;
  - refus explicite (InsufficientData) sous la taille d'echantillon minimale ;
  - etancheite as-of (aucune ligne knowable_at > asof) et exclusion de la pseudo-adresse
    TWAP ;
  - le temoin BaselineRate et la comparaison contradictoire qui le rend utile.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ht.probability import (
    KNOWN_BIASES,
    MIN_TRIALS_DIRECT,
    TWAP_PSEUDO_ADDRESS,
    BaselineRate,
    BetaPrior,
    HierarchicalProportion,
    ModelCard,
    Observation,
    ProbabilityModel,
    ProportionEstimate,
    assert_not_post_hoc,
    beta_binomial_proportion,
    brier_score,
    compare_to_baseline,
    counts_by_group,
    fit_cohort_prior,
    log_score,
    observations_asof,
    wilson_proportion,
)
from ht.schema import InsufficientData

ASOF = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- fixtures
def fixture_binomial(p_vrai: float, n: int, graine: int) -> int:
    """Nombre de succes simule sur n essais de Bernoulli(p_vrai). Donnee SYNTHETIQUE."""
    return int(np.random.default_rng(graine).binomial(n, p_vrai))


def fixture_cohorte(
    alpha: float, beta: float, n_groupes: int, essais_par_groupe: int, graine: int
) -> tuple[dict[str, tuple[int, int]], dict[str, float]]:
    """
    Cohorte SYNTHETIQUE : n_groupes taux tires d'une Beta(alpha, beta), puis des essais
    binomiaux. Retourne ({groupe: (succes, essais)}, {groupe: p_vrai}).
    """
    rng = np.random.default_rng(graine)
    p = rng.beta(alpha, beta, size=n_groupes)
    k = rng.binomial(essais_par_groupe, p)
    comptes = {f"w{i:04d}": (int(k[i]), essais_par_groupe) for i in range(n_groupes)}
    verites = {f"w{i:04d}": float(p[i]) for i in range(n_groupes)}
    return comptes, verites


def fixture_observations(
    comptes: dict[str, tuple[int, int]],
    *,
    source: str = "fills",
    fin: datetime = ASOF - timedelta(hours=1),
    pas: timedelta = timedelta(seconds=1),
) -> list[Observation]:
    """Deplie des comptages en observations SYNTHETIQUES horodatees avant `fin`."""
    obs: list[Observation] = []
    t = fin
    for groupe, (k, n) in comptes.items():
        for i in range(n):
            t -= pas
            obs.append(Observation(group_id=groupe, success=(i < k), valid_time=t, source=source))
    return obs


# --------------------------------------------------------------------------- prior
def test_prior_refuse_parametres_invalides():
    with pytest.raises(ValueError):
        BetaPrior(alpha=0.0, beta=1.0, justification="nul")
    with pytest.raises(ValueError):
        BetaPrior(alpha=-1.0, beta=1.0, justification="negatif")


def test_prior_sans_justification_est_interdit():
    """Un prior non justifie est un parametre libre deguise."""
    with pytest.raises(ValueError, match="justification"):
        BetaPrior(alpha=2.0, beta=8.0, justification="   ")


def test_prior_moyenne_et_force():
    p = BetaPrior.from_mean_strength(0.25, 40.0, justification="fixture: 25% sur 40 essais equivalents")
    assert p.mean == pytest.approx(0.25)
    assert p.strength == pytest.approx(40.0)


# --------------------------------------------------------------------------- convergence
@pytest.mark.parametrize("p_vrai", [0.07, 0.37, 0.83])
def test_convergence_vers_la_vraie_proportion(p_vrai):
    """La posterieure converge vers p_vrai et l'intervalle se resserre quand n grandit."""
    prior = BetaPrior.jeffreys()
    erreurs, largeurs = [], []
    for n in (100, 1_000, 10_000, 100_000):
        k = fixture_binomial(p_vrai, n, graine=int(p_vrai * 1000) + n)
        est = beta_binomial_proportion(k, n, prior=prior, asof=ASOF)
        erreurs.append(abs(est.mean - p_vrai))
        largeurs.append(est.width)
    # l'intervalle retrecit strictement, en ~1/sqrt(n)
    assert largeurs == sorted(largeurs, reverse=True)
    assert largeurs[-1] < largeurs[0] / 20
    # a 100k essais, l'erreur est sous 1/200
    assert erreurs[-1] < 0.005
    assert erreurs[-1] < erreurs[0]


def test_convergence_intervalle_en_racine_de_n():
    """La largeur doit suivre 1/sqrt(n) : x100 essais -> largeur divisee par ~10."""
    prior = BetaPrior.jeffreys()
    l1 = beta_binomial_proportion(fixture_binomial(0.4, 200, 1), 200, prior=prior, asof=ASOF).width
    l2 = beta_binomial_proportion(fixture_binomial(0.4, 20_000, 2), 20_000, prior=prior, asof=ASOF).width
    assert 8.0 < l1 / l2 < 12.5


# --------------------------------------------------------------------------- couverture
def test_couverture_de_l_intervalle_de_credibilite():
    """
    Calibration bayesienne : si les taux sont reellement tires du prior, un intervalle
    a 90% doit contenir le vrai taux dans ~90% des cas. Test SYNTHETIQUE, seule facon
    de mesurer une couverture (la verite terrain n'existe pas sur donnees reelles).
    """
    a_vrai, b_vrai, n_essais, repetitions = 3.0, 7.0, 40, 1500
    rng = np.random.default_rng(20260821)
    p = rng.beta(a_vrai, b_vrai, size=repetitions)
    k = rng.binomial(n_essais, p)
    prior = BetaPrior(a_vrai, b_vrai, justification="fixture: prior generateur exact")
    dedans = 0
    for i in range(repetitions):
        est = beta_binomial_proportion(int(k[i]), n_essais, prior=prior, asof=ASOF, level=0.90)
        dedans += int(est.lower <= p[i] <= est.upper)
    couverture = dedans / repetitions
    assert 0.875 <= couverture <= 0.925, f"couverture effective {couverture:.3f} pour un niveau 0.90"


def test_couverture_a_50_pourcent():
    """Un intervalle a 50% doit couvrir ~50% : la calibration doit tenir a tout niveau."""
    rng = np.random.default_rng(7)
    p = rng.beta(2.0, 5.0, size=1200)
    k = rng.binomial(60, p)
    prior = BetaPrior(2.0, 5.0, justification="fixture: prior generateur exact")
    dedans = sum(
        int(beta_binomial_proportion(int(k[i]), 60, prior=prior, asof=ASOF, level=0.50).lower
            <= p[i]
            <= beta_binomial_proportion(int(k[i]), 60, prior=prior, asof=ASOF, level=0.50).upper)
        for i in range(1200)
    )
    assert 0.45 <= dedans / 1200 <= 0.55


# --------------------------------------------------------------------------- prior dominant
def test_le_prior_domine_sur_petit_echantillon():
    """
    4 succes sur 4 essais ne font pas un wallet a 100% de reussite. Avec un prior de
    cohorte Beta(50,50), la posterieure reste collee a la cohorte : c'est exactement le
    garde-fou anti-surapprentissage exige.
    """
    prior = BetaPrior(50.0, 50.0, justification="fixture: cohorte a 50% sur 100 essais equivalents")
    est = beta_binomial_proportion(4, 4, prior=prior, asof=ASOF)
    assert est.shrinkage_to_prior > 0.95
    assert abs(est.mean - prior.mean) < abs(est.mean - 1.0)
    assert est.mean < 0.56
    # la version frequentiste, elle, affirme 100% : c'est le piege que l'on evite
    freq = wilson_proportion(4, 4, asof=ASOF, min_trials=1)
    assert freq.mean == 1.0
    assert est.mean < freq.mean


def test_le_prior_s_efface_quand_les_donnees_abondent():
    prior = BetaPrior(50.0, 50.0, justification="fixture: cohorte a 50%")
    petit = beta_binomial_proportion(8, 10, prior=prior, asof=ASOF)
    grand = beta_binomial_proportion(8_000, 10_000, prior=prior, asof=ASOF)
    assert petit.shrinkage_to_prior > grand.shrinkage_to_prior
    assert grand.shrinkage_to_prior < 0.02
    assert abs(grand.mean - 0.80) < 0.01
    assert abs(petit.mean - 0.80) > 0.20   # le petit echantillon reste tire vers 0.5


# --------------------------------------------------------------------------- refus
def test_refus_sous_la_taille_minimale():
    prior = BetaPrior.jeffreys()
    with pytest.raises(InsufficientData, match="echantillon insuffisant"):
        beta_binomial_proportion(2, 5, prior=prior, asof=ASOF, min_trials=MIN_TRIALS_DIRECT)
    with pytest.raises(InsufficientData, match="echantillon insuffisant"):
        wilson_proportion(2, 5, asof=ASOF)


def test_wilson_refuse_n_zero_au_lieu_de_rendre_zero():
    """Regle 1 : jamais 0.0 a la place d'une donnee absente."""
    with pytest.raises(InsufficientData):
        wilson_proportion(0, 0, asof=ASOF, min_trials=0)


def test_comptages_incoherents_rejetes():
    prior = BetaPrior.jeffreys()
    with pytest.raises(ValueError):
        beta_binomial_proportion(11, 10, prior=prior, asof=ASOF)
    with pytest.raises(ValueError):
        beta_binomial_proportion(-1, 10, prior=prior, asof=ASOF)
    with pytest.raises(TypeError):
        beta_binomial_proportion(1.5, 10, prior=prior, asof=ASOF)


def test_asof_naif_rejete():
    prior = BetaPrior.jeffreys()
    with pytest.raises(ValueError, match="timezone-aware"):
        beta_binomial_proportion(5, 10, prior=prior, asof=datetime(2026, 8, 21, 12, 0, 0))


# --------------------------------------------------------------------------- Wilson
def test_wilson_valeur_de_reference():
    """20/100 a 95% -> [0.1333, 0.2888], valeur tabulee de l'intervalle de score."""
    est = wilson_proportion(20, 100, asof=ASOF, level=0.95)
    assert est.mean == pytest.approx(0.20)
    assert est.lower == pytest.approx(0.1333, abs=5e-4)
    assert est.upper == pytest.approx(0.2888, abs=5e-4)


def test_wilson_contient_toujours_le_point_et_reste_borne():
    for k, n in ((0, 50), (1, 50), (25, 50), (50, 50)):
        est = wilson_proportion(k, n, asof=ASOF, min_trials=1)
        assert 0.0 <= est.lower <= est.mean <= est.upper <= 1.0
        assert est.width > 0.0   # jamais un intervalle degenere, contrairement a Wald


def test_bayesien_et_frequentiste_convergent_sur_gros_echantillon():
    """Prior non informatif + n grand : les deux ecoles doivent tomber d'accord."""
    k, n = fixture_binomial(0.42, 50_000, graine=3), 50_000
    bay = beta_binomial_proportion(k, n, prior=BetaPrior.jeffreys(), asof=ASOF, level=0.95)
    freq = wilson_proportion(k, n, asof=ASOF, level=0.95)
    assert abs(bay.mean - freq.mean) < 1e-4
    assert abs(bay.lower - freq.lower) < 2e-3
    assert abs(bay.upper - freq.upper) < 2e-3


def test_hdi_pas_plus_large_que_equi_caudal():
    prior = BetaPrior.jeffreys()
    eq = beta_binomial_proportion(3, 80, prior=prior, asof=ASOF, interval="equal_tailed")
    hdi = beta_binomial_proportion(3, 80, prior=prior, asof=ASOF, interval="hdi")
    assert hdi.width <= eq.width + 1e-9
    assert hdi.width < eq.width      # posterieure franchement asymetrique


def test_une_estimation_porte_toujours_son_intervalle():
    est = beta_binomial_proportion(30, 100, prior=BetaPrior.jeffreys(), asof=ASOF)
    assert isinstance(est, ProportionEstimate)
    assert est.lower < est.mean < est.upper
    assert est.level == 0.90 and est.trials == 100 and est.method == "beta_binomial"


# --------------------------------------------------------------------------- etancheite as-of
def test_asof_exclut_les_lignes_non_encore_connaissables():
    """
    Regle 2 : aucune ligne dont knowable_at > asof. La latence de publication de `fills`
    est de 2 s, donc un fait valide 1 s avant l'asof n'est PAS encore connaissable.
    """
    passe = Observation("w1", True, ASOF - timedelta(minutes=5), "fills")
    limite = Observation("w2", True, ASOF - timedelta(seconds=1), "fills")   # knowable a asof+1s
    futur = Observation("w3", False, ASOF + timedelta(hours=2), "fills")
    gardees, rapport = observations_asof([passe, limite, futur], asof=ASOF)
    assert [o.group_id for o in gardees] == ["w1"]
    assert rapport.n_future_dropped == 2
    assert rapport.n_kept == 1 and rapport.n_input == 3


def test_knowable_at_derive_de_la_latence_de_publication():
    o = Observation("w1", True, ASOF - timedelta(hours=1), "orders_5m")
    assert o.knowable_at == ASOF - timedelta(hours=1) + timedelta(seconds=300)


def test_observation_refuse_horloges_incoherentes():
    with pytest.raises(ValueError, match="naif"):
        Observation("w1", True, datetime(2026, 8, 21, 12, 0, 0), "fills")
    with pytest.raises(ValueError, match="publiable avant"):
        Observation("w1", True, ASOF, "fills", knowable_at=ASOF - timedelta(seconds=10))
    with pytest.raises(ValueError, match="SOURCES"):
        Observation("w1", True, ASOF, "source_inventee")


def test_pseudo_adresse_twap_exclue_des_agregations():
    obs = [
        Observation("w1", True, ASOF - timedelta(hours=1), "fills"),
        Observation(TWAP_PSEUDO_ADDRESS, True, ASOF - timedelta(hours=1), "fills"),
        Observation(TWAP_PSEUDO_ADDRESS, False, ASOF - timedelta(hours=1), "fills"),
    ]
    gardees, rapport = observations_asof(obs, asof=ASOF)
    assert rapport.n_twap_dropped == 2
    assert set(counts_by_group(gardees)) == {"w1"}
    assert len(TWAP_PSEUDO_ADDRESS) == 66   # 0x + 64 hex : pas une adresse EVM


def test_colonne_post_hoc_interdite():
    """Regle 3 : `partial` de closed_trades n'est connu qu'apres coup."""
    with pytest.raises(InsufficientData, match="post-hoc"):
        assert_not_post_hoc("closed_trades", ["realizedPnlUsd", "partial"])
    assert_not_post_hoc("closed_trades", ["realizedPnlUsd", "closeTime"])   # ne leve pas
    with pytest.raises(InsufficientData, match="source inconnue"):
        assert_not_post_hoc("inexistante", ["x"])


# --------------------------------------------------------------------------- prior de cohorte
def test_bayes_empirique_retrouve_le_prior_generateur():
    comptes, _ = fixture_cohorte(alpha=2.0, beta=8.0, n_groupes=400, essais_par_groupe=80, graine=11)
    prior = fit_cohort_prior(comptes, asof=ASOF, method="mml")
    assert prior.source == "bayes_empirique"
    assert prior.mean == pytest.approx(0.20, abs=0.02)
    assert prior.alpha == pytest.approx(2.0, rel=0.35)
    assert prior.beta == pytest.approx(8.0, rel=0.35)
    assert prior.n_groups == 400 and prior.n_trials == 32_000
    assert "survie" in prior.justification


def test_bayes_empirique_par_moments_est_du_meme_ordre():
    comptes, _ = fixture_cohorte(2.0, 8.0, 400, 80, graine=12)
    mml = fit_cohort_prior(comptes, asof=ASOF, method="mml")
    mom = fit_cohort_prior(comptes, asof=ASOF, method="moments")
    assert mom.mean == pytest.approx(mml.mean, abs=0.02)
    assert mom.strength == pytest.approx(mml.strength, rel=0.5)


def test_bayes_empirique_refuse_une_cohorte_trop_petite():
    comptes, _ = fixture_cohorte(2.0, 8.0, 5, 80, graine=13)
    with pytest.raises(InsufficientData, match="cohorte insuffisante"):
        fit_cohort_prior(comptes, asof=ASOF)


def test_bayes_empirique_refuse_une_cohorte_sans_dispersion():
    """Tous les groupes au meme taux : la dispersion inter-groupes n'est pas identifiable."""
    rng = np.random.default_rng(14)
    comptes = {f"w{i}": (int(rng.binomial(200, 0.3)), 200) for i in range(120)}
    with pytest.raises(InsufficientData, match="dispersion inter-groupes non identifiable"):
        fit_cohort_prior(comptes, asof=ASOF)


def test_bayes_empirique_refuse_une_cohorte_degeneree():
    comptes = {f"w{i}": (0, 60) for i in range(60)}
    with pytest.raises(InsufficientData, match="degeneree"):
        fit_cohort_prior(comptes, asof=ASOF)


# --------------------------------------------------------------------------- hierarchique
def test_retrecissement_hierarchique_vers_la_cohorte():
    """
    Un groupe minuscule et flatteur (5/5) est ramene vers la cohorte ; un gros groupe
    garde son taux observe. C'est la traduction operationnelle de l'anti-overfit.
    """
    comptes, _ = fixture_cohorte(2.0, 8.0, 300, 60, graine=15)
    comptes["petit_flatteur"] = (5, 5)
    comptes["gros_regulier"] = (600, 1_000)
    modele = HierarchicalProportion(min_trials_per_group=5)
    modele._counts = comptes                      # injection directe des comptages fixture
    modele._prior_fitted = fit_cohort_prior(comptes, asof=ASOF)
    modele._asof = ASOF
    petit, gros = modele.predict_proba(["petit_flatteur", "gros_regulier"], asof=ASOF)
    cohorte = modele.cohort_prior.mean
    assert petit.mean < 0.60                       # loin des 100% observes
    assert abs(petit.mean - cohorte) < abs(petit.mean - 1.0)
    assert petit.shrinkage_to_prior > gros.shrinkage_to_prior
    assert abs(gros.mean - 0.60) < 0.02            # le gros groupe garde son taux
    assert petit.width > gros.width                # l'incertitude reste visible


def test_hierarchique_bout_en_bout_sur_observations():
    comptes, _ = fixture_cohorte(3.0, 7.0, 60, 40, graine=16)
    obs = fixture_observations(comptes)
    modele = HierarchicalProportion(min_trials_per_group=5, target="fixture: succes binaire")
    modele.fit(obs, asof=ASOF)
    assert modele.asof_report.n_kept == 60 * 40
    est = modele.predict_proba(["w0000"], asof=ASOF)[0]
    assert est.group_id == "w0000" and est.trials == 40
    carte = modele.describe()
    assert isinstance(carte, ModelCard)
    assert carte.n_groups == 60 and carte.n_observations == 2_400
    assert carte.post_hoc_columns_used == ()
    assert carte.biases == KNOWN_BIASES


def test_hierarchique_refuse_sous_le_plancher_par_groupe():
    comptes, _ = fixture_cohorte(3.0, 7.0, 80, 50, graine=17)
    modele = HierarchicalProportion(min_trials_per_group=10)
    modele._counts = dict(comptes, minuscule=(1, 2))
    modele._prior_fitted = fit_cohort_prior(comptes, asof=ASOF)
    modele._asof = ASOF
    with pytest.raises(InsufficientData, match="plancher"):
        modele.predict_proba(["minuscule"], asof=ASOF)
    with pytest.raises(InsufficientData, match="plancher"):
        modele.predict_proba(["groupe_jamais_vu"], asof=ASOF)
    # sortie prior-seul possible, mais uniquement sur demande EXPLICITE
    permissif = HierarchicalProportion(min_trials_per_group=10, allow_prior_only=True)
    permissif._counts, permissif._prior_fitted, permissif._asof = (
        modele._counts, modele._prior_fitted, ASOF)
    est = permissif.predict_proba(["groupe_jamais_vu"], asof=ASOF)[0]
    assert est.trials == 0 and est.shrinkage_to_prior == 1.0
    assert est.method == "beta_binomial_prior_seul"


def test_hierarchique_refuse_la_pseudo_adresse_twap():
    comptes, _ = fixture_cohorte(3.0, 7.0, 80, 50, graine=18)
    modele = HierarchicalProportion()
    modele._counts, modele._asof = comptes, ASOF
    modele._prior_fitted = fit_cohort_prior(comptes, asof=ASOF)
    with pytest.raises(InsufficientData, match="TWAP"):
        modele.predict_proba([TWAP_PSEUDO_ADDRESS], asof=ASOF)


# --------------------------------------------------------------------------- temoin
def test_baseline_predit_le_taux_de_base_pour_toute_cle():
    comptes, _ = fixture_cohorte(2.0, 8.0, 50, 40, graine=19)
    obs = fixture_observations(comptes)
    temoin = BaselineRate(target="fixture: succes binaire").fit(obs, asof=ASOF)
    total_k = sum(k for k, _ in comptes.values())
    assert temoin.base_rate.mean == pytest.approx(total_k / 2_000, abs=0.001)
    p = temoin.predict_proba(["w0000", "w0001", "adresse_inconnue"], asof=ASOF)
    assert len({e.mean for e in p}) == 1           # aucune information par groupe
    assert [e.group_id for e in p] == ["w0000", "w0001", "adresse_inconnue"]
    assert all(e.lower < e.mean < e.upper for e in p)


def test_baseline_non_entraine_refuse_de_predire():
    temoin = BaselineRate()
    with pytest.raises(InsufficientData, match="non entraine"):
        temoin.predict_proba(["w1"], asof=ASOF)
    with pytest.raises(InsufficientData, match="non entraine"):
        _ = temoin.base_rate


def test_baseline_refuse_un_ajustement_sans_donnee_connaissable():
    futur = [Observation("w1", True, ASOF + timedelta(days=1), "fills")]
    with pytest.raises(InsufficientData, match="aucune observation connaissable"):
        BaselineRate().fit(futur, asof=ASOF)


def test_prediction_dans_le_passe_du_modele_refusee():
    comptes, _ = fixture_cohorte(2.0, 8.0, 50, 40, graine=20)
    temoin = BaselineRate().fit(fixture_observations(comptes), asof=ASOF)
    with pytest.raises(InsufficientData, match="fuite"):
        temoin.predict_proba(["w0000"], asof=ASOF - timedelta(days=1))


def test_les_modeles_respectent_le_protocole():
    assert isinstance(BaselineRate(), ProbabilityModel)
    assert isinstance(HierarchicalProportion(), ProbabilityModel)


def test_carte_de_modele_porte_les_biais_connus():
    carte = BaselineRate().describe()
    assert carte.trained_asof is None and carte.kind == "temoin"
    assert any("survie" in b for b in carte.biases)
    assert any("2026-09-02" in b for b in carte.biases)
    assert any("TWAP" in b for b in carte.biases)


# --------------------------------------------------------------------------- scores
def test_scores_refusent_un_echantillon_vide():
    with pytest.raises(InsufficientData):
        brier_score([], [])
    with pytest.raises(InsufficientData):
        log_score([], [])


def test_log_score_refuse_une_certitude_absolue():
    with pytest.raises(ValueError, match="log-perte infinie"):
        log_score([1.0, 0.5], [True, False])


def test_brier_de_reference():
    assert brier_score([0.5, 0.5], [True, False]) == pytest.approx(0.25)
    assert brier_score([1.0, 0.0], [True, False]) == pytest.approx(0.0)


def test_le_modele_hierarchique_bat_le_temoin_quand_les_groupes_different():
    """
    Sur une cohorte SYNTHETIQUE ou les groupes ont reellement des taux differents, le
    modele hierarchique doit battre le taux de base. Le test verifie surtout que la
    machinerie de comparaison rend un verdict exploitable.
    """
    rng = np.random.default_rng(21)
    n_groupes, n_train, n_test = 200, 60, 40
    p = rng.beta(2.0, 6.0, size=n_groupes)
    noms = [f"w{i:04d}" for i in range(n_groupes)]
    comptes_train = {noms[i]: (int(rng.binomial(n_train, p[i])), n_train) for i in range(n_groupes)}

    modele = HierarchicalProportion(min_trials_per_group=5)
    modele._counts, modele._asof = comptes_train, ASOF
    modele._prior_fitted = fit_cohort_prior(comptes_train, asof=ASOF)

    temoin = BaselineRate(min_trials=MIN_TRIALS_DIRECT)
    temoin._estimate = beta_binomial_proportion(
        sum(k for k, _ in comptes_train.values()), n_groupes * n_train,
        prior=BetaPrior.jeffreys(), asof=ASOF,
    )
    temoin._asof, temoin._n_groups = ASOF, n_groupes

    issues, p_modele, p_temoin = [], [], []
    pred_m = {e.group_id: e.mean for e in modele.predict_proba(noms, asof=ASOF)}
    pred_t = {e.group_id: e.mean for e in temoin.predict_proba(noms, asof=ASOF)}
    for i, nom in enumerate(noms):
        for y in rng.binomial(1, p[i], size=n_test):
            issues.append(bool(y))
            p_modele.append(pred_m[nom])
            p_temoin.append(pred_t[nom])

    fiche = compare_to_baseline(p_modele, p_temoin, issues)
    assert fiche.n == n_groupes * n_test
    assert fiche.beats_baseline
    assert fiche.brier_skill > 0.05


def test_un_modele_identique_au_temoin_ne_le_bat_pas():
    """Garde-fou du garde-fou : skill nul quand le modele ne fait que recopier le temoin."""
    rng = np.random.default_rng(22)
    issues = [bool(y) for y in rng.binomial(1, 0.3, size=500)]
    p = [0.3] * 500
    fiche = compare_to_baseline(p, p, issues)
    assert fiche.brier_skill == pytest.approx(0.0)
    assert not fiche.beats_baseline


def test_compare_refuse_un_temoin_parfait():
    with pytest.raises(InsufficientData, match="Brier nul"):
        compare_to_baseline([0.9, 0.1], [1.0, 0.0], [True, False])


# --------------------------------------------------------------------------- coherence globale
def test_aucune_valeur_par_defaut_ne_remplace_une_donnee_absente():
    """
    Balayage des points d'entree : chacun doit lever plutot que rendre un chiffre.
    C'est la regle 1 du contrat, testee explicitement.
    """
    cas = [
        lambda: wilson_proportion(0, 0, asof=ASOF, min_trials=0),
        lambda: beta_binomial_proportion(0, 0, prior=BetaPrior.jeffreys(), asof=ASOF, min_trials=1),
        lambda: fit_cohort_prior({}, asof=ASOF),
        lambda: BaselineRate().fit([], asof=ASOF),
        lambda: HierarchicalProportion().fit([], asof=ASOF),
        lambda: brier_score([], []),
    ]
    for appel in cas:
        with pytest.raises(InsufficientData):
            appel()


def test_repr_lisible_d_une_estimation():
    est = beta_binomial_proportion(30, 100, prior=BetaPrior.jeffreys(), asof=ASOF)
    texte = str(est)
    assert "k=30/n=100" in texte and "beta_binomial" in texte and "90%" in texte
    assert not math.isnan(est.mean)
