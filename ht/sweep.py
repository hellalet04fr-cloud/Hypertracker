#!/usr/bin/env python3
"""
Detecteur LIQUIDITY SWEEP et evaluation des 12 variantes PRE-ENREGISTREES.

Implemente litteralement `preenregistrement_liquidity_sweep.json`. Aucun parametre
n'est ajustable hors des trois axes geles ; aucune variante ne peut etre ajoutee.

Le sweep n'est pas une cassure : le prix va chercher la liquidite au-dela d'un extreme
recent — la ou dorment les stops — puis REFERME a l'interieur. C'est la cloture qui
distingue le balayage de la sortie de range, et c'est pour cela qu'elle est exigee.

Aucune donnee intrabarre n'est utilisee, et l'ATR se calcule strictement sur les barres
ANTERIEURES a la barre de signal : le detecteur ne peut pas voir son propre resultat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .schema import DERIVED, InsufficientData, require

TP_ATR = 1.5
SL_ATR = 1.0
ATR_PERIODE = 14
FRAIS_ALLER_RETOUR_BP = 17.32      # mesure sur 216 closed_trades natifs, non suppose
MIN_BOUGIES = 3000


@dataclass
class Evenement:
    coin: str
    t: int
    sens: str                      # LONG / SHORT
    entree: float
    sl: float
    tp: float
    atr: float
    issue: int | None = None       # 1 = TP avant SL, 0 = sinon, None = non resolu
    barres_tenues: int = 0
    rendement_brut: float = 0.0    # en fraction du notionnel
    funding: float | None = None
    classification: str = DERIVED


def _atr(bougies: Sequence[Mapping[str, Any]], i: int, periode: int = ATR_PERIODE) -> float | None:
    """ATR sur les `periode` barres se terminant en i-1. Jamais la barre i."""
    if i - periode < 1:
        return None
    s = 0.0
    for k in range(i - periode, i):
        h, b = float(bougies[k]["h"]), float(bougies[k]["l"])
        pc = float(bougies[k - 1]["c"])
        s += max(h - b, abs(h - pc), abs(b - pc))
    return s / periode


def detecter(bougies: Sequence[Mapping[str, Any]], *, coin: str, lookback: int,
             penetration_atr: float, horizon_barres: int) -> list[Evenement]:
    """Applique UNE variante a UNE serie de bougies. Retourne les evenements resolus."""
    require(lookback >= 2, "lookback trop court")
    n = len(bougies)
    out: list[Evenement] = []
    debut = max(lookback, ATR_PERIODE + 1)
    for i in range(debut, n - horizon_barres):
        atr = _atr(bougies, i)
        if not atr or atr <= 0:
            continue
        fen = bougies[i - lookback:i]
        H = max(float(x["h"]) for x in fen)
        L = min(float(x["l"]) for x in fen)
        h, b, c = float(bougies[i]["h"]), float(bougies[i]["l"]), float(bougies[i]["c"])

        if h > H + penetration_atr * atr and c < H:
            sens, sl, tp = "SHORT", c + SL_ATR * atr, c - TP_ATR * atr
        elif b < L - penetration_atr * atr and c > L:
            sens, sl, tp = "LONG", c - SL_ATR * atr, c + TP_ATR * atr
        else:
            continue

        e = Evenement(coin=coin, t=int(bougies[i]["t"]), sens=sens, entree=c,
                      sl=sl, tp=tp, atr=atr)
        for j in range(i + 1, min(i + 1 + horizon_barres, n)):
            hj, bj = float(bougies[j]["h"]), float(bougies[j]["l"])
            e.barres_tenues = j - i
            touche_sl = (bj <= e.sl) if sens == "LONG" else (hj >= e.sl)
            touche_tp = (hj >= e.tp) if sens == "LONG" else (bj <= e.tp)
            if touche_sl and touche_tp:
                # ordre intrabarre inconnu : trancher en sa faveur serait fabriquer
                # de la donnee. On compte PERDANT.
                e.issue, e.rendement_brut = 0, (e.sl - e.entree) / e.entree
                if sens == "SHORT":
                    e.rendement_brut = (e.entree - e.sl) / e.entree
                break
            if touche_sl:
                e.issue = 0
                e.rendement_brut = ((e.sl - e.entree) if sens == "LONG"
                                    else (e.entree - e.sl)) / e.entree
                break
            if touche_tp:
                e.issue = 1
                e.rendement_brut = ((e.tp - e.entree) if sens == "LONG"
                                    else (e.entree - e.tp)) / e.entree
                break
        if e.issue is None:
            j = min(i + horizon_barres, n - 1)
            cj = float(bougies[j]["c"])
            e.barres_tenues = j - i
            e.rendement_brut = ((cj - e.entree) if sens == "LONG"
                                else (e.entree - cj)) / e.entree
            e.issue = 1 if e.rendement_brut > 0 else 0
        out.append(e)
    return out


def appliquer_couts(evs: Sequence[Evenement],
                    funding_par_coin: Mapping[str, Sequence[tuple[int, float]]] | None = None
                    ) -> None:
    """
    Retranche les frais MESURES, puis le funding REEL sur la duree de detention.

    Un evenement dont le funding n'a pas pu etre mesure garde `funding = None` et sera
    EXCLU par l'appelant : un funding inconnu ne devient jamais zero.
    """
    frais = FRAIS_ALLER_RETOUR_BP / 10_000.0
    for e in evs:
        e.rendement_brut -= frais
        if funding_par_coin is None:
            continue
        serie = funding_par_coin.get(e.coin)
        if not serie:
            continue
        fin = e.t + e.barres_tenues * 3_600_000
        taux = sum(r for tt, r in serie if e.t <= tt < fin)
        # funding paye par un long, encaisse par un short
        e.funding = -taux if e.sens == "LONG" else taux
        e.rendement_brut += e.funding


# --------------------------------------------------------------- execution maker
FRAIS_MAKER_BP = 1.500     # mesure sur 674 fills maker reels (crossed=False)
FRAIS_TAKER_BP = 4.320     # mesure sur 6156 fills taker reels (crossed=True)

NON_REMPLI = "NON_REMPLI"
NON_OBSERVABLE = "NON_OBSERVABLE"
REMPLI = "REMPLI"


@dataclass
class Execution:
    """Sort d'UN signal soumis a une entree a cours limite."""
    coin: str
    t: int
    sens: str
    etat: str
    prix_limite: float
    barres_attente: int = 0
    issue: int | None = None
    rendement_net: float | None = None
    funding: float | None = None


def executer_maker(bougies: Sequence[Mapping[str, Any]], ev: "Evenement", i: int, *,
                   distance_atr: float, attente_barres: int, horizon_barres: int,
                   funding_serie: Sequence[tuple[int, float]] | None = None) -> Execution:
    """
    Soumet un signal a une entree limite et n'en fait un trade QUE si le remplissage
    est demontrable.

    PENETRATION STRICTE. Un achat limite a P n'est declare rempli que si une barre
    verifie low < P : le prix a traverse le niveau, donc l'execution est certaine quelle
    que soit la position dans la file d'attente. Un simple contact (low == P) ne prouve
    rien et sort en NON_OBSERVABLE — jamais converti en fill hypothetique.

    L'horizon court depuis la barre de SIGNAL, pas depuis le fill : attendre ne donne
    aucun temps supplementaire. C'est ce qui empeche l'execution maker de se fabriquer
    un avantage en tenant ses positions plus longtemps.
    """
    n = len(bougies)
    lim = (ev.entree - distance_atr * ev.atr) if ev.sens == "LONG" \
        else (ev.entree + distance_atr * ev.atr)
    ex = Execution(coin=ev.coin, t=ev.t, sens=ev.sens, etat=NON_REMPLI, prix_limite=lim)

    j_fill = None
    for j in range(i + 1, min(i + 1 + attente_barres, n)):
        lo, hi = float(bougies[j]["l"]), float(bougies[j]["h"])
        if ev.sens == "LONG":
            if lo < lim:
                j_fill = j; break
            if lo == lim:
                ex.etat = NON_OBSERVABLE; return ex
        else:
            if hi > lim:
                j_fill = j; break
            if hi == lim:
                ex.etat = NON_OBSERVABLE; return ex
    if j_fill is None:
        return ex

    ex.etat = REMPLI
    ex.barres_attente = j_fill - i
    sl = lim - SL_ATR * ev.atr if ev.sens == "LONG" else lim + SL_ATR * ev.atr
    tp = lim + TP_ATR * ev.atr if ev.sens == "LONG" else lim - TP_ATR * ev.atr
    fin = min(i + horizon_barres, n - 1)          # horizon depuis le SIGNAL

    r = None
    for j in range(j_fill + 1, fin + 1):
        lo, hi = float(bougies[j]["l"]), float(bougies[j]["h"])
        t_sl = (lo <= sl) if ev.sens == "LONG" else (hi >= sl)
        t_tp = (hi >= tp) if ev.sens == "LONG" else (lo <= tp)
        if t_sl and t_tp:
            ex.issue = 0
            r = (sl - lim) / lim if ev.sens == "LONG" else (lim - sl) / lim
            break
        if t_sl:
            ex.issue = 0
            r = (sl - lim) / lim if ev.sens == "LONG" else (lim - sl) / lim
            break
        if t_tp:
            ex.issue = 1
            r = (tp - lim) / lim if ev.sens == "LONG" else (lim - tp) / lim
            break
        ex.barres_attente = j - i
    if r is None:
        c = float(bougies[fin]["c"])
        r = (c - lim) / lim if ev.sens == "LONG" else (lim - c) / lim
        ex.issue = 1 if r > 0 else 0

    r -= (FRAIS_MAKER_BP + FRAIS_TAKER_BP) / 1e4      # entree maker, sortie taker
    if funding_serie:
        t0 = int(bougies[j_fill]["t"])
        t1 = int(bougies[fin]["t"])
        taux = sum(x for tt, x in funding_serie if t0 <= tt < t1)
        ex.funding = -taux if ev.sens == "LONG" else taux
        r += ex.funding
    ex.rendement_net = r
    return ex


def balayer_parallele(taches, fonction, *, max_workers: int = 8):
    """
    Repartit un balayage de grille sur les coeurs disponibles.

    MESURE, pas suppose : sur 6 combinaisons x 174 coins, 171,8 s en sequentiel contre
    84,0 s sur 8 processus, soit 2,05x, resultats identiques au comptage pres. Une
    variante ou chaque worker rechargeait les bougies depuis le disque a ete essayee
    puis JETEE : 1,58x seulement, la relecture de 174 fichiers par processus coutant
    plus cher que le pickle qu'elle evitait.

    Une tache par combinaison, pas par coin : le decoupage plus fin ajoute de l'IPC
    sans equilibrer davantage la charge.
    """
    from concurrent.futures import ProcessPoolExecutor
    import os
    n = min(max_workers, os.cpu_count() or 1)
    if n <= 1 or len(taches) <= 1:
        return [fonction(t) for t in taches]
    with ProcessPoolExecutor(max_workers=n) as ex:
        return list(ex.map(fonction, taches))
