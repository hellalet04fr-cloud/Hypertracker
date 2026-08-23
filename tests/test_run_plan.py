"""
Tests de l'executeur du plan (ht/run_plan.py). AUCUN appel reseau : toutes les
fonctions qui toucheraient l'API sont soit non appelees, soit simulees.

Ce qui est verifie : le budget ne peut pas etre depasse, le compteur est par jour UTC
et survit a un redemarrage, la deduplication des resumes tient, et une interruption
laisse un etat exactement reprenable.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def rp(tmp_path, monkeypatch):
    """Instance isolee : ledger dans tmp_path, aucun contact avec le vrai depot."""
    monkeypatch.setenv("HT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HT_BUDGET", "100")
    for m in [k for k in list(sys.modules) if k.startswith("ht.run_plan")]:
        del sys.modules[m]
    import ht.run_plan as module
    monkeypatch.setattr(module, "DATA", str(tmp_path))
    monkeypatch.setattr(module, "LEDGER", os.path.join(str(tmp_path), "ledger.db"))
    monkeypatch.setattr(module, "QUOTA_JOUR", 100)
    return module


# =========================================================================== budget
def test_compteur_demarre_a_zero(rp):
    assert rp.depense(0) == 0
    assert rp.reste() == 100


def test_compteur_s_incremente_et_persiste(rp):
    rp.depense(10)
    rp.depense(5)
    assert rp.depense(0) == 15
    assert rp.reste() == 85
    # simulation d'un redemarrage : nouvelle connexion sur le meme fichier
    assert rp.depense(0) == 15


def test_reste_ne_devient_jamais_negatif(rp):
    rp.depense(250)
    assert rp.reste() == 0


def test_compteur_est_par_jour_utc(rp):
    rp.depense(40)
    j = rp._jour()
    assert j == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with rp._db() as c:
        lignes = c.execute("SELECT jour, used FROM spend").fetchall()
    assert lignes == [(j, 40)]
    # une autre journee repart de zero, sans effacer la precedente
    with rp._db() as c:
        c.execute("INSERT INTO spend(jour, used) VALUES('2020-01-01', 99)")
        n = c.execute("SELECT COUNT(*) FROM spend").fetchone()[0]
    assert n == 2
    assert rp.depense(0) == 40


def test_budget_epuise_ne_lance_rien(rp, capsys, monkeypatch):
    """Garde-fou principal : aucune etape ne doit demarrer si le budget est a zero."""
    rp.depense(100)
    appelee = {"perissables": False}

    def _ne_doit_pas_etre_appelee():
        appelee["perissables"] = True
        return True, ""

    monkeypatch.setattr(rp, "etape_perissables", _ne_doit_pas_etre_appelee)
    code = rp.main()
    assert code == 0
    assert appelee["perissables"] is False
    assert "epuise" in capsys.readouterr().out


# =========================================================================== resumes
def test_resumes_dedupliques(rp, monkeypatch):
    """Une adresse deja resumee ne doit jamais etre redemandee : c'est ce qui garantit
    qu'une reprise apres interruption ne redepense pas les requetes deja payees."""
    a1, a2 = "0x" + "1" * 40, "0x" + "2" * 40
    with rp._db() as c:
        c.execute("INSERT INTO summaries VALUES(?,?,?)", (a1, "2026-01-01", "{}"))

    demandees = []

    def faux_urlopen(req, timeout=0):
        demandees.append(req.full_url)
        raise RuntimeError("coupe volontairement : aucun reseau en test")

    monkeypatch.setenv("HT_TOKEN", "factice")
    monkeypatch.setattr(rp.urllib.request, "urlopen", faux_urlopen)
    rp.etape_resumes([a1, a2], budget=10)
    assert len(demandees) == 1
    assert a2 in demandees[0] and a1 not in demandees[0]


def test_resumes_respectent_le_budget(rp, monkeypatch):
    adresses = [f"0x{i:040x}" for i in range(50)]
    demandees = []

    def faux_urlopen(req, timeout=0):
        demandees.append(req.full_url)
        raise RuntimeError("coupe volontairement")

    monkeypatch.setenv("HT_TOKEN", "factice")
    monkeypatch.setattr(rp.urllib.request, "urlopen", faux_urlopen)
    rp.etape_resumes(adresses, budget=7)
    assert len(demandees) == 7


def test_resumes_budget_nul_ne_demande_rien(rp, monkeypatch):
    appels = []
    monkeypatch.setattr(rp.urllib.request, "urlopen",
                        lambda *a, **k: appels.append(1))
    assert rp.etape_resumes(["0x" + "3" * 40], budget=0) == 0
    assert appels == []


def test_resumes_s_arretent_sur_429(rp, monkeypatch):
    """Aucun retry agressif : un 429 stoppe la boucle au lieu de marteler l'API."""
    import io
    import urllib.error

    adresses = [f"0x{i:040x}" for i in range(20)]
    appels = []

    def faux_urlopen(req, timeout=0):
        appels.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b"{}"))

    monkeypatch.setenv("HT_TOKEN", "factice")
    monkeypatch.setattr(rp.urllib.request, "urlopen", faux_urlopen)
    obtenus = rp.etape_resumes(adresses, budget=20)
    assert obtenus == 0
    assert len(appels) == 1          # arret immediat, pas 20 tentatives


# =========================================================================== reprise
def test_adresses_leaderboards_vide_sans_donnees(rp):
    assert rp.adresses_leaderboards() == []


def test_archive_budget_nul_ne_fait_rien(rp):
    assert rp.etape_archive(0) == 0


# =========================================================================== natifs + portail
def test_adresses_derivees_vide_sans_parquet(rp):
    assert rp.adresses_derivees() == []


def test_natifs_budget_nul_ne_demande_rien(rp, monkeypatch):
    appels = []
    monkeypatch.setattr(rp.urllib.request, "urlopen", lambda *a, **k: appels.append(1))
    assert rp.etape_natifs(["0x" + "1" * 40], budget=0) == 0
    assert appels == []


def test_natifs_dedupliques_et_bornes(rp, monkeypatch):
    adresses = [f"0x{i:040x}" for i in range(30)]
    demandees = []

    def faux(req, timeout=0):
        demandees.append(req.full_url)
        raise RuntimeError("coupe volontairement : aucun reseau en test")

    monkeypatch.setenv("HT_TOKEN", "factice")
    monkeypatch.setattr(rp.urllib.request, "urlopen", faux)
    rp.etape_natifs(adresses, budget=6)
    assert len(demandees) == 6
    assert all("closed-trades?address=" in u for u in demandees)


def test_natifs_s_arretent_sur_429(rp, monkeypatch):
    import io
    import urllib.error
    appels = []

    def faux(req, timeout=0):
        appels.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b"{}"))

    monkeypatch.setenv("HT_TOKEN", "factice")
    monkeypatch.setattr(rp.urllib.request, "urlopen", faux)
    assert rp.etape_natifs([f"0x{i:040x}" for i in range(10)], budget=10) == 0
    assert len(appels) == 1


def test_portail_sans_donnees_rend_not_ready(rp, capsys):
    """L'enchainement automatique constate sans requete et ne leve jamais."""
    import ht.gate as G
    assert rp.etape_gate() == G.NOT_READY
    assert "GATE" in capsys.readouterr().out
