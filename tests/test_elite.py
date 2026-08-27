"""
Tests du protocole Elite (ht/elite.py). Aucun reseau.

Toutes les series sont des fixtures a verite connue. Aucun chiffre ici ne decrit un
wallet reel : aucun trade clos n'a encore ete collecte.
"""

from __future__ import annotations

# Cycle LOURD : ce fichier travaille sur le lac de donnees reel et depasse
# la minute. Il est exclu du cycle rapide par pytest.ini ; lancer avec
# `pytest -m lent` pour l'executer.
import pytest
pytestmark = pytest.mark.lent


import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import InsufficientData  # noqa: E402
import ht.elite as E  # noqa: E402
from tests.test_integration import fixture_univers  # noqa: E402

ASOF = datetime(2026, 7, 1, tzinfo=timezone.utc)


def fixture_gros_univers(seed=3):
    """Assez de wallets, de trades et de mois pour franchir tous les seuils."""
    return fixture_univers(n_wallets=33, n_trades=90, seed=seed)


# =========================================================================== refus
def test_refuse_sans_trades():
    with pytest.raises(InsufficientData):
        E.classer(ASOF, [])


def test_refuse_classement_definitif_sous_les_seuils():
    """Exigence explicite : aucun classement definitif avant d'avoir assez de trades."""
    trades, wallets = fixture_univers(n_wallets=6, n_trades=40)
    with pytest.raises(InsufficientData) as e:
        E.classer(ASOF, trades, wallets)
    msg = str(e.value)
    assert "refuse" in msg
    assert "wallets classables" in msg or "trades clos" in msg


def test_provisoire_marque_chaque_entree():
    trades, wallets = fixture_univers(n_wallets=6, n_trades=40)
    c = E.classer(ASOF, trades, wallets, provisoire=True)
    assert not c.definitif
    assert c.raisons_non_definitif
    assert all(not e.definitif for e in c.entrees)
    assert all(e.libelle.startswith("?") for e in c.entrees)


def test_sonde_pret_coherente_avec_classer():
    petit, w_petit = fixture_univers(n_wallets=6, n_trades=40)
    ok, raisons = E.pret(petit)
    assert not ok and raisons

    gros, w_gros = fixture_gros_univers()
    ok2, raisons2 = E.pret(gros)
    assert ok2 and raisons2 == ()
    E.classer(ASOF, gros, w_gros)          # ne doit pas lever


# =========================================================================== classement
def test_classement_definitif_au_dessus_des_seuils():
    trades, wallets = fixture_gros_univers()
    c = E.classer(ASOF, trades, wallets)
    assert c.definitif
    assert c.raisons_non_definitif == ()
    assert c.entrees
    assert all(e.definitif and not e.libelle.startswith("?") for e in c.entrees)
    assert c.n_mois_distincts >= E.MIN_TRADES_TOTAL // E.MIN_TRADES_TOTAL * 3


def test_paliers_dans_le_vocabulaire_et_tries():
    trades, wallets = fixture_gros_univers()
    c = E.classer(ASOF, trades, wallets)
    assert all(e.palier in E.PALIERS for e in c.entrees)
    scores = [e.score for e in c.entrees]
    assert scores == sorted(scores, reverse=True)


def test_metriques_exigees_presentes():
    trades, wallets = fixture_gros_univers()
    c = E.classer(ASOF, trades, wallets)
    e = c.entrees[0]
    for champ in ("win_rate", "expectancy", "max_drawdown_usd", "roi",
                  "persistance", "n_trades", "confiance"):
        assert getattr(e, champ) is not None, champ
    assert 0.0 <= e.win_rate <= 1.0
    assert e.n_trades >= E.MIN_TRADES_PAR_WALLET


def test_profit_factor_none_sans_perte():
    """Sans aucune perte, le profit factor est indefini : on rend None, jamais un
    infini qui passerait pour une performance."""
    assert E._profit_factor({"n_gains": 10, "n_pertes": 0,
                             "gain_moyen": 5.0, "perte_moyenne": 0.0}) is None
    pf = E._profit_factor({"n_gains": 10, "n_pertes": 5,
                           "gain_moyen": 4.0, "perte_moyenne": -2.0})
    assert pf == pytest.approx(40.0 / 10.0)


# =========================================================================== plafond
def test_palier_plafonne_par_la_credibilite():
    """Un score eleve sur petit echantillon ne peut pas atteindre S+."""
    assert E._plafond(0.30) == "C"
    assert E._plafond(0.60) == "A"
    assert E._plafond(0.90) == "S+"
    # le plafond gagne toujours sur le score brut
    assert E._min_palier("S+", "B") == "B"
    assert E._min_palier("C", "S") == "C"


def test_score_eleve_petit_echantillon_ne_donne_pas_s_plus():
    trades, wallets = fixture_gros_univers()
    c = E.classer(ASOF, trades, wallets)
    for e in c.entrees:
        if e.confiance < 0.85:
            assert e.palier != "S+", (e.address, e.confiance, e.score)


def test_drapeau_plafonnement_expose():
    trades, wallets = fixture_gros_univers()
    c = E.classer(ASOF, trades, wallets)
    for e in c.entrees:
        brut = E._palier_brut(e.score)
        assert e.palier_plafonne == (e.palier != brut)


# =========================================================================== divers
def test_par_palier_couvre_tout_le_vocabulaire():
    trades, wallets = fixture_gros_univers()
    d = E.classer(ASOF, trades, wallets).par_palier()
    assert set(d) == set(E.PALIERS)
    assert sum(len(v) for v in d.values()) == len(E.classer(ASOF, trades, wallets).entrees)


def test_resume_lisible():
    trades, wallets = fixture_gros_univers()
    assert "Elite DEFINITIF" in E.classer(ASOF, trades, wallets).resume()

    petit, w_petit = fixture_univers(n_wallets=6, n_trades=40)
    txt = E.classer(ASOF, petit, w_petit, provisoire=True).resume()
    assert "Elite PROVISOIRE" in txt and "manque:" in txt


def test_depuis_pipeline_refuse_si_ranking_non_ok():
    import ht.pipeline as PL
    rap = PL.run(ASOF, closed_trades=None)
    with pytest.raises(InsufficientData) as e:
        E.depuis_pipeline(rap)
    assert "ranking" in str(e.value)
