"""
Le lot qui depensera le quota HyperTracker doit etre verifie AVANT de le depenser.

Une fenetre de quota vaut 100 requetes et ne revient qu'a 03:00 UTC. Un bug dans
`etape_top5` — mauvaise borne, boucle qui ne s'arrete pas, refus mal traite — la
gaspillerait entierement et couterait une journee au projet. Ces tests remplacent le
transport HTTP par un double : aucune requete reelle, mais toute la logique de decision
est exercee.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def bac(tmp_path, monkeypatch):
    """Un ledger et un classement jetables : aucun contact avec les donnees reelles."""
    import ht.quota as Q
    import ht.run_plan as RP

    monkeypatch.setattr(RP, "DATA", str(tmp_path))
    monkeypatch.setattr(RP, "LEDGER", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(Q, "DATA", str(tmp_path))
    monkeypatch.setattr(Q, "LEDGER", str(tmp_path / "ledger.db"))
    monkeypatch.setattr("ht.perishable._token", lambda: "jeton-de-test")

    with open(tmp_path / "classement_wallets.json", "w") as f:
        json.dump({"classement": [{"a": f"0x{i:040x}", "score": 100 - i} for i in range(8)]}, f)
    with sqlite3.connect(tmp_path / "ledger.db") as c:
        c.execute("""CREATE TABLE IF NOT EXISTS closed_trades_natifs(
            address TEXT, fenetre TEXT, observed_at TEXT, payload TEXT,
            PRIMARY KEY(address, fenetre))""")
    return tmp_path, RP, Q


def _reponse(n_trades: int, jours: int = 20):
    """Trades au format REEL de l'API : sans closeTime, le double ne testerait pas
    le chemin qui mesure l'etendue de la fenetre."""
    base = datetime(2026, 1, 5, tzinfo=timezone.utc)
    pas = jours / max(1, n_trades)
    corps = json.dumps({"trades": [
        {"id": str(i), "coin": "BTC",
         "closeTime": (base + timedelta(days=i * pas)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
         "realizedPnlUsd": 1.0, "feeUsd": 0.01, "fundingUsd": 0.0}
        for i in range(n_trades)], "nextCursor": None}).encode()

    class R:
        def read(self): return corps
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return R()


def test_une_seule_requete_large_suffit(bac, monkeypatch):
    """Fenetre large acceptee et >= 30 trades : UNE requete par wallet, pas plus.
    C'est l'optimisation qui fait passer le top-5 de ~20 requetes a 5."""
    tmp, RP, Q = bac
    appels = []

    def faux(req, timeout=None):
        appels.append(req.full_url)
        return _reponse(40, jours=200)
    monkeypatch.setattr(urllib.request, "urlopen", faux)

    n = RP.etape_top5(budget=100)
    assert n == 5, f"{n} requetes au lieu de 5"
    assert all("limit=500" in u for u in appels), "le parametre limit n'est pas envoye"


def test_respecte_le_budget(bac, monkeypatch):
    """Aucun trade rendu : la boucle ne doit jamais depasser le budget accorde."""
    tmp, RP, Q = bac
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _reponse(0))
    assert RP.etape_top5(budget=7) == 7


def test_un_429_interrompt_tout_le_lot(bac, monkeypatch):
    """Le premier refus sert de sonde : on ne gaspille pas requete par requete."""
    tmp, RP, Q = bac
    appels = []

    def faux(req, timeout=None):
        appels.append(1)
        if len(appels) >= 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        return _reponse(1)
    monkeypatch.setattr(urllib.request, "urlopen", faux)

    n = RP.etape_top5(budget=100)
    assert len(appels) == 3, "le lot a continue apres un 429"
    assert n == 2, f"{n} requetes reussies comptees au lieu de 2"
    assert Q.epuise() is True


def test_ne_tente_rien_si_deja_refuse(bac, monkeypatch):
    """Un 429 dans la fenetre courante interdit toute nouvelle tentative."""
    tmp, RP, Q = bac
    Q.journaliser("closed-trades", "0x0", 429)
    appele = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: appele.append(1) or _reponse(1))
    assert RP.etape_top5(budget=100) == 0
    assert appele == [], "des requetes ont ete tentees malgre un quota refuse"


def test_ne_recollecte_pas_une_fenetre_deja_en_base(bac, monkeypatch):
    """Une fenetre deja stockee ne doit jamais etre repayee."""
    tmp, RP, Q = bac
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _reponse(0))
    RP.etape_top5(budget=4)
    with sqlite3.connect(tmp / "ledger.db") as c:
        n1 = c.execute("SELECT COUNT(*) FROM closed_trades_natifs").fetchone()[0]
    assert n1 == 4
    RP.etape_top5(budget=4)
    with sqlite3.connect(tmp / "ledger.db") as c:
        n2 = c.execute("SELECT COUNT(*) FROM closed_trades_natifs").fetchone()[0]
    assert n2 == 8, "les memes fenetres ont ete recollectees"


def test_journalise_chaque_code(bac, monkeypatch):
    """L'ecart serveur/registre ne se corrige qu'en enregistrant les codes REELS."""
    tmp, RP, Q = bac
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _reponse(30))
    RP.etape_top5(budget=100)
    b = Q.bilan()
    assert b["reussies"] == 5 and b["refusees_429"] == 0
    assert b["epuise"] is False


def test_ne_touche_que_le_top5(bac, monkeypatch):
    """Le classement contient 8 wallets ; seuls les 5 premiers doivent etre interroges."""
    tmp, RP, Q = bac
    vus = []

    def faux(req, timeout=None):
        vus.append(req.full_url)
        return _reponse(30)
    monkeypatch.setattr(urllib.request, "urlopen", faux)
    RP.etape_top5(budget=100)
    adresses = {u.split("address=")[1].split("&")[0] for u in vus}
    assert len(adresses) == 5, f"{len(adresses)} wallets interroges au lieu de 5"
