"""
Tests du portail de verification (ht/gate.py). Aucun reseau.

Le comportement essentiel : VERIFIED ne doit JAMAIS sortir sans que TOUTES les
conditions soient reunies. Chaque test ci-dessous casse une condition et verifie
que le portail refuse.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import DERIVED, OBSERVED, InsufficientData  # noqa: E402
import ht.gate as G  # noqa: E402

W = "0x" + "a" * 40
T0 = 1_700_000_000_000
ASOF = datetime(2026, 7, 1, tzinfo=timezone.utc)


def trade(i, *, addr=W, coin="BTC", pnl=10.0, fee=1.0, fills=2, dt_ms=0, **kw):
    t_close = T0 + i * 3_600_000 + dt_ms
    d = {"address": addr, "coin": coin, "hash": f"h{i}",
         "openTime": T0 + i * 3_600_000 - 60_000, "closeTime": t_close,
         "realizedPnlUsd": pnl, "feeUsd": fee, "countFills": fills}
    d.update(kw)
    return d


def paire_parfaite(n=150, coin_par=7):
    """n paires natif/reconstruit strictement identiques."""
    nat = [trade(i, coin=f"C{i % coin_par}") for i in range(n)]
    rec = [dict(t, source="hyperliquid_reconstruit", classification=DERIVED,
                tronque=False, funding_couvert=True) for t in nat]
    return rec, nat


def oos_bon(seed=1, n=400):
    """Trois jeux DISJOINTS, calibres par construction."""
    def jeu(s):
        rng = np.random.default_rng(s)
        p = rng.uniform(0.05, 0.95, n)
        y = (rng.uniform(0, 1, n) < p).astype(float)
        return (y, p)
    return G.DecoupageOOS(train=jeu(seed), calibration=jeu(seed + 1), test=jeu(seed + 2))


# =========================================================================== NOT_READY
def test_pas_de_natifs():
    v = G.evaluer([{"address": W}], [])
    assert v.etat == G.NOT_READY
    assert not v.verifie


def test_pas_de_reconstruits():
    v = G.evaluer([], [{"address": W}])
    assert v.etat == G.NOT_READY


def test_aucun_wallet_commun():
    rec, nat = paire_parfaite(120)
    autres = [dict(t, address="0x" + "b" * 40) for t in nat]
    v = G.evaluer(rec, autres)
    assert v.etat == G.NOT_READY
    assert "commun" in " ".join(v.raisons)


# =========================================================================== VERIFIED
def test_verified_quand_tout_concorde():
    rec, nat = paire_parfaite(150)
    v = G.evaluer(rec, nat, decoupage_oos=oos_bon(), classification_oos=OBSERVED)
    assert v.etat == G.VERIFIED, v.raisons
    assert v.verifie and v.n_paires >= G.MIN_PAIRES_APPARIEES
    assert v.ece is not None and v.ece <= G.MAX_ECE_CERTIFIEE


# =========================================================================== chaque verrou
def test_refus_trop_peu_de_paires():
    rec, nat = paire_parfaite(20)
    v = G.evaluer(rec, nat, decoupage_oos=oos_bon(), classification_oos=OBSERVED)
    assert v.etat == G.INSUFFICIENT_DATA
    assert any("paires appariees" in r for r in v.raisons)


def test_refus_concordance_pnl_insuffisante():
    rec, nat = paire_parfaite(150)
    for r in rec[:40]:                       # 27 % de PnL faux
        r["realizedPnlUsd"] = 999.0
    v = G.evaluer(rec, nat, decoupage_oos=oos_bon(), classification_oos=OBSERVED)
    assert v.etat == G.INSUFFICIENT_DATA
    assert any("concordance PnL" in r for r in v.raisons)


def test_refus_ecart_temporel():
    rec, nat = paire_parfaite(150)
    for r in rec:
        r["openTime"] = r["openTime"] - 5 * 60_000     # 5 min de decalage
    v = G.evaluer(rec, nat, decoupage_oos=oos_bon(), classification_oos=OBSERVED)
    assert v.etat == G.INSUFFICIENT_DATA
    assert any("openTime" in r for r in v.raisons)


def test_refus_sans_decoupage_oos():
    rec, nat = paire_parfaite(150)
    v = G.evaluer(rec, nat)
    assert v.etat == G.INSUFFICIENT_DATA
    assert any("hors echantillon" in r for r in v.raisons)


def test_refus_ece_sur_derived():
    """Exigence absolue : jamais d'ECE certifiee sur du DERIVED."""
    rec, nat = paire_parfaite(150)
    v = G.evaluer(rec, nat, decoupage_oos=oos_bon(), classification_oos=DERIVED)
    assert v.etat == G.INSUFFICIENT_DATA
    assert any("ECE non certifiable" in r for r in v.raisons)


def test_refus_non_reconciliation_excessive():
    rec, nat = paire_parfaite(150)
    nat += [trade(i, coin="ZZZ") for i in range(200, 260)]   # natifs sans contrepartie
    v = G.evaluer(rec, nat, decoupage_oos=oos_bon(), classification_oos=OBSERVED)
    assert v.etat == G.INSUFFICIENT_DATA
    assert any("non-reconciliation" in r for r in v.raisons)


# =========================================================================== ECE stricte
def test_ece_refuse_jeux_non_disjoints():
    j = oos_bon()
    identique = G.DecoupageOOS(train=j.train, calibration=j.train, test=j.test)
    with pytest.raises(InsufficientData) as e:
        G.ece_certifiee(identique, classification=OBSERVED)
    assert "DISTINCTS" in str(e.value)


def test_ece_refuse_jeu_vide():
    j = oos_bon()
    vide = G.DecoupageOOS(train=j.train, calibration=(np.array([]), np.array([])),
                          test=j.test)
    with pytest.raises(InsufficientData):
        G.ece_certifiee(vide, classification=OBSERVED)


def test_ece_certifiee_mesuree_sur_le_test():
    assert 0.0 <= G.ece_certifiee(oos_bon(), classification=OBSERVED) <= 1.0


# =========================================================================== diagnostic
def test_diagnostic_identifie_la_troncature():
    rec, nat = paire_parfaite(20)
    for r in rec[:5]:
        r["realizedPnlUsd"] = 1.0
        r["tronque"] = True
    d = G.diagnostiquer_ecarts(G._reapparier(rec, nat))
    assert d["causes"].get("tronque") == 5


def test_diagnostic_identifie_les_fills_manquants():
    rec, nat = paire_parfaite(20)
    for r in rec[:4]:
        r["countFills"] = 1
    d = G.diagnostiquer_ecarts(G._reapparier(rec, nat))
    assert d["causes"].get("fills_manquants") == 4


def test_diagnostic_identifie_les_frais_non_usdc():
    rec, nat = paire_parfaite(20)
    for r in rec[:3]:
        r["feeUsd"] = 0.0                    # frais absents, PnL identique
    d = G.diagnostiquer_ecarts(G._reapparier(rec, nat))
    assert d["causes"].get("frais_non_usdc") == 3


def test_diagnostic_identifie_une_convention_de_pnl():
    """Ecart systematique et de meme signe : ce n'est pas du bruit, c'est une
    convention brut/net differente."""
    rec, nat = paire_parfaite(30)
    for r in rec:
        r["realizedPnlUsd"] = r["realizedPnlUsd"] - 1.0
    d = G.diagnostiquer_ecarts(G._reapparier(rec, nat))
    assert d["causes"].get("convention_pnl") == 30
    assert d["ecart_pnl_median_signe"] == pytest.approx(-1.0)


def test_diagnostic_ecarts_aleatoires_restent_inexpliques():
    rec, nat = paire_parfaite(40)
    for i, r in enumerate(rec):
        r["realizedPnlUsd"] += (1.0 if i % 2 else -1.0)   # signes alternes
    d = G.diagnostiquer_ecarts(G._reapparier(rec, nat))
    assert d["causes"].get("inexplique", 0) > 0
    assert "convention_pnl" not in d["causes"]


def test_diagnostic_paires_parfaites_sans_ecart():
    rec, nat = paire_parfaite(30)
    d = G.diagnostiquer_ecarts(G._reapparier(rec, nat))
    assert d["n_discordantes"] == 0 and d["causes"] == {}


# =========================================================================== automatisation
def test_execution_degrade_en_provisoire_si_non_verifie():
    rec, nat = paire_parfaite(20)
    w = [{"address": W, "perpEquity": 1e5, "observed_at": "2026-01-01T00:00:00+00:00"}]
    out = G.executer_si_pret(nat, rec, w)
    assert out["verdict"].etat != G.VERIFIED
    assert out["definitif"] is False
    assert "PROVISOIRE" in out["note"] or "impossible" in out["note"]


def test_execution_ne_leve_jamais():
    """L'enchainement automatique ne doit pas interrompre la collecte : il degrade."""
    out = G.executer_si_pret([], [], [])
    assert out["verdict"].etat == G.NOT_READY
    assert out["definitif"] is False


def test_resume_lisible():
    rec, nat = paire_parfaite(20)
    for r in rec[:3]:
        r["tronque"] = True
        r["realizedPnlUsd"] = 0.0
    v = G.evaluer(rec, nat)
    txt = v.resume()
    assert "GATE" in txt and G.INSUFFICIENT_DATA in txt
