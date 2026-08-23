"""
Tests de la couche d'acces as-of.

Deux familles, jamais melangees :
  - `test_reel_*` : execute sur les VRAIS snapshots de C:/Users/maram/ht_data.
    Ces tests se sautent proprement si le lac n'est pas la (autre machine, CI).
  - `test_fixture_*` : execute sur des lacs fabriques dans tmp_path, dont les fichiers
    sont prefixes `fixture_`. Une sortie de ces tests n'est PAS un resultat sur donnees
    reelles et ne doit jamais etre citee comme tel.

Aucun acces reseau.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ht.schema import SOURCES, InsufficientData, knowable_at_for
from ht.store import (
    TWAP_PSEUDO_ADDRESS,
    Coverage,
    open_lake,
)

UTC = timezone.utc
LAC_REEL = Path(os.environ.get("HT_LAKE_ROOT", str(Path.home() / "ht_data")))


# ============================================================ helpers fixtures

def _ecrire_fixture(dossier: Path, nom: str, table: pa.Table) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"fixture_{nom}.parquet"
    pq.write_table(table, chemin)
    return chemin


def _fixture_fills(racine: Path, *, avec_twap: bool = True) -> Path:
    """Lac fabrique : source `fills` (address + time en epoch ms)."""
    base = int(datetime(2026, 3, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
    adresses = ["0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40]
    if avec_twap:
        adresses.append(TWAP_PSEUDO_ADDRESS)
    lignes = []
    for i, addr in enumerate(adresses):
        for k in range(3):
            lignes.append({
                "address": addr, "coin": "BTC", "side": "B",
                "px": 60000.0 + k, "sz": 1.0 + k,
                "time": base + (i * 3 + k) * 60_000,
                "oid": 1000 + i * 3 + k, "fee": 0.1, "closedPnl": 5.0 * k,
            })
    table = pa.Table.from_pylist(lignes)
    _ecrire_fixture(racine / "fills" / "dt=2026-03-01", "fills-001", table)
    return racine


def _fixture_closed_trades(racine: Path) -> Path:
    """Lac fabrique : `closed_trades`, avec la colonne post-hoc `partial`."""
    base = int(datetime(2026, 3, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
    lignes = [{
        "address": "0x" + "a" * 40, "coin": "ETH", "side": "A", "hash": f"0x{i:064x}",
        "realizedPnlUsd": 10.0 * i, "avgEntry": 3000.0, "avgExit": 3010.0,
        "openTime": base, "closeTime": base + i * 3_600_000, "duration": 3600,
        "fee": 0.1, "feeUsd": 0.1, "fundingUsd": 0.0, "countFills": 2,
        "partial": bool(i % 2),
    } for i in range(5)]
    _ecrire_fixture(racine / "closed_trades", "ct-001", pa.Table.from_pylist(lignes))
    return racine


# ============================================================ lac reel

@pytest.fixture(scope="module")
def lac_reel():
    if not (LAC_REEL / "orders_5m").is_dir():
        pytest.skip(f"lac reel absent : {LAC_REEL}")
    lake = open_lake(LAC_REEL)
    if not lake.available("orders_5m"):
        lake.close()
        pytest.skip("aucun snapshot orders_5m sur disque")
    yield lake
    lake.close()


def test_reel_sources_presentes_et_absentes(lac_reel):
    assert lac_reel.available("orders_5m") is True
    # Rien d'autre n'a encore ete collecte : le lac doit le dire, pas le masquer.
    assert "orders_5m" in lac_reel.sources_available()
    for absente in lac_reel.sources_missing():
        assert absente in SOURCES
        assert lac_reel.available(absente) is False


def test_reel_source_absente_leve_avec_le_chemin_cherche(lac_reel):
    manquantes = lac_reel.sources_missing()
    if not manquantes:
        pytest.skip("toutes les sources sont presentes")
    nom = manquantes[0]
    with pytest.raises(InsufficientData) as err:
        lac_reel.as_of(nom, datetime.now(UTC))
    assert nom in str(err.value)
    assert "absente du lac" in str(err.value)


def test_reel_source_inconnue_est_une_erreur_de_programmation(lac_reel):
    with pytest.raises(ValueError):
        lac_reel.available("orders_1m")
    with pytest.raises(ValueError):
        lac_reel.as_of("pnl_magique", datetime.now(UTC))


def test_reel_couverture_orders(lac_reel):
    cov = lac_reel.coverage("orders_5m")
    assert isinstance(cov, Coverage)
    assert cov.n_rows > 0
    assert cov.n_partitions == len(lac_reel.files("orders_5m"))
    assert cov.min_valid_time <= cov.max_valid_time
    assert cov.min_valid_time.tzinfo is not None
    assert cov.min_valid_time.utcoffset() == timedelta(0)
    # snapshotTime est un epoch ms : mal interprete, on tomberait en 1970.
    assert cov.min_valid_time.year >= 2025
    assert cov.null_valid_time_count == 0
    assert cov.as_tuple() == (cov.min_valid_time, cov.max_valid_time,
                              cov.n_rows, cov.n_partitions)


def test_reel_couverture_coherente_avec_le_disque(lac_reel):
    cov = lac_reel.coverage("orders_5m")
    total_brut = lac_reel.raw("orders_5m").aggregate("count(*)").fetchone()[0]
    assert cov.n_rows + cov.twap_rows == total_brut


def test_reel_asof_avant_toute_publication_ne_rend_rien(lac_reel):
    premier = lac_reel.first_knowable_at("orders_5m")
    rel = lac_reel.orders_asof(premier - timedelta(microseconds=1))
    assert rel.aggregate("count(*)").fetchone()[0] == 0


def test_reel_asof_apres_tout_rend_tout(lac_reel):
    dernier = lac_reel.last_knowable_at("orders_5m")
    n = lac_reel.orders_asof(dernier).aggregate("count(*)").fetchone()[0]
    assert n == lac_reel.coverage("orders_5m").n_rows


def test_reel_asof_est_monotone(lac_reel):
    cov = lac_reel.coverage("orders_5m")
    debut = lac_reel.first_knowable_at("orders_5m")
    fin = lac_reel.last_knowable_at("orders_5m")
    pas = (fin - debut) / 4
    comptes = [
        lac_reel.orders_asof(debut + pas * i).aggregate("count(*)").fetchone()[0]
        for i in range(5)
    ]
    assert comptes == sorted(comptes)
    assert comptes[0] > 0
    assert comptes[-1] == cov.n_rows
    # Un as-of intermediaire doit vraiment couper : sinon le filtre ne sert a rien.
    assert comptes[0] < comptes[-1]


def test_reel_aucune_ligne_du_futur(lac_reel):
    debut = lac_reel.first_knowable_at("orders_5m")
    fin = lac_reel.last_knowable_at("orders_5m")
    asof = debut + (fin - debut) / 2
    rel = lac_reel.orders_asof(asof)
    ka_max, vt_max = rel.aggregate("max(knowable_at), max(valid_time)").fetchone()
    assert ka_max <= asof
    assert vt_max <= asof  # valid_time <= knowable_at, donc a fortiori


def test_reel_knowable_at_suit_le_contrat_schema(lac_reel):
    lag = lac_reel.publication_lag_s("orders_5m")
    attendu = (knowable_at_for("orders_5m", datetime(2026, 1, 1, tzinfo=UTC))
               - datetime(2026, 1, 1, tzinfo=UTC)).total_seconds()
    assert lag == attendu
    fin = lac_reel.last_knowable_at("orders_5m")
    vt, ka = lac_reel.orders_asof(fin).aggregate(
        "max(valid_time), max(knowable_at)").fetchone()
    assert (ka - vt).total_seconds() == pytest.approx(lag, abs=1e-3)


def test_reel_valid_time_correspond_au_snapshottime(lac_reel):
    """La conversion epoch-ms -> instant doit etre exacte, pas approchee."""
    fin = lac_reel.last_knowable_at("orders_5m")
    rel = lac_reel.orders_asof(fin)
    ms, vt = rel.aggregate('min("snapshotTime"), min(valid_time)').fetchone()
    assert vt == datetime.fromtimestamp(ms / 1000.0, UTC)


def test_reel_asof_naif_refuse(lac_reel):
    with pytest.raises(ValueError):
        lac_reel.orders_asof(datetime(2026, 1, 19, 11, 0))
    with pytest.raises(ValueError):
        lac_reel.orders_asof("2026-01-19T11:00:00Z")


def test_reel_pas_de_pseudo_adresse_twap(lac_reel):
    fin = lac_reel.last_knowable_at("orders_5m")
    n = lac_reel.orders_asof(fin).filter(
        f"lower(address) = '{TWAP_PSEUDO_ADDRESS}'").aggregate("count(*)").fetchone()[0]
    assert n == 0


def test_reel_colonnes_du_contrat_presentes(lac_reel):
    assert lac_reel.missing_columns("orders_5m") == ()
    lac_reel.check_columns("orders_5m", ("address", "coin", "sz", "snapshotTime"))
    with pytest.raises(InsufficientData):
        lac_reel.check_columns("orders_5m", ("realizedPnlUsd",))


def test_reel_require_coverage_refuse_une_fenetre_trop_courte(lac_reel):
    cov = lac_reel.coverage("orders_5m")
    lac_reel.require_coverage("orders_5m", min_rows=1, min_span=timedelta(0))
    with pytest.raises(InsufficientData) as err:
        lac_reel.require_coverage("orders_5m", min_span=cov.span + timedelta(days=365))
    assert "couverture" in str(err.value)
    with pytest.raises(InsufficientData):
        lac_reel.require_coverage("orders_5m", min_rows=cov.n_rows + 1)


def test_reel_coverage_asof_refuse_avant_publication(lac_reel):
    premier = lac_reel.first_knowable_at("orders_5m")
    with pytest.raises(InsufficientData) as err:
        lac_reel.coverage_asof("orders_5m", premier - timedelta(hours=1))
    assert "connaissable" in str(err.value)
    cov = lac_reel.coverage_asof("orders_5m", lac_reel.last_knowable_at("orders_5m"))
    assert cov.n_rows == lac_reel.coverage("orders_5m").n_rows


# ============================================================ lacs fabriques

def test_fixture_lac_vide_ne_plante_pas(tmp_path):
    with open_lake(tmp_path) as lake:
        assert lake.sources_available() == ()
        assert set(lake.sources_missing()) == set(SOURCES)
        for nom in SOURCES:
            assert lake.available(nom) is False
        with pytest.raises(InsufficientData):
            lake.coverage("orders_5m")


def test_fixture_twap_exclu_partout(tmp_path):
    racine = _fixture_fills(tmp_path, avec_twap=True)
    with open_lake(racine) as lake:
        assert lake.available("fills") is True
        assert lake.twap_excluded_count("fills") == 3
        fin = lake.last_knowable_at("fills")
        rel = lake.fills_asof(fin)
        adresses = {r[0] for r in rel.project("address").fetchall()}
        assert TWAP_PSEUDO_ADDRESS not in adresses
        assert len(adresses) == 3
        assert rel.aggregate("count(*)").fetchone()[0] == 9
        # Le brut, lui, contient toujours le TWAP : le biais est mesurable.
        assert lake.raw("fills").aggregate("count(*)").fetchone()[0] == 12
        cov = lake.coverage("fills")
        assert cov.n_rows == 9 and cov.twap_rows == 3


def test_fixture_colonne_post_hoc_refusee(tmp_path):
    racine = _fixture_closed_trades(tmp_path)
    with open_lake(racine) as lake:
        fin = lake.last_knowable_at("closed_trades")
        assert "partial" in SOURCES["closed_trades"].post_hoc
        with pytest.raises(InsufficientData) as err:
            lake.select_asof("closed_trades", ["address", "partial"], fin)
        assert "post-hoc" in str(err.value)
        # Les colonnes saines passent, avec les deux horloges ajoutees.
        rel = lake.select_asof("closed_trades", ["address", "realizedPnlUsd"], fin)
        assert set(rel.columns) == {"address", "realizedPnlUsd", "valid_time", "knowable_at"}


def test_fixture_colonnes_manquantes_signalees(tmp_path):
    """Une source DOCUMENTED peut arriver tronquee : on le detecte, on ne complete pas."""
    base = int(datetime(2026, 3, 1, tzinfo=UTC).timestamp() * 1000)
    table = pa.Table.from_pylist([{"address": "0x" + "a" * 40, "hash": "0x1",
                                   "closeTime": base + i} for i in range(3)])
    _ecrire_fixture(tmp_path / "closed_trades", "tronque", table)
    with open_lake(tmp_path) as lake:
        manquantes = lake.missing_columns("closed_trades")
        assert "realizedPnlUsd" in manquantes
        assert "address" not in manquantes
        with pytest.raises(InsufficientData):
            lake.select_asof("closed_trades", ["realizedPnlUsd"], datetime.now(UTC))


def test_fixture_valid_time_null_est_ecarte_pas_date_a_epoch(tmp_path):
    base = int(datetime(2026, 3, 1, tzinfo=UTC).timestamp() * 1000)
    lignes = [{"address": "0x" + "a" * 40, "coin": "BTC", "side": "B", "px": 1.0,
               "sz": 1.0, "time": (base + i * 1000) if i < 3 else None,
               "oid": i, "fee": 0.0, "closedPnl": 0.0} for i in range(5)]
    _ecrire_fixture(tmp_path / "fills", "avec-nulls", pa.Table.from_pylist(lignes))
    with open_lake(tmp_path) as lake:
        cov = lake.coverage("fills")
        assert cov.n_rows == 5
        assert cov.null_valid_time_count == 2
        # Les lignes non datables ne sont jamais connaissables : elles ne sortent pas.
        n = lake.fills_asof(datetime(2030, 1, 1, tzinfo=UTC)).aggregate(
            "count(*)").fetchone()[0]
        assert n == 3


def test_fixture_toutes_lignes_non_datables_leve(tmp_path):
    lignes = [{"address": "0x" + "a" * 40, "coin": "BTC", "side": "B", "px": 1.0,
               "sz": 1.0, "time": None, "oid": i, "fee": 0.0, "closedPnl": 0.0}
              for i in range(4)]
    _ecrire_fixture(tmp_path / "fills", "sans-date",
                    pa.Table.from_pylist(lignes, schema=pa.schema([
                        ("address", pa.string()), ("coin", pa.string()),
                        ("side", pa.string()), ("px", pa.float64()),
                        ("sz", pa.float64()), ("time", pa.int64()),
                        ("oid", pa.int64()), ("fee", pa.float64()),
                        ("closedPnl", pa.float64())])))
    with open_lake(tmp_path) as lake:
        with pytest.raises(InsufficientData) as err:
            lake.fills_asof(datetime(2030, 1, 1, tzinfo=UTC))
        assert "datable" in str(err.value)


def test_fixture_epoch_hors_bornes_refuse(tmp_path):
    """Un timestamp d'unite indecidable ne recoit pas d'unite par defaut."""
    lignes = [{"address": "0x" + "a" * 40, "coin": "BTC", "side": "B", "px": 1.0,
               "sz": 1.0, "time": 42 + i, "oid": i, "fee": 0.0, "closedPnl": 0.0}
              for i in range(3)]
    _ecrire_fixture(tmp_path / "fills", "epoch-absurde", pa.Table.from_pylist(lignes))
    with open_lake(tmp_path) as lake:
        with pytest.raises(InsufficientData) as err:
            lake.fills_asof(datetime(2030, 1, 1, tzinfo=UTC))
        assert "epoch" in str(err.value).lower()


def test_fixture_timestamp_natif_accepte(tmp_path):
    """wallets.observed_at peut arriver en TIMESTAMP arrow, pas en epoch : les deux marchent."""
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    lignes = [{"address": "0x" + "a" * 40, "totalEquity": 100.0 * i,
               "observed_at": t0 + timedelta(minutes=10 * i)} for i in range(4)]
    _ecrire_fixture(tmp_path / "wallets", "ts-natif", pa.Table.from_pylist(lignes))
    with open_lake(tmp_path) as lake:
        cov = lake.coverage("wallets")
        assert cov.min_valid_time == t0
        assert cov.max_valid_time == t0 + timedelta(minutes=30)
        lag = lake.publication_lag_s("wallets")
        assert lake.wallets_asof(t0 + timedelta(seconds=lag)).aggregate(
            "count(*)").fetchone()[0] == 1
        assert lake.wallets_asof(t0 + timedelta(seconds=lag - 1)).aggregate(
            "count(*)").fetchone()[0] == 0


def test_fixture_knowable_at_natif_prime_sur_le_defaut(tmp_path):
    """Si l'ingestion a mesure la latence, on utilise sa colonne plutot que le defaut prudent."""
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    lignes = [{"address": "0x" + "a" * 40, "totalEquity": 1.0,
               "observed_at": t0, "knowable_at": t0 + timedelta(seconds=5)}]
    _ecrire_fixture(tmp_path / "wallets", "ka-natif", pa.Table.from_pylist(lignes))
    with open_lake(tmp_path) as lake:
        assert lake.publication_lag_s("wallets") is None
        assert lake.wallets_asof(t0 + timedelta(seconds=5)).aggregate(
            "count(*)").fetchone()[0] == 1
        assert lake.wallets_asof(t0 + timedelta(seconds=4)).aggregate(
            "count(*)").fetchone()[0] == 0


def test_fixture_refresh_voit_une_nouvelle_source(tmp_path):
    with open_lake(tmp_path) as lake:
        assert lake.available("fills") is False
        _fixture_fills(tmp_path)
        assert lake.available("fills") is False  # pas de magie : il faut rafraichir
        lake.refresh()
        assert lake.available("fills") is True


def test_fixture_partitions_hive_comptees(tmp_path):
    base = int(datetime(2026, 3, 1, tzinfo=UTC).timestamp() * 1000)
    for jour in range(2):
        lignes = [{"address": "0x" + "a" * 40, "coin": "BTC", "side": "B", "px": 1.0,
                   "sz": 1.0, "time": base + jour * 86_400_000 + i * 1000,
                   "oid": jour * 10 + i, "fee": 0.0, "closedPnl": 0.0} for i in range(2)]
        _ecrire_fixture(tmp_path / "fills" / f"dt=2026-03-0{jour + 1}",
                        f"j{jour}", pa.Table.from_pylist(lignes))
    with open_lake(tmp_path) as lake:
        cov = lake.coverage("fills")
        assert cov.n_partitions == 2
        assert cov.n_hive_partitions == 2
        assert cov.n_rows == 4
