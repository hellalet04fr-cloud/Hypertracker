"""
Tests cibles : rattachement du funding, ponderation de couverture, garde-fou ECE.

AUCUN reseau. Fills et paiements de funding FABRIQUES, au format reel constate sur
l'API publique Hyperliquid.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import DERIVED, OBSERVED, InsufficientData  # noqa: E402
import ht.reconstruct as R  # noqa: E402
import ht.hl_public as HL  # noqa: E402
import ht.calibration as CAL  # noqa: E402

W = "0x" + "a" * 40
T0 = 1_700_000_000_000
JOUR = 86_400_000


def fill(dir_, sz, px, *, t, coin="BTC", pnl=0.0, fee=0.0, start=0.0, tid=None):
    return {"coin": coin, "px": str(px), "sz": str(sz), "side": "B", "time": t,
            "startPosition": str(start), "dir": dir_, "closedPnl": str(pnl),
            "hash": "0x0", "oid": 1, "crossed": True, "fee": str(fee),
            "tid": tid if tid is not None else t, "feeToken": "USDC", "twapId": None}


def fund(t, coin, usdc, taux="0.0000125", szi="1.0"):
    """Format reel constate : le signe de `usdc` porte le sens (negatif = paye)."""
    return {"time": t, "hash": "0x" + "0" * 64,
            "delta": {"type": "funding", "coin": coin, "usdc": str(usdc),
                      "szi": szi, "fundingRate": taux, "nSamples": 1}}


def _trade_simple(coin="BTC", t_open=T0, t_close=None):
    t_close = t_close if t_close is not None else T0 + JOUR
    return R.reconstruire_wallet(W, [
        fill("Open Long", 1, 100, t=t_open, coin=coin),
        fill("Close Long", 1, 110, t=t_close, coin=coin, pnl=10.0),
    ]).trades


# =========================================================================== funding
def test_funding_non_rattache_vaut_none_pas_zero():
    """Distinction cruciale : None = non mesure, 0.0 = mesure et nul."""
    t = _trade_simple()[0]
    assert t.fundingUsd is None
    assert t.funding_couvert is False


def test_funding_dans_la_fenetre_est_somme():
    trades = _trade_simple()
    evs = [fund(T0 + 3600_000, "BTC", -0.5),
           fund(T0 + 7200_000, "BTC", -0.25),
           fund(T0 + 10800_000, "BTC", 0.1)]
    n = R.rattacher_funding(trades, {W: evs})
    assert n == 1
    assert trades[0].funding_couvert is True
    assert trades[0].fundingUsd == pytest.approx(-0.65)
    assert trades[0].n_paiements_funding == 3


def test_funding_hors_fenetre_ignore():
    trades = _trade_simple()
    evs = [fund(T0 - JOUR, "BTC", -9.0),          # avant l'ouverture
           fund(T0 + 3600_000, "BTC", -0.5),      # dedans
           fund(T0 + 3 * JOUR, "BTC", -7.0)]      # apres la cloture
    R.rattacher_funding(trades, {W: evs})
    assert trades[0].fundingUsd == pytest.approx(-0.5)
    assert trades[0].n_paiements_funding == 1


def test_funding_du_mauvais_coin_ignore():
    trades = _trade_simple(coin="BTC")
    evs = [fund(T0 + 3600_000, "ETH", -5.0), fund(T0 + 3600_000, "BTC", -0.5)]
    R.rattacher_funding(trades, {W: evs})
    assert trades[0].fundingUsd == pytest.approx(-0.5)


def test_trade_hors_fenetre_interrogee_reste_non_couvert():
    """La couverture est definie par la fenetre INTERROGEE. Un trade anterieur a
    cette fenetre n'a pas ete mesure : son funding vaut None, pas zero."""
    trades = _trade_simple(t_open=T0 - 100 * JOUR, t_close=T0 - 99 * JOUR)
    R.rattacher_funding(trades, {W: [fund(T0, "BTC", -0.5)]},
                        fenetres={W: (T0, T0 + 10 * JOUR)})
    assert trades[0].fundingUsd is None
    assert trades[0].funding_couvert is False


def test_wallet_sans_funding_interroge_reste_non_couvert():
    trades = _trade_simple()
    R.rattacher_funding(trades, {})          # l'adresse n'a pas ete interrogee
    assert trades[0].fundingUsd is None
    assert trades[0].funding_couvert is False


def test_funding_couvert_mais_nul():
    trades = _trade_simple()
    R.rattacher_funding(trades, {W: [fund(T0 - 1000, "BTC", -1.0),
                                     fund(T0 + 2 * JOUR, "BTC", -1.0)]})
    assert trades[0].funding_couvert is True
    assert trades[0].fundingUsd == pytest.approx(0.0)
    assert trades[0].n_paiements_funding == 0


def test_entrees_non_funding_ignorees():
    trades = _trade_simple()
    depot = {"time": T0 + 3600_000, "hash": "0x1",
             "delta": {"type": "deposit", "usdc": "500.0"}}
    R.rattacher_funding(trades, {W: [depot, fund(T0 + 3600_000, "BTC", -0.5)]})
    assert trades[0].fundingUsd == pytest.approx(-0.5)


def test_client_user_funding_valide_l_adresse():
    with pytest.raises(InsufficientData):
        HL.user_funding("0x123", poster=lambda c: [])


def test_client_user_funding_transmet_la_fenetre():
    vus = []

    def faux(corps):
        vus.append(corps)
        return []

    HL.user_funding(W, start_ms=111, end_ms=222, poster=faux)
    assert vus[0]["type"] == "userFunding"
    assert vus[0]["startTime"] == 111 and vus[0]["endTime"] == 222


# =========================================================================== ponderation
def _couv(addr, n_trades, taux, rythme, jours):
    return R.Couverture(address=addr, n_fills=n_trades * 2, n_trades=n_trades,
                        n_tronques=int(n_trades * taux), n_ouverts=0,
                        premier_fill_ms=T0, dernier_fill_ms=T0 + int(jours * JOUR),
                        jours_couverts=jours, fills_par_jour=rythme,
                        taux_troncature=taux, utilisable=True, raisons=(),
                        risque_biais="")


def test_poids_penalise_le_rythme():
    lent = R.ponderer([_couv("a", 100, 0.0, 1.0, 365)])[0]
    rapide = R.ponderer([_couv("b", 100, 0.0, 500.0, 365)])[0]
    assert lent.poids > rapide.poids
    assert rapide.w_rythme < 0.15


def test_poids_penalise_la_troncature():
    propre = R.ponderer([_couv("a", 100, 0.0, 1.0, 365)])[0]
    tronque = R.ponderer([_couv("b", 100, 0.5, 1.0, 365)])[0]
    assert tronque.w_troncature == pytest.approx(0.5)
    assert tronque.poids < propre.poids


def test_poids_penalise_la_faible_profondeur():
    court = R.ponderer([_couv("a", 100, 0.0, 1.0, 30)])[0]
    long_ = R.ponderer([_couv("b", 100, 0.0, 1.0, 365)])[0]
    assert court.w_profondeur == pytest.approx(30 / 365, abs=1e-3)
    assert court.poids < long_.poids


def test_un_seul_facteur_effondre_le_poids():
    """Produit et non moyenne : une troncature totale annule le poids meme si le
    rythme et la profondeur sont parfaits."""
    p = R.ponderer([_couv("a", 500, 1.0, 0.1, 365)])[0]
    assert p.poids == pytest.approx(0.0)
    assert p.n_effectif == pytest.approx(0.0)


def test_poids_borne_zero_un():
    for c in (_couv("a", 10, 0.0, 0.0, 1000), _couv("b", 10, 1.0, 1e6, 0.0)):
        p = R.ponderer([c])[0]
        assert 0.0 <= p.poids <= 1.0


def test_n_effectif_reduit_l_echantillon_declare():
    p = R.ponderer([_couv("a", 200, 0.0, 50.0, 182.5)])[0]
    assert p.n_effectif < p.n_trades
    assert p.n_effectif == pytest.approx(200 * p.poids, abs=0.2)


# =========================================================================== ECE OOS
def _jeu(n=400, seed=1):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.95, n)
    y = (rng.uniform(0, 1, n) < p).astype(float)
    return y, p


def test_ece_refusee_sur_donnees_derivees():
    """Exigence : aucune probabilite certifiee sans validation reelle."""
    y, p = _jeu()
    with pytest.raises(InsufficientData) as e:
        CAL.ece_hors_echantillon(y, p, classification=DERIVED)
    assert "DERIVED" in str(e.value)


def test_ece_publiable_sur_observed():
    y, p = _jeu()
    ece = CAL.ece_hors_echantillon(y, p, classification=OBSERVED)
    assert 0.0 <= ece < 0.10


def test_ece_refuse_le_jeu_d_ajustement():
    y, p = _jeu()
    with pytest.raises(InsufficientData) as e:
        CAL.ece_hors_echantillon(y, p, classification=OBSERVED, jeu_ajustement=(y, p))
    assert "ajustement" in str(e.value)


def test_ece_accepte_un_jeu_distinct():
    y1, p1 = _jeu(seed=1)
    y2, p2 = _jeu(seed=2)
    assert CAL.ece_hors_echantillon(y2, p2, classification=OBSERVED,
                                    jeu_ajustement=(y1, p1)) >= 0.0
