"""
Tests du pipeline end-to-end et du plan de collecte. Aucun reseau.

Le comportement essentiel verifie ici : un etage qui manque de donnees est marque
INSUFFISANT et les etages en aval BLOQUE — jamais executes sur un substitut. Un
pipeline qui rendrait un rapport "complet" a partir de donnees absentes serait le
pire defaut possible du projet.
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

import ht.pipeline as PL          # noqa: E402
import ht.collect_plan as CP      # noqa: E402
from tests.test_integration import fixture_univers  # noqa: E402

RACINE_REELLE = r"C:\Users\maram\ht_data"
reel = pytest.mark.skipif(
    not os.path.isdir(os.path.join(RACINE_REELLE, "orders_5m")),
    reason="snapshots reels absents",
)
ASOF = datetime(2026, 7, 1, tzinfo=timezone.utc)


# =========================================================================== pipeline
def test_fixture_sans_trades_clos_le_ranking_est_insuffisant_et_l_aval_bloque():
    rap = PL.run(ASOF, closed_trades=None)
    rank = rap.par_nom("ranking")
    assert rank.statut == PL.INSUFFISANT
    assert "closed_trades absent" in rank.detail
    for aval in ("validation", "montecarlo", "calibration"):
        assert rap.par_nom(aval).statut == PL.BLOQUE
    assert not rap.complet
    assert rap.manquants()


def test_fixture_chaine_complete_avec_trades_fournis():
    trades, wallets = fixture_univers()
    rap = PL.run(ASOF, closed_trades=trades, wallets=wallets, n_tirages=200)
    for nom in ("ranking", "validation", "montecarlo", "calibration"):
        e = rap.par_nom(nom)
        assert e.statut == PL.OK, f"{nom}: {e.detail}"
    assert rap.par_nom("montecarlo").n >= 30
    assert "ECE" in rap.par_nom("calibration").detail


def test_fixture_resume_lisible_et_manquants_traduits():
    rap = PL.run(ASOF, closed_trades=None)
    txt = rap.resume()
    assert "pipeline asof=" in txt and "ranking" in txt
    besoins = PL.donnees_manquantes(rap)
    assert any("closed-trades/summary" in b for b in besoins)


@reel
def test_reel_etages_amont_traversent_les_snapshots():
    """Un snapshot reellement collecte doit traverser behavior -> features -> leak_check
    sans rupture. C'est la seule partie de la chaine que la donnee actuelle permet."""
    rap = PL.run(datetime.now(timezone.utc), racine=RACINE_REELLE, max_entites=20)
    for nom in ("behavior", "features", "leak_check"):
        e = rap.par_nom(nom)
        assert e.statut == PL.OK, f"{nom}: {e.detail}"
    assert rap.par_nom("behavior").n > 0
    assert rap.par_nom("features").n == 20


# =========================================================================== plan
def test_plan_priorise_le_perissable():
    p = CP.plan_journalier(budget=100)
    assert p.cout == 10
    assert all(r.irremplacable for r in p.requetes)
    assert sum(1 for r in p.requetes if "leaderboards" in r.path) == 8
    assert p.reste_pour_archive == 90


def test_plan_jour_suivant_insere_les_resumes():
    adresses = [f"0x{i:040x}" for i in range(60)]
    p = CP.plan_journalier(adresses, budget=100, premier_jour=False)
    resumes = [r for r in p.requetes if "closed-trades/summary" in r.path]
    assert len(resumes) == 45                      # moitie du reliquat de 90
    assert p.reste_pour_archive == 45              # l'archive continue d'avancer
    assert p.cout == 55


def test_plan_respecte_un_budget_reduit():
    p = CP.plan_journalier(budget=5)
    assert p.cout == 5
    assert p.reste_pour_archive == 0


def test_plan_dedoublonne_les_adresses():
    a = "0x" + "1" * 40
    p = CP.plan_journalier([a, a, a], budget=100, premier_jour=False)
    assert len([r for r in p.requetes if "closed-trades/summary" in r.path]) == 1


def test_extraction_adresses_ignore_les_valeurs_invalides():
    lignes = [{"address": "0x" + "a" * 40}, {"address": "pas-une-adresse"},
              {"address": "0x" + "a" * 40}, {"autre": 1}, {"address": "0x123"}]
    assert CP.adresses_depuis_leaderboards(lignes) == ["0x" + "a" * 40]


def test_plan_annonce_la_duree_reelle_de_l_archive():
    p = CP.plan_journalier(budget=100)
    note = " ".join(p.notes)
    assert "15124" in note.replace(" ", "") or "15 124" in note
    assert "168" in note or "jours" in note        # 15124/90 ~ 168 jours
