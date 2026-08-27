"""
Tests du cadre walk-forward (ht.validation).

Deux familles, jamais mélangées :
  - `fixture_*` : calendriers SYNTHETIQUES, construits pour vérifier la géométrie.
    Aucune sortie de ces tests n'est un résultat de marché.
  - `test_snapshots_reels_*` : lit les vrais Parquet orders_5m s'ils sont présents,
    sinon skip. Ne mesure que la couverture temporelle réelle, jamais une performance.

Aucun test n'a besoin du réseau.
"""

from __future__ import annotations

# Cycle LOURD : ce fichier travaille sur le lac de donnees reel et depasse
# la minute. Il est exclu du cycle rapide par pytest.ini ; lancer avec
# `pytest -m lent` pour l'executer.
import pytest
pytestmark = pytest.mark.lent


import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ht.schema import InsufficientData
from ht.validation import (
    Coverage,
    Fold,
    LeakageError,
    STRUCTURAL_BREAKS,
    ValidationConfigError,
    WalkForwardPlan,
    assert_capture_covers,
    assert_no_crossing,
    assert_no_future,
    assert_no_leakage,
    assert_not_post_hoc,
    calendrier_epoch_ms,
    check_purge_covers,
    folds_crossing,
    latest_usable_valid_time,
    pit_mask,
    publication_lag,
    walk_forward,
)

J = timedelta(days=1)
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def d(n: int) -> datetime:
    """Date n du calendrier synthétique de référence (pas quotidien depuis T0)."""
    return T0 + n * J


def fixture_calendrier_quotidien(n: int = 100) -> list[datetime]:
    """Calendrier SYNTHETIQUE : n dates quotidiennes d0..d(n-1). Pas une donnée de marché."""
    return [d(i) for i in range(n)]


def fixture_pli_valide(**surcharges) -> Fold:
    base = dict(index=0, train_start=d(0), train_end=d(30), test_start=d(31), test_end=d(41),
                purge=J, embargo=J)
    base.update(surcharges)
    return Fold(**base)


# --------------------------------------------------------------------------- géométrie exacte
def test_nombre_de_plis_exact_sur_calendrier_connu():
    """100 dates quotidiennes, train 30j / purge 1j / test 10j / pas 10j.
    test_end(i) = d(41 + 10i) <= d(99)  =>  i in 0..5  =>  exactement 6 plis."""
    plan = walk_forward(fixture_calendrier_quotidien(100),
                        train_window=30 * J, test_window=10 * J, step=10 * J,
                        purge=J, embargo=J)
    assert isinstance(plan, WalkForwardPlan)
    assert len(plan) == 6
    assert plan.coverage.n_slots == 6
    assert [f.index for f in plan] == [0, 1, 2, 3, 4, 5]

    p0 = plan[0]
    assert (p0.train_start, p0.train_end) == (d(0), d(30))
    assert (p0.test_start, p0.test_end) == (d(31), d(41))
    assert p0.train_asof == d(30) and p0.test_asof == d(41)
    assert p0.n_train == 30 and p0.n_test == 10

    p5 = plan[5]
    assert (p5.train_start, p5.train_end) == (d(50), d(80))
    assert (p5.test_start, p5.test_end) == (d(81), d(91))
    assert p5.test_end <= d(99)


def test_couverture_reelle_rapportee():
    plan = walk_forward(fixture_calendrier_quotidien(100),
                        train_window=30 * J, test_window=10 * J, step=10 * J,
                        purge=J, embargo=J)
    cov = plan.coverage
    assert isinstance(cov, Coverage)
    assert cov.n_dates == 100
    # union des tests = d31..d90 => 60 dates.
    # union des trains = d0..d79 (80 dates) MOINS les dates sous embargo d'un pli
    # antérieur, retirées de tous les trains ultérieurs : d41, d51, d61, d71 => 76.
    assert cov.dates_in_test == 60
    assert cov.dates_in_train == 76
    embargees = {d(41), d(51), d(61), d(71)}
    assert not any(f.in_train(t) for f in plan for t in embargees)
    assert cov.tested_span == 60 * J
    # jamais utilisées : d91..d99
    assert cov.dates_unused == 9
    assert cov.unused_tail == 8 * J
    assert cov.fraction_tested == pytest.approx(0.60)
    assert cov.overlapping_tests is False
    assert "plis" in cov.rapport()


def test_plis_ancres_fenetre_expansive():
    plan = walk_forward(fixture_calendrier_quotidien(100),
                        train_window=30 * J, test_window=10 * J, step=10 * J,
                        purge=J, embargo=J, anchored=True)
    assert len(plan) == 6
    assert all(f.train_start == d(0) for f in plan)
    assert [f.train_end for f in plan] == [d(30), d(40), d(50), d(60), d(70), d(80)]


def test_pas_de_pli_fabrique_quand_les_dates_manquent():
    """Trou de calendrier : les slots sans dates réelles sont écartés, pas remplis."""
    dates = [d(i) for i in range(0, 40)] + [d(i) for i in range(60, 100)]
    plan = walk_forward(dates, train_window=30 * J, test_window=10 * J, step=10 * J,
                        purge=J, embargo=J)
    assert len(plan) < plan.coverage.n_slots
    assert plan.coverage.dropped, "les slots vides doivent être rapportés, pas silencieux"
    for idx, motif in plan.coverage.dropped:
        assert "insuffisantes" in motif
    for f in plan:
        assert f.n_train is not None and f.n_train >= 1
        assert f.n_test is not None and f.n_test >= 1


# --------------------------------------------------------------------------- plis fuyants refusés
def test_pli_fuyant_test_avant_train_refuse():
    with pytest.raises(LeakageError, match="PRECEDE"):
        Fold(index=0, train_start=d(10), train_end=d(20),
             test_start=d(0), test_end=d(5), purge=J, embargo=J)


def test_pli_fuyant_chevauchement_sans_purge_refuse():
    with pytest.raises(LeakageError, match="[Cc]hevauchement"):
        Fold(index=0, train_start=d(0), train_end=d(30),
             test_start=d(20), test_end=d(40), purge=J, embargo=J)


def test_pli_fuyant_purge_nulle_refusee():
    with pytest.raises(LeakageError, match="strictement positif"):
        fixture_pli_valide(purge=timedelta(0))


def test_pli_fuyant_embargo_nul_refuse():
    with pytest.raises(LeakageError, match="strictement positif"):
        fixture_pli_valide(embargo=timedelta(0))


def test_pli_fuyant_ecart_inferieur_a_la_purge_refuse():
    """Train et test collés : l'étiquette ouverte à la frontière recouvre le test."""
    with pytest.raises(LeakageError, match="écart train/test"):
        Fold(index=0, train_start=d(0), train_end=d(10),
             test_start=d(10), test_end=d(12), purge=J, embargo=J)


def test_pli_fuyant_train_vide_refuse():
    with pytest.raises(ValidationConfigError, match="vide ou inversée"):
        Fold(index=0, train_start=d(10), train_end=d(10),
             test_start=d(20), test_end=d(25), purge=J, embargo=J)


def test_walk_forward_refuse_purge_nulle():
    with pytest.raises(LeakageError, match="strictement positif"):
        walk_forward(fixture_calendrier_quotidien(100), 30 * J, 10 * J, 10 * J,
                     purge=timedelta(0), embargo=J)


def test_walk_forward_refuse_embargo_nul():
    with pytest.raises(LeakageError, match="strictement positif"):
        walk_forward(fixture_calendrier_quotidien(100), 30 * J, 10 * J, 10 * J,
                     purge=J, embargo=timedelta(0))


def test_walk_forward_refuse_dates_naives():
    naives = [datetime(2026, 1, 1) + i * J for i in range(100)]
    with pytest.raises(ValidationConfigError, match="timezone-aware"):
        walk_forward(naives, 30 * J, 10 * J, 10 * J, purge=J, embargo=J)


def test_walk_forward_refuse_tests_chevauchants_par_defaut():
    with pytest.raises(ValidationConfigError, match="chevauchent"):
        walk_forward(fixture_calendrier_quotidien(200), 30 * J, 20 * J, 5 * J,
                     purge=J, embargo=J)
    plan = walk_forward(fixture_calendrier_quotidien(200), 30 * J, 20 * J, 5 * J,
                        purge=J, embargo=J, allow_overlapping_tests=True)
    assert plan.coverage.overlapping_tests is True


def test_walk_forward_refuse_origine_posterieure_au_calendrier():
    with pytest.raises(ValidationConfigError, match="postérieure"):
        walk_forward(fixture_calendrier_quotidien(100), 30 * J, 10 * J, 10 * J,
                     purge=J, embargo=J, origin=d(200))


# --------------------------------------------------------------------------- embargo
def test_embargo_exclu_de_l_entrainement_des_plis_suivants():
    """Pli 0 : test [d11,d13), embargo [d13,d16). Pli 2 s'entraîne sur [d4,d14)
    et doit donc exclure [d13,d14)."""
    plan = walk_forward(fixture_calendrier_quotidien(40),
                        train_window=10 * J, test_window=2 * J, step=2 * J,
                        purge=J, embargo=3 * J)
    p0, p2 = plan[0], plan[2]
    assert p0.embargo_interval == (d(13), d(16))
    assert (p2.train_start, p2.train_end) == (d(4), d(14))
    assert p2.excluded == ((d(13), d(14)),)
    assert p2.in_train(d(12)) is True
    assert p2.in_train(d(13)) is False, "date sous embargo réinjectée dans le train"
    assert d(13) not in [d(i) for i in p2.select([d(i) for i in range(40)], "train")]


def test_assert_no_leakage_detecte_un_embargo_ignore():
    """Deux plis construits à la main : le second s'entraîne dans l'embargo du premier."""
    p0 = Fold(index=0, train_start=d(0), train_end=d(10), test_start=d(11), test_end=d(13),
              purge=J, embargo=3 * J)
    p1 = Fold(index=1, train_start=d(4), train_end=d(14), test_start=d(15), test_end=d(17),
              purge=J, embargo=3 * J)          # aucune exclusion : fuite
    with pytest.raises(LeakageError, match="empiète sur l'embargo"):
        assert_no_leakage([p0, p1])


def test_plan_genere_passe_la_verification_independante():
    plan = walk_forward(fixture_calendrier_quotidien(120), 30 * J, 10 * J, 10 * J,
                        purge=2 * J, embargo=3 * J)
    assert_no_leakage(plan)
    for f in plan:
        assert f.train_end + f.purge <= f.test_start
        assert f.train_end < f.test_start < f.test_end
        assert not any(f.in_train(t) and f.in_test(t) for t in fixture_calendrier_quotidien(120))


# --------------------------------------------------------------------------- couverture insuffisante
def test_moins_de_trois_plis_leve_insufficient_data_avec_le_compte():
    """55 dates : un seul pli possible. Le message doit dire combien, pas retourner []."""
    with pytest.raises(InsufficientData) as exc:
        walk_forward(fixture_calendrier_quotidien(55), 30 * J, 10 * J, 10 * J,
                     purge=J, embargo=J)
    msg = str(exc.value)
    m = re.search(r"(\d+) pli\(s\) exploitable\(s\)", msg)
    assert m is not None, msg
    assert int(m.group(1)) == 2       # test_end(i)=d(41+10i) <= d(54) -> i in {0,1}
    assert "Il manque" in msg
    assert "10 days" in msg           # (min_folds-1)*step - marge restante


def test_calendrier_vide_refuse():
    with pytest.raises(InsufficientData, match="calendrier vide"):
        walk_forward([], 30 * J, 10 * J, 10 * J, purge=J, embargo=J)


def test_min_folds_configurable_mais_jamais_contourne():
    plan = walk_forward(fixture_calendrier_quotidien(55), 30 * J, 10 * J, 10 * J,
                        purge=J, embargo=J, min_folds=2)
    assert len(plan) == 2


# --------------------------------------------------------------------------- purge / étiquettes
def test_purge_doit_couvrir_la_detention_maximale():
    check_purge_covers(2 * J, timedelta(hours=36))
    with pytest.raises(LeakageError, match="détention maximale"):
        check_purge_covers(timedelta(hours=6), timedelta(hours=36))


# --------------------------------------------------------------------------- point-in-time
def test_latence_de_publication_depuis_le_schema():
    assert publication_lag("orders_5m") == timedelta(seconds=300)
    assert publication_lag("fills") == timedelta(seconds=2)
    assert publication_lag("orders_5m", publication_lag_s=30) == timedelta(seconds=30)
    with pytest.raises(InsufficientData, match="source inconnue"):
        publication_lag("inexistante")


def test_borne_point_in_time_en_retard_sur_asof():
    asof = d(30)
    assert latest_usable_valid_time("orders_5m", asof) == asof - timedelta(seconds=300)
    vts = [asof - timedelta(seconds=600), asof - timedelta(seconds=299), asof]
    assert pit_mask("orders_5m", vts, asof) == (True, False, False)


def test_variables_du_train_bornees_par_train_asof():
    plan = walk_forward(fixture_calendrier_quotidien(100), 30 * J, 10 * J, 10 * J,
                        purge=J, embargo=J)
    p0 = plan[0]
    ok = [p0.train_asof - timedelta(seconds=1), p0.train_asof]
    p0.assert_pit(ok, "train")
    with pytest.raises(LeakageError, match="knowable_at > asof"):
        p0.assert_pit(ok + [p0.train_asof + timedelta(seconds=1)], "train")
    with pytest.raises(LeakageError):
        assert_no_future([p0.test_end + J], p0.test_asof, "test")


def test_colonnes_post_hoc_interdites():
    with pytest.raises(LeakageError, match="post-hoc"):
        assert_not_post_hoc("closed_trades", ["realizedPnlUsd", "partial"])
    assert_not_post_hoc("closed_trades", ["realizedPnlUsd", "closeTime"])


# --------------------------------------------------------------------------- biais connus
def test_rupture_structurelle_du_2026_09_02_signalee():
    rupture = STRUCTURAL_BREAKS["liquidation_px"]
    dates = [rupture - 60 * J + i * J for i in range(120)]
    plan = walk_forward(dates, 30 * J, 10 * J, 10 * J, purge=J, embargo=J)
    croisants = folds_crossing(plan, rupture)
    assert croisants, "un pli à cheval sur la rupture doit être détecté"
    with pytest.raises(ValidationConfigError, match="deux régimes"):
        assert_no_crossing(plan, rupture, "rupture des prix de liquidation")


def test_source_non_reconstituable_refuse_les_plis_anterieurs_a_la_capture():
    plan = walk_forward(fixture_calendrier_quotidien(100), 30 * J, 10 * J, 10 * J,
                        purge=J, embargo=J)
    assert_capture_covers(plan, "leaderboards", d(0))     # capture dès le début : rien à dire
    with pytest.raises(InsufficientData, match="non reconstituable"):
        assert_capture_covers(plan, "leaderboards", d(25))
    with pytest.raises(InsufficientData, match="source inconnue"):
        assert_capture_covers(plan, "inexistante", d(0))


# --------------------------------------------------------------------------- snapshots réels
RACINE_DATA = Path(os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data"))


def _snapshot_times_reels() -> list[datetime]:
    fichiers = sorted(RACINE_DATA.glob("orders_5m/dt=*/*.parquet"))
    if not fichiers:
        pytest.skip(f"aucun snapshot réel sous {RACINE_DATA / 'orders_5m'}")
    pq = pytest.importorskip("pyarrow.parquet")
    valeurs: set[int] = set()
    for f in fichiers:
        col = pq.read_table(str(f), columns=["snapshotTime"]).column("snapshotTime")
        valeurs.update(int(v.as_py()) for v in col)
    return list(calendrier_epoch_ms(valeurs))


def test_snapshots_reels_couverture_insuffisante_pour_des_plis_journaliers():
    """Donnée RÉELLE : les snapshots collectés couvrent moins d'une heure.
    Aucun walk-forward journalier n'est possible — et le module le dit."""
    cal = _snapshot_times_reels()
    assert len(cal) >= 2
    assert cal[-1] - cal[0] < timedelta(days=1), (
        "le calendrier réel a grandi : réviser ce test au lieu de le contourner")
    with pytest.raises(InsufficientData) as exc:
        walk_forward(cal, train_window=7 * J, test_window=J, step=J, purge=J, embargo=J)
    assert re.search(r"(\d+) pli\(s\) exploitable\(s\)", str(exc.value))


def test_snapshots_reels_walk_forward_a_l_echelle_des_snapshots():
    """Donnée RÉELLE, échelle 5 minutes. On ne mesure QUE la géométrie temporelle :
    aucune performance n'est calculée ici."""
    cal = _snapshot_times_reels()
    m = timedelta(minutes=1)
    try:
        plan = walk_forward(cal, train_window=10 * m, test_window=5 * m, step=5 * m,
                            purge=5 * m, embargo=5 * m)
    except InsufficientData as e:
        pytest.skip(f"snapshots réels insuffisants même à l'échelle 5 min : {e}")
    assert_no_leakage(plan)
    assert plan.coverage.n_dates == len(cal)
    assert plan.coverage.n_folds <= plan.coverage.n_slots
    for f in plan:
        dates_train = [cal[i] for i in f.select(cal, "train")]
        dates_test = [cal[i] for i in f.select(cal, "test")]
        assert dates_train and dates_test
        assert max(dates_train) < min(dates_test)
        assert f.test_start - max(dates_train) >= f.purge
        f.assert_pit([latest_usable_valid_time("orders_5m", f.train_asof)], "train")
