"""
Tests de ht/wallet_intel.py, ht/regime.py, ht/conditional.py, ht/research.py.
Aucun reseau, entierement deterministe.

Les series sont FABRIQUEES (`fixture_*`) a verite connue : c'est la seule facon de
verifier qu'une composante absente reste absente au lieu de valoir zero.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import DERIVED, OBSERVED, InsufficientData  # noqa: E402
import ht.wallet_intel as WI  # noqa: E402
import ht.regime as RG  # noqa: E402
import ht.conditional as CD  # noqa: E402
import ht.research as RS  # noqa: E402
import ht.signaux as SG  # noqa: E402

W = "0x" + "a" * 40
ASOF = datetime(2026, 8, 1, tzinfo=timezone.utc)
T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
JOUR = 86_400_000


def fixture_trade(i, pnl, *, usd=1000.0, fee=0.5, funding=None, couvert=True,
                  coin="BTC", jour=None):
    t = {"address": W, "coin": coin, "trade_id": f"t{i}",
         "realizedPnlUsd": pnl + fee, "realizedPnlNetUsd": pnl,
         "feeUsd": fee, "totalUsd": usd,
         "openTime": T0 + (jour if jour is not None else i) * JOUR,
         "closeTime": T0 + (jour if jour is not None else i) * JOUR + 3600_000,
         "countFills": 2, "tronque": False, "position_ouverte": False}
    if funding is not None:
        t["fundingUsd"] = funding
        t["funding_couvert"] = couvert
    return t


def fixture_serie(n=60, mu=5.0, sigma=2.0, seed=1, **kw):
    import random
    r = random.Random(seed)
    return [fixture_trade(i, r.gauss(mu, sigma), **kw) for i in range(n)]


def fixture_couverture(taux=0.0, rythme=5.0, jours=300.0):
    return {"taux_troncature": taux, "fills_par_jour": rythme, "jours_couverts": jours}


# =========================================================================== scoring
def test_echantillon_insuffisant_aucun_score():
    s = WI.evaluer_wallet(W, fixture_serie(10), fixture_couverture(), asof=ASOF)
    assert s.score is None and not s.complet
    assert "echantillon" in " ".join(s.manquantes)


def test_score_decomposable_et_somme_coherente():
    s = WI.evaluer_wallet(W, fixture_serie(80), fixture_couverture(), asof=ASOF)
    assert s.score is not None
    dispo = [c for c in s.composantes if c.calculable]
    attendu = sum(c.score * c.poids for c in dispo) / sum(c.poids for c in dispo)
    assert s.score == pytest.approx(attendu)
    assert 0.0 <= s.score <= 1.0


def test_contributions_triees_et_exhaustives():
    s = WI.evaluer_wallet(W, fixture_serie(80), fixture_couverture(), asof=ASOF)
    c = s.contributions()
    assert c == sorted(c, key=lambda x: -x[1])
    assert len(c) == sum(1 for x in s.composantes if x.calculable)


def test_composante_absente_n_est_pas_zero():
    """Sans notionnel, le rendement n'a pas de denominateur : il doit etre ABSENT,
    pas nul — sinon l'ignorance passerait pour de la mediocrite."""
    ts = [dict(t, totalUsd=0.0) for t in fixture_serie(60)]
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    r = s.par_nom("rendement_net")
    assert not r.calculable and r.score is None and r.valeur is None
    assert "rendement_net" in s.manquantes and not s.complet


def test_couverture_absente_non_supposee_bonne():
    s = WI.evaluer_wallet(W, fixture_serie(60), None, asof=ASOF)
    c = s.par_nom("couverture")
    assert not c.calculable
    assert s.n_effectif == pytest.approx(60.0)     # pas de ponderation inventee


def test_funding_absent_marque_absent():
    s = WI.evaluer_wallet(W, fixture_serie(60), fixture_couverture(), asof=ASOF)
    assert not s.par_nom("cout_funding").calculable
    ts = fixture_serie(60, funding=-0.2, couvert=True)
    s2 = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    assert s2.par_nom("cout_funding").calculable


def test_funding_non_couvert_ignore():
    ts = fixture_serie(60, funding=-0.2, couvert=False)
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    assert not s.par_nom("cout_funding").calculable


def test_ecart_type_nul_stabilite_absente():
    ts = [fixture_trade(i, 5.0) for i in range(60)]
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    assert not s.par_nom("stabilite").calculable


def test_rythme_eleve_reduit_l_echantillon_effectif():
    lent = WI.evaluer_wallet(W, fixture_serie(60), fixture_couverture(rythme=1), asof=ASOF)
    rapide = WI.evaluer_wallet(W, fixture_serie(60), fixture_couverture(rythme=500), asof=ASOF)
    assert rapide.n_effectif < lent.n_effectif
    assert any("rythme" in a for a in rapide.alertes)


def test_troncature_alerte_et_penalise():
    s = WI.evaluer_wallet(W, fixture_serie(60), fixture_couverture(taux=0.5), asof=ASOF)
    assert any("troncature" in a for a in s.alertes)
    assert s.par_nom("couverture").valeur < 0.5


def test_drawdown_nul_plafonne_explicitement():
    ts = [fixture_trade(i, 5.0 + i * 0.01) for i in range(60)]
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    d = s.par_nom("drawdown")
    assert d.calculable and math.isinf(d.valeur) and d.score == 1.0
    assert any("plafonne" in a for a in s.alertes)


def test_fraicheur_penalise_l_inactivite():
    vieux = WI.evaluer_wallet(W, fixture_serie(60), fixture_couverture(),
                              asof=ASOF + timedelta(days=200))
    assert any("dernier trade" in a for a in vieux.alertes)
    assert vieux.par_nom("fraicheur").score == pytest.approx(0.0)


def test_evaluer_tous_trie_et_corrige_les_tests_multiples():
    m = {f"0x{i:040x}": fixture_serie(60, seed=i) for i in range(3)}
    out = WI.evaluer_tous(m, {a: fixture_couverture() for a in m}, asof=ASOF)
    assert len(out) == 3
    sc = [s.score for s in out if s.score is not None]
    assert sc == sorted(sc, reverse=True)


def test_poids_modifiables_changent_le_score():
    ts = fixture_serie(80)
    a = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    b = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF,
                          poids={"rendement_net": 0.9})
    assert a.score != b.score


# =========================================================================== regime
def fixture_prix_tendance(n=40, depart=100.0, pas=1.0):
    return [depart + i * pas for i in range(n)]


def fixture_prix_range(n=40, depart=100.0, amplitude=2.0):
    return [depart + (amplitude if i % 2 else -amplitude) for i in range(n)]


def test_regime_refuse_serie_courte():
    with pytest.raises(InsufficientData):
        RG.classifier(fixture_prix_tendance(10))


def test_regime_refuse_prix_invalides():
    p = fixture_prix_tendance(30)
    p[5] = -1.0
    with pytest.raises(InsufficientData):
        RG.classifier(p)


def test_regime_detecte_la_tendance():
    r = RG.classifier(fixture_prix_tendance(40))
    assert r.direction == RG.TENDANCE_HAUSSE
    assert r.ratio_directionnel > 0.9
    r2 = RG.classifier(fixture_prix_tendance(40, pas=-1.0))
    assert r2.direction == RG.TENDANCE_BAISSE


def test_regime_detecte_le_range():
    r = RG.classifier(fixture_prix_range(40))
    assert r.direction == RG.RANGE
    assert r.ratio_directionnel < 0.35


def test_ratio_directionnel_borne():
    for p in (fixture_prix_tendance(40), fixture_prix_range(40)):
        assert 0.0 <= RG.ratio_directionnel(p) <= 1.0


def test_serie_constante_refusee():
    with pytest.raises(InsufficientData):
        RG.ratio_directionnel([100.0] * 30)


def test_volatilite_sans_reference_reste_normale():
    r = RG.classifier(fixture_prix_tendance(40))
    assert r.volatilite == RG.NORMALE
    assert r.volatilite_reference is None
    assert r.changement is False


def test_expansion_et_compression_detectees():
    calme = [100.0 + (0.1 if i % 2 else -0.1) for i in range(40)]
    agite = [100.0 + (5.0 if i % 2 else -5.0) for i in range(40)]
    assert RG.classifier(agite, reference=calme).volatilite == RG.EXPANSION
    assert RG.classifier(calme, reference=agite).volatilite == RG.COMPRESSION


def test_changement_de_regime_signale():
    r = RG.classifier(fixture_prix_tendance(40), reference=fixture_prix_range(40))
    assert r.changement is True


def test_serie_de_regimes():
    pts = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i), 100.0 + i)
           for i in range(120)]
    rs = RG.serie_de_regimes(pts, taille_fenetre=30, pas=15)
    assert len(rs) >= 2
    assert all(r.debut is not None and r.fin is not None for r in rs)
    with pytest.raises(InsufficientData):
        RG.serie_de_regimes(pts[:10])


def test_mid_carnet_refuse_cote_unique():
    ordres = [{"coin": "BTC", "side": "B", "limitPx": 100.0, "isTrigger": False}]
    with pytest.raises(InsufficientData):
        RG.mid_depuis_carnet(ordres, "BTC")


def test_mid_carnet_valeur_connue():
    ordres = [{"coin": "BTC", "side": "B", "limitPx": 99.0, "isTrigger": False},
              {"coin": "BTC", "side": "B", "limitPx": 98.0, "isTrigger": False},
              {"coin": "BTC", "side": "A", "limitPx": 101.0, "isTrigger": False},
              {"coin": "ETH", "side": "A", "limitPx": 5.0, "isTrigger": False}]
    assert RG.mid_depuis_carnet(ordres, "BTC") == pytest.approx(100.0)


# =========================================================================== conditionnel
def fixture_regimes():
    d = T0
    return [{"debut": d, "fin": d + 30 * JOUR, "etiquette": "TENDANCE_HAUSSE/NORMALE"},
            {"debut": d + 30 * JOUR + 1, "fin": d + 90 * JOUR, "etiquette": "RANGE/NORMALE"}]


def test_conditionnel_refuse_sans_regimes():
    with pytest.raises(InsufficientData):
        CD.analyser(W, fixture_serie(60), [])


def test_conditionnel_repartit_et_borne_l_incertitude():
    ts = [fixture_trade(i, 5.0 if i % 3 else -2.0, jour=i) for i in range(80)]
    a = CD.analyser(W, ts, fixture_regimes(), asof=ASOF)
    assert a.n_total == 80
    exp = [p for p in a.par_regime if p.suffisant]
    assert exp
    for p in exp:
        assert p.win_rate_bas <= p.win_rate <= p.win_rate_haut
        assert 0.0 <= p.win_rate_bas and p.win_rate_haut <= 1.0


def test_conditionnel_petit_regime_non_exploite():
    ts = [fixture_trade(i, 1.0, jour=i) for i in range(5)]
    a = CD.analyser(W, ts, fixture_regimes(), asof=ASOF)
    assert all(not p.suffisant for p in a.par_regime)
    assert a.regimes_insuffisants


def test_conditionnel_trades_hors_regime_comptes_a_part():
    ts = [fixture_trade(i, 1.0, jour=500 + i) for i in range(30)]
    a = CD.analyser(W, ts, fixture_regimes(), asof=ASOF)
    assert a.n_sans_regime == 30
    assert a.par_regime == []


def test_conditionnel_ecart_non_declare_si_ic_se_chevauchent():
    ts = ([fixture_trade(i, 1.0 if i % 2 else -1.0, jour=i) for i in range(40)]
          + [fixture_trade(100 + i, 1.0 if i % 2 else -1.0, jour=40 + i) for i in range(40)])
    a = CD.analyser(W, ts, fixture_regimes(), asof=ASOF)
    assert not a.ecart_significatif
    assert "chevauchent" in a.commentaire or "un seul regime" in a.commentaire


# =========================================================================== research
def test_rapport_explique_le_classement():
    ts = fixture_serie(80)
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    r = RS.rapport(s, ts)
    assert r.pourquoi
    assert "POURQUOI" in r.texte() and "OU L'AVANTAGE DISPARAIT" in r.texte()


def test_rapport_signale_la_concentration_du_pnl():
    ts = [fixture_trade(i, 0.1) for i in range(59)] + [fixture_trade(99, 500.0)]
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    r = RS.rapport(s, ts)
    assert any("un seul trade" in x for x in r.invalidation)


def test_rapport_signale_la_classification_derived():
    ts = fixture_serie(60)
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    r = RS.rapport(s, ts, classification=DERIVED)
    assert any("DERIVED" in x for x in r.incertitudes)


def test_rapport_liste_les_composantes_absentes():
    ts = [dict(t, totalUsd=0.0) for t in fixture_serie(60)]
    s = WI.evaluer_wallet(W, ts, None, asof=ASOF)
    r = RS.rapport(s, ts)
    assert any("rendement_net" in x for x in r.incertitudes)
    assert any("couverture" in x for x in r.incertitudes)


def test_rapport_signale_un_regime_perdant():
    ts = ([fixture_trade(i, 5.0, jour=i) for i in range(40)]
          + [fixture_trade(100 + i, -5.0, jour=40 + i) for i in range(40)])
    s = WI.evaluer_wallet(W, ts, fixture_couverture(), asof=ASOF)
    c = CD.analyser(W, ts, fixture_regimes(), asof=ASOF)
    r = RS.rapport(s, ts, c)
    assert any("ne tient pas dans ce contexte" in x for x in r.invalidation)


# =========================================================================== interface signal
def test_contexte_bloque_par_defaut():
    ctx = SG.ContexteSignal(wallet=W, score_wallet=0.8, score_complet=True,
                            regime="RANGE/NORMALE", classification=DERIVED)
    bl = ctx.blocages()
    assert bl and any("DERIVED" in b for b in bl)
    s = SG.evaluer_avec_contexte(ASOF, ctx, 700, 1000)
    assert s.direction == SG.NO_TRADE
    assert s.refus == bl


def test_contexte_manquant_bloque():
    for kw in ({"score_wallet": None}, {"regime": None}, {"score_complet": False},
               {"ece": None}):
        base = dict(wallet=W, score_wallet=0.8, score_complet=True,
                    regime="RANGE/NORMALE", classification=OBSERVED,
                    ece=0.02, perf_conditionnelle=None)
        base.update(kw)
        assert SG.ContexteSignal(**base).blocages()


def test_contexte_complet_laisse_passer_l_evaluation():
    class P:
        suffisant = True
    ctx = SG.ContexteSignal(wallet=W, score_wallet=0.8, score_complet=True,
                            regime="RANGE/NORMALE", perf_conditionnelle=P(),
                            ece=0.02, classification=OBSERVED)
    assert ctx.blocages() == ()
    s = SG.evaluer_avec_contexte(ASOF, ctx, 700, 1000)
    assert s.direction == SG.LONG
    assert s.detail.get("wallet") == W


def test_sans_issues_reste_no_trade():
    class P:
        suffisant = True
    ctx = SG.ContexteSignal(wallet=W, score_wallet=0.8, score_complet=True,
                            regime="RANGE/NORMALE", perf_conditionnelle=P(),
                            ece=0.02, classification=OBSERVED)
    s = SG.evaluer_avec_contexte(ASOF, ctx)
    assert s.direction == SG.NO_TRADE
