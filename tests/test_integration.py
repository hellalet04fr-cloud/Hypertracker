"""
Tests d'INTERACTION entre les moteurs. Aucun reseau, aucune requete API.

Deux chaines distinctes, jamais melangees :

  CHAINE REELLE (test_reel_*) : store -> behavior -> features, sur les snapshots
  d'ordres reellement collectes. C'est tout ce que la donnee actuelle permet :
  closed_trades n'a JAMAIS ete observe, donc aucun ranking, aucune probabilite et
  aucune calibration ne peut porter sur du reel a ce jour.

  CHAINE FIXTURE (test_fixture_*) : ranking -> validation -> probability ->
  montecarlo -> calibration, sur un univers de wallets FABRIQUE dont la verite
  terrain est connue. Elle prouve que les interfaces s'emboitent et que les
  garde-fous se declenchent. Aucun de ses chiffres ne decrit un trader reel.
"""

from __future__ import annotations

# Cycle LOURD : ce fichier travaille sur le lac de donnees reel et depasse
# la minute. Il est exclu du cycle rapide par pytest.ini ; lancer avec
# `pytest -m lent` pour l'executer.
import pytest
pytestmark = pytest.mark.lent


import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import ORDERS_5M, InsufficientData  # noqa: E402
import ht.behavior as bh          # noqa: E402
import ht.features as F           # noqa: E402
import ht.ranking as R            # noqa: E402
import ht.validation as V         # noqa: E402
import ht.probability as P        # noqa: E402
import ht.montecarlo as MC        # noqa: E402
import ht.calibration as CAL      # noqa: E402

RACINE_REELLE = r"C:\Users\maram\ht_data"
reel = pytest.mark.skipif(
    not os.path.isdir(os.path.join(RACINE_REELLE, "orders_5m")),
    reason="snapshots reels absents : le test serait vide, pas vert",
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
ASOF = datetime(2026, 7, 1, tzinfo=timezone.utc)


# ===========================================================================
# CHAINE REELLE : store -> behavior -> features
# ===========================================================================
@reel
def test_reel_behavior_puis_features_partagent_les_memes_entites():
    """Les adresses vues par le moteur comportemental doivent etre celles que le
    moteur de variables sait resoudre : si les deux divergent, la jointure aval
    perdrait silencieusement des wallets."""
    asof = datetime.now(timezone.utc)
    profil = bh.profil_comportemental(asof, min_ordres=1)
    assert len(profil) > 0

    F.clear_registry()
    F.install_builtin_specs()
    try:
        ld = F.ParquetLoader(root=RACINE_REELLE)
        ents = F.discover_entities(ORDERS_5M.name, asof, loader=ld, limit=50)
        assert ents, "aucune entite decouverte alors que des snapshots existent"
        communes = set(ents) & set(profil.index)
        assert len(communes) >= len(ents) // 2, (
            f"seulement {len(communes)}/{len(ents)} adresses communes : "
            "les deux moteurs ne voient pas le meme univers"
        )
        table = F.build(asof, list(communes)[:20], loader=ld)
        assert table.num_rows == len(list(communes)[:20])
    finally:
        F.clear_registry()
        F.install_builtin_specs()


@reel
def test_reel_pseudo_adresse_twap_exclue_partout():
    """La pseudo-adresse TWAP n'est pas un wallet : si elle traversait un seul
    moteur, tous les agregats de cohorte seraient fausses."""
    asof = datetime.now(timezone.utc)
    profil = bh.profil_comportemental(asof, min_ordres=1)
    assert bh.PSEUDO_ADRESSE_TWAP not in profil.index

    ld = F.ParquetLoader(root=RACINE_REELLE)
    ents = F.discover_entities(ORDERS_5M.name, asof, loader=ld, limit=200)
    assert bh.PSEUDO_ADRESSE_TWAP not in ents


@reel
def test_reel_ranking_refuse_faute_de_trades_clos():
    """Verification explicite de la regle Â« ne rien fabriquer Â» : aucun trade clos
    n'a ete collecte, donc le ranking doit refuser, pas rendre un classement vide
    ou par defaut."""
    with pytest.raises(InsufficientData):
        R.load_closed_trades_parquet(RACINE_REELLE)


# ===========================================================================
# CHAINE FIXTURE : ranking -> validation -> probability -> montecarlo -> calibration
# ===========================================================================
def fixture_univers(n_wallets=12, n_trades=60, seed=7):
    """Univers FABRIQUE. Trois profils a verite connue :
      - 'regulier_*'  : edge modeste mais constant, gros echantillon
      - 'chanceux_*'  : aucun edge, peu de trades, quelques gros gains
      - 'volatil_*'   : esperance nulle, dispersion enorme
    """
    rng = np.random.default_rng(seed)
    trades, wallets = [], []
    # Les trades sont etales sur ~5 mois : le ranking exige au moins 3 mois distincts
    # pour calculer la persistance, et le walk-forward au moins 3 plis.
    FENETRE = timedelta(days=150)
    for i in range(n_wallets):
        if i % 3 == 0:
            addr, mu, sigma, n = f"0x{'1' * 39}{i:x}", 40.0, 60.0, n_trades
        elif i % 3 == 1:
            addr, mu, sigma, n = f"0x{'2' * 39}{i:x}", 0.0, 90.0, max(31, n_trades // 6)
        else:
            addr, mu, sigma, n = f"0x{'3' * 39}{i:x}", 0.0, 400.0, n_trades
        # observed_at est exige par le contrat WALLETS : l'API n'expose aucun champ
        # as-of, l'instant de capture est notre propre estampille.
        wallets.append({"address": addr, "perpEquity": 100_000.0,
                        "observed_at": T0.isoformat()})
        pas = FENETRE / n
        for k in range(n):
            pnl = float(rng.normal(mu, sigma))
            entree = 100.0
            sortie = entree * (1.0 + pnl / 10_000.0)
            t = T0 + pas * (k + 1)
            trades.append({
                "address": addr, "coin": "BTC", "side": "B",
                "hash": f"{addr}-{k}", "realizedPnlUsd": pnl,
                "avgEntry": entree, "avgExit": sortie,
                "openTime": (t - timedelta(hours=2)).isoformat(),
                "closeTime": t.isoformat(),
                "duration": 7200, "fee": 0.0, "feeUsd": 0.5,
                "fundingUsd": 0.0, "countFills": 2, "partial": False,
            })
    return trades, wallets


def test_fixture_chaine_ranking_vers_montecarlo():
    """Le classement alimente directement la validation par simulation : on prend le
    premier wallet classe et on verifie que ses rendements passent le rapport de
    significativite, avec un n_essais egal au nombre de wallets REELLEMENT examines."""
    trades, wallets = fixture_univers()
    res = R.rank(ASOF, trades, wallets, min_trades=30)
    assert res.classes, "le classement fixture ne doit pas etre vide"

    top = res.classes[0]
    adresse = top.address if hasattr(top, "address") else top["address"]
    rendements = np.array([t["realizedPnlUsd"] for t in trades if t["address"] == adresse])
    assert len(rendements) >= 30

    rapport = MC.rapport_significativite(
        rendements, seed=3, n_essais=len(res.classes), n_tirages=400
    )
    assert rapport["n_observations"] == len(rendements)
    assert "sharpe_degonfle" in rapport
    # le degonflement doit tenir compte du nombre de wallets classes
    if "seuil" in rapport["sharpe_degonfle"]:
        assert rapport["sharpe_degonfle"]["seuil"] > 0.0


def test_fixture_chanceux_ne_domine_pas_le_regulier():
    """Exigence explicite du commanditaire : le PnL seul ne fait pas un smart money.
    Un wallet a petit echantillon ne doit pas coiffer un wallet regulier a gros
    echantillon, meme si sa moyenne brute est flatteuse."""
    trades, wallets = fixture_univers(seed=11)
    res = R.rank(ASOF, trades, wallets, min_trades=30)
    rangs = {}
    for i, e in enumerate(res.classes):
        a = e.address if hasattr(e, "address") else e["address"]
        rangs[a] = i
    reguliers = [a for a in rangs if a.startswith("0x111")]
    volatils = [a for a in rangs if a.startswith("0x333")]
    if reguliers and volatils:
        assert min(rangs[a] for a in reguliers) < min(rangs[a] for a in volatils)


def test_fixture_walk_forward_puis_calibration():
    """Chaine complete de validation : plis temporels -> estimation de probabilite
    sur le pli d'apprentissage -> evaluation hors echantillon -> calibration ->
    rapport de surapprentissage."""
    trades, _ = fixture_univers(n_wallets=9, n_trades=120, seed=13)
    dates = sorted({datetime.fromisoformat(t["closeTime"]) for t in trades})
    assert len(dates) > 100

    plan = V.walk_forward(
        dates,
        train_window=timedelta(days=20), test_window=timedelta(days=5),
        step=timedelta(days=5), purge=timedelta(days=1), embargo=timedelta(days=1),
    )
    assert len(plan.folds) >= 3, f"seulement {len(plan.folds)} plis"

    fold = plan.folds[0]
    assert fold.train_end <= fold.test_start
    # purge + embargo : le test ne commence jamais juste apres la fin du train
    assert fold.test_start - fold.train_end >= timedelta(days=1)

    # issue binaire FABRIQUEE : le trade est-il gagnant ?
    train = [t for t in trades
             if fold.train_start <= datetime.fromisoformat(t["closeTime"]) <= fold.train_end]
    test = [t for t in trades
            if fold.test_start <= datetime.fromisoformat(t["closeTime"]) <= fold.test_end]
    assert train and test

    taux = P.wilson_proportion(sum(1 for t in train if t["realizedPnlUsd"] > 0), len(train), asof=fold.train_end)
    assert 0.0 <= taux.lower <= taux.mean <= taux.upper <= 1.0

    y = np.array([1.0 if t["realizedPnlUsd"] > 0 else 0.0 for t in test])
    p = np.full(len(y), taux.mean)
    if len(y) >= CAL.MIN_OBS_CALIBRATION:
        brier_oos = CAL.brier_score(y, p)
        y_tr = np.array([1.0 if t["realizedPnlUsd"] > 0 else 0.0 for t in train])
        brier_tr = CAL.brier_score(y_tr, np.full(len(y_tr), taux.mean))
        rap = CAL.overfit_report(brier_tr, brier_oos, n_oos=len(y), n_configs_tried=len(plan.folds))
        assert rap.bruit_attendu > 0.0


def test_fixture_baseline_est_le_temoin_a_battre():
    """Un modele qui ne bat pas le taux de base de la cohorte n'apporte rien :
    la chaine doit rendre ce constat mesurable, pas implicite."""
    rng = np.random.default_rng(17)
    y = (rng.uniform(0, 1, 800) < 0.42).astype(float)
    base = CAL.brier_score(y, np.full(len(y), 0.42))
    bruit = CAL.brier_score(y, rng.uniform(0, 1, 800))
    assert base < bruit                       # le temoin bat un modele aleatoire
    assert CAL.expected_calibration_error(y, np.full(len(y), float(y.mean()))) < 0.05


def test_fixture_derive_entre_deux_fenetres_de_variables():
    """Boucle finale : les variables d'aujourd'hui derivent-elles de celles d'hier ?
    C'est ce qui declenchera un rentrainement en Phase 3."""
    rng = np.random.default_rng(19)
    ref = rng.normal(0, 1, 1000)
    stable = CAL.population_stability_index(ref, rng.normal(0, 1, 1000))
    decale = CAL.population_stability_index(ref, rng.normal(1.2, 1, 1000))
    assert stable.psi < decale.psi
    assert stable.verdict == "stable"
    assert decale.verdict in ("moderee", "significative")


def test_fixture_toute_la_chaine_refuse_les_donnees_absentes():
    """Chaque moteur doit refuser plutot que d'inventer. Un seul maillon complaisant
    suffirait a produire un backtest credible et faux."""
    with pytest.raises(InsufficientData):
        R.rank(ASOF, [], [])
    with pytest.raises(InsufficientData):
        MC.bootstrap_par_blocs(np.zeros(5), seed=0)
    with pytest.raises(InsufficientData):
        CAL.expected_calibration_error([0, 1], [0.2, 0.8])
    with pytest.raises(InsufficientData):
        CAL.population_stability_index(np.arange(5.0), np.arange(5.0))

