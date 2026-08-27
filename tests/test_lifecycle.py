#!/usr/bin/env python3
"""
Tests du cycle de vie, du registre, des alertes et du cycle du matin.

RAPIDES PAR CONSTRUCTION : aucune requete reseau, aucun acces au lac de donnees,
aucune base de production. Le registre est cree en memoire ou dans le repertoire
temporaire du test. Ils sont donc utilisables comme garde-fou de regression, ce
que les tests marques `reel` ne peuvent pas etre.
"""
from __future__ import annotations

import json
import math
import os
import time

import pytest

from ht import alertes as A
from ht import classement as CL
from ht import lifecycle as L
from ht import registre as R
from ht import scoring as SC


# =============================================================== fixtures
@pytest.fixture()
def base(tmp_path):
    """Registre neuf, isole de la production."""
    c = R.connexion(str(tmp_path / "registre.db"))
    yield c
    c.close()


def metriques(**kw) -> dict:
    """Metriques d'un wallet largement qualifie, que chaque test degrade a sa guise."""
    m = {"n": 300, "jours": 400.0, "conc": 0.15, "troncature": 0.01, "qualite": 3}
    m.update(kw)
    return m


# ================================================ AUCUNE DERIVE SCIENTIFIQUE
# Ces tests existent pour une raison precise : les primitives de score ont ete
# DEPLACEES d'un script hors depot vers ht/scoring.py. Deplacer ne doit pas
# modifier. Si l'une d'elles derivait, meme au dernier chiffre, ces tests
# tomberaient avant que le classement ne change en silence.
def test_sharpe_valeur_exacte():
    r = [1.0, -1.0, 2.0, -2.0, 3.0]
    attendu = (0.6) / math.sqrt(sum((x - 0.6) ** 2 for x in r) / len(r))
    assert SC.sharpe(r) == pytest.approx(attendu, abs=1e-15)


def test_sharpe_refuse_sans_dispersion():
    assert SC.sharpe([2.0, 2.0, 2.0]) is None       # ecart type nul
    assert SC.sharpe([1.0]) is None                  # un seul point


def test_se_sharpe_correction_mertens():
    r = [1.0, -1.0, 2.0, -2.0, 3.0, 0.5, -0.5]
    v = SC.se_sharpe(r)
    assert v is not None and v > 0
    assert SC.se_sharpe([1.0, 2.0]) is None          # moins de trois points


def test_concentration_est_la_part_ABSOLUE_bornee():
    """La metrique de production, declaree par classement_wallets.json elle-meme :
    part absolue = max|r| / somme|r|, bornee [0,1]. La formulation naive
    max(r)/somme(r) etait indefinie pour 163 wallets sur 231 et atteignait 34.38."""
    assert SC.concentration([3.0, 1.0, 1.0]) == pytest.approx(3 / 5)
    # un PnL total NEGATIF garde une concentration definie et bornee
    c = SC.concentration([-10.0, 1.0, 1.0])
    assert c == pytest.approx(10 / 12)
    assert 0.0 <= c <= 1.0
    assert SC.concentration([0.0, 0.0]) is None      # aucun mouvement


def test_drawdown_part_du_sommet_zero():
    """Convention du moteur : le sommet demarre a 0, pas au premier point.
    S'en ecarter donnait jusqu'a 5 499 USD d'ecart sur la population livree."""
    assert SC.drawdown([-5.0, 2.0]) == pytest.approx(5.0)
    assert SC.drawdown([10.0, -4.0, 1.0]) == pytest.approx(4.0)
    assert SC.drawdown([1.0, 2.0, 3.0]) == pytest.approx(0.0)


def test_apriori_deconvolution_retire_le_bruit():
    srs = [0.1, 0.2, 0.3, 0.4, 0.5]
    ses = [0.05] * 5
    m, tau2 = SC.apriori(srs, ses)
    assert m == pytest.approx(0.3)
    assert tau2 == pytest.approx(SC.mad(srs) ** 2 - 0.05 ** 2, abs=1e-12)
    # jamais negatif, meme quand le bruit domine toute la dispersion
    _, t2 = SC.apriori([0.1, 0.1, 0.1], [10.0, 10.0, 10.0])
    assert t2 > 0


def test_seuils_de_qualification_inchanges():
    """Aucun seuil n'a ete invente ni deplace pour ce chantier."""
    from ht import screening as S
    assert (S.MIN_TRADES, S.MIN_JOURS, S.MAX_CONCENTRATION, S.MAX_TRONCATURE) \
        == (30, 130.0, 0.40, 0.20)
    assert (CL.MIN_TRADES_FIABLE, CL.MAX_CONC, CL.MIN_JOURS) == (150, 0.40, 130.0)
    assert SC.MIN_TRADES == 30


def test_la_garde_refuse_un_seuil_modifie(monkeypatch):
    """Modifier un seuil scelle doit etre REFUSE, pas seulement signale."""
    from ht import garde as G
    assert G.verifier_seuils().autorise
    monkeypatch.setattr("ht.ranking.MIN_TRADES_FOR_RANKING", 5, raising=False)
    v = G.verifier_seuils()
    assert not v.autorise, "un seuil abaisse doit faire echouer la garde"


def test_derived_ne_certifie_jamais():
    from ht import garde as G
    assert not G.verifier_provenance("DERIVED", "certification").autorise
    assert G.verifier_provenance("OBSERVED", "certification").autorise


# ====================================================== QUALIFICATION
def test_candidat_valide_est_qualifie():
    v = L.qualifies_for_ranking(metriques())
    assert v.classe == L.EXCELLENT and v.qualifie


def test_candidat_prometteur_est_qualifie_mais_signale():
    v = L.qualifies_for_ranking(metriques(n=60, qualite=2))
    assert v.classe == L.PROMETTEUR and v.qualifie
    assert any("qualite de donnees" in x for x in v.raisons)


def test_trop_peu_de_trades_reste_en_observation():
    v = L.qualifies_for_ranking(metriques(n=10))
    assert v.classe == L.DONNEES_INSUFFISANTES and not v.qualifie
    assert v.refute, "un compte de trades est exact : il refute vraiment"


def test_concentration_excessive_est_rejetee():
    v = L.qualifies_for_ranking(metriques(conc=0.71))
    assert v.classe == L.REJETE and not v.qualifie and v.refute


def test_troncature_excessive_est_rejetee():
    v = L.qualifies_for_ranking(metriques(troncature=0.55))
    assert v.classe == L.REJETE and v.refute


def test_wallet_inconnu_n_est_pas_rejete_mais_insuffisant():
    """Un wallet sans aucune donnee n'est pas un mauvais wallet : c'est un wallet
    dont on ne sait rien. Le REJETER le priverait de toute chance d'etre reexamine."""
    v = L.qualifies_for_ranking({})
    assert v.classe == L.DONNEES_INSUFFISANTES


def test_anciennete_courte_n_est_pas_une_refutation():
    """`jours` mesure l'ecart entre le premier et le dernier trade CLOS ; le seuil
    porte sur les JOURS COUVERTS, toujours superieurs. Un ecart court ne refute
    donc rien — mesure : 33 wallets sur 231 auraient ete archives a tort."""
    v = L.qualifies_for_ranking(metriques(jours=40.0))
    assert not v.qualifie
    assert not v.refute, "critere non concluant, donc non refute"
    assert v.indetermines
    part, _ = L.doit_archiver(metriques(jours=40.0))
    assert part is False, "on ne retire pas sur une absence de preuve"


def test_jours_couverts_connus_refutent_vraiment():
    v = L.qualifies_for_ranking(metriques(jours_couverts=40.0))
    assert v.refute and not v.qualifie


def test_troncature_inconnue_est_declaree_pas_supposee():
    v = L.qualifies_for_ranking(metriques(troncature=None))
    assert v.qualifie
    assert any("troncature" in x for x in v.indetermines)


# ====================================================== TRANSITIONS
def test_nouveau_wallet_entre_en_discovery(base):
    assert R.enregistrer_decouverte(base, "0xAB", "carnet") is True
    assert R.wallet(base, "0xab")["statut"] == R.DISCOVERY


def test_decouverte_dupliquee_ne_cree_rien(base):
    R.enregistrer_decouverte(base, "0xab", "carnet")
    assert R.enregistrer_decouverte(base, "0xAB", "leaderboard") is False
    assert R.wallet(base, "0xab")["source"] == "carnet", "la provenance d'origine est un fait"
    assert R.compter(base)[R.DISCOVERY] == 1


def test_discovery_qualifie_devient_ranked():
    cible, _ = L.etat_cible(metriques(), R.DISCOVERY)
    assert cible == R.RANKED


def test_discovery_insuffisant_reste_discovery():
    cible, _ = L.etat_cible(metriques(n=5), R.DISCOVERY)
    assert cible == R.DISCOVERY


def test_ranked_degrade_devient_archived():
    cible, raison = L.etat_cible(metriques(conc=0.9), R.RANKED)
    assert cible == R.ARCHIVED and raison.startswith(L.RAISON_DEGRADATION)


def test_archived_requalifie_revient_en_ranked():
    cible, raison = L.etat_cible(metriques(), R.ARCHIVED)
    assert cible == R.RANKED and raison == L.RAISON_RETOUR


def test_archived_non_qualifie_reste_archived():
    """Le renvoyer en DISCOVERY effacerait son motif de retrait et sa date."""
    cible, _ = L.etat_cible(metriques(conc=0.9), R.ARCHIVED)
    assert cible == R.ARCHIVED


def test_watchlist_protege_de_l_archivage():
    part, raison = L.doit_archiver(metriques(n=1, conc=0.99), watch=True)
    assert part is False and "suivi manuellement" in raison


def test_watchlist_persistee(base):
    R.enregistrer_decouverte(base, "0xab", "carnet")
    R.suivre(base, "0xab", True)
    assert R.compter(base)["watch"] == 1


# ====================================================== HISTORIQUE
def test_historique_jamais_supprime(base):
    R.enregistrer_decouverte(base, "0xab", "carnet")
    for statut, raison in ((R.RANKED, "qualifie"), (R.ARCHIVED, "degradation"),
                           (R.RANKED, "requalified")):
        R.transition(base, "0xab", statut, raison, metriques={"score": 50.0, "rang": 3})
    h = R.historique(base, "0xab")
    assert len(h) == 3, "chaque transition laisse une trace"
    assert [x["raison"] for x in h] == ["requalified", "degradation", "qualifie"]
    assert R.wallet(base, "0xab")["archive_raison"] is None, \
        "le retour au classement efface le motif d'archivage, pas l'historique"


def test_archivage_conserve_motif_et_date(base):
    R.enregistrer_decouverte(base, "0xab", "carnet")
    R.transition(base, "0xab", R.ARCHIVED, L.RAISON_DEGRADATION)
    w = R.wallet(base, "0xab")
    assert w["archive_raison"] == L.RAISON_DEGRADATION and w["archive_le"]


def test_priorite_de_reevaluation(base):
    for a, st in (("0x1", R.DISCOVERY), ("0x2", R.RANKED), ("0x3", R.ARCHIVED)):
        R.enregistrer_decouverte(base, a, "test")
        R.transition(base, a, st, "mise en place")
        R.marquer_sale(base, [a], True)
    assert R.a_reevaluer(base)[0] == "0x2", "un wallet classe passe avant tout"


# ====================================================== ALERTES
def test_alertes_dedupliquees(base):
    e = [{"categorie": A.RANK_UP, "adresse": "0xab", "message": "monte"}]
    assert A.emettre(base, "c1", e) == 1
    assert A.emettre(base, "c2", e) == 0, "meme evenement, meme jour : une seule alerte"


def test_croissance_de_population_ne_declenche_pas_de_baisse():
    """43 fausses alertes mesurees sur un cycle reel : neuf wallets entrent, tous
    ceux du dessous perdent des places sans avoir decline."""
    avant = {f"0x{i}": {"rang": i} for i in range(1, 101)}
    apres = dict(avant)
    rangs = {a: v["rang"] + 9 for a, v in avant.items()}
    ev = A.comparer(avant, apres, nouveaux_rangs=rangs, n_avant=100, n_apres=109)
    assert not [x for x in ev if x["categorie"] == A.RANK_DOWN]


def test_vraie_chute_de_rang_est_signalee():
    avant = {"0xab": {"rang": 5}}
    apres = {"0xab": {}}
    ev = A.comparer(avant, apres, nouveaux_rangs={"0xab": 80}, n_avant=100, n_apres=100)
    assert [x["categorie"] for x in ev] == [A.RANK_DOWN]


def test_nouveau_remarquable_exige_qualification_ET_rang():
    """Jamais sur le PnL seul : un wallet qui n'est pas EXCELLENT n'est pas signale,
    quel que soit son gain."""
    riche = {"0xab": {"classe": L.PROMETTEUR, "n": 40, "qualite": 2, "pnl": 9e9}}
    ev = A.comparer({}, riche, nouveaux_rangs={"0xab": 1}, n_avant=1, n_apres=1)
    assert not ev
    bon = {"0xab": {"classe": L.EXCELLENT, "n": 400, "qualite": 3}}
    ev = A.comparer({}, bon, nouveaux_rangs={"0xab": 3}, n_avant=1, n_apres=1)
    assert [x["categorie"] for x in ev] == [A.NEW_WALLET]


def test_nouveau_hors_du_top_n_alerte_pas():
    bon = {"0xab": {"classe": L.EXCELLENT, "n": 400, "qualite": 3}}
    ev = A.comparer({}, bon, nouveaux_rangs={"0xab": 150}, n_avant=1, n_apres=1)
    assert not ev


# ====================================================== QUOTA
def test_quota_le_429_fait_autorite(tmp_path, monkeypatch):
    """Le compteur local a deja diverge de la realite (100, puis 98, puis 76) :
    seule la reponse du serveur fait foi."""
    from ht import quota as Q
    monkeypatch.setattr(Q, "LEDGER", str(tmp_path / "l.db"))
    assert Q.epuise() is False
    Q.journaliser("/api/external/closed-trades", "0xab", 200)
    assert Q.epuise() is False
    Q.journaliser("/api/external/closed-trades", "0xab", 429)
    assert Q.epuise() is True, "un 429 epuise, quel que soit le compteur local"


def test_le_cycle_ne_depense_aucun_quota_hypertracker():
    """Propriete structurelle : aucune source du cycle n'appelle HyperTracker."""
    import inspect
    from ht import decouverte, matin
    for mod in (matin, decouverte):
        src = inspect.getsource(mod)
        assert "closed-trades" not in src and "api/external" not in src


# ====================================================== DONNEES MANQUANTES
def test_aucune_valeur_inventee_pour_une_donnee_absente():
    """Une metrique absente ne devient jamais une valeur favorable."""
    v = L.qualifies_for_ranking({"n": 300, "jours": 400.0, "conc": None,
                                 "troncature": None})
    assert "concentration non calculable" in " ".join(v.indetermines)
    assert v.classe != L.EXCELLENT


def test_probabilite_absente_reste_absente():
    """Le modele isotonique n'etant pas persiste, un wallet nouveau n'a PAS de
    probabilite calibree — il n'en a pas une qui vaudrait zero."""
    doc = {"classement": [{"a": "0xab", "p_comp": 0.9}, {"a": "0xcd", "p_comp": 0.1}]}
    out = CL.reporter_p_cal(doc, {"classement": [{"a": "0xab", "p_cal": 0.77}]})
    assert out["classement"][0]["p_cal"] == 0.77
    assert out["classement"][1]["p_cal"] is None
    assert out["sans_p_cal"] == 1


# ====================================================== PLANIFICATION
def test_fuseau_europe_paris_pas_un_decalage_fixe():
    from ht import planifier as P
    ok, motif = P.coherence_horaire()
    assert isinstance(ok, bool) and "Europe/Paris" in motif or "coincide" in motif


def test_la_commande_planifiee_lance_bien_le_cycle():
    from ht import planifier as P
    assert "ht.matin" in P.commande()
    assert P.HEURE == "08:00" and P.ZONE == "Europe/Paris"


# ====================================================== REPRISE
def test_registre_survit_a_une_reouverture(tmp_path):
    """Reprise apres arret brutal : l'etat se relit, il n'est pas en memoire."""
    chemin = str(tmp_path / "r.db")
    c = R.connexion(chemin)
    R.enregistrer_decouverte(c, "0xab", "carnet")
    R.transition(c, "0xab", R.RANKED, "qualifie", metriques={"score": 42.0, "rang": 1})
    c.commit()
    c.close()
    c2 = R.connexion(chemin)
    assert R.wallet(c2, "0xab")["statut"] == R.RANKED
    assert len(R.historique(c2, "0xab")) == 1
    c2.close()


def test_cycle_journalise_ce_qu_il_decide(base):
    R.ouvrir_cycle(base, "c1", "reel")
    R.journaliser(base, "c1", "LIFECYCLE", "transition", adresse="0xab",
                  statut_avant=R.DISCOVERY, statut_apres=R.RANKED, raison="qualifie")
    R.fermer_cycle(base, "c1", "OK", "{}")
    base.commit()
    j = base.execute("select * from journal where cycle_id='c1'").fetchall()
    assert len(j) == 1 and j[0]["raison"] == "qualifie"
    assert R.dernier_cycle(base)["resultat"] == "OK"


# ====================================================== RAPPORT
def test_rapport_quotidien_a_les_sections_exigees(tmp_path, monkeypatch):
    from ht import matin as M
    monkeypatch.setattr(M, "SERIES", str(tmp_path / "s.json"))
    monkeypatch.setattr(M, "CLASSEMENT", str(tmp_path / "c.json"))
    monkeypatch.setattr(M, "RAPPORT", str(tmp_path / "r.json"))
    monkeypatch.setattr(R, "BASE", str(tmp_path / "reg.db"))
    json.dump({}, open(M.SERIES, "w"))

    cy = M.Cycle(dry_run=True)
    cy.p1_data()
    cy.phases["DISCOVERY"] = {"nouveaux": 0}
    cy.p3_evaluation()
    cy.p4_ranking()
    cy.p5_lifecycle()
    cy.p6_alerts()
    cy.p7_report()
    r = cy.rapport
    for cle in ("new_today", "top_movers", "declining", "archived", "top20",
                "data_health", "system_health", "cycle_id", "mode"):
        assert cle in r, f"section « {cle} » absente du rapport"
    assert r["mode"] == "dry-run"
    assert r["data_health"]["requetes_hypertracker_utilisees"] == 0
    cy.c.close()


def test_dry_run_n_ecrit_rien(tmp_path, monkeypatch):
    from ht import matin as M
    monkeypatch.setattr(M, "SERIES", str(tmp_path / "s.json"))
    monkeypatch.setattr(M, "CLASSEMENT", str(tmp_path / "c.json"))
    monkeypatch.setattr(M, "RAPPORT", str(tmp_path / "r.json"))
    monkeypatch.setattr(R, "BASE", str(tmp_path / "reg.db"))
    json.dump({}, open(M.SERIES, "w"))
    cy = M.Cycle(dry_run=True)
    cy.p1_data(); cy.p3_evaluation(); cy.p4_ranking(); cy.p5_lifecycle()
    cy.p6_alerts(); cy.p7_report()
    assert not os.path.exists(M.RAPPORT), "le dry-run ne doit produire aucun fichier"
    assert not os.path.exists(M.CLASSEMENT)
    assert R.compter(cy.c)[R.RANKED] == 0, "le dry-run ne doit rien promouvoir"
    cy.c.close()


def test_dry_run_de_collecte_ne_fait_aucune_requete(tmp_path, monkeypatch):
    from ht import matin as M
    monkeypatch.setattr(M, "SERIES", str(tmp_path / "s.json"))
    monkeypatch.setattr(R, "BASE", str(tmp_path / "reg.db"))
    json.dump({}, open(M.SERIES, "w"))
    cy = M.Cycle(dry_run=True)
    R.enregistrer_decouverte(cy.c, "0xab", "carnet")
    cy.c.commit()

    def interdit(*a, **k):                       # pragma: no cover
        raise AssertionError("aucune requete ne doit partir en dry-run")
    monkeypatch.setattr("ht.screening.trier", interdit)
    b = cy.p2b_collecte(10)
    assert b["requetes"] == 0 and b["series_ajoutees"] == 0
    cy.c.close()
