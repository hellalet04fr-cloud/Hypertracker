#!/usr/bin/env python3
"""
Tests du classement multi-criteres (ht.ranking).

Toutes les donnees de ce fichier sont SYNTHETIQUES et nommees fixture_* : aucune sortie
produite ici n'est un resultat reel. Les vraies donnees closed_trades n'ont pas encore
ete collectees (quota API epuise) ; ces tests verifient la mecanique du classement, pas
la performance de wallets existants.

Aucun acces reseau, aucun acces disque hors verification d'absence.
"""
from __future__ import annotations

import calendar
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ht import ranking as R
from ht.schema import CLOSED_TRADES, InsufficientData

ASOF = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

# Base de la fenetre mensuelle : 12 mois pleins avant asof.
BASE_ANNEE, BASE_MOIS = 2025, 8


# --------------------------------------------------------------------------- outils

def _mois(offset: int) -> tuple[int, int]:
    """(annee, mois) a `offset` mois apres la base."""
    total = (BASE_ANNEE * 12 + (BASE_MOIS - 1)) + offset
    return total // 12, total % 12 + 1


def _date_dans_le_mois(offset: int, i: int) -> datetime:
    annee, mois = _mois(offset)
    dernier = calendar.monthrange(annee, mois)[1]
    jour = 1 + (i % min(27, dernier))
    heure = i % 24
    return datetime(annee, mois, jour, heure, 30, tzinfo=timezone.utc)


def _trade(address: str, idx: int, close_dt: datetime, notionnel: float,
           rendement_prix: float, prix_entree: float = 100.0,
           fee_usd: float = 0.0, funding_usd: float = 0.0) -> dict:
    """Construit une ligne closed_trades coherente.

    Le module deduit le notionnel de |realizedPnlUsd| / |(exit-entry)/entry| : on part
    donc du notionnel voulu et de la variation de prix voulue, et on en derive le PnL.
    Toutes les colonnes du schema sont presentes, y compris 'partial' (post_hoc) que le
    module ne doit jamais lire.
    """
    prix_sortie = prix_entree * (1.0 + rendement_prix)
    pnl = notionnel * rendement_prix
    ouverture = close_dt - timedelta(hours=6)
    return {
        "address": address,
        "coin": "BTC",
        "side": "long" if rendement_prix >= 0 else "short",
        "hash": f"{address}-{idx:06d}",
        "realizedPnlUsd": pnl,
        "avgEntry": prix_entree,
        "avgExit": prix_sortie,
        "openTime": int(ouverture.timestamp() * 1000),
        "closeTime": int(close_dt.timestamp() * 1000),
        "duration": 6 * 3600 * 1000,
        "fee": fee_usd,
        "feeUsd": fee_usd,
        "fundingUsd": funding_usd,
        "countFills": 2,
        "partial": False,          # colonne post_hoc : presente mais jamais lue
    }


# --------------------------------------------------------------------------- fixtures

ADDR_REGULIER = "0x" + "1" * 40
ADDR_CHANCEUX = "0x" + "2" * 40
ADDR_DRAWDOWN = "0x" + "3" * 40
ADDR_WINRATE = "0x" + "4" * 40
ADDR_PETIT = "0x" + "5" * 40
ADDR_UN_MOIS = "0x" + "6" * 40


def fixture_wallet_regulier(address: str = ADDR_REGULIER) -> list[dict]:
    """420 trades sur 12 mois, cycle +120 / +120 / -80 / +120 / -80.

    Win rate 60 %, payoff 1.5, tous les mois gagnants, drawdown minuscule,
    rendements par trade homogenes. PnL net total = +16 800 USD.
    """
    lignes, idx = [], 0
    for offset in range(12):
        for cycle in range(7):
            for pas, (notionnel, r) in enumerate(
                    [(2000.0, 0.06), (2000.0, 0.06), (2000.0, -0.04),
                     (2000.0, 0.06), (2000.0, -0.04)]):
                lignes.append(_trade(address, idx, _date_dans_le_mois(offset, cycle * 5 + pas),
                                     notionnel, r))
                idx += 1
    return lignes


def fixture_wallet_chanceux(address: str = ADDR_CHANCEUX) -> list[dict]:
    """35 trades : un coup unique a +50 000 puis 34 pertes de -500.

    PnL net total = +33 000 USD, soit PLUS que le wallet regulier. C'est exactement le
    piege que le classement doit refuser : profit concentre sur un seul trade, 5 mois
    perdants d'affilee, drawdown de 17 000, echantillon court.
    """
    lignes, idx = [], 0
    lignes.append(_trade(address, idx, _date_dans_le_mois(0, 0), 100_000.0, 0.50))
    idx += 1
    for i in range(4):
        lignes.append(_trade(address, idx, _date_dans_le_mois(0, i + 1), 50_000.0, -0.01))
        idx += 1
    for offset in range(1, 6):
        for i in range(6):
            lignes.append(_trade(address, idx, _date_dans_le_mois(offset, i), 50_000.0, -0.01))
            idx += 1
    return lignes


def fixture_wallet_gros_drawdown(address: str = ADDR_DRAWDOWN) -> list[dict]:
    """90 trades sur 9 mois : +8 000, puis -21 000, puis +15 000. PnL net = +2 000.

    Rentable au total mais avec un drawdown de 21 000 USD, soit dix fois le gain final.
    """
    lignes, idx = [], 0
    for offset in range(4):          # 40 trades gagnants
        for i in range(10):
            lignes.append(_trade(address, idx, _date_dans_le_mois(offset, i), 4000.0, 0.05))
            idx += 1
    for offset in range(4, 7):       # 30 trades perdants
        for i in range(10):
            lignes.append(_trade(address, idx, _date_dans_le_mois(offset, i), 7000.0, -0.10))
            idx += 1
    for offset in range(7, 9):       # 20 trades de rattrapage
        for i in range(10):
            lignes.append(_trade(address, idx, _date_dans_le_mois(offset, i), 7500.0, 0.10))
            idx += 1
    return lignes


def fixture_wallet_winrate_trompeur(address: str = ADDR_WINRATE) -> list[dict]:
    """100 trades sur 10 mois : 90 % de gagnants a +10, 10 % de perdants a -150.

    Win rate 0.90, payoff 0.067 : esperance negative, PnL net = -600 USD.
    Un win rate eleve sans payoff n'est pas un edge.
    """
    lignes, idx = [], 0
    for offset in range(10):
        for i in range(9):
            lignes.append(_trade(address, idx, _date_dans_le_mois(offset, i), 1000.0, 0.01))
            idx += 1
        lignes.append(_trade(address, idx, _date_dans_le_mois(offset, 9), 1500.0, -0.10))
        idx += 1
    return lignes


def fixture_wallet_petit_echantillon(address: str = ADDR_PETIT) -> list[dict]:
    """8 trades, tous gagnants, sur 4 mois. Doit rester NON classe, pas mal classe."""
    lignes, idx = [], 0
    for offset in range(4):
        for i in range(2):
            lignes.append(_trade(address, idx, _date_dans_le_mois(offset, i), 3000.0, 0.20))
            idx += 1
    return lignes


def fixture_wallet_un_seul_mois(address: str = ADDR_UN_MOIS) -> list[dict]:
    """40 trades concentres sur un seul mois : la persistance n'est pas calculable."""
    return [_trade(address, i, _date_dans_le_mois(3, i), 2000.0, 0.03 if i % 2 else -0.02)
            for i in range(40)]


def fixture_wallet_twap() -> list[dict]:
    """Trades attribues a la pseudo-adresse TWAP (64 hex) : a exclure integralement."""
    return [_trade(R.TWAP_PSEUDO_ADDRESS, i, _date_dans_le_mois(i % 6, i), 10_000.0, 0.30)
            for i in range(50)]


def fixture_cohorte() -> list[dict]:
    """La cohorte de reference complete."""
    return (fixture_wallet_regulier() + fixture_wallet_chanceux()
            + fixture_wallet_gros_drawdown() + fixture_wallet_winrate_trompeur()
            + fixture_wallet_petit_echantillon() + fixture_wallet_un_seul_mois())


@pytest.fixture(scope="module")
def resultat():
    return R.rank(asof=ASOF, closed_trades=fixture_cohorte())


# --------------------------------------------------------------------------- coherence

def test_poids_par_defaut_somment_a_un():
    R.check_weights(R.DEFAULT_WEIGHTS)
    assert set(R.DEFAULT_WEIGHTS) == set(R.DIMENSIONS)
    assert abs(sum(R.DEFAULT_WEIGHTS.values()) - 1.0) < 1e-12


def test_poids_invalides_refuses():
    with pytest.raises(InsufficientData):
        R.check_weights({d: 0.5 for d in R.DIMENSIONS})
    with pytest.raises(InsufficientData):
        R.check_weights({"performance": 1.0})


def test_aucune_colonne_post_hoc_requise():
    assert CLOSED_TRADES.post_hoc == frozenset({"partial"})
    assert "partial" not in R.REQUIRED_TRADE_COLUMNS
    with pytest.raises(InsufficientData):
        R._forbid_post_hoc(["realizedPnlUsd", "partial"])


def test_colonne_post_hoc_absente_ne_change_rien():
    """Supprimer 'partial' de toutes les lignes doit laisser le classement identique."""
    lignes = fixture_cohorte()
    sans = [{k: v for k, v in t.items() if k != "partial"} for t in lignes]
    a = R.rank(asof=ASOF, closed_trades=lignes)
    b = R.rank(asof=ASOF, closed_trades=sans)
    assert [w.address for w in a.classes] == [w.address for w in b.classes]
    for wa, wb in zip(a.classes, b.classes):
        assert wa.score == pytest.approx(wb.score)


def test_colonne_obligatoire_manquante_leve():
    lignes = fixture_wallet_regulier()
    for t in lignes:
        del t["fundingUsd"]
    with pytest.raises(InsufficientData) as e:
        R.rank(asof=ASOF, closed_trades=lignes)
    assert "fundingUsd" in str(e.value)


def test_aucune_donnee_leve_insufficient_data():
    with pytest.raises(InsufficientData) as e:
        R.rank(asof=ASOF, closed_trades=[])
    assert "aucun trade clos" in str(e.value)


def test_aucun_wallet_eligible_leve():
    """Uniquement des petits echantillons : pas de cohorte, donc pas de score fabrique."""
    with pytest.raises(InsufficientData) as e:
        R.rank(asof=ASOF, closed_trades=fixture_wallet_petit_echantillon())
    assert "aucun wallet eligible" in str(e.value)


# --------------------------------------------------------------------------- anti-overfit

def test_le_chanceux_ne_bat_pas_le_regulier(resultat):
    """Le coeur de l'exigence : le PnL le plus eleve ne gagne pas le classement."""
    reg = resultat.par_adresse(ADDR_REGULIER)
    chanceux = resultat.par_adresse(ADDR_CHANCEUX)
    # Le chanceux a un PnL net STRICTEMENT superieur...
    assert chanceux.metriques["pnl_net_total"] > reg.metriques["pnl_net_total"]
    # ... et un score strictement inferieur.
    assert reg.score > chanceux.score
    assert resultat.classes[0].address == ADDR_REGULIER


def test_profit_concentre_sanctionne_par_la_stabilite(resultat):
    chanceux = resultat.par_adresse(ADDR_CHANCEUX)
    assert chanceux.metriques["part_meilleur_trade"] == pytest.approx(1.0)
    reg = resultat.par_adresse(ADDR_REGULIER)
    assert reg.scores_bruts["stabilite"] > chanceux.scores_bruts["stabilite"]


def test_win_rate_eleve_mais_payoff_faible_est_dernier(resultat):
    w = resultat.par_adresse(ADDR_WINRATE)
    assert w.metriques["win_rate"] == pytest.approx(0.90)
    assert w.metriques["payoff_ratio"] < 0.10
    assert w.metriques["esperance_R"] < 0.0
    assert w.metriques["pnl_net_total"] < 0.0
    reg = resultat.par_adresse(ADDR_REGULIER)
    assert reg.score > w.score
    assert resultat.classes[-1].address == ADDR_WINRATE


def test_gros_drawdown_penalise(resultat):
    dd = resultat.par_adresse(ADDR_DRAWDOWN)
    assert dd.metriques["max_drawdown_usd"] == pytest.approx(21_000.0)
    assert dd.metriques["pnl_net_total"] == pytest.approx(2_000.0)
    assert dd.metriques["ratio_pnl_maxdd"] < 0.15
    reg = resultat.par_adresse(ADDR_REGULIER)
    assert reg.scores_bruts["drawdown"] > dd.scores_bruts["drawdown"]
    assert reg.score > dd.score


def test_petit_echantillon_non_classe_pas_mal_classe(resultat):
    w = resultat.par_adresse(ADDR_PETIT)
    assert w.statut == R.STATUS_INSUFFICIENT_SAMPLE
    assert w.score is None
    assert w.n_trades == 8
    assert ADDR_PETIT not in [c.address for c in resultat.classes]
    assert "echantillon" in w.criteres_manquants


def test_dimension_manquante_bloque_le_score(resultat):
    w = resultat.par_adresse(ADDR_UN_MOIS)
    assert w.statut == R.STATUS_MISSING_DIMENSION
    assert w.score is None
    assert w.criteres_manquants == ["persistance"]
    assert "performance" in w.criteres_calcules
    assert "mois distincts" in w.detail


def test_chaque_wallet_classe_porte_ses_six_criteres(resultat):
    for w in resultat.classes:
        assert w.statut == R.STATUS_RANKED
        assert sorted(w.criteres_calcules) == sorted(R.DIMENSIONS)
        assert w.criteres_manquants == []
        assert set(w.scores_dimensions) == set(R.DIMENSIONS)
        assert all(0.0 <= v <= 1.0 for v in w.scores_dimensions.values())
        assert 0.0 <= w.score <= 1.0


def test_persistance_mesuree(resultat):
    reg = resultat.par_adresse(ADDR_REGULIER)
    assert reg.metriques["n_periodes"] == 12
    assert reg.metriques["ratio_mois_gagnants"] == pytest.approx(1.0)
    assert reg.metriques["plus_longue_serie_perdante"] == 0
    chanceux = resultat.par_adresse(ADDR_CHANCEUX)
    assert chanceux.metriques["ratio_mois_gagnants"] == pytest.approx(1.0 / 6.0)
    assert chanceux.metriques["plus_longue_serie_perdante"] == 5


def test_performance_est_un_rendement_pas_un_pnl_brut(resultat):
    """Le chanceux gagne plus en dollars mais deploie 9 fois plus de capital."""
    reg = resultat.par_adresse(ADDR_REGULIER)
    chanceux = resultat.par_adresse(ADDR_CHANCEUX)
    assert reg.metriques["capital_engage"] == pytest.approx(420 * 2000.0)
    assert chanceux.metriques["capital_engage"] == pytest.approx(100_000.0 + 34 * 50_000.0)
    assert reg.metriques["rendement_sur_capital_engage"] == pytest.approx(16_800.0 / 840_000.0)
    # Les frais et le funding entrent bien dans le PnL net.
    assert reg.metriques["pnl_net_total"] == pytest.approx(
        reg.metriques["pnl_brut_total"] + reg.metriques["funding_total"]
        - reg.metriques["frais_total"])


def test_frais_et_funding_reduisent_le_pnl_net():
    lignes = [_trade("0x" + "7" * 40, i, _date_dans_le_mois(i % 4, i), 2000.0, 0.05,
                     fee_usd=12.0, funding_usd=-3.0) for i in range(40)]
    trades, _ = R.prepare_trades(lignes, ASOF)
    m, manquants = R.compute_metrics(trades["0x" + "7" * 40])
    assert manquants == {}
    assert m["pnl_brut_total"] == pytest.approx(40 * 100.0)
    assert m["pnl_net_total"] == pytest.approx(40 * (100.0 - 3.0 - 12.0))


# --------------------------------------------------------------------------- shrinkage

def test_formule_de_shrinkage():
    # w = n/(n+K) : 8 trades ne pesent que 8/48 de leur propre statistique.
    assert R.shrink(1.0, 8, 0.0, 40.0) == pytest.approx(8.0 / 48.0)
    assert R.shrink(1.0, 400, 0.0, 40.0) == pytest.approx(400.0 / 440.0)
    # Ancrage neutre : si la valeur egale l'ancre, le shrinkage ne change rien.
    assert R.shrink(0.42, 5, 0.42, 40.0) == pytest.approx(0.42)
    # Monotone en n a valeur brute > ancre.
    suite = [R.shrink(0.9, n, 0.3, 40.0) for n in (1, 10, 100, 1000)]
    assert suite == sorted(suite)


def test_shrinkage_ecrase_les_petits_echantillons(resultat):
    """Le petit echantillon (35 trades) est davantage tire vers la cohorte que le gros."""
    chanceux = resultat.par_adresse(ADDR_CHANCEUX)
    reg = resultat.par_adresse(ADDR_REGULIER)
    assert chanceux.credibilite < reg.credibilite
    for dim in ("performance", "persistance", "drawdown", "winrate_payoff", "stabilite"):
        ecart_chanceux = abs(chanceux.scores_dimensions[dim] - resultat.cohorte[dim])
        assert ecart_chanceux <= abs(chanceux.scores_bruts[dim] - resultat.cohorte[dim]) + 1e-12
    # La dimension echantillon n'est pas retrecie : elle EST la credibilite.
    assert reg.scores_dimensions["echantillon"] == pytest.approx(reg.scores_bruts["echantillon"])


def test_cohorte_petite_signalee_comme_fragile(resultat):
    assert resultat.taille_cohorte == 4
    assert resultat.shrinkage_fragile is True


# --------------------------------------------------------------------------- point-in-time

def test_aucune_ligne_du_futur_n_est_lue():
    base = fixture_wallet_regulier()
    futur = _trade(ADDR_REGULIER, 99_999, ASOF + timedelta(days=3), 100_000.0, 1.0)
    a = R.rank(asof=ASOF, closed_trades=base)
    b = R.rank(asof=ASOF, closed_trades=base + [futur], )
    assert b.n_trades_ecartes_futur == 1
    reg_a, reg_b = a.par_adresse(ADDR_REGULIER), b.par_adresse(ADDR_REGULIER)
    assert reg_a.n_trades == reg_b.n_trades == 420
    assert reg_a.score == pytest.approx(reg_b.score)
    assert reg_b.metriques["pnl_net_total"] == pytest.approx(16_800.0)


def test_latence_de_publication_respectee():
    """closeTime a asof - 5 s n'est pas connaissable : la latence par defaut est 10 s."""
    base = fixture_wallet_regulier()
    trop_recent = _trade(ADDR_REGULIER, 99_998, ASOF - timedelta(seconds=5), 2000.0, 0.06)
    juste_avant = _trade(ADDR_REGULIER, 99_997, ASOF - timedelta(seconds=60), 2000.0, 0.06)
    r1 = R.rank(asof=ASOF, closed_trades=base + [trop_recent])
    assert r1.par_adresse(ADDR_REGULIER).n_trades == 420
    assert r1.n_trades_ecartes_futur == 1
    r2 = R.rank(asof=ASOF, closed_trades=base + [juste_avant])
    assert r2.par_adresse(ADDR_REGULIER).n_trades == 421
    assert r2.n_trades_ecartes_futur == 0


def test_asof_naif_refuse():
    with pytest.raises(InsufficientData):
        R.rank(asof=datetime(2026, 8, 21), closed_trades=fixture_cohorte())


def test_asof_anterieur_reduit_le_classement():
    """Un asof plus ancien ne peut que retirer des trades, jamais en ajouter."""
    lignes = fixture_cohorte()
    tot = R.rank(asof=ASOF, closed_trades=lignes)
    tot_court = R.rank(asof=datetime(2026, 3, 1, tzinfo=timezone.utc), closed_trades=lignes)
    assert tot_court.n_trades_retenus < tot.n_trades_retenus
    assert tot_court.par_adresse(ADDR_REGULIER).n_trades < tot.par_adresse(ADDR_REGULIER).n_trades


# --------------------------------------------------------------------------- biais connus

def test_pseudo_adresse_twap_exclue():
    lignes = fixture_cohorte() + fixture_wallet_twap()
    res = R.rank(asof=ASOF, closed_trades=lignes)
    assert res.n_trades_twap == 50
    adresses = [w.address for w in res.classes + res.non_classes]
    assert R.TWAP_PSEUDO_ADDRESS not in adresses
    assert len(R.TWAP_PSEUDO_ADDRESS) == 66  # "0x" + 64 hex, pas une adresse EVM


def test_segments_de_wallets_jamais_lus():
    """La cohorte amont est retro-attribuee : passer 'segments' ne doit rien changer."""
    lignes = fixture_cohorte()
    wallets = [{"address": ADDR_CHANCEUX, "observed_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
                "perpEquity": 1_000_000.0, "exposureRatio": 0.4,
                "segments": '["whale","top-pnl"]'}]
    sans = R.rank(asof=ASOF, closed_trades=lignes)
    avec = R.rank(asof=ASOF, closed_trades=lignes, wallets=wallets)
    assert [w.address for w in sans.classes] == [w.address for w in avec.classes]
    for a, b in zip(sans.classes, avec.classes):
        assert a.score == pytest.approx(b.score)
    ctx = avec.par_adresse(ADDR_CHANCEUX).metriques["exposition_wallet"]
    assert "segments" not in ctx
    assert ctx["perpEquity"] == 1_000_000.0


def test_capture_wallets_du_futur_ignoree():
    lignes = fixture_cohorte()
    wallets = [{"address": ADDR_CHANCEUX, "observed_at": ASOF + timedelta(hours=1),
                "perpEquity": 1.0}]
    res = R.rank(asof=ASOF, closed_trades=lignes, wallets=wallets)
    assert "exposition_wallet" not in res.par_adresse(ADDR_CHANCEUX).metriques


def test_biais_documentes_dans_le_resultat(resultat):
    joint = " ".join(resultat.biais).lower()
    for mot in ("survie", "retro-attribuee", "leaderboards", "liquidation", "twap"):
        assert mot in joint


# --------------------------------------------------------------------------- chargement

def test_chargement_parquet_absent_leve(tmp_path):
    with pytest.raises(InsufficientData) as e:
        R.load_closed_trades_parquet(str(tmp_path))
    assert "closed_trades" in str(e.value)


def test_chargement_depuis_le_depot_reel_leve():
    """Etat reel du depot aujourd'hui : aucun closed_trades collecte."""
    racine = r"C:\Users\maram\ht_data"
    with pytest.raises(InsufficientData):
        R.load_closed_trades_parquet(racine)


# --------------------------------------------------------------------------- horodatages

def test_horodatage_illisible_leve():
    lignes = fixture_wallet_regulier()
    lignes[0]["closeTime"] = "pas une date"
    with pytest.raises(InsufficientData):
        R.rank(asof=ASOF, closed_trades=lignes)


def test_horodatage_nul_leve():
    lignes = fixture_wallet_regulier()
    lignes[3]["closeTime"] = None
    with pytest.raises(InsufficientData):
        R.rank(asof=ASOF, closed_trades=lignes)


def test_pnl_non_numerique_leve():
    lignes = fixture_wallet_regulier()
    lignes[7]["realizedPnlUsd"] = None
    with pytest.raises(InsufficientData):
        R.rank(asof=ASOF, closed_trades=lignes)


def test_formats_epoch_secondes_et_iso_equivalents():
    d = datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    assert R._to_utc(int(d.timestamp()), "closeTime", "t") == d
    assert R._to_utc(int(d.timestamp() * 1000), "closeTime", "t") == d
    assert R._to_utc(d.isoformat().replace("+00:00", "Z"), "closeTime", "t") == d


def test_notionnel_non_derivable_marque_le_trade():
    """PnL nul : le notionnel implicite n'existe pas, aucune valeur n'est inventee."""
    addr = "0x" + "8" * 40
    lignes = [_trade(addr, i, _date_dans_le_mois(i % 4, i), 2000.0, 0.05) for i in range(40)]
    for t in lignes:                      # tous a variation de prix nulle
        t["avgExit"] = t["avgEntry"]
        t["realizedPnlUsd"] = 0.0
    trades, _ = R.prepare_trades(lignes, ASOF)
    assert all(t.notionnel is None for t in trades[addr])
    m, manquants = R.compute_metrics(trades[addr])
    assert "performance" in manquants and "stabilite" in manquants
    assert "rendement_sur_capital_engage" not in m
