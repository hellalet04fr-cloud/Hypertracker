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
    import ht.planificateur as P
    import ht.quota as Q

    etat = tmp_path / "project_state.json"
    # un verrou REEL : depuis que les taches descendent des verrous, un etat sans
    # verrou ne produit que les taches perennes — le fixture doit refleter cela.
    json.dump({"progression_pct": 75, "prochaine_action": "x",
               "verrous": [{"id": "CONFIRMATION_OBSERVED_TOP5", "statut": "OUVERT",
                            "mesure": "0/5 wallets du top-5 ont des natifs"}]},
              open(etat, "w"))
    monkeypatch.setattr(O, "DATA", str(tmp_path))
    monkeypatch.setattr(O, "ETAT", str(etat))
    monkeypatch.setattr(O, "TACHES", str(tmp_path / "tasks.json"))
    monkeypatch.setattr(O, "DECISIONS", str(tmp_path / "decisions.json"))
    # sans ce patch, stagnation() lirait le cycles.json de PRODUCTION : une fuite
    # d'etat reel dans les tests, qui les rendait dependants de l'historique.
    monkeypatch.setattr(O, "CYCLES", str(tmp_path / "cycles.json"))
    monkeypatch.setattr(P, "DATA", str(tmp_path))
    # sans cela, la tache d'audit relancerait pytest sur CE fichier, qui relancerait
    # un cycle, qui relancerait pytest : recursion infinie.
    monkeypatch.setattr(O, "TESTS_PAR_TACHE", {})
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


# ------------------------------------------------------- planification par verrous
def test_les_taches_descendent_des_verrous():
    """Une tache doit etre tracable a un verrou : c'est ce qui empeche l'improvisation."""
    import ht.planificateur as P
    etat = {"verrous": [{"id": "CONFIRMATION_OBSERVED_TOP5", "statut": "OUVERT",
                         "mesure": "0/5"}]}
    c, d = P.planifier(etat)
    ids = {x.id for x in c}
    assert "collecte_observed_top5" in ids and "verdict_observed" in ids
    assert all(x.verrou for x in c), "une tache sans verrou d'origine"
    assert not d


def test_un_verrou_inconnu_produit_un_diagnostic_pas_une_tache():
    """La frontiere de l'autonomie est dite, pas comblee par de l'invention."""
    import ht.planificateur as P
    c, d = P.planifier({"verrous": [{"id": "VERROU_JAMAIS_VU", "statut": "OUVERT"}]})
    assert d and "sans patron" in d[0]
    assert all(x.verrou == "(perenne)" for x in c)


def test_un_verrou_ferme_ne_produit_plus_de_tache():
    import ht.planificateur as P
    c, _ = P.planifier({"verrous": [{"id": "CONFIRMATION_OBSERVED_TOP5",
                                     "statut": "FERME"}]})
    assert "collecte_observed_top5" not in {x.id for x in c}


def test_chaque_candidate_est_arbitrable():
    """Objectif, raison, cout, gain, risque, conditions : sans quoi on ne peut
    pas decider sans l'executer."""
    import ht.planificateur as P
    c, _ = P.planifier({"verrous": [{"id": "CONFIRMATION_OBSERVED_TOP5",
                                     "statut": "OUVERT"}]})
    for x in c:
        assert x.objectif and x.raison and x.gain and x.risque
        assert x.condition_succes and x.condition_arret
        assert x.fichiers and x.roi > 0


# ------------------------------------------------------------ detection de boucle
def test_bloque_une_tache_qui_echoue_deux_fois_pareil(bac):
    """Reessayer une troisieme fois ne serait pas de la tenacite."""
    tmp, O = bac
    for _ in range(2):
        O._ajouter(O.DECISIONS, {"horodatage": "t", "tache": "collecte_observed_top5",
                                 "decision": "ECHEC",
                                 "motif": "connexion refusee par le serveur distant",
                                 "prochaine": ""})
    b = O.taches_bloquees()
    assert "collecte_observed_top5" in b


def test_un_seul_echec_ne_bloque_pas(bac):
    tmp, O = bac
    O._ajouter(O.DECISIONS, {"horodatage": "t", "tache": "collecte_observed_top5",
                             "decision": "ECHEC", "motif": "erreur passagere",
                             "prochaine": ""})
    assert "collecte_observed_top5" not in O.taches_bloquees()


def test_arrete_sur_stagnation(bac):
    """Plusieurs cycles sans progres arretent la boucle avec un diagnostic."""
    tmp, O = bac
    for _ in range(O.CYCLES_SANS_PROGRES_MAX):
        O._ajouter(O.CYCLES, {"horodatage": "t", "tache": "x", "decision": "REFUSEE",
                              "motif": "quota epuise", "etat_avant": "a",
                              "etat_apres": "a"})
    assert O.stagnation() is True
    r = O.cycle()
    assert r.decision == "STAGNATION"
    assert r.blocage, "une stagnation doit produire un diagnostic"


def test_la_stagnation_a_une_porte_de_sortie(bac):
    """Sans cela, un blocage passager deviendrait definitif apres correction."""
    tmp, O = bac
    for _ in range(O.CYCLES_SANS_PROGRES_MAX):
        O._ajouter(O.CYCLES, {"horodatage": "t", "tache": "x", "decision": "REFUSEE",
                              "motif": "quota epuise", "etat_avant": "a",
                              "etat_apres": "a"})
    r = O.cycle(ignorer_stagnation=True)
    assert r.decision != "STAGNATION", "aucune reprise possible apres stagnation"


def test_un_changement_detat_rompt_la_stagnation(bac):
    """C'est le changement d'etat qui compte, pas le succes d'execution."""
    tmp, O = bac
    for av, ap in (("a", "a"), ("a", "b"), ("b", "b")):
        O._ajouter(O.CYCLES, {"horodatage": "t", "tache": "x", "decision": "EXECUTEE",
                              "motif": "", "etat_avant": av, "etat_apres": ap})
    assert O.stagnation() is False


def test_des_cycles_verts_sans_effet_sont_une_stagnation(bac):
    """Une tache perenne qui reussit sans rien deplacer ne doit pas faire tourner
    la boucle indefiniment : mesure, elle avait tourne 20 fois."""
    tmp, O = bac
    for _ in range(O.CYCLES_SANS_PROGRES_MAX):
        O._ajouter(O.CYCLES, {"horodatage": "t", "tache": "audit_integrite",
                              "decision": "EXECUTEE", "motif": "sans erreur",
                              "etat_avant": "75% | x", "etat_apres": "75% | x"})
    assert O.stagnation() is True


def test_le_journal_de_cycle_est_complet(bac):
    """Les douze champs demandes doivent etre presents, pas seulement le resultat."""
    tmp, O = bac
    r = O.cycle(sec=True)
    j = r.journal(1)
    for champ in ("CYCLE", "OBJECTIF", "TACHE CHOISIE", "RAISON", "COUT", "RESULTAT",
                  "TESTS", "AUDIT", "ETAT AVANT", "ETAT APRES", "PROCHAINE TACHE"):
        assert champ in j, f"champ manquant du journal : {champ}"
