"""
Tests de ht/book_series.py et robustesse de ht/regime.py.
Aucun reseau, deterministes. Snapshots FABRIQUES ; les tests `reel_*` s'appuient sur
les carnets reellement persistes et sont SKIP si absents.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ht.schema import InsufficientData  # noqa: E402
import ht.book_series as BS  # noqa: E402
import ht.regime as RG  # noqa: E402

RACINE_REELLE = r"C:\Users\maram\ht_data"
reel = pytest.mark.skipif(
    not os.path.isdir(os.path.join(RACINE_REELLE, BS.SOUS_DOSSIER)),
    reason="carnets reels absents",
)
T0 = int(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)

_SCHEMA = pa.schema([("snapshotTime", pa.int64()), ("coin", pa.string()),
                     ("side", pa.string()), ("limitPx", pa.float64()),
                     ("sz", pa.float64()), ("isTrigger", pa.bool_())])


def fixture_snapshot(racine, t, lignes):
    d = os.path.join(racine, BS.SOUS_DOSSIER, f"dt={datetime.fromtimestamp(t/1000, timezone.utc):%Y-%m-%d}")
    os.makedirs(d, exist_ok=True)
    rows = [dict(l, snapshotTime=t) for l in lignes]
    cols = {n: [r[n] for r in rows] for n in _SCHEMA.names}
    pq.write_table(pa.table({n: pa.array(cols[n], type=_SCHEMA.field(n).type)
                             for n in _SCHEMA.names}, schema=_SCHEMA),
                   os.path.join(d, f"snapshot-{t}.parquet"))


def ordre(coin, side, px, sz=1.0, trig=False):
    return {"coin": coin, "side": side, "limitPx": px, "sz": sz, "isTrigger": trig}


def fixture_carnet(px_bid=99.0, px_ask=101.0, coin="BTC"):
    return [ordre(coin, "B", px_bid, 2.0), ordre(coin, "B", px_bid - 1, 1.0),
            ordre(coin, "A", px_ask, 1.0), ordre(coin, "A", px_ask + 1, 3.0)]


# =========================================================================== carnet
def test_mid_spread_profondeur_valeurs_connues(tmp_path):
    r = str(tmp_path)
    fixture_snapshot(r, T0, fixture_carnet(99.0, 101.0))
    pts = BS.points_du_snapshot(
        os.path.join(r, BS.SOUS_DOSSIER, f"dt=2026-02-01", f"snapshot-{T0}.parquet"))
    p = next(x for x in pts if x.coin == "BTC")
    assert p.mid == pytest.approx(100.0)
    assert p.meilleur_bid == 99.0 and p.meilleur_ask == 101.0
    assert p.spread_bp == pytest.approx(200.0)          # 2/100 = 200 bp
    # profondeur = somme sz*px : bids 2*99 + 1*98 = 296 ; asks 1*101 + 3*102 = 407
    assert p.profondeur_bid == pytest.approx(296.0)
    assert p.profondeur_ask == pytest.approx(407.0)
    assert p.desequilibre == pytest.approx((296 - 407) / 703)
    assert p.complet


def test_ordres_declenches_exclus(tmp_path):
    """Un stop loin du marche n'est pas de la liquidite offerte : l'inclure
    ecraserait le spread."""
    r = str(tmp_path)
    fixture_snapshot(r, T0, fixture_carnet() + [ordre("BTC", "B", 130.0, 9.0, trig=True)])
    pts = BS.points_du_snapshot(
        os.path.join(r, BS.SOUS_DOSSIER, "dt=2026-02-01", f"snapshot-{T0}.parquet"))
    assert next(x for x in pts if x.coin == "BTC").meilleur_bid == 99.0


def test_cote_unique_donne_mid_none(tmp_path):
    r = str(tmp_path)
    fixture_snapshot(r, T0, [ordre("SOL", "B", 10.0)])
    p = next(x for x in BS.points_du_snapshot(
        os.path.join(r, BS.SOUS_DOSSIER, "dt=2026-02-01", f"snapshot-{T0}.parquet"))
        if x.coin == "SOL")
    assert p.mid is None and p.spread_bp is None and not p.complet
    assert p.meilleur_bid == 10.0 and p.meilleur_ask is None


def test_carnet_croise_reste_defini(tmp_path):
    r = str(tmp_path)
    fixture_snapshot(r, T0, [ordre("X", "B", 101.0), ordre("X", "A", 99.0)])
    p = next(x for x in BS.points_du_snapshot(
        os.path.join(r, BS.SOUS_DOSSIER, "dt=2026-02-01", f"snapshot-{T0}.parquet"))
        if x.coin == "X")
    assert p.mid == pytest.approx(100.0)


def test_prix_invalides_ignores(tmp_path):
    r = str(tmp_path)
    fixture_snapshot(r, T0, [ordre("Y", "B", 0.0), ordre("Y", "B", 5.0),
                             ordre("Y", "A", 7.0)])
    p = next(x for x in BS.points_du_snapshot(
        os.path.join(r, BS.SOUS_DOSSIER, "dt=2026-02-01", f"snapshot-{T0}.parquet"))
        if x.coin == "Y")
    assert p.meilleur_bid == 5.0 and p.n_bids == 1


# =========================================================================== serie
def test_serie_et_qualite(tmp_path):
    r = str(tmp_path)
    for i in range(6):
        fixture_snapshot(r, T0 + i * 300_000, fixture_carnet(99 + i, 101 + i))
    pts, q = BS.construire_serie(r)
    assert q.n_snapshots == 6 and q.doublons == 0 and q.trous == 0
    assert q.intervalle_median_min == pytest.approx(5.0)
    assert q.distribution_intervalles == {5: 5}
    assert q.ordonnee and q.coins == 1
    s = BS.serie_prix(pts, "BTC")
    assert [round(p, 1) for _, p in s] == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]


def test_trous_comptes_sans_interpolation(tmp_path):
    r = str(tmp_path)
    for i in (0, 1, 5, 6):                       # trou de 3 creneaux
        fixture_snapshot(r, T0 + i * 300_000, fixture_carnet(99 + i, 101 + i))
    pts, q = BS.construire_serie(r)
    assert q.n_snapshots == 4
    assert q.creneaux_attendus == 7 and q.trous == 3
    assert 20 in q.distribution_intervalles           # le saut de 20 min est visible
    assert len(BS.serie_prix(pts, "BTC")) == 4        # aucun point invente


def test_doublons_dedupliques(tmp_path):
    r = str(tmp_path)
    fixture_snapshot(r, T0, fixture_carnet())
    d = os.path.join(r, BS.SOUS_DOSSIER, "dt=2026-02-01")
    import shutil
    shutil.copy(os.path.join(d, f"snapshot-{T0}.parquet"),
                os.path.join(d, "copie.parquet"))
    _, q = BS.construire_serie(r)
    assert q.n_fichiers == 2 and q.n_snapshots == 1 and q.doublons == 1


def test_serie_vide_refusee(tmp_path):
    with pytest.raises(InsufficientData):
        BS.construire_serie(str(tmp_path))


def test_coins_exploitables_filtre(tmp_path):
    r = str(tmp_path)
    for i in range(4):
        lignes = fixture_carnet(99 + i, 101 + i)
        if i < 2:
            lignes += [ordre("ETH", "B", 5.0), ordre("ETH", "A", 6.0)]
        fixture_snapshot(r, T0 + i * 300_000, lignes)
    pts, _ = BS.construire_serie(r)
    assert BS.coins_exploitables(pts, min_points=3) == [("BTC", 4)]
    assert dict(BS.coins_exploitables(pts, min_points=2))["ETH"] == 2


def test_classifier_coin_propage_le_refus(tmp_path):
    r = str(tmp_path)
    for i in range(6):
        fixture_snapshot(r, T0 + i * 300_000, fixture_carnet(99 + i, 101 + i))
    pts, _ = BS.construire_serie(r)
    with pytest.raises(InsufficientData) as e:
        BS.classifier_coin(pts, "BTC")
    assert "points requis" in str(e.value)
    with pytest.raises(InsufficientData):
        BS.classifier_coin(pts, "COIN_INEXISTANT")


# =========================================================================== robustesse regime
def test_regime_serie_clairsemee_refusee():
    with pytest.raises(InsufficientData):
        RG.classifier([100.0 + i for i in range(19)])       # 19 < MIN_POINTS


def test_regime_volatilite_extreme_reste_fini():
    """Alterner 100 et 300 ne donne PAS un range : +200 % puis -67 %, les variations
    relatives sont asymetriques et ne se compensent pas. On teste donc ce qui est vrai —
    des valeurs finies et bornees — et non une etiquette supposee."""
    p = [100.0 * (3.0 if i % 2 else 1.0) for i in range(40)]
    r = RG.classifier(p)
    assert r.direction in (RG.RANGE, RG.TENDANCE_HAUSSE, RG.TENDANCE_BAISSE)
    assert 0.0 <= r.ratio_directionnel <= 1.0
    assert 0.0 < r.volatilite_realisee < float("inf")


def test_regime_range_symetrique_en_relatif():
    """Un vrai range : oscillation faible autour d'un niveau, ou les variations
    relatives se compensent presque."""
    p = [100.0 + (1.0 if i % 2 else -1.0) for i in range(40)]
    assert RG.classifier(p).direction == RG.RANGE


def test_regime_changement_de_direction():
    montee = [100.0 + i for i in range(40)]
    descente = [140.0 - i for i in range(40)]
    r = RG.classifier(descente, reference=montee)
    assert r.direction == RG.TENDANCE_BAISSE and r.changement is True


def test_regime_serie_monotone_ratio_maximal():
    assert RG.ratio_directionnel([100.0 + i for i in range(40)]) == pytest.approx(1.0)


def test_regime_absence_de_spread_sans_effet():
    """Le regime ne lit que le milieu : un spread nul n'empeche pas de classer."""
    r = RG.classifier([100.0 + i * 0.5 for i in range(30)])
    assert r.direction == RG.TENDANCE_HAUSSE


def test_regime_gros_trou_temporel_ne_bloque_pas_la_classification():
    """La classification porte sur la suite des prix ; c'est le rapport de qualite,
    pas le moteur, qui doit signaler le trou."""
    r = RG.classifier([100.0 + i for i in range(30)])
    assert r.n_points == 30


# =========================================================================== reel
@reel
def test_reel_inventaire_coherent():
    pts, q = BS.construire_serie(RACINE_REELLE, coins=["BTC"])
    assert q.n_snapshots > 0 and q.doublons == 0
    assert q.ordonnee
    assert q.trous == q.creneaux_attendus - q.n_snapshots


@reel
def test_reel_btc_a_un_milieu_defini():
    pts, _ = BS.construire_serie(RACINE_REELLE, coins=["BTC"])
    s = BS.serie_prix(pts, "BTC")
    assert len(s) == len({t for t, _ in s})       # un point par instant
    assert all(p > 0 for _, p in s)


@reel
def test_reel_regime_refuse_si_profondeur_insuffisante():
    """Verdict honnete : tant que la couverture est sous le seuil, aucun regime."""
    pts, _ = BS.construire_serie(RACINE_REELLE, coins=["BTC"])
    s = BS.serie_prix(pts, "BTC")
    if len(s) >= RG.MIN_POINTS:
        r = BS.classifier_coin(pts, "BTC")
        assert r.direction in (RG.TENDANCE_HAUSSE, RG.TENDANCE_BAISSE, RG.RANGE)
    else:
        with pytest.raises(InsufficientData):
            BS.classifier_coin(pts, "BTC")
