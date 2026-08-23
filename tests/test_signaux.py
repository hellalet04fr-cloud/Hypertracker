"""
Tests du moteur de signal (ht/signal.py). Aucun reseau, entierement deterministe.

Tous les comptages sont FABRIQUES. Aucune sortie ne decrit un marche reel : aucune
issue binaire etiquetee n'a encore ete collectee (closed_trades jamais observe).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import InsufficientData  # noqa: E402
import ht.signaux as S  # noqa: E402

ASOF = datetime(2026, 7, 1, tzinfo=timezone.utc)
ECE_OK = 0.02


# =========================================================================== refus
def test_echantillon_insuffisant_refuse():
    s = S.evaluer(ASOF, 40, 50, ece=ECE_OK)
    assert s.direction == S.NO_TRADE
    assert s.probability is None and s.confidence is None
    assert any("echantillon insuffisant" in r for r in s.refus)


def test_calibration_non_mesuree_refuse():
    """Exigence : ne jamais presenter la probabilite comme une certitude. Sans ECE
    mesuree hors echantillon, aucun pourcentage n'est publie."""
    s = S.evaluer(ASOF, 700, 1000, ece=None)
    assert s.direction == S.NO_TRADE
    assert s.probability is None
    assert any("calibration non mesuree" in r for r in s.refus)


def test_calibration_trop_mauvaise_refuse():
    s = S.evaluer(ASOF, 700, 1000, ece=0.25)
    assert s.direction == S.NO_TRADE
    assert any("calibration insuffisante" in r for r in s.refus)


def test_intervalle_englobant_le_seuil_refuse():
    """Un edge non distinguable de zero n'est pas un edge, meme si le point est > 0,5."""
    s = S.evaluer(ASOF, 102, 200, ece=ECE_OK)
    assert s.direction == S.NO_TRADE
    assert s.interval is not None
    assert s.interval[0] <= 0.50 <= s.interval[1]
    assert any("englobe le seuil" in r for r in s.refus)


def test_marge_insuffisante_refuse():
    """Significatif mais economiquement inexploitable : l'IC est entierement au-dessus
    de 0,50 sans jamais depasser 0,50 + marge."""
    s = S.evaluer(ASOF, 5150, 10000, ece=ECE_OK, marge=0.05)
    assert s.direction == S.NO_TRADE
    assert any("marge insuffisante" in r or "englobe le seuil" in r for r in s.refus)


# =========================================================================== emission
def test_long_emis_sur_edge_franc():
    s = S.evaluer(ASOF, 700, 1000, ece=ECE_OK)
    assert s.direction == S.LONG
    assert s.actionable
    assert 60.0 < s.probability < 75.0
    assert 0.0 < s.confidence <= 100.0
    assert s.sample_size == 1000
    assert s.interval[0] > 0.50


def test_short_emis_sur_edge_inverse():
    s = S.evaluer(ASOF, 300, 1000, ece=ECE_OK)
    assert s.direction == S.SHORT
    assert 25.0 < s.probability < 40.0
    assert s.interval[1] < 0.50


def test_signal_porte_raisons_et_invalidation():
    s = S.evaluer(ASOF, 700, 1000, ece=ECE_OK)
    assert s.reasons and s.invalidation
    assert any("issues favorables observees" in r for r in s.reasons)
    assert any("ECE" in i for i in s.invalidation)
    assert any("echantillon retombe" in i for i in s.invalidation)


def test_decision_sur_la_borne_pas_sur_le_point():
    """55 % sur 200 tirages : le point depasse le seuil+marge, mais la borne basse non.
    Le moteur doit refuser — c'est tout l'interet de decider sur l'intervalle."""
    s = S.evaluer(ASOF, 110, 200, ece=ECE_OK)
    assert s.interval[0] < 0.53
    assert s.direction == S.NO_TRADE


# =========================================================================== confiance
def test_confiance_croit_avec_l_echantillon():
    petit = S.evaluer(ASOF, 140, 200, ece=ECE_OK)
    gros = S.evaluer(ASOF, 7000, 10000, ece=ECE_OK)
    assert petit.actionable and gros.actionable
    assert gros.confidence > petit.confidence


def test_confiance_decroit_quand_la_calibration_se_degrade():
    bonne = S.evaluer(ASOF, 700, 1000, ece=0.01)
    mediocre = S.evaluer(ASOF, 700, 1000, ece=0.09)
    assert bonne.confidence > mediocre.confidence


def test_confiance_effondree_par_un_seul_facteur():
    """Le produit, pas la moyenne : une calibration au bord du seuil doit ecraser la
    confiance meme avec un enorme echantillon."""
    s = S.evaluer(ASOF, 70000, 100000, ece=0.099)
    assert s.actionable
    assert s.confidence < 5.0


def test_confiance_bornee():
    for succ, tot in ((700, 1000), (9000, 10000), (140, 200)):
        s = S.evaluer(ASOF, succ, tot, ece=0.001)
        if s.actionable:
            assert 0.0 <= s.confidence <= 100.0


# =========================================================================== divers
def test_comptages_incoherents_levent():
    with pytest.raises(InsufficientData):
        S.evaluer(ASOF, 10, 5, ece=ECE_OK)
    with pytest.raises(InsufficientData):
        S.evaluer(ASOF, -1, 100, ece=ECE_OK)


def test_deterministe():
    a = S.evaluer(ASOF, 700, 1000, ece=ECE_OK)
    b = S.evaluer(ASOF, 700, 1000, ece=ECE_OK)
    assert (a.direction, a.probability, a.confidence, a.interval) == \
           (b.direction, b.probability, b.confidence, b.interval)


def test_resume_lisible_dans_les_deux_cas():
    assert "NO TRADE" in S.evaluer(ASOF, 40, 50, ece=ECE_OK).resume()
    r = S.evaluer(ASOF, 700, 1000, ece=ECE_OK).resume()
    assert "LONG" in r and "confiance=" in r and "invalide si" in r


def test_depuis_issues_compte_les_pnl_positifs():
    trades = [{"realizedPnlUsd": 1.0}] * 700 + [{"realizedPnlUsd": -1.0}] * 300
    s = S.depuis_issues(ASOF, trades, ece=ECE_OK)
    assert s.direction == S.LONG
    assert s.sample_size == 1000


def test_depuis_issues_refuse_champ_manquant():
    """Compter sur des issues incompletes fausserait la proportion : on leve."""
    trades = [{"realizedPnlUsd": 1.0}] * 99 + [{"autre": 3}]
    with pytest.raises(InsufficientData) as e:
        S.depuis_issues(ASOF, trades, ece=ECE_OK)
    assert "exploitable" in str(e.value)
