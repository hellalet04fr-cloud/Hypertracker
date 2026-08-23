#!/usr/bin/env python3
"""
Research Report — repond a deux questions, et seulement a celles-la :

  « Pourquoi ce wallet est-il classe ici ? »
      -> decomposition du score, contribution de chaque composante, composantes
         absentes, alertes de qualite de donnees.

  « Dans quelles conditions son avantage disparait-il ? »
      -> conditions d'invalidation, deduites de ce qui est MESURE : regimes ou
         l'avantage n'est pas distinguable, fragilite au test de permutation,
         dependance a quelques trades, couverture insuffisante, fraicheur.

Ce module ne produit aucun signal et ne recommande aucune action. Il explique un
classement, ce qui est une condition necessaire pour qu'on puisse le contester.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .schema import DERIVED, InsufficientData

SEUIL_CONCENTRATION = 0.40      # part du PnL portee par le meilleur trade


@dataclass
class Rapport:
    address: str
    classification: str
    score: float | None
    complet: bool
    n_trades: int
    n_effectif: float
    pourquoi: list[str] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    incertitudes: list[str] = field(default_factory=list)
    conditionnel: Any = field(default=None, repr=False)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("conditionnel", None)
        return d

    def texte(self) -> str:
        l = [f"=== {self.address} ===",
             f"classification : {self.classification}"
             + ("" if self.complet else "   [SCORE INCOMPLET]"),
             f"score : {'n/a' if self.score is None else f'{self.score:.4f}'}"
             f"   n={self.n_trades}   n_effectif={self.n_effectif:.1f}",
             "",
             "POURQUOI CE CLASSEMENT"]
        l += [f"  - {x}" for x in self.pourquoi] or ["  - (aucun element)"]
        l += ["", "OU L'AVANTAGE DISPARAIT"]
        l += [f"  - {x}" for x in self.invalidation] or ["  - (aucune condition identifiee)"]
        if self.incertitudes:
            l += ["", "CE QUI N'EST PAS MESURE"]
            l += [f"  - {x}" for x in self.incertitudes]
        return "\n".join(l)


def rapport(score, trades: Sequence[Mapping[str, Any]] = (),
            conditionnel=None, *, classification: str = DERIVED) -> Rapport:
    """
    Construit le rapport d'un wallet a partir d'un `ScoreWallet` (ht.wallet_intel),
    de ses trades et, si disponible, de son analyse conditionnelle (ht.conditional).
    """
    r = Rapport(address=score.address, classification=classification,
                score=score.score, complet=score.complet,
                n_trades=score.n_trades, n_effectif=score.n_effectif,
                conditionnel=conditionnel)

    # -- pourquoi : contributions triees, dans l'unite du score final
    contribs = score.contributions()
    total = sum(c for _, c in contribs) or 1.0
    for nom, c in contribs[:4]:
        comp = score.par_nom(nom)
        r.pourquoi.append(
            f"{nom} contribue {c:.4f} ({c/total:.0%} du score) — "
            f"valeur {comp.valeur:.4f} {comp.unite}".rstrip())
    faibles = [n for n, c in contribs[-2:] if c < 0.02]
    for nom in faibles:
        r.pourquoi.append(f"{nom} ne contribue presque rien ({nom} faible)")

    # -- ce qui n'est pas mesure
    for nom in score.manquantes:
        comp = score.par_nom(nom)
        r.incertitudes.append(f"{nom} : {comp.raison if comp else 'non calculable'}")
    if not score.complet:
        r.incertitudes.append(
            "le score est renormalise sur les composantes disponibles : le comparer "
            "a un score complet reste risque")

    # -- invalidation : d'abord ce que les alertes disent deja
    r.invalidation.extend(score.alertes)

    # -- fragilite statistique
    rob = score.par_nom("robustesse")
    if rob and rob.calculable and rob.valeur is not None and rob.valeur > 0.05:
        r.invalidation.append(
            f"la performance n'est pas distinguable du hasard (p={rob.valeur:.3f} au "
            "test de permutation) : l'avantage disparait des qu'on exige la significativite")

    # -- concentration du PnL sur quelques trades
    pnls = []
    for t in trades:
        v = t.get("realizedPnlNetUsd")
        if v is None:
            v = t.get("realizedPnlUsd")
        if v is not None:
            pnls.append(float(v))
    if pnls:
        tot = sum(pnls)
        if tot > 0:
            meilleur = max(pnls)
            part = meilleur / tot
            if part > SEUIL_CONCENTRATION:
                r.invalidation.append(
                    f"{part:.0%} du PnL vient d'un seul trade : retirer ce trade "
                    "efface l'essentiel de l'avantage")
            gagnants = sorted([p for p in pnls if p > 0], reverse=True)
            if gagnants:
                k = 0
                cum = 0.0
                while k < len(gagnants) and cum < 0.5 * tot:
                    cum += gagnants[k]
                    k += 1
                if k <= max(2, len(pnls) // 20):
                    r.invalidation.append(
                        f"la moitie du PnL tient a {k} trade(s) sur {len(pnls)}")

    # -- couverture et fraicheur
    cov = score.par_nom("couverture")
    if cov and cov.calculable and cov.valeur is not None and cov.valeur < 0.3:
        r.invalidation.append(
            f"qualite de couverture faible ({cov.valeur:.2f}) : l'historique visible "
            "est ampute, la performance mesuree n'est pas celle du wallet")
    fr = score.par_nom("fraicheur")
    if fr and fr.calculable and fr.valeur is not None and fr.valeur > 30:
        r.invalidation.append(
            f"aucun trade depuis {fr.valeur:.0f} jours : l'avantage n'est plus observe")

    # -- conditionnel : la ou l'avantage tient et la ou il ne tient pas
    if conditionnel is not None:
        exploitables = [p for p in conditionnel.par_regime if p.suffisant]
        if not exploitables:
            r.incertitudes.append(
                "aucun regime n'atteint le minimum de trades : la performance "
                "conditionnelle n'est pas mesurable")
        else:
            perdants = [p for p in exploitables if p.pnl_net_total <= 0]
            for p in perdants:
                r.invalidation.append(
                    f"en regime {p.regime} : PnL {p.pnl_net_total:.2f} sur "
                    f"{p.n_trades} trades — l'avantage ne tient pas dans ce contexte")
            if not conditionnel.ecart_significatif and len(exploitables) >= 2:
                r.incertitudes.append(
                    "aucun ecart distinguable entre regimes : rien ne prouve que le "
                    "wallet soit meilleur dans un contexte que dans un autre")
        if conditionnel.n_sans_regime:
            r.incertitudes.append(
                f"{conditionnel.n_sans_regime} trades hors de toute fenetre de regime "
                "connue : non pris en compte")

    if classification == DERIVED:
        r.incertitudes.append(
            "donnees DERIVED : reconstruites depuis Hyperliquid, non validees contre "
            "la source native — aucun classement definitif n'en decoule")
    return r


def rapport_collectif(scores: Sequence[Any],
                      trades_par_wallet: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                      conditionnels: Mapping[str, Any] | None = None,
                      **kw) -> list[Rapport]:
    tp = trades_par_wallet or {}
    cond = conditionnels or {}
    return [rapport(s, tp.get(s.address, ()), cond.get(s.address), **kw) for s in scores]
