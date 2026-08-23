"""
Tests de ht/oos.py et ht/final_gate.py. Aucun reseau, deterministes.

Le comportement central : VERIFIED exige les NEUF conditions. Chaque test ci-dessous
casse une seule condition et verifie que le portail refuse — et refuse en nommant la
bonne.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import DERIVED, OBSERVED, InsufficientData  # noqa: E402
import ht.oos as OOS  # noqa: E402
import ht.final_gate as FG  # noqa: E402
import ht.gate as G  # noqa: E402

W = "0x" + "a" * 40
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
JOUR = 86_400_000


def fixture_trades(n=300, pnl=5.0, fee=0.5, pas_h=6):
    """Trades FABRIQUES, etales dans le temps, sans chevauchement."""
    out = []
    for i in range(n):
        o = int((T0 + timedelta(hours=i * pas_h)).timestamp() * 1000)
        out.append({"address": W, "coin": "BTC", "hash": f"h{i}",
                    "openTime": o, "closeTime": o + 3600_000,
                    "realizedPnlUsd": pnl + fee, "realizedPnlNetUsd": pnl,
                    "feeUsd": fee, "fundingUsd": 0.0, "funding_couvert": True,
                    "countFills": 2})
    return out


def fixture_oos_bon(n=200, seed=1):
    def jeu(s):
        rng = np.random.default_rng(s)
        p = rng.uniform(0.05, 0.95, n)
        y = (rng.uniform(0, 1, n) < p).astype(float)
        return (y, p)
    return G.DecoupageOOS(train=jeu(seed), calibration=jeu(seed + 1), test=jeu(seed + 2))


def fixture_contexte_complet():
    rng = np.random.default_rng(7)
    rend = list(rng.normal(6.0, 3.0, 200))
    trades = fixture_trades(300)
    return {
        "verdict_segmentation": type("V", (), {"etat": G.VERIFIED})(),
        "classification": OBSERVED,
        "decoupage": OOS.decouper(trades, classification=OBSERVED),
        "decoupage_oos": fixture_oos_bon(),
        "rendements": rend,
        "trades": trades,
        "metrique_train": 0.60,
        "metrique_oos": 0.55,
        "n_essais": 1,
        "n_tirages": 400,
    }


# =========================================================================== oos
def test_decoupage_ordre_temporel_strict():
    d = OOS.decouper(fixture_trades(300), classification=OBSERVED)
    assert d.train.fin <= d.calibration.debut <= d.calibration.fin <= d.test.debut


def test_decoupage_blocs_disjoints():
    d = OOS.decouper(fixture_trades(300), classification=OBSERVED)
    a, b, c = (set(x.indices) for x in d.blocs)
    assert not (a & b) and not (b & c) and not (a & c)


def test_decoupage_purge_retire_des_trades():
    d = OOS.decouper(fixture_trades(300), classification=OBSERVED,
                     purge=timedelta(days=3), embargo=timedelta(days=3))
    assert d.n_purges > 0
    assert d.train.n + d.calibration.n + d.test.n == d.n_total - d.n_purges


def test_decoupage_refuse_echantillon_court():
    with pytest.raises(InsufficientData) as e:
        OOS.decouper(fixture_trades(20), classification=OBSERVED)
    assert "au moins" in str(e.value)


def test_decoupage_refuse_parts_incoherentes():
    with pytest.raises(Exception):
        OOS.decouper(fixture_trades(300), classification=OBSERVED, parts=(0.5, 0.5, 0.5))


def test_decoupage_refuse_purge_negative():
    with pytest.raises(Exception):
        OOS.decouper(fixture_trades(300), classification=OBSERVED,
                     purge=timedelta(days=-1))


def test_conversion_vers_decoupage_oos():
    tr = fixture_trades(300)
    d = OOS.decouper(tr, classification=OBSERVED)
    probs = [0.5] * len(tr)
    dd = OOS.vers_decoupage_oos(d, tr, probs)
    assert len(dd.train[0]) == d.train.n
    assert set(dd.test[0]) <= {0.0, 1.0}


def test_conversion_refuse_probabilite_hors_bornes():
    tr = fixture_trades(300)
    d = OOS.decouper(tr, classification=OBSERVED)
    probs = [0.5] * len(tr)
    probs[d.train.indices[0]] = 1.5
    with pytest.raises(InsufficientData):
        OOS.vers_decoupage_oos(d, tr, probs)


# =========================================================================== final gate
def test_verified_si_toutes_les_conditions_tiennent():
    v = FG.evaluer(fixture_contexte_complet())
    assert v.etat == FG.VERIFIED, [c.nom + ":" + c.detail for c in v.echecs()]
    assert v.verifie and len(v.conditions) == len(FG.ORDRE)


def test_dry_run_ne_peut_jamais_valider():
    v = FG.evaluer(fixture_contexte_complet(), dry_run=True)
    assert v.etat == FG.DRY_RUN
    assert not v.verifie
    # la chaine a bien ete exercee : toutes les conditions sont evaluees
    assert all(c.evaluee for c in v.conditions)


def test_contexte_vide_refuse_sans_planter():
    v = FG.evaluer({})
    assert v.etat == FG.REFUSED
    assert len(v.echecs()) >= 1


def test_segmentation_non_validee_refuse():
    ctx = fixture_contexte_complet()
    ctx["verdict_segmentation"] = type("V", (), {"etat": G.INSUFFICIENT_DATA})()
    v = FG.evaluer(ctx)
    assert not v.verifie
    assert not v.par_nom(FG.SEGMENTATION).satisfaite


def test_source_derived_refuse_et_bloque_l_aval():
    ctx = fixture_contexte_complet()
    ctx["classification"] = DERIVED
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.SOURCE).satisfaite
    # les conditions dependant de la source ne doivent PAS etre evaluees
    for nom in (FG.DECOUPAGE, FG.ROBUSTESSE, FG.SENSIBILITE):
        c = v.par_nom(nom)
        assert not c.evaluee and FG.SOURCE in c.dependances_manquantes


def test_ece_trop_elevee_refuse():
    """Une probabilite constante est entierement corrigeable par l'isotonique : pour
    obtenir une ECE reellement mauvaise il faut une RUPTURE DE POPULATION entre le jeu
    de calibration et le test — le recalibrage apprend alors le mauvais taux de base."""
    n = 400
    rng = np.random.default_rng(3)
    p_ca = rng.uniform(0.6, 0.9, n)
    y_ca = (rng.uniform(0, 1, n) < 0.85).astype(float)      # taux de base eleve
    p_te = rng.uniform(0.6, 0.9, n)
    y_te = (rng.uniform(0, 1, n) < 0.10).astype(float)      # taux de base effondre
    ctx = fixture_contexte_complet()
    ctx["decoupage_oos"] = G.DecoupageOOS(train=(y_ca, p_ca), calibration=(y_ca, p_ca),
                                          test=(y_te, p_te))
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.ECE).satisfaite


def test_robustesse_absente_refuse():
    ctx = fixture_contexte_complet()
    ctx["rendements"] = list(np.random.default_rng(5).normal(0.0, 3.0, 200))
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.ROBUSTESSE).satisfaite


def test_sensibilite_aux_couts_refuse_si_net_negatif():
    ctx = fixture_contexte_complet()
    ctx["trades"] = fixture_trades(300, pnl=-1.0, fee=6.0)
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.SENSIBILITE).satisfaite


def test_stabilite_degradation_excessive_refuse():
    ctx = fixture_contexte_complet()
    ctx["metrique_train"], ctx["metrique_oos"] = 0.80, 0.10
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.STABILITE).satisfaite


def test_stabilite_non_mesurable_refuse():
    ctx = fixture_contexte_complet()
    ctx["metrique_oos"] = None
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.STABILITE).satisfaite


def test_concentration_excessive_refuse():
    ctx = fixture_contexte_complet()
    ctx["rendements"] = [0.1] * 199 + [500.0]
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.CONCENTRATION).satisfaite


def test_correction_tests_multiples_durcit_le_verdict():
    """
    Plus on a examine de candidats, plus le meme edge doit etre difficile a certifier.

    On teste l'INVARIANT, pas un nombre magique : la probabilite degonflee doit
    decroitre strictement quand n_essais croit, et un n_essais assez grand doit finir
    par refuser. Fixer un seuil en dur ferait dependre le test de la force de la
    fixture, donc casserait a la moindre correction de l'estimateur.
    """
    ctx = fixture_contexte_complet()
    probas = []
    for n in (1, 10, 1_000, 10**6, 10**12, 10**30):
        ctx["n_essais"] = n
        c = FG.evaluer(ctx).par_nom(FG.ROBUSTESSE)
        probas.append((n, c.satisfaite))
    # decroissance : une fois refusee, la condition ne doit jamais redevenir vraie
    vues_refus = False
    for _, ok in probas:
        if not ok:
            vues_refus = True
        else:
            assert not vues_refus, "le durcissement doit etre monotone en n_essais"
    assert not probas[-1][1], "un nombre d'essais assez grand doit finir par refuser"


def test_une_seule_condition_suffit_a_refuser():
    for cle, val in (("verdict_segmentation", None), ("classification", DERIVED),
                     ("rendements", None), ("metrique_oos", None)):
        ctx = fixture_contexte_complet()
        ctx[cle] = val
        assert not FG.evaluer(ctx).verifie


def test_panne_technique_n_est_pas_un_succes():
    ctx = fixture_contexte_complet()
    ctx["decoupage_oos"] = object()            # forme invalide -> exception interne
    v = FG.evaluer(ctx)
    assert not v.par_nom(FG.ECE).satisfaite
    assert not v.verifie


def test_dependances_declarees_coherentes():
    assert set(FG.DEPENDANCES) == set(FG.ORDRE)
    for nom, deps in FG.DEPENDANCES.items():
        for d in deps:
            assert FG.ORDRE.index(d) < FG.ORDRE.index(nom), f"{nom} depend d'un suivant"
    assert set(FG.independantes()) | set(FG.chaine_dependante()) == set(FG.ORDRE)
    assert FG.independantes() == [FG.SEGMENTATION, FG.SOURCE]


def test_resume_lisible():
    txt = FG.evaluer({}).resume()
    assert "FINAL_GATE" in txt and FG.REFUSED in txt
