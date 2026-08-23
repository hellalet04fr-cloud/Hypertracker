"""
La couche d'autonomie ne vaut que si ses refus sont verifies.

Un garde-fou qu'on n'a jamais vu bloquer est une hypothese, pas une protection. Ces
tests provoquent chaque refus deliberement : branche abandonnee, seuil deplace, sceau
rompu, quota epuise, rendement insuffisant.
"""
from __future__ import annotations

import json
import sqlite3

import pytest


# ------------------------------------------------------------------------- gardes
def test_refuse_les_branches_abandonnees():
    import ht.garde as G
    for t in ("optimiser le TP/SL du liquidity sweep",
              "chercher un edge de trading",
              "backtest de strategie sur les wallets",
              "ameliorer l'execution maker/taker"):
        v = G.verifier_derive(t)
        assert not v, f"la derive n'a pas ete bloquee : {t}"
        assert "abandonnee" in v.motifs[0]


def test_refuse_ce_qui_ne_sert_pas_le_produit():
    import ht.garde as G
    assert not G.verifier_derive("refactoriser le systeme de journalisation general")
    assert G.verifier_derive("collecter les natifs OBSERVED du top-5 de wallets")


def test_detecte_un_seuil_deplace(monkeypatch):
    """Le cas le plus dangereux : le test passe PARCE QUE le seuil a bouge."""
    import ht.gate as GA
    import ht.garde as G
    assert G.verifier_seuils(), "les seuils devraient etre conformes au depart"
    monkeypatch.setattr(GA, "MAX_ECE_CERTIFIEE", 0.50)
    v = G.verifier_seuils()
    assert not v, "un seuil deplace n'a pas ete detecte"
    assert any("SEUIL DEPLACE" in m for m in v.motifs)


def test_detecte_un_sceau_rompu(tmp_path):
    import ht.garde as G
    p = tmp_path / "preenregistrement_observed.json"
    json.dump({"top5": ["0xaaa"], "sha256": "0" * 64}, open(p, "w"))
    v = G.verifier_scelles(str(tmp_path))
    assert not v
    assert any("SCEAU ROMPU" in m for m in v.motifs)


def test_derived_ne_certifie_jamais():
    import ht.garde as G
    from ht.schema import DERIVED, OBSERVED
    assert not G.verifier_provenance(DERIVED, "certification")
    assert G.verifier_provenance(OBSERVED, "certification")
    assert G.verifier_provenance(DERIVED, "criblage")


# ------------------------------------------------------------------------ budgets
def test_refuse_si_le_quota_est_epuise():
    import ht.budgets as B
    e = B.Etat(ht_restant=0, ht_epuise=True, hl_par_minute=30, cpu_max_s=1800)
    ok, motif = B.autorise(B.Cout(hypertracker=1), roi=100.0, e=e)
    assert not ok and "refuse par le serveur" in motif


def test_refuse_si_le_cout_depasse_le_reliquat():
    import ht.budgets as B
    e = B.Etat(ht_restant=3, ht_epuise=False, hl_par_minute=30, cpu_max_s=1800)
    ok, motif = B.autorise(B.Cout(hypertracker=5), roi=100.0, e=e)
    assert not ok and "disponibles" in motif


def test_refuse_un_rendement_insuffisant():
    """Pouvoir se le permettre ne suffit pas : c'est la difference entre
    un budget et un solde."""
    import ht.budgets as B
    e = B.Etat(ht_restant=100, ht_epuise=False, hl_par_minute=30, cpu_max_s=1800)
    ok, motif = B.autorise(B.Cout(hypertracker=10), roi=0.5, e=e)
    assert not ok and "rendement insuffisant" in motif
    ok2, _ = B.autorise(B.Cout(hypertracker=10), roi=50.0, e=e)
    assert ok2


def test_refuse_un_cpu_hors_plafond():
    import ht.budgets as B
    e = B.Etat(ht_restant=100, ht_epuise=False, hl_par_minute=30, cpu_max_s=60)
    ok, motif = B.autorise(B.Cout(cpu_s=600), roi=100.0, e=e)
    assert not ok and "CPU" in motif


# ------------------------------------------------------------------ orchestrateur
@pytest.fixture
def bac(tmp_path, monkeypatch):
    import ht.orchestrateur as O
    import ht.quota as Q

    etat = tmp_path / "project_state.json"
    json.dump({"progression_pct": 75, "verrous": [], "prochaine_action": "x"},
              open(etat, "w"))
    monkeypatch.setattr(O, "DATA", str(tmp_path))
    monkeypatch.setattr(O, "ETAT", str(etat))
    monkeypatch.setattr(O, "TACHES", str(tmp_path / "tasks.json"))
    monkeypatch.setattr(O, "DECISIONS", str(tmp_path / "decisions.json"))
    monkeypatch.setattr(Q, "DATA", str(tmp_path))
    monkeypatch.setattr(Q, "LEDGER", str(tmp_path / "ledger.db"))
    with sqlite3.connect(tmp_path / "ledger.db") as c:
        c.execute("""CREATE TABLE IF NOT EXISTS closed_trades_natifs(
            address TEXT, fenetre TEXT, observed_at TEXT, payload TEXT)""")
    json.dump({"top5": [f"0x{i:040x}" for i in range(5)], "sha256": "z"},
              open(tmp_path / "preenregistrement_observed.json", "w"))
    return tmp_path, O


def test_bloque_tout_si_lintegrite_est_rompue(bac, monkeypatch):
    tmp, O = bac
    import ht.garde as G
    monkeypatch.setattr(G, "verifier_seuils",
                        lambda: G.Verdict(False, ["seuil deplace pour le test"]))
    r = O.cycle()
    assert r.decision == "BLOQUEE"
    assert "seuil deplace" in r.motif


def test_choisit_la_tache_executable_la_plus_rentable(bac, monkeypatch):
    """Quota epuise : la tache a ROI 10 est ecartee, l'audit local passe."""
    tmp, O = bac
    import ht.quota as Q
    Q.journaliser("closed-trades", "0x0", 429)
    r = O.cycle()
    assert r.decision == "EXECUTEE"
    assert r.tache == "audit_integrite", f"tache retenue : {r.tache}"


def test_journalise_les_refus(bac):
    """Sans trace des refus, une session future ignore qu'une tache prioritaire
    existait mais etait bloquee."""
    tmp, O = bac
    import ht.quota as Q
    Q.journaliser("closed-trades", "0x0", 429)
    O.cycle()
    d = json.load(open(tmp / "decisions.json"))
    assert any(x["decision"] == "NON_RETENUE" for x in d), "aucun refus journalise"
    assert any("collecte_observed_top5" in x["tache"] for x in d)


def test_reprend_apres_interruption(bac):
    """Rien ne vit en memoire : deux cycles successifs repartent du disque."""
    tmp, O = bac
    import ht.quota as Q
    Q.journaliser("closed-trades", "0x0", 429)
    O.cycle()
    O.cycle()
    t = json.load(open(tmp / "tasks.json"))
    assert len(t) == 2, f"{len(t)} taches journalisees au lieu de 2"
    assert all(x["horodatage"] for x in t)


def test_execution_a_blanc_ne_consomme_rien(bac):
    tmp, O = bac
    r = O.cycle(sec=True)
    assert r.decision == "REFUSEE" and "blanc" in r.motif
