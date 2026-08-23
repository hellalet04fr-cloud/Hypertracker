#!/usr/bin/env python3
"""
Regime Engine — classification du contexte de marche.

Produit UNIQUEMENT des variables verifiables. Aucun signal de trading n'en sort :
ce module decrit l'etat du marche, il ne dit jamais quoi en faire.

Regimes, deliberement orthogonaux sur deux axes plutot qu'une seule etiquette
fourre-tout — un marche peut etre en tendance ET en compression, et ecraser les deux
en un seul label perdrait l'information :
  direction   : TENDANCE_HAUSSE | TENDANCE_BAISSE | RANGE
  volatilite  : COMPRESSION | NORMALE | EXPANSION
plus un drapeau CHANGEMENT_DE_REGIME quand la fenetre courante rompt avec la precedente.

Toutes les mesures exigent un minimum de points. En dessous, InsufficientData : un
regime estime sur cinq observations decrit le bruit d'echantillonnage, pas le marche.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .schema import InsufficientData, require

TENDANCE_HAUSSE = "TENDANCE_HAUSSE"
TENDANCE_BAISSE = "TENDANCE_BAISSE"
RANGE = "RANGE"
COMPRESSION = "COMPRESSION"
NORMALE = "NORMALE"
EXPANSION = "EXPANSION"
INCONNU = "INCONNU"

MIN_POINTS = 20              # sous ce seuil, aucune classification n'est emise
MIN_POINTS_CHANGEMENT = 40   # il faut deux fenetres comparables


@dataclass(frozen=True)
class Regime:
    direction: str
    volatilite: str
    changement: bool
    # variables brutes, exposees pour etre verifiables independamment de l'etiquette
    rendement_total: float
    ratio_directionnel: float      # |somme des variations| / somme des |variations|
    volatilite_realisee: float
    volatilite_reference: float | None
    n_points: int
    debut: datetime | None = None
    fin: datetime | None = None

    @property
    def etiquette(self) -> str:
        return f"{self.direction}/{self.volatilite}" + ("/CHANGEMENT" if self.changement else "")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["etiquette"] = self.etiquette
        return d


# --------------------------------------------------------------------------- mesures
def _variations(prix: Sequence[float]) -> list[float]:
    return [(prix[i] - prix[i - 1]) / prix[i - 1]
            for i in range(1, len(prix)) if prix[i - 1] > 0]


def ratio_directionnel(prix: Sequence[float]) -> float:
    """
    |deplacement net| / distance parcourue, dans [0,1].

    Proche de 1 : le marche va quelque part (tendance). Proche de 0 : il fait des
    aller-retours (range). C'est l'efficience de Kaufman, choisie parce qu'elle ne
    depend d'aucun seuil de prix ni d'aucune moyenne mobile a calibrer — donc rien
    a sur-ajuster.
    """
    v = _variations(prix)
    require(len(v) >= 2, f"au moins 3 prix requis (recu {len(prix)})")
    parcourue = sum(abs(x) for x in v)
    if parcourue <= 0:
        raise InsufficientData("serie de prix constante : direction indefinie")
    return abs(sum(v)) / parcourue


def volatilite_realisee(prix: Sequence[float]) -> float:
    """Ecart-type des variations relatives. Non annualise : l'annualisation exigerait
    une frequence d'echantillonnage stable, que rien ne garantit ici."""
    v = _variations(prix)
    require(len(v) >= 2, f"au moins 3 prix requis (recu {len(prix)})")
    return statistics.stdev(v)


# --------------------------------------------------------------------------- moteur
def classifier(prix: Sequence[float],
               *,
               reference: Sequence[float] | None = None,
               seuil_tendance: float = 0.35,
               seuil_compression: float = 0.6,
               seuil_expansion: float = 1.6,
               debut: datetime | None = None,
               fin: datetime | None = None) -> Regime:
    """
    Classe une fenetre de prix.

    `reference` : fenetre precedente, servant d'echelle a la volatilite. Sans elle, la
    volatilite est classee NORMALE et le changement de regime reste indetermine — on
    ne peut pas dire qu'une volatilite est « elevee » sans dire elevee par rapport a quoi.

    Les seuils sont des constantes NOMMEES et modifiables, pas des nombres magiques.
    Ils n'ont pas ete ajustes sur des donnees : 0,35 sur le ratio directionnel separe
    l'aller-retour du deplacement net, 0,6 et 1,6 encadrent un rapport de volatilite
    neutre. Aucune validation hors echantillon ne les soutient a ce stade.
    """
    require(len(prix) >= MIN_POINTS,
            f"au moins {MIN_POINTS} points requis pour classer un regime "
            f"(recu {len(prix)}) — en dessous on decrirait le bruit")
    if not all(isinstance(p, (int, float)) and p > 0 and math.isfinite(p) for p in prix):
        raise InsufficientData("serie de prix invalide : valeurs nulles, negatives ou non finies")

    rd = ratio_directionnel(prix)
    vol = volatilite_realisee(prix)
    rendement = (prix[-1] - prix[0]) / prix[0]

    if rd >= seuil_tendance:
        direction = TENDANCE_HAUSSE if rendement > 0 else TENDANCE_BAISSE
    else:
        direction = RANGE

    vol_ref = None
    volat = NORMALE
    changement = False
    if reference is not None and len(reference) >= MIN_POINTS:
        vol_ref = volatilite_realisee(reference)
        if vol_ref > 0:
            r = vol / vol_ref
            volat = COMPRESSION if r < seuil_compression else (
                EXPANSION if r > seuil_expansion else NORMALE)
            try:
                rd_ref = ratio_directionnel(reference)
                # Changement = bascule de famille directionnelle OU rupture de volatilite
                dir_ref = RANGE if rd_ref < seuil_tendance else (
                    TENDANCE_HAUSSE if (reference[-1] - reference[0]) > 0 else TENDANCE_BAISSE)
                changement = (dir_ref != direction) or volat in (COMPRESSION, EXPANSION)
            except InsufficientData:
                changement = volat in (COMPRESSION, EXPANSION)

    return Regime(direction=direction, volatilite=volat, changement=changement,
                  rendement_total=rendement, ratio_directionnel=rd,
                  volatilite_realisee=vol, volatilite_reference=vol_ref,
                  n_points=len(prix), debut=debut, fin=fin)


def serie_de_regimes(points: Sequence[tuple[datetime, float]],
                     *, taille_fenetre: int = 30, pas: int = 10, **kw) -> list[Regime]:
    """
    Classe une serie complete en fenetres glissantes, chaque fenetre prenant la
    precedente comme reference. Sert a produire des variables datees, pas un signal.
    """
    require(len(points) >= 2 * MIN_POINTS,
            f"au moins {2 * MIN_POINTS} points pour une serie de regimes "
            f"(recu {len(points)})")
    pts = sorted(points, key=lambda x: x[0])
    out = []
    i = taille_fenetre
    while i + taille_fenetre <= len(pts):
        ref = [p for _, p in pts[i - taille_fenetre:i]]
        cur = pts[i:i + taille_fenetre]
        out.append(classifier([p for _, p in cur], reference=ref,
                              debut=cur[0][0], fin=cur[-1][0], **kw))
        i += pas
    if not out:
        raise InsufficientData(
            f"aucune fenetre complete : {len(pts)} points pour une fenetre de "
            f"{taille_fenetre} avec reference de meme taille")
    return out


# --------------------------------------------------------------------------- carnet
def mid_depuis_carnet(ordres: Sequence[Mapping[str, Any]], coin: str) -> float:
    """
    Prix milieu d'un coin a partir d'un snapshot de carnet.

    Le meilleur bid est le plus haut prix cote B, le meilleur ask le plus bas cote A.
    Si un seul cote est present, le milieu n'existe pas — on leve plutot que de rendre
    le prix du seul cote disponible, qui serait biaise par construction.
    """
    bids = [float(o["limitPx"]) for o in ordres
            if o.get("coin") == coin and str(o.get("side")) == "B"
            and not o.get("isTrigger") and float(o.get("limitPx") or 0) > 0]
    asks = [float(o["limitPx"]) for o in ordres
            if o.get("coin") == coin and str(o.get("side")) == "A"
            and not o.get("isTrigger") and float(o.get("limitPx") or 0) > 0]
    if not bids or not asks:
        raise InsufficientData(
            f"{coin} : carnet unilateral ({len(bids)} bids, {len(asks)} asks), "
            "le milieu n'est pas defini")
    b, a = max(bids), min(asks)
    if a < b:
        # Carnet croise : normal sur un snapshot agrege, mais le milieu reste defini.
        b, a = a, b
    return (a + b) / 2.0
