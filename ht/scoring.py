#!/usr/bin/env python3
"""
Primitives statistiques du score des wallets.

CE MODULE NE CONTIENT AUCUNE SCIENCE NOUVELLE. Les sept fonctions ci-dessous
sont reprises A L'IDENTIQUE des scripts qui ont produit le classement livre.
Elles vivaient hors du depot, dans un repertoire de travail temporaire, ce qui
avait une consequence lourde : l'etape de classement ne pouvait pas etre rejouee
par le systeme lui-meme. Aucune automatisation quotidienne n'etait possible tant
que le calcul du classement n'existait pas dans le depot.

Deplacer n'est pas modifier. `tests/test_lifecycle.py` verifie que ce module
reproduit l'a priori scelle du classement en production — m = -0.0724 et
tau = 0.0744 — au dix-millieme pres. Si une seule de ces fonctions derivait, ce
test tomberait.
"""
from __future__ import annotations

import math
import statistics as st

__all__ = ["sharpe", "se_sharpe", "mad", "apriori", "phi", "rangs", "spearman",
           "drawdown", "concentration", "MIN_TRADES"]

# Plancher de trades pour qu'un wallet entre dans le calcul du classement.
# Identique a ht.ranking.MIN_TRADES_FOR_RANKING, qui est un seuil SCELLE.
MIN_TRADES = 30


def sharpe(r):
    """Sharpe par trade, non annualise."""
    if len(r) < 2:
        return None
    sd = st.pstdev(r)
    return (st.mean(r) / sd) if sd > 0 else None


def se_sharpe(r):
    """Erreur type du Sharpe, corrigee asymetrie/kurtosis (Mertens)."""
    n = len(r)
    if n < 3:
        return None
    m, sd = st.mean(r), st.pstdev(r)
    if sd <= 0:
        return None
    sr = m / sd
    g3 = sum(((x - m) / sd) ** 3 for x in r) / n
    g4 = sum(((x - m) / sd) ** 4 for x in r) / n
    v = (1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) / (n - 1)
    return math.sqrt(v) if v > 0 else None


def mad(v):
    """Ecart absolu median, remis a l'echelle d'un ecart type gaussien."""
    m = st.median(v)
    return st.median([abs(x - m) for x in v]) / 0.6745


def apriori(srs, ses):
    """m robuste, tau^2 par DECONVOLUTION (retire le bruit d'estimation)."""
    m = st.median(srs)
    disp = mad(srs)
    tau2 = max(1e-9, disp ** 2 - st.mean([s ** 2 for s in ses]))
    return m, tau2


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def rangs(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        moy = (i + j) / 2.0
        for k in range(i, j + 1):
            r[o[k]] = moy
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = rangs(x), rangs(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else 0.0


def drawdown(r):
    """Repli maximal de la courbe de PnL net cumule.

    Le sommet part de 0.0 et non du premier point : un repli sous le point de
    depart compte. C'est la convention de ht.ranking, et s'en ecarter donnait
    jusqu'a 5 499 USD d'ecart sur les wallets du classement.
    """
    c = pic = dd = 0.0
    for x in r:
        c += x
        pic = max(pic, c)
        dd = max(dd, pic - c)
    return dd


def concentration(r):
    """PART ABSOLUE : max|r| / somme|r|, bornee dans [0, 1].

    C'est la metrique en vigueur dans `classement_wallets.json`, qui la declare
    elle-meme dans son champ `metrique_concentration`. La formulation naive
    max(r) / somme(r) a ete abandonnee : elle etait indefinie pour 163 wallets
    sur 231 — un PnL total negatif ou nul n'a pas de part — atteignait 34.38 la
    ou une part est censee vivre dans [0, 1], et correlait au score a 0.54. La
    part absolue est definie partout ou le wallet a trade, bornee par
    construction, et sa correlation au score tombe a 0.11.

    None seulement si le wallet n'a aucun mouvement : la aussi, on ne substitue
    aucune valeur.
    """
    t = sum(abs(x) for x in r)
    return (max(abs(x) for x in r) / t) if t > 0 else None
