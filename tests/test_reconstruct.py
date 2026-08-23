"""
Tests de la reconstruction DERIVED (ht/reconstruct.py, ht/hl_public.py).

AUCUN reseau : tous les fills sont FABRIQUES et le client HTTP est simule. Aucune
sortie ne decrit un wallet reel.

Couverture demandee : long, short, fermeture partielle, ajout, reduction, retournement,
position ouverte au debut, position ouverte a la fin, plusieurs coins, frais, PnL,
fills desordonnes.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import DERIVED, RECONSTRUCTED_CLOSED_TRADES, InsufficientData  # noqa: E402
import ht.reconstruct as R  # noqa: E402
import ht.hl_public as HL  # noqa: E402

W = "0x" + "a" * 40
W2 = "0x" + "b" * 40
T0 = 1_700_000_000_000


def fill(dir_, sz, px, *, t, coin="BTC", pnl=0.0, fee=0.0, start=0.0, tid=None):
    """Un fill FABRIQUE au format Hyperliquid reel (champs constates sur l'API)."""
    return {"coin": coin, "px": str(px), "sz": str(sz), "side": "B",
            "time": t, "startPosition": str(start), "dir": dir_,
            "closedPnl": str(pnl), "hash": "0xdead", "oid": 1,
            "crossed": True, "fee": str(fee), "tid": tid if tid is not None else t,
            "feeToken": "USDC", "twapId": None}


# =========================================================================== marquage
def test_source_et_classification_toujours_presentes():
    r = R.reconstruire_wallet(W, [fill("Open Long", 1, 100, t=T0),
                                  fill("Close Long", 1, 110, t=T0 + 1000, pnl=10.0)])
    assert len(r.trades) == 1
    d = r.trades[0].as_dict()
    assert d["source"] == "hyperliquid_reconstruit"
    assert d["classification"] == DERIVED
    assert RECONSTRUCTED_CLOSED_TRADES.status == DERIVED


def test_source_declaree_dans_le_contrat():
    assert RECONSTRUCTED_CLOSED_TRADES.name == "reconstructed_closed_trades"
    from ht.schema import SOURCES_POUR_CLASSEMENT_DEFINITIF, est_derive
    assert est_derive("reconstructed_closed_trades")
    assert "reconstructed_closed_trades" not in SOURCES_POUR_CLASSEMENT_DEFINITIF


# =========================================================================== cas simples
def test_long_simple_pnl_et_prix():
    r = R.reconstruire_wallet(W, [
        fill("Open Long", 2, 100, t=T0, fee=0.5),
        fill("Close Long", 2, 110, t=T0 + 60_000, pnl=20.0, fee=0.6),
    ])
    t = r.trades[0]
    assert t.side == "LONG" and t.countFills == 2
    assert t.realizedPnlUsd == pytest.approx(20.0)
    assert t.feeUsd == pytest.approx(1.1)
    assert t.avgEntry == pytest.approx(100.0)
    assert t.avgExit == pytest.approx(110.0)
    assert t.duration == pytest.approx(60.0)
    assert not t.tronque and not t.position_ouverte


def test_short_simple():
    r = R.reconstruire_wallet(W, [
        fill("Open Short", 3, 50, t=T0),
        fill("Close Short", 3, 45, t=T0 + 5000, pnl=15.0),
    ])
    t = r.trades[0]
    assert t.side == "SHORT"
    assert t.realizedPnlUsd == pytest.approx(15.0)
    assert t.avgEntry == pytest.approx(50.0) and t.avgExit == pytest.approx(45.0)


def test_ajout_de_position_vwap_pondere():
    """VWAP d'entree sur deux ajouts de tailles differentes : (1*100 + 3*120)/4 = 115."""
    r = R.reconstruire_wallet(W, [
        fill("Open Long", 1, 100, t=T0),
        fill("Open Long", 3, 120, t=T0 + 1000),
        fill("Close Long", 4, 130, t=T0 + 2000, pnl=40.0),
    ])
    t = r.trades[0]
    assert t.avgEntry == pytest.approx(115.0)
    assert t.countFills == 3 and t.n_fills_ouverture == 2


def test_reduction_puis_fermeture_partielle():
    """Une reduction ne clot pas le trade : un seul trade doit sortir, VWAP de sortie
    pondere = (1*105 + 1*115)/2 = 110."""
    r = R.reconstruire_wallet(W, [
        fill("Open Long", 2, 100, t=T0),
        fill("Close Long", 1, 105, t=T0 + 1000, pnl=5.0),
        fill("Close Long", 1, 115, t=T0 + 2000, pnl=15.0),
    ])
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.avgExit == pytest.approx(110.0)
    assert t.realizedPnlUsd == pytest.approx(20.0)
    assert t.n_fills_fermeture == 2


def test_retournement_long_vers_short():
    """`Long > Short` solde la position en cours et en ouvre une opposee."""
    r = R.reconstruire_wallet(W, [
        fill("Open Long", 1, 100, t=T0),
        fill("Long > Short", 2, 110, t=T0 + 1000, pnl=10.0),
        fill("Close Short", 1, 105, t=T0 + 2000, pnl=5.0),
    ])
    assert len(r.trades) >= 1
    assert r.trades[0].realizedPnlUsd == pytest.approx(10.0)


def test_plusieurs_coins_independants():
    r = R.reconstruire_wallet(W, [
        fill("Open Long", 1, 100, t=T0, coin="BTC"),
        fill("Open Short", 5, 20, t=T0 + 500, coin="ETH"),
        fill("Close Long", 1, 110, t=T0 + 1000, coin="BTC", pnl=10.0),
        fill("Close Short", 5, 18, t=T0 + 1500, coin="ETH", pnl=10.0),
    ])
    assert len(r.trades) == 2
    coins = {t.coin: t for t in r.trades}
    assert coins["BTC"].side == "LONG" and coins["ETH"].side == "SHORT"
    assert coins["BTC"].countFills == 2 and coins["ETH"].countFills == 2


# =========================================================================== bords
def test_position_ouverte_au_debut_marquee_tronquee():
    """startPosition non nulle sur le premier fill vu : l'ouverture est hors fenetre."""
    r = R.reconstruire_wallet(W, [
        fill("Close Long", 2, 110, t=T0, pnl=20.0, start=2.0),
    ])
    assert len(r.trades) == 1
    assert r.trades[0].tronque is True
    assert r.couvertures[0].n_tronques == 1


def test_position_encore_ouverte_a_la_fin_non_emise():
    r = R.reconstruire_wallet(W, [fill("Open Long", 1, 100, t=T0)])
    assert r.trades == []
    assert len(r.positions_ouvertes) == 1
    assert r.positions_ouvertes[0]["coin"] == "BTC"


def test_fills_desordonnes_donnent_le_meme_resultat():
    """L'ordre d'arrivee ne doit rien changer : le tri est par (time, tid)."""
    fs = [fill("Close Long", 1, 110, t=T0 + 1000, pnl=10.0),
          fill("Open Long", 1, 100, t=T0)]
    a = R.reconstruire_wallet(W, fs)
    b = R.reconstruire_wallet(W, list(reversed(fs)))
    assert [t.as_dict() for t in a.trades] == [t.as_dict() for t in b.trades]
    assert a.trades[0].openTime == T0


def test_aucun_fill():
    r = R.reconstruire_wallet(W, [])
    assert r.trades == [] and r.couvertures[0].n_fills == 0
    assert not r.couvertures[0].utilisable


def test_adresse_vide_refusee():
    with pytest.raises(InsufficientData):
        R.reconstruire_wallet("", [fill("Open Long", 1, 100, t=T0)])


def test_dir_hors_modele_compte_frais_sans_casser():
    r = R.reconstruire_wallet(W, [
        fill("Open Long", 1, 100, t=T0),
        fill("Net Child Vaults", 0, 0, t=T0 + 10, fee=0.2),
        fill("Close Long", 1, 110, t=T0 + 1000, pnl=10.0),
    ])
    assert len(r.trades) == 1
    assert r.trades[0].feeUsd == pytest.approx(0.2)


# =========================================================================== couverture
def _serie(n, coin="BTC", pas=86_400_000):
    fs = []
    for i in range(n):
        fs.append(fill("Open Long", 1, 100, t=T0 + i * pas, coin=coin, tid=2 * i))
        fs.append(fill("Close Long", 1, 101, t=T0 + i * pas + 1000, coin=coin,
                       pnl=1.0, tid=2 * i + 1))
    return fs


def test_wallet_bien_couvert_est_utilisable():
    r = R.reconstruire_wallet(W, _serie(40))
    c = r.couvertures[0]
    assert c.n_trades == 40 and c.utilisable, c.raisons
    assert c.jours_couverts > R.MIN_JOURS_COUVERTURE
    assert c.risque_biais == "FAIBLE"


def test_refus_trop_peu_de_trades():
    c = R.reconstruire_wallet(W, _serie(5)).couvertures[0]
    assert not c.utilisable
    assert any("trades clos" in x for x in c.raisons)


def test_refus_fenetre_trop_courte():
    c = R.reconstruire_wallet(W, _serie(30, pas=3600_000)).couvertures[0]
    assert not c.utilisable
    assert any("jours couverts" in x for x in c.raisons)


def test_refus_troncature_excessive():
    fs = [fill("Close Long", 1, 110, t=T0 + i * 86_400_000, pnl=1.0, start=1.0, tid=i)
          for i in range(40)]
    c = R.reconstruire_wallet(W, fs).couvertures[0]
    assert c.taux_troncature == pytest.approx(1.0)
    assert not c.utilisable
    assert any("troncature" in x for x in c.raisons)


def test_risque_biais_croit_avec_le_rythme():
    lent = R.reconstruire_wallet(W, _serie(40, pas=86_400_000)).couvertures[0]
    rapide = R.reconstruire_wallet(W, _serie(400, pas=60_000)).couvertures[0]
    assert lent.risque_biais == "FAIBLE"
    assert rapide.risque_biais.startswith(("ELEVE", "CRITIQUE"))


def test_utilisables_exclut_tronques_et_ouverts_par_defaut():
    fs = _serie(40) + [fill("Close Long", 1, 110, t=T0 + 99 * 86_400_000,
                            pnl=5.0, start=1.0, coin="ETH", tid=9999)]
    r = R.reconstruire_wallet(W, fs)
    tous = r.utilisables(inclure_tronques=True)
    sans = r.utilisables()
    assert len(sans) == len(tous) - 1
    assert all(not t["tronque"] for t in sans)
    assert all(not t["position_ouverte"] for t in tous)


def test_wallet_refuse_ne_fournit_aucun_trade():
    """Garde-fou principal : un wallet a couverture insuffisante est ecarte en bloc."""
    r = R.reconstruire_wallet(W, _serie(5))
    assert not r.couvertures[0].utilisable
    assert r.utilisables() == []


def test_reconstruire_plusieurs_wallets():
    r = R.reconstruire({W: _serie(40), W2: _serie(3)})
    assert len(r.couvertures) == 2
    ok = {c.address: c.utilisable for c in r.couvertures}
    assert ok[W] and not ok[W2]
    assert {t["address"] for t in r.utilisables()} == {W}


# =========================================================================== validation croisee
def test_validation_appariement_parfait():
    natifs = [{"address": W, "coin": "BTC", "closeTime": T0 + 1000,
               "openTime": T0, "realizedPnlUsd": 10.0, "countFills": 2, "feeUsd": 1.1}]
    rec = R.reconstruire_wallet(W, [
        fill("Open Long", 2, 100, t=T0, fee=0.5),
        fill("Close Long", 2, 110, t=T0 + 1000, pnl=10.0, fee=0.6),
    ])
    rap = R.valider_contre_natifs([t.as_dict() for t in rec.trades], natifs)
    assert rap.n_apparies == 1 and rap.n_non_reconciliables == 0
    assert rap.concordance_exacte["realizedPnlUsd"] == pytest.approx(1.0)
    assert rap.erreur_moyenne["closeTime"] == pytest.approx(0.0)


def test_validation_compte_les_non_reconciliables():
    natifs = [{"address": W, "coin": "SOL", "closeTime": T0, "openTime": T0,
               "realizedPnlUsd": 1.0, "countFills": 2, "feeUsd": 0.0}]
    rap = R.valider_contre_natifs([], natifs)
    assert rap.n_non_reconciliables == 1
    assert rap.taux_non_reconciliables == pytest.approx(1.0)


def test_validation_mesure_les_ecarts():
    natifs = [{"address": W, "coin": "BTC", "closeTime": T0 + 1000, "openTime": T0,
               "realizedPnlUsd": 12.0, "countFills": 3, "feeUsd": 2.0}]
    rec = [{"address": W, "coin": "BTC", "closeTime": T0 + 1000, "openTime": T0,
            "realizedPnlUsd": 10.0, "countFills": 2, "feeUsd": 1.0}]
    rap = R.valider_contre_natifs(rec, natifs)
    assert rap.n_apparies == 1
    assert rap.erreur_moyenne["realizedPnlUsd"] == pytest.approx(2.0)
    assert rap.concordance_exacte["realizedPnlUsd"] == pytest.approx(0.0)


def test_validation_jamais_marquee_validee():
    """Exigence explicite : le cross-validator existe mais n'est pas fiable tant
    qu'aucun natif n'a ete confronte."""
    rap = R.valider_contre_natifs([], [])
    assert rap.valide is False
    assert "PAS" in rap.note or "pas" in rap.note


def test_validation_un_reconstruit_ne_sert_qu_une_fois():
    natifs = [{"address": W, "coin": "BTC", "closeTime": T0, "openTime": T0,
               "realizedPnlUsd": 1.0, "countFills": 1, "feeUsd": 0.0},
              {"address": W, "coin": "BTC", "closeTime": T0 + 10, "openTime": T0,
               "realizedPnlUsd": 1.0, "countFills": 1, "feeUsd": 0.0}]
    rec = [{"address": W, "coin": "BTC", "closeTime": T0, "openTime": T0,
            "realizedPnlUsd": 1.0, "countFills": 1, "feeUsd": 0.0}]
    rap = R.valider_contre_natifs(rec, natifs)
    assert rap.n_apparies == 1 and rap.n_non_reconciliables == 1


# =========================================================================== client public
def test_client_refuse_adresse_invalide():
    for mauvaise in ("", "0x123", "0x" + "0" * 64):
        with pytest.raises(InsufficientData):
            HL.user_fills_by_time(mauvaise)


def test_client_pagine_et_deduplique():
    pages = [[fill("Open Long", 1, 100, t=T0 + i, tid=i) for i in range(2000)],
             [fill("Open Long", 1, 100, t=T0 + 2000 + i, tid=2000 + i) for i in range(10)]]
    appels = []

    def faux_poster(corps):
        appels.append(corps)
        return pages[len(appels) - 1] if len(appels) <= len(pages) else []

    fills = HL.user_fills_by_time(W, poster=faux_poster, pages_max=5)
    assert len(appels) == 2                       # 2e page incomplete -> arret
    assert len({f["tid"] for f in fills}) == len(fills)
    assert fills == sorted(fills, key=lambda f: (f["time"], f["tid"]))


def test_client_pagine_vers_le_PRESENT_pas_vers_le_passe():
    """Le serveur rend les fills les PLUS ANCIENS de la plage. La pagination doit donc
    avancer `startTime`, sinon elle s'eloigne du present a chaque page — c'est ce qui
    avait rendu impossible tout recouvrement avec des donnees recentes."""
    appels = []

    def faux_poster(corps):
        appels.append(dict(corps))
        n = len(appels)
        if n == 1:
            return [fill("Open Long", 1, 100, t=T0 + i, tid=i) for i in range(2000)]
        return []

    HL.user_fills_by_time(W, start_ms=T0, end_ms=T0 + 10_000_000,
                          poster=faux_poster, pages_max=3)
    assert len(appels) >= 2
    # la 2e requete doit demarrer APRES le fill le plus recent de la 1re
    assert appels[1]["startTime"] > appels[0]["startTime"]
    assert appels[1]["startTime"] == T0 + 1999 + 1
    assert appels[1]["endTime"] == appels[0]["endTime"]      # borne haute inchangee


def test_client_arrete_sur_page_vide():
    def faux_poster(corps):
        return []
    assert HL.user_fills_by_time(W, poster=faux_poster) == []


def test_limite_debit_espace_les_appels():
    lim = HL.LimiteDebit(par_minute=600)          # 100 ms entre appels
    import time as _t
    t0 = _t.monotonic()
    lim.attendre()
    lim.attendre()
    assert _t.monotonic() - t0 >= 0.09
