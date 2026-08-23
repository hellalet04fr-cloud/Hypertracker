"""
Tests du Wallet Behavior Engine (ht/behavior.py). Aucun reseau.

Deux familles, jamais melangees :
  - `fixture_*` : mini-carnets FABRIQUES, dont les valeurs attendues sont calculees
    a la main dans les commentaires. Ils prouvent la CORRECTION des formules.
    Aucune sortie de ces tests n'est un resultat sur donnees reelles.
  - `test_reel_*` : executes sur les vrais snapshots presents sur disque
    (C:\\Users\\maram\\ht_data\\orders_5m). Ils prouvent que le module tourne sur la
    donnee reelle et verifient des invariants, pas des valeurs devinees.
    Ils sont SKIP (jamais verts par defaut) si la donnee est absente.
"""
from __future__ import annotations

import os
import sys
import dataclasses
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import ORDERS_5M, InsufficientData, knowable_at_for  # noqa: E402
import ht.behavior as bh  # noqa: E402


# =========================================================================== fixtures
T0 = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
WA = "0x" + "a" * 40
WB = "0x" + "b" * 40
WC = "0x" + "c" * 40
WD = "0x" + "d" * 40
WE = "0x" + "e" * 40

_SCHEMA = pa.schema([
    ("snapshotTime", pa.int64()), ("timestamp", pa.int64()), ("height", pa.int64()),
    ("address", pa.string()), ("coin", pa.string()), ("side", pa.string()),
    ("limitPx", pa.float64()), ("sz", pa.float64()), ("oid", pa.int64()),
    ("triggerCondition", pa.string()), ("isTrigger", pa.bool_()),
    ("triggerPx", pa.float64()), ("children", pa.string()),
    ("isPositionTpsl", pa.bool_()), ("reduceOnly", pa.bool_()),
    ("orderType", pa.string()), ("origSz", pa.float64()), ("tif", pa.string()),
    ("cloid", pa.string()), ("status", pa.string()), ("builder", pa.string()),
    ("builderFee", pa.int64()), ("untriggered", pa.bool_()),
])


def fixture_ordre(addr, coin, side, px, sz, oid, *, trigger=False,
                  order_type="Limit", tif="Gtc", reduce_only=False, orig=None):
    """Une ligne de carnet FABRIQUEE, conforme au contrat ORDERS_5M."""
    return {
        "timestamp": 0, "height": 0, "address": addr, "coin": coin, "side": side,
        "limitPx": float(px), "sz": float(sz), "oid": int(oid),
        "triggerCondition": "N/A", "isTrigger": trigger, "triggerPx": 0.0,
        "children": "[]", "isPositionTpsl": False, "reduceOnly": reduce_only,
        "orderType": order_type, "origSz": float(orig if orig is not None else sz),
        "tif": tif, "cloid": "", "status": "open", "builder": "", "builderFee": 0,
        "untriggered": trigger,
    }


def fixture_ecrire(racine: str, snapshots: dict[datetime, list[dict]]) -> str:
    """Materialise des snapshots FABRIQUES dans la disposition attendue par le moteur."""
    rep = os.path.join(racine, bh.SOUS_DOSSIER)
    for quand, lignes in snapshots.items():
        ms = int(quand.timestamp() * 1000)
        rows = [dict(l, snapshotTime=ms) for l in lignes]
        cols = {n: [r[n] for r in rows] for n in _SCHEMA.names}
        table = pa.table({n: pa.array(cols[n], type=_SCHEMA.field(n).type)
                          for n in _SCHEMA.names}, schema=_SCHEMA)
        d = os.path.join(rep, f"dt={quand:%Y-%m-%d}")
        os.makedirs(d, exist_ok=True)
        pq.write_table(table, os.path.join(d, f"fixture-snapshot-{quand:%H%M}.parquet"))
    return racine


# Carnet fabrique, snapshot A (BTC), valeurs attendues calculees a la main :
#   cote B : 100 (WA seul), 99 (WB seul)      cote A : 101 (WB seul), 102 (WC seul)
#   leave-one-out :
#     WA/100 -> bid_hors_soi 99, ask 101 -> milieu 100.0  -> 0 bp, au touche
#     WB/99  -> bid 100, ask_hors_soi 102  -> milieu 101.0 -> 198.0198 bp, hors touche
#     WB/101 -> bid 100, ask_hors_soi 102  -> milieu 101.0 -> 0 bp, au touche
#     WC/102 -> bid 100, ask 101           -> milieu 100.5 -> 149.2537 bp, hors touche
def fixture_snapshot_a():
    return [
        fixture_ordre(WA, "BTC", "B", 100.0, 1.0, 1, tif="Alo"),
        fixture_ordre(WB, "BTC", "B", 99.0, 2.0, 2),
        fixture_ordre(WB, "BTC", "A", 101.0, 1.0, 3),
        fixture_ordre(WC, "BTC", "A", 102.0, 1.0, 4),
        # WA porte aussi un stop sur ETH : declencheur, tif vide cote API
        fixture_ordre(WA, "ETH", "A", 90.0, 3.0, 5, trigger=True,
                      order_type="Stop Market", tif="", reduce_only=True),
        # WD n'a QUE des declencheurs : part_alo doit etre NULL, jamais 0.0
        fixture_ordre(WD, "SOL", "A", 10.0, 5.0, 6, trigger=True,
                      order_type="Take Profit Market", tif="", reduce_only=True),
        # pseudo-adresse TWAP (64 hex) : doit disparaitre de toute agregation
        fixture_ordre(bh.PSEUDO_ADRESSE_TWAP, "BTC", "B", 100.5, 9.0, 7, tif="Alo"),
    ]


def fixture_snapshot_b():
    """t0 + 5 min : oid 1 disparu (WA), les autres survivent, WE apparait."""
    return [
        fixture_ordre(WB, "BTC", "B", 99.0, 2.0, 2),
        fixture_ordre(WB, "BTC", "A", 101.0, 1.0, 3),
        fixture_ordre(WC, "BTC", "A", 102.0, 1.0, 4),
        fixture_ordre(WA, "ETH", "A", 90.0, 3.0, 5, trigger=True,
                      order_type="Stop Market", tif="", reduce_only=True),
        fixture_ordre(WD, "SOL", "A", 10.0, 5.0, 6, trigger=True,
                      order_type="Take Profit Market", tif="", reduce_only=True),
        fixture_ordre(WE, "BTC", "B", 98.0, 1.0, 8),
    ]


@pytest.fixture()
def fixture_racine_ab(tmp_path):
    """Deux snapshots CONSECUTIFS (pas de 5 min)."""
    return fixture_ecrire(str(tmp_path / "fixture_ht_data"),
                          {T0: fixture_snapshot_a(),
                           T0 + timedelta(minutes=5): fixture_snapshot_b()})


@pytest.fixture()
def fixture_racine_trouee(tmp_path):
    """Deux snapshots NON consecutifs (trou de 25 min)."""
    return fixture_ecrire(str(tmp_path / "fixture_ht_data_trouee"),
                          {T0: fixture_snapshot_a(),
                           T0 + timedelta(minutes=25): fixture_snapshot_b()})


APRES = T0 + timedelta(hours=1)          # asof largement posterieur aux fixtures


# =========================================================================== indexation
def test_fixture_indexation_et_horloges(fixture_racine_ab):
    snaps = bh.indexer_snapshots(fixture_racine_ab)
    assert [s.valid_time for s in snaps] == [T0, T0 + timedelta(minutes=5)]
    for s in snaps:
        assert s.knowable_at == knowable_at_for(ORDERS_5M.name, s.valid_time)
        assert s.knowable_at - s.valid_time == timedelta(seconds=300)
    assert [s.n_lignes for s in snaps] == [7, 6]


def test_fixture_asof_borne_strictement_la_fenetre(fixture_racine_ab):
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    # une microseconde avant le premier knowable_at : rien n'est lisible
    with pytest.raises(InsufficientData) as e:
        bh.fenetre_visible(ka0 - timedelta(microseconds=1), fixture_racine_ab)
    assert "connaissable" in str(e.value)
    # pile a knowable_at : exactement un snapshot
    f = bh.fenetre_visible(ka0, fixture_racine_ab)
    assert len(f.snapshots) == 1 and f.snapshots[0].valid_time == T0
    assert f.paires_consecutives == ()
    # apres le second : deux snapshots, une paire consecutive
    f2 = bh.fenetre_visible(APRES, fixture_racine_ab)
    assert len(f2.snapshots) == 2
    assert f2.paires_consecutives == ((T0, T0 + timedelta(minutes=5)),)


def test_fixture_asof_doit_etre_aware(fixture_racine_ab):
    with pytest.raises(InsufficientData):
        bh.fenetre_visible(datetime(2026, 2, 1, 12, 0), fixture_racine_ab)


def test_fixture_snapshot_time_non_constant_refuse(tmp_path):
    """Un fichier melangeant deux snapshotTime casserait le filtrage par fichier."""
    racine = str(tmp_path / "fixture_ht_data_melange")
    rep = os.path.join(racine, bh.SOUS_DOSSIER, "dt=2026-02-01")
    os.makedirs(rep, exist_ok=True)
    rows = [dict(fixture_ordre(WA, "BTC", "B", 100.0, 1.0, 1),
                 snapshotTime=int(T0.timestamp() * 1000)),
            dict(fixture_ordre(WA, "BTC", "B", 100.0, 1.0, 2),
                 snapshotTime=int((T0 + timedelta(minutes=5)).timestamp() * 1000))]
    table = pa.table({n: pa.array([r[n] for r in rows], type=_SCHEMA.field(n).type)
                      for n in _SCHEMA.names}, schema=_SCHEMA)
    pq.write_table(table, os.path.join(rep, "fixture-snapshot-melange.parquet"))
    with pytest.raises(InsufficientData) as e:
        bh.indexer_snapshots(racine)
    assert "non constant" in str(e.value)


def test_fixture_repertoire_absent(tmp_path):
    with pytest.raises(InsufficientData):
        bh.indexer_snapshots(str(tmp_path / "nexiste_pas"))


def test_garde_post_hoc(monkeypatch):
    """Regle 3 : si le contrat marquait une colonne post_hoc, la lire doit exploser."""
    contamine = dataclasses.replace(ORDERS_5M, post_hoc=frozenset({"tif"}))
    monkeypatch.setattr(bh, "ORDERS_5M", contamine)
    with pytest.raises(ValueError) as e:
        bh._verifier_colonnes_autorisees(bh.COLONNES_UTILES)
    assert "post_hoc" in str(e.value)


def test_garde_colonne_hors_contrat():
    with pytest.raises(ValueError):
        bh._verifier_colonnes_autorisees(("address", "colonne_inventee"))


# =========================================================================== empreinte
def test_fixture_empreinte_valeurs_exactes(fixture_racine_ab):
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    d = bh.empreinte_ordres(ka0, fixture_racine_ab)      # snapshot A seul
    assert bh.PSEUDO_ADRESSE_TWAP not in d.index         # TWAP exclu
    assert set(d.index) == {WA, WB, WC, WD}

    assert d.at[WA, "n_ordres"] == 2 and d.at[WA, "n_coins"] == 2
    assert d.at[WA, "n_trigger"] == 1 and d.at[WA, "part_trigger"] == 0.5
    assert d.at[WA, "part_stop"] == 0.5 and d.at[WA, "part_reduce_only"] == 0.5
    # WA : 1 seul ordre porte un tif, et c'est Alo -> 1.0 (denominateur 1, pas 2)
    assert d.at[WA, "n_ordres_avec_tif"] == 1 and d.at[WA, "part_alo"] == 1.0
    assert d.at[WB, "part_gtc"] == 1.0 and d.at[WB, "part_alo"] == 0.0
    assert d.at[WB, "part_achat"] == 0.5


def test_fixture_aucune_valeur_par_defaut_sur_tif(fixture_racine_ab):
    """WD n'a que des declencheurs : part_alo est NULL, jamais 0.0."""
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    d = bh.empreinte_ordres(ka0, fixture_racine_ab)
    assert d.at[WD, "n_ordres_avec_tif"] == 0          # comptage reel : 0 est un fait
    assert pd.isna(d.at[WD, "part_alo"])               # taux : NULL, pas 0.0
    assert pd.isna(d.at[WD, "part_gtc"])


# =========================================================================== concentration
def test_fixture_concentration_hhi(fixture_racine_ab):
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    d = bh.concentration(ka0, fixture_racine_ab)
    # WA : 1 ordre BTC + 1 ordre ETH -> HHI = 0.5^2 + 0.5^2 = 0.5, 2 actifs effectifs
    assert d.at[WA, "hhi_ordres"] == pytest.approx(0.5)
    assert d.at[WA, "n_coins_effectif"] == pytest.approx(2.0)
    # en notionnel, seul l'ordre de carnet BTC compte -> mono-actif
    assert d.at[WA, "hhi_notionnel"] == pytest.approx(1.0)
    assert d.at[WA, "notionnel_total"] == pytest.approx(100.0)
    # WB : 2 ordres BTC -> mono-actif
    assert d.at[WB, "hhi_ordres"] == pytest.approx(1.0)
    assert d.at[WB, "coin_principal"] == "BTC"
    # WD : aucun ordre chiffrable -> hhi_notionnel NULL, jamais 0.0 ni 1.0 invente
    assert d.at[WD, "n_ordres_chiffrables_coin"] == 0
    assert pd.isna(d.at[WD, "hhi_notionnel"])
    assert pd.isna(d.at[WD, "n_coins_effectif_notionnel"])


# =========================================================================== agressivite
def test_fixture_agressivite_leave_one_out(fixture_racine_ab):
    """Un wallet seul au sommet ne doit pas se servir de reference a lui-meme."""
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    d = bh.agressivite_placement(ka0, fixture_racine_ab)
    # WA seul a 100 : reference hors soi = (99 + 101)/2 = 100 -> 0 bp, au touche
    assert d.at[WA, "n_ordres_cotables"] == 1
    assert d.at[WA, "distance_milieu_bp_mediane"] == pytest.approx(0.0, abs=1e-9)
    assert d.at[WA, "part_au_touche"] == 1.0
    # WC a 102 : reference (100 + 101)/2 = 100.5 -> (102-100.5)/100.5*1e4
    assert d.at[WC, "distance_milieu_bp_mediane"] == pytest.approx(149.25373134, rel=1e-9)
    assert d.at[WC, "part_au_touche"] == 0.0
    # WB : ses deux ordres, milieu hors soi = (100 + 102)/2 = 101
    assert d.at[WB, "n_ordres_cotables"] == 2
    assert d.at[WB, "distance_milieu_bp_moyenne"] == pytest.approx(
        (198.01980198 + 0.0) / 2, rel=1e-9)
    assert d.at[WB, "part_au_touche"] == 0.5
    # WD sans ordre de carnet : tout est NULL, les comptages valent 0
    assert d.at[WD, "n_ordres_carnet"] == 0 and d.at[WD, "n_ordres_cotables"] == 0
    assert pd.isna(d.at[WD, "distance_milieu_bp_mediane"])
    assert pd.isna(d.at[WD, "part_au_touche"])
    assert pd.isna(d.at[WD, "couverture_cotation"])


def test_fixture_agressivite_reference_inconnue_non_substituee(tmp_path):
    """Coin a sens unique : aucun milieu n'existe, les ordres sont exclus, pas bouches."""
    racine = fixture_ecrire(str(tmp_path / "fixture_ht_data_unilateral"), {
        T0: [fixture_ordre(WA, "BTC", "B", 100.0, 1.0, 1),
             fixture_ordre(WB, "BTC", "B", 99.0, 1.0, 2)],
    })
    d = bh.agressivite_placement(knowable_at_for(ORDERS_5M.name, T0), racine)
    assert d.at[WA, "n_ordres_carnet"] == 1
    assert d.at[WA, "n_ordres_cotables"] == 0
    assert pd.isna(d.at[WA, "distance_milieu_bp_mediane"])


# =========================================================================== persistance
def test_fixture_persistance_valeurs_exactes(fixture_racine_ab):
    d = bh.persistance_ordres(APRES, fixture_racine_ab)
    # WA : oid 1 et 5 appariables, seul 5 survit
    assert (d.at[WA, "n_oid_appariables"], d.at[WA, "n_oid_survivants"]) == (2, 1)
    assert d.at[WA, "taux_persistance"] == pytest.approx(0.5)
    assert d.at[WA, "taux_churn"] == pytest.approx(0.5)
    assert d.at[WB, "taux_persistance"] == pytest.approx(1.0)
    assert d.at[WC, "taux_persistance"] == pytest.approx(1.0)
    # WE n'apparait qu'au second snapshot : rien a apparier -> NULL, pas 0.0
    assert d.at[WE, "n_oid_appariables"] == 0
    assert pd.isna(d.at[WE, "taux_persistance"])
    assert d.at[WE, "n_paires_snapshots"] == 1


def test_fixture_persistance_impossible_sur_un_seul_snapshot(fixture_racine_ab):
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    with pytest.raises(InsufficientData) as e:
        bh.persistance_ordres(ka0, fixture_racine_ab)
    assert "aucune paire de snapshots consecutifs" in str(e.value)


def test_fixture_persistance_impossible_sur_snapshots_non_consecutifs(fixture_racine_trouee):
    f = bh.fenetre_visible(APRES, fixture_racine_trouee)
    assert len(f.snapshots) == 2 and f.paires_consecutives == ()
    with pytest.raises(InsufficientData):
        bh.persistance_ordres(APRES, fixture_racine_trouee)


def test_fixture_profil_sans_persistance_documente_le_trou(fixture_racine_trouee):
    p = bh.profil_comportemental(APRES, fixture_racine_trouee, avec_persistance=False)
    assert "taux_persistance" not in p.columns      # aucune colonne bouchee a 0
    assert p.attrs["persistance"].startswith("indisponible:")
    with pytest.raises(InsufficientData):
        bh.profil_comportemental(APRES, fixture_racine_trouee)


# =========================================================================== tailles
def test_fixture_tailles_et_dispersion(fixture_racine_ab):
    ka0 = knowable_at_for(ORDERS_5M.name, T0)
    d = bh.tailles_ordres(ka0, fixture_racine_ab)
    # WB : notionnels 99*2 = 198 et 101*1 = 101 -> mediane 149.5
    assert d.at[WB, "n_ordres_chiffrables"] == 2
    assert d.at[WB, "notionnel_median"] == pytest.approx(149.5)
    assert d.at[WB, "notionnel_moyen"] == pytest.approx(149.5)
    assert d.at[WB, "ecart_type_log_notionnel"] > 0
    # WA : un seul ordre chiffrable -> un ecart-type n'existe pas, il vaut NULL
    assert d.at[WA, "n_ordres_chiffrables"] == 1
    assert d.at[WA, "notionnel_median"] == pytest.approx(100.0)
    assert pd.isna(d.at[WA, "ecart_type_log_notionnel"])
    assert pd.isna(d.at[WA, "coef_variation_notionnel"])
    # WD : aucun ordre chiffrable
    assert d.at[WD, "n_ordres_chiffrables"] == 0
    assert pd.isna(d.at[WD, "notionnel_median"])
    assert pd.isna(d.at[WD, "part_partiellement_remplis"])


def test_fixture_remplissage_partiel(tmp_path):
    racine = fixture_ecrire(str(tmp_path / "fixture_ht_data_partiel"), {
        T0: [fixture_ordre(WA, "BTC", "B", 100.0, 0.4, 1, orig=1.0),
             fixture_ordre(WA, "BTC", "B", 99.0, 1.0, 2, orig=1.0),
             fixture_ordre(WB, "BTC", "A", 101.0, 1.0, 3, orig=1.0)],
    })
    d = bh.tailles_ordres(knowable_at_for(ORDERS_5M.name, T0), racine)
    assert d.at[WA, "n_partiellement_remplis"] == 1
    assert d.at[WA, "part_partiellement_remplis"] == pytest.approx(0.5)


# =========================================================================== profil / acces
def test_fixture_profil_et_acces_scalaire(fixture_racine_ab):
    p = bh.profil_comportemental(APRES, fixture_racine_ab)
    assert set(p.index) == {WA, WB, WC, WD, WE}
    assert p.attrs["n_snapshots"] == 2 and p.attrs["n_paires_consecutives"] == 1
    assert p.attrs["source"] == "orders_5m"
    assert p.index.is_unique
    # acces scalaire : valeur presente -> float ; valeur NULL -> InsufficientData
    # WA totalise 3 ordres sur les DEUX snapshots, dont 2 trigger (comptage manuel
    # sur les fixtures). L'attendu 0.5 valait pour le seul snapshot_a.
    assert bh.variable(p, WA, "part_trigger") == pytest.approx(2 / 3)
    with pytest.raises(InsufficientData) as e:
        bh.variable(p, WD, "part_alo")
    assert "non calculable" in str(e.value)
    with pytest.raises(InsufficientData):
        bh.variable(p, "0x" + "f" * 40, "part_trigger")
    with pytest.raises(InsufficientData):
        bh.variable(p, WA, "variable_qui_nexiste_pas")


def test_fixture_min_ordres_filtre_sans_inventer(fixture_racine_ab):
    p = bh.profil_comportemental(APRES, fixture_racine_ab, min_ordres=3)
    assert (p["n_ordres"] >= 3).all()
    with pytest.raises(InsufficientData):
        bh.profil_comportemental(APRES, fixture_racine_ab, min_ordres=10_000)


def test_fixture_profil_est_point_in_time(fixture_racine_ab):
    """Le profil calcule tot ne peut pas contenir d'information du snapshot suivant."""
    tot = bh.profil_comportemental(knowable_at_for(ORDERS_5M.name, T0),
                                   fixture_racine_ab, avec_persistance=False)
    tard = bh.profil_comportemental(APRES, fixture_racine_ab)
    assert WE not in tot.index and WE in tard.index      # WE n'existe qu'au 2e snapshot
    for a in tot.index:
        assert tot.at[a, "n_ordres"] <= tard.at[a, "n_ordres"]


# =========================================================================== donnees reelles
def _donnees_reelles_dispo() -> bool:
    try:
        return len(bh.indexer_snapshots()) > 0
    except InsufficientData:
        return False


reel = pytest.mark.skipif(
    not _donnees_reelles_dispo(),
    reason=f"aucun snapshot reel sous {bh.repertoire_snapshots()} : "
           f"les tests sur donnees reelles ne peuvent pas etre simules",
)


@pytest.fixture(scope="module")
def profil_reel():
    asof = datetime.now(timezone.utc)
    return bh.profil_comportemental(asof, min_ordres=1)


@reel
def test_reel_fenetre_et_grille():
    f = bh.fenetre_visible(datetime.now(timezone.utc))
    assert len(f.snapshots) >= 1
    for a, b in f.paires_consecutives:
        assert b - a == bh.PAS_SNAPSHOT
    # un snapshot n'est jamais lisible avant sa latence de publication
    for s in f.snapshots:
        assert s.knowable_at > s.valid_time
        assert s.knowable_at <= f.asof


@reel
def test_reel_profil_invariants(profil_reel):
    p = profil_reel
    assert len(p) > 0 and p.index.is_unique
    assert bh.PSEUDO_ADRESSE_TWAP not in p.index
    # Index.map rend un Index, qui n'a pas de .eq : comparaison directe.
    assert all(len(a) == bh.LONGUEUR_ADRESSE_EVM for a in p.index)
    for col in [c for c in p.columns if c.startswith("part_") or c.startswith("taux_")]:
        s = p[col].dropna()
        assert ((s >= -1e-12) & (s <= 1 + 1e-12)).all(), col
    for col in ("hhi_ordres", "hhi_notionnel"):
        s = p[col].dropna()
        assert ((s > 0) & (s <= 1 + 1e-12)).all(), col
    assert (p["n_coins_effectif"].dropna() >= 1 - 1e-9).all()
    assert (p["n_ordres_cotables"] <= p["n_ordres_carnet"]).all()
    assert (p["n_oid_survivants"] <= p["n_oid_appariables"]).all()
    assert (p["n_oid_distincts"] <= p["n_ordres"]).all()
    assert (p["notionnel_median"].dropna() > 0).all()


@reel
def test_reel_aucune_valeur_par_defaut(profil_reel):
    """Sur la vraie donnee, les trous restent des trous."""
    p = profil_reel
    sans_tif = p["n_ordres_avec_tif"] == 0
    assert sans_tif.any(), "cas non couvert par la donnee du jour"
    assert p.loc[sans_tif, "part_alo"].isna().all()
    sans_carnet = p["n_ordres_chiffrables"] == 0
    if sans_carnet.any():
        assert p.loc[sans_carnet, "notionnel_median"].isna().all()
        assert p.loc[sans_carnet, "ecart_type_log_notionnel"].isna().all()
    seul_ordre = p["n_ordres_chiffrables"] == 1
    if seul_ordre.any():
        assert p.loc[seul_ordre, "ecart_type_log_notionnel"].isna().all()
    sans_paire = p["n_oid_appariables"] == 0
    if sans_paire.any():
        assert p.loc[sans_paire, "taux_persistance"].isna().all()


@reel
def test_reel_comptage_coherent_avec_la_source(profil_reel):
    """La somme des n_ordres doit egaler le nombre de lignes reellement retenues."""
    import duckdb
    f = bh.fenetre_visible(datetime.now(timezone.utc))
    attendu = duckdb.connect().execute(
        f"select count(*) from read_parquet({bh._litteral_liste(f.chemins)}) "
        f"where address is not null and length(address) = {bh.LONGUEUR_ADRESSE_EVM} "
        f"and address <> '{bh.PSEUDO_ADRESSE_TWAP}'"
    ).fetchone()[0]
    assert int(profil_reel["n_ordres"].sum()) == attendu
    assert attendu <= f.snapshots[0].n_lignes * len(f.snapshots) * 2


@reel
def test_reel_asof_anterieur_reduit_strictement_la_fenetre(profil_reel):
    """Rempart anti-fuite : reculer asof ne peut qu'enlever de l'information."""
    f = bh.fenetre_visible(datetime.now(timezone.utc))
    if len(f.snapshots) < 2:
        pytest.skip("un seul snapshot reel connaissable : comparaison impossible")
    asof_tot = f.snapshots[len(f.snapshots) // 2].knowable_at
    ftot = bh.fenetre_visible(asof_tot)
    assert len(ftot.snapshots) < len(f.snapshots)
    assert set(ftot.chemins).issubset(set(f.chemins))
    ptot = bh.profil_comportemental(asof_tot, avec_persistance=len(ftot.paires_consecutives) > 0)
    communs = ptot.index.intersection(profil_reel.index)
    assert len(communs) > 0
    assert (ptot.loc[communs, "n_ordres"] <= profil_reel.loc[communs, "n_ordres"]).all()


@reel
def test_reel_agressivite_a_du_signal(profil_reel):
    """La distance au milieu doit varier entre wallets : une colonne constante
    signalerait une reference de prix cassee."""
    s = profil_reel["distance_milieu_bp_mediane"].dropna()
    assert len(s) > 100
    assert s.std() > 0
    # Ce qui signalerait un milieu cassÃ©, c'est un inf (division par un milieu nul),
    # PAS une grande valeur : mesurÃ© sur les snapshots rÃ©els, 8 wallets dÃ©passent
    # 1e6 bp â€” des ordres Ã  cours limite posÃ©s trÃ¨s loin du marchÃ©, ce qui existe
    # bel et bien sur les actifs peu liquides. Plafonner ici masquerait du vrai.
    assert np.isfinite(s).all()
    au_touche = profil_reel["part_au_touche"].dropna()
    assert au_touche.between(0, 1).all()
    assert 0 < au_touche.mean() < 1

