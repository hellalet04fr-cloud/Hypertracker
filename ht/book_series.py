#!/usr/bin/env python3
"""
Serie temporelle normalisee a partir des snapshots de carnet deja persistes.

Ne collecte rien. Transforme les fichiers Parquet du lac en une serie
(timestamp, coin) -> variables de carnet reellement calculables, avec un rapport de
qualite qui rend les trous et les intervalles visibles plutot que lisses.

Choix explicites :
  - UNE SEULE LECTURE PAR SNAPSHOT, tous coins a la fois. Extraire coin par coin
    relisait le fichier entier a chaque fois : mesure a 0,71 s par coin et par
    snapshot, contre une passe unique pour 248 coins.
  - LES ORDRES DECLENCHES SONT EXCLUS du carnet. Un stop a 30 % du marche n'est pas
    de la liquidite offerte : l'inclure ecraserait le spread et fausserait le milieu.
  - UN COTE MANQUANT N'EST PAS UN PRIX. Si un coin n'a que des bids, `mid` vaut None
    et la ligne est marquee incomplete — jamais remplacee par le meilleur bid.
"""
from __future__ import annotations

import glob
import os
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .schema import InsufficientData, require

SOUS_DOSSIER = "orders_5m"
COLONNES = ("snapshotTime", "coin", "side", "limitPx", "sz", "isTrigger")
PAS_ATTENDU_MS = 300_000            # grille de 5 minutes, propriete de la source


@dataclass(frozen=True)
class PointCarnet:
    """Etat d'un coin a un instant. `mid` a None signifie carnet unilateral."""
    t: int
    coin: str
    mid: float | None
    meilleur_bid: float | None
    meilleur_ask: float | None
    spread_bp: float | None
    n_bids: int
    n_asks: int
    profondeur_bid: float
    profondeur_ask: float
    desequilibre: float | None       # (bid - ask) / (bid + ask), dans [-1, 1]

    @property
    def complet(self) -> bool:
        return self.mid is not None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualiteSerie:
    n_snapshots: int
    n_fichiers: int
    doublons: int
    debut: datetime | None
    fin: datetime | None
    duree_min: float
    intervalle_median_min: float | None
    distribution_intervalles: dict
    creneaux_attendus: int
    trous: int
    coins: int
    ordonnee: bool

    def as_dict(self) -> dict:
        d = asdict(self)
        d["debut"] = self.debut.isoformat() if self.debut else None
        d["fin"] = self.fin.isoformat() if self.fin else None
        return d

    def resume(self) -> str:
        return (f"{self.n_snapshots} snapshots ({self.n_fichiers} fichiers, "
                f"{self.doublons} doublon(s)) | "
                f"{self.debut:%Y-%m-%d %H:%M} -> {self.fin:%Y-%m-%d %H:%M} "
                f"({self.duree_min:.0f} min) | pas median "
                f"{self.intervalle_median_min:.0f} min | trous {self.trous}/"
                f"{self.creneaux_attendus} | {self.coins} coins"
                if self.debut else "serie vide")


# --------------------------------------------------------------------------- lecture
def inventorier(racine: str) -> list[tuple[int, str]]:
    """(snapshotTime, chemin) tries, dedupliques. Ne lit que les metadonnees et une
    colonne d'une ligne : inventorier 100 Mo ne doit pas couter une lecture complete."""
    import pyarrow.parquet as pq

    rep = os.path.join(racine, SOUS_DOSSIER)
    fichiers = sorted(glob.glob(os.path.join(rep, "**", "*.parquet"), recursive=True))
    vus: dict[int, str] = {}
    doublons = 0
    for f in fichiers:
        try:
            t = pq.read_table(f, columns=["snapshotTime"]).column(0)[0].as_py()
        except Exception:
            continue
        t = int(t)
        if t in vus:
            doublons += 1
            continue
        vus[t] = f
    return sorted(vus.items()), doublons, len(fichiers)


def points_du_snapshot(chemin: str, *, coins: Sequence[str] | None = None
                       ) -> list[PointCarnet]:
    """
    Toutes les variables de carnet d'un snapshot, en UNE passe pour tous les coins.

    Les ordres declenches (`isTrigger`) sont exclus : ce sont des ordres conditionnels,
    pas de la liquidite affichee.
    """
    import pyarrow.parquet as pq

    t = pq.read_table(chemin, columns=list(COLONNES))
    ts = int(t.column("snapshotTime")[0].as_py())
    cols = {n: t.column(n).to_pylist() for n in COLONNES}
    garder = set(coins) if coins else None

    agg: dict[str, dict] = {}
    for i in range(t.num_rows):
        if cols["isTrigger"][i]:
            continue
        c = cols["coin"][i]
        if garder is not None and c not in garder:
            continue
        px = cols["limitPx"][i]
        sz = cols["sz"][i]
        if px is None or not (px > 0) or sz is None:
            continue
        a = agg.setdefault(c, {"b": [], "a": [], "vb": 0.0, "va": 0.0})
        if cols["side"][i] == "B":
            a["b"].append(px)
            a["vb"] += abs(float(sz)) * float(px)
        else:
            a["a"].append(px)
            a["va"] += abs(float(sz)) * float(px)

    out = []
    for c, a in agg.items():
        bid = max(a["b"]) if a["b"] else None
        ask = min(a["a"]) if a["a"] else None
        mid = spread = None
        if bid is not None and ask is not None:
            lo, hi = (bid, ask) if ask >= bid else (ask, bid)
            mid = (lo + hi) / 2.0
            spread = (hi - lo) / mid * 10_000 if mid > 0 else None
        tot = a["vb"] + a["va"]
        des = (a["vb"] - a["va"]) / tot if tot > 0 else None
        out.append(PointCarnet(t=ts, coin=c, mid=mid, meilleur_bid=bid,
                               meilleur_ask=ask, spread_bp=spread,
                               n_bids=len(a["b"]), n_asks=len(a["a"]),
                               profondeur_bid=a["vb"], profondeur_ask=a["va"],
                               desequilibre=des))
    return out


def construire_serie(racine: str, *, coins: Sequence[str] | None = None
                     ) -> tuple[list[PointCarnet], QualiteSerie]:
    """Serie complete + rapport de qualite. Aucune interpolation, aucun remplissage."""
    inv, doublons, n_fichiers = inventorier(racine)
    require(bool(inv), f"aucun snapshot de carnet sous {racine}/{SOUS_DOSSIER}")
    pts: list[PointCarnet] = []
    for _, chemin in inv:
        pts.extend(points_du_snapshot(chemin, coins=coins))

    ts = [t for t, _ in inv]
    ecarts = [(ts[i] - ts[i - 1]) / 60000 for i in range(1, len(ts))]
    dist = {}
    for e in ecarts:
        k = round(e)
        dist[k] = dist.get(k, 0) + 1
    attendus = int((ts[-1] - ts[0]) / PAS_ATTENDU_MS) + 1 if len(ts) > 1 else 1
    q = QualiteSerie(
        n_snapshots=len(ts), n_fichiers=n_fichiers, doublons=doublons,
        debut=datetime.fromtimestamp(ts[0] / 1000, timezone.utc),
        fin=datetime.fromtimestamp(ts[-1] / 1000, timezone.utc),
        duree_min=(ts[-1] - ts[0]) / 60000,
        intervalle_median_min=statistics.median(ecarts) if ecarts else None,
        distribution_intervalles=dict(sorted(dist.items())),
        creneaux_attendus=attendus, trous=max(0, attendus - len(ts)),
        coins=len({p.coin for p in pts}), ordonnee=ts == sorted(ts))
    return pts, q


# --------------------------------------------------------------------------- extraction
def serie_prix(points: Sequence[PointCarnet], coin: str) -> list[tuple[datetime, float]]:
    """Serie (instant, mid) d'un coin. Les instants sans milieu defini sont OMIS,
    jamais interpoles : un trou reste un trou."""
    s = [(datetime.fromtimestamp(p.t / 1000, timezone.utc), p.mid)
         for p in points if p.coin == coin and p.mid is not None]
    s.sort(key=lambda x: x[0])
    return s


def coins_exploitables(points: Sequence[PointCarnet], *, min_points: int
                       ) -> list[tuple[str, int]]:
    """Coins ayant au moins `min_points` milieux definis, du mieux couvert au moins bon.
    Sert a savoir ce qui EST classable avant de tenter de classer."""
    c: dict[str, int] = {}
    for p in points:
        if p.mid is not None:
            c[p.coin] = c.get(p.coin, 0) + 1
    return sorted([(k, v) for k, v in c.items() if v >= min_points],
                  key=lambda x: -x[1])


@dataclass
class RapportRegime:
    """Sortie de bout en bout : snapshots -> serie -> variables -> regimes -> walk-forward."""
    qualite: QualiteSerie
    n_points_coin_instant: int
    coins_classables: int
    coins_total: int
    regimes: dict = field(default_factory=dict)          # coin -> Regime
    walk_forward: dict = field(default_factory=dict)     # coin -> list[Regime]
    refus: dict = field(default_factory=dict)            # coin -> raison
    etat: str = "INSUFFISANT"

    def resume(self) -> str:
        l = [f"REGIME {self.etat}", "  " + self.qualite.resume(),
             f"  {self.n_points_coin_instant} points coin-instant | "
             f"{self.coins_classables}/{self.coins_total} coins classables"]
        for coin, r in list(self.regimes.items())[:8]:
            wf = len(self.walk_forward.get(coin, ()))
            l.append(f"    {coin:<12} {r.etiquette:<34} walk-forward: {wf} fenetre(s)")
        if self.refus:
            coin, raison = next(iter(self.refus.items()))
            l.append(f"  refus ({len(self.refus)} coins), ex. {coin} : {raison[:70]}")
        return "\n".join(l)


def rapport_regime(racine: str, *, coins: Sequence[str] | None = None,
                   max_coins: int = 20, taille_fenetre: int | None = None,
                   pas: int = 5) -> RapportRegime:
    """
    Chaine complete, sans aucune requete : lit le lac, normalise, classe, et tente
    le walk-forward. Rien n'est a modifier a la main quand de nouveaux snapshots
    arrivent — c'est le nombre de points disponibles qui fait basculer l'etat.

    `etat` : INSUFFISANT tant qu'aucun coin n'atteint le minimum ; PROVISOIRE quand
    des regimes sortent mais qu'aucun walk-forward n'est possible ; COMPLET quand les
    deux le sont.
    """
    from . import regime as RG

    pts, q = construire_serie(racine, coins=coins)
    fen = taille_fenetre or RG.MIN_POINTS
    classables = coins_exploitables(pts, min_points=RG.MIN_POINTS)
    rap = RapportRegime(qualite=q, n_points_coin_instant=len(pts),
                        coins_classables=len(classables), coins_total=q.coins)

    for coin, _ in classables[:max_coins]:
        try:
            rap.regimes[coin] = classifier_coin(pts, coin)
        except InsufficientData as e:
            rap.refus[coin] = str(e)
            continue
        try:
            rap.walk_forward[coin] = RG.serie_de_regimes(
                serie_prix(pts, coin), taille_fenetre=fen, pas=pas)
        except InsufficientData as e:
            rap.refus.setdefault(coin + " (walk-forward)", str(e))

    if not classables:
        # On expose la raison sur un coin representatif plutot qu'un simple compteur.
        for coin, _ in coins_exploitables(pts, min_points=1)[:1]:
            try:
                classifier_coin(pts, coin)
            except InsufficientData as e:
                rap.refus[coin] = str(e)
        rap.etat = "INSUFFISANT"
    elif rap.walk_forward:
        rap.etat = "COMPLET"
    else:
        rap.etat = "PROVISOIRE"
    return rap


def classifier_coin(points: Sequence[PointCarnet], coin: str, **kw):
    """Passe la serie d'un coin au moteur de regime. Propage InsufficientData tel quel :
    un coin insuffisamment couvert doit rester non classe, pas classe par defaut."""
    from . import regime as RG

    s = serie_prix(points, coin)
    if not s:
        raise InsufficientData(f"{coin} : aucun milieu defini dans la serie")
    return RG.classifier([p for _, p in s], debut=s[0][0], fin=s[-1][0], **kw)
