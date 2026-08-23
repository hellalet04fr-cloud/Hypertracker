"""
Tests de ht/features.py. Aucun reseau.

Deux familles, jamais melangees :
  - `fixture_*` : mini-tables FABRIQUEES, valeurs attendues calculees a la main.
  - `test_reel_*` : executes sur les vrais snapshots (C:\\Users\\maram\\ht_data),
    SKIP si la donnee est absente. Invariants seulement, jamais de valeur devinee.

Le test central est le REPLAY DIFFERENTIEL : un vecteur construit pour un meme `asof`
depuis deux points d'observation (`vantage` = asof, puis asof + 30 j) doit etre
IDENTIQUE. Une variable honnete ne depend pas du moment ou on la calcule. Un test de
simple monotonie laisserait passer une valeur revisee apres coup — exactement la fuite
recherchee.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

import pytest
import pyarrow as pa

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import ORDERS_5M, CLOSED_TRADES, InsufficientData, knowable_at_for  # noqa: E402
import ht.features as F  # noqa: E402


T0 = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
TARD = T0 + timedelta(days=10)
WA = "0x" + "a" * 40
WB = "0x" + "b" * 40
APRES = T0 + timedelta(hours=1)
RACINE_REELLE = r"C:\Users\maram\ht_data"

reel = pytest.mark.skipif(
    not os.path.isdir(os.path.join(RACINE_REELLE, "orders_5m")),
    reason="snapshots reels absents : le test serait vide, pas vert",
)


# =========================================================================== fixtures
def fixture_ordre(addr, coin, side, px, sz, oid, quand, **kw):
    """Une ligne d'ordre FABRIQUEE conforme au contrat ORDERS_5M."""
    base = {
        "snapshotTime": int(quand.timestamp() * 1000), "timestamp": 0, "height": 0,
        "address": addr, "coin": coin, "side": side, "limitPx": float(px),
        "sz": float(sz), "oid": int(oid), "triggerCondition": "N/A",
        "isTrigger": False, "triggerPx": 0.0, "children": "[]",
        "isPositionTpsl": False, "reduceOnly": False, "orderType": "Limit",
        "origSz": float(sz), "tif": "Gtc", "cloid": "", "status": "open",
        "builder": "", "builderFee": 0, "untriggered": False,
    }
    base.update(kw)
    return base


def fixture_loader(lignes):
    return F.InMemoryLoader(tables={ORDERS_5M.name: pa.Table.from_pylist(lignes)})


def fixture_carnet_simple():
    """WA : 2 ordres BTC a T0. WB : 1 BTC + 1 ETH reduceOnly a T0."""
    return [
        fixture_ordre(WA, "BTC", "B", 100.0, 1.0, 1, T0),
        fixture_ordre(WA, "BTC", "B", 99.0, 2.0, 2, T0),
        fixture_ordre(WB, "BTC", "A", 101.0, 1.0, 3, T0),
        fixture_ordre(WB, "ETH", "A", 50.0, 4.0, 4, T0, reduceOnly=True),
    ]


def fixture_carnet_avec_futur():
    """Le magasin contient AUSSI des lignes posterieures a asof : c'est ce qui rend
    le replay differentiel capable de distinguer une spec honnete d'une spec fuyante."""
    return fixture_carnet_simple() + [
        fixture_ordre(WA, "BTC", "B", 200.0, 9.0, 98, TARD),
        fixture_ordre(WA, "BTC", "B", 201.0, 9.0, 99, TARD),
    ]


def spec_nommee(nom: str) -> F.FeatureSpec:
    return F.REGISTRY[nom]


@pytest.fixture(autouse=True)
def registre_propre():
    """Le registre est global : on l'isole entre tests, puis on restaure les specs
    integrees pour ne pas casser les tests reels qui en dependent."""
    F.clear_registry()
    yield
    F.clear_registry()
    F.install_builtin_specs()


# =========================================================================== registre
def test_fixture_doublon_refuse():
    @F.feature("f_a", source=ORDERS_5M.name, requires=("address",))
    def _a(ctx, entite):
        return 1.0

    with pytest.raises(Exception):
        @F.feature("f_a", source=ORDERS_5M.name, requires=("address",))
        def _b(ctx, entite):
            return 2.0


def test_fixture_remplacement_explicite_autorise():
    @F.feature("f_r", source=ORDERS_5M.name, requires=("address",))
    def _a(ctx, entite):
        return 1.0

    @F.feature("f_r", source=ORDERS_5M.name, requires=("address",), replace=True)
    def _b(ctx, entite):
        return 2.0

    assert spec_nommee("f_r").fn is _b


def test_fixture_colonne_post_hoc_interdite():
    """closed_trades.partial est marque post_hoc : une spec qui le reclame est rejetee."""
    assert "partial" in CLOSED_TRADES.post_hoc
    with pytest.raises(Exception):
        @F.feature("f_ph", source=CLOSED_TRADES.name, requires=("address", "partial"))
        def _ph(ctx, entite):
            return 1.0


# =========================================================================== construction
def test_fixture_build_une_ligne_par_entite():
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_n", source=ORDERS_5M.name, requires=("address", "oid"))
    def _n(ctx, entite):
        return float(len(ctx.rows()))

    t = F.build(APRES, [WA, WB], loader=ld)
    assert t.num_rows == 2
    d = {r["entity"]: r for r in t.to_pylist()}
    # comptage manuel sur la fixture : WA -> 2 ordres, WB -> 2 ordres
    assert d[WA]["f_n"] == pytest.approx(2.0)
    assert d[WB]["f_n"] == pytest.approx(2.0)


def test_fixture_colonnes_de_tracabilite():
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_c", source=ORDERS_5M.name, requires=("address",))
    def _c(ctx, entite):
        return 1.0

    noms = set(F.build(APRES, [WA], loader=ld).column_names)
    assert "entity" in noms and "asof" in noms
    assert any("knowable" in n for n in noms), noms


def test_fixture_asof_naif_refuse():
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_d", source=ORDERS_5M.name, requires=("address",))
    def _d(ctx, entite):
        return 1.0

    with pytest.raises((ValueError, InsufficientData)):
        F.build(datetime(2026, 2, 1, 12, 0), [WA], loader=ld)


def test_fixture_asof_borne_strictement_la_fenetre():
    """A knowable_at pile, les 2 ordres de WA sont visibles. Une microseconde avant,
    plus rien n'est connaissable : la variable doit etre NULLE, jamais imputee."""
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_e", source=ORDERS_5M.name, requires=("address", "oid"))
    def _e(ctx, entite):
        n = len(ctx.rows())
        if n == 0:
            raise InsufficientData("aucune ligne connaissable a cet asof")
        return float(n)

    ka = knowable_at_for(ORDERS_5M.name, T0)
    assert F.build(ka, [WA], loader=ld).to_pylist()[0]["f_e"] == pytest.approx(2.0)

    ligne = F.build(ka - timedelta(microseconds=1), [WA], loader=ld).to_pylist()[0]
    assert ligne["f_e"] is None


# =========================================================================== incompletude
def test_fixture_ligne_incomplete_non_imputee():
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_f", source=ORDERS_5M.name, requires=("address",))
    def _f(ctx, entite):
        if entite == WB:
            raise InsufficientData("indisponible pour WB")
        return 3.0

    t = F.build(APRES, [WA, WB], loader=ld)
    d = {r["entity"]: r for r in t.to_pylist()}
    assert d[WA]["f_f"] == pytest.approx(3.0)
    assert d[WB]["f_f"] is None                 # NULL, jamais 0.0 ni une moyenne
    if "complete" in t.column_names:
        assert d[WB]["complete"] is False


def test_fixture_source_absente_marque_la_ligne_incomplete():
    """Le chargeur est paresseux : une source absente ne coute rien tant qu'aucune
    spec ne la lit. Des qu'une spec y touche, la ligne doit etre marquee incomplete
    et la valeur laissee NULLE — jamais imputee."""
    ld = F.InMemoryLoader(tables={})

    @F.feature("f_g", source=ORDERS_5M.name, requires=("address", "oid"))
    def _g(ctx, entite):
        return float(len(ctx.rows()))          # touche reellement la source

    ligne = F.build(APRES, [WA], [spec_nommee("f_g")], loader=ld).to_pylist()[0]
    assert ligne["f_g"] is None
    assert ligne["complete"] is False
    assert ligne["missing"]                      # la raison est conservee


def test_fixture_chargeur_paresseux_ne_charge_pas_inutilement():
    """Corollaire : une spec constante n'a pas besoin de la source, et ne doit pas
    echouer simplement parce que celle-ci est absente."""
    ld = F.InMemoryLoader(tables={})

    @F.feature("f_const", source=ORDERS_5M.name, requires=("address",))
    def _const(ctx, entite):
        return 1.0

    ligne = F.build(APRES, [WA], [spec_nommee("f_const")], loader=ld).to_pylist()[0]
    assert ligne["f_const"] == pytest.approx(1.0)
    assert ligne["complete"] is True


# =========================================================================== replay differentiel
def test_fixture_leak_check_accepte_spec_saine():
    """Le magasin contient des lignes posterieures a asof ; une spec qui passe par
    ctx.rows() ne les voit jamais, donc les deux reconstructions coincident."""
    ld = fixture_loader(fixture_carnet_avec_futur())

    @F.feature("f_saine", source=ORDERS_5M.name, requires=("address", "oid"))
    def _saine(ctx, entite):
        return float(len(ctx.rows()))

    r = F.leak_check(spec_nommee("f_saine"), knowable_at_for(ORDERS_5M.name, T0),
                     [WA], loader=ld)
    assert r.ecarts == ()
    assert r.entites_comparees == 1


def test_fixture_leak_check_detecte_spec_fuyante():
    """`ctx.rows_at_run_time()` voit le magasin tel qu'il est au moment de l'execution
    (vantage), pas tel qu'il etait a asof. C'est la definition meme de la fuite :
    le resultat change quand on recule le point d'observation de 30 jours."""
    ld = fixture_loader(fixture_carnet_avec_futur())

    @F.feature("f_fuyante", source=ORDERS_5M.name, requires=("address", "oid"))
    def _fuyante(ctx, entite):
        return float(len(ctx.rows_at_run_time()))

    with pytest.raises(F.LeakDetected):
        F.leak_check(spec_nommee("f_fuyante"), knowable_at_for(ORDERS_5M.name, T0),
                     [WA], loader=ld, strict=True)


def test_fixture_leak_check_non_strict_rapporte_sans_lever():
    ld = fixture_loader(fixture_carnet_avec_futur())

    @F.feature("f_fuyante2", source=ORDERS_5M.name, requires=("address", "oid"))
    def _f2(ctx, entite):
        return float(len(ctx.rows_at_run_time()))

    r = F.leak_check(spec_nommee("f_fuyante2"), knowable_at_for(ORDERS_5M.name, T0),
                     [WA], loader=ld, strict=False)
    assert len(r.ecarts) >= 1
    assert r.spec == "f_fuyante2"


def test_fixture_leak_check_refuse_verdict_sur_echantillon_vide():
    """Un « pas de fuite » tire de zero entite serait un mensonge."""
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_vide", source=ORDERS_5M.name, requires=("address",))
    def _v(ctx, entite):
        return 1.0

    with pytest.raises(InsufficientData):
        F.leak_check(spec_nommee("f_vide"), APRES, [], loader=ld)


def test_fixture_horizon_negatif_refuse():
    ld = fixture_loader(fixture_carnet_simple())

    @F.feature("f_h", source=ORDERS_5M.name, requires=("address",))
    def _h(ctx, entite):
        return 1.0

    with pytest.raises(ValueError):
        F.leak_check(spec_nommee("f_h"), APRES, [WA], loader=ld,
                     horizon=timedelta(0))


# =========================================================================== reel
@reel
def test_reel_build_sur_snapshots_presents():
    F.install_builtin_specs()
    ld = F.ParquetLoader(root=RACINE_REELLE)
    asof = datetime.now(timezone.utc)
    ents = F.discover_entities(ORDERS_5M.name, asof, loader=ld, limit=20)
    assert len(ents) > 0
    t = F.build(asof, ents, loader=ld)
    assert t.num_rows == len(ents)
    assert "entity" in t.column_names


@reel
def test_reel_specs_integrees_ne_fuient_pas():
    """Les variables livrees avec le module doivent passer le replay differentiel
    sur la donnee reellement collectee."""
    F.install_builtin_specs()
    ld = F.ParquetLoader(root=RACINE_REELLE)
    asof = datetime.now(timezone.utc)
    ents = F.discover_entities(ORDERS_5M.name, asof, loader=ld, limit=25)
    specs = [s for s in F.REGISTRY.values() if s.source == ORDERS_5M.name]
    if not specs:
        pytest.skip("aucune spec integree enregistree")
    for nom, r in F.leak_check_all(specs, asof, ents, loader=ld, strict=False).items():
        assert r.ecarts == (), f"{nom} presente {len(r.ecarts)} ecart(s) au replay"
