#!/usr/bin/env python3
"""
Wallet x Regime — performance conditionnelle.

Mesure si un wallet se comporte differemment selon le contexte de marche, et surtout
si l'ecart observe est distinguable du hasard. Sans intervalle d'incertitude, une
performance conditionnelle n'est qu'un decoupage de plus d'un petit echantillon :
avec assez de decoupages, on trouve toujours un regime ou un wallet « brille ».

C'est precisement le piege que ce module doit rendre visible plutot que d'exploiter.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .schema import InsufficientData, require

MIN_TRADES_PAR_REGIME = 20      # sous ce seuil, aucune statistique conditionnelle


@dataclass(frozen=True)
class PerfRegime:
    regime: str
    n_trades: int
    pnl_net_total: float
    pnl_moyen: float
    win_rate: float
    win_rate_bas: float             # bornes de credibilite, jamais le point seul
    win_rate_haut: float
    max_drawdown: float
    ecart_type: float
    suffisant: bool
    raison: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalyseConditionnelle:
    address: str
    par_regime: list[PerfRegime] = field(default_factory=list)
    n_total: int = 0
    n_sans_regime: int = 0
    regimes_insuffisants: tuple[str, ...] = ()
    ecart_significatif: bool = False
    commentaire: str = ""

    def regime(self, nom: str) -> PerfRegime | None:
        return next((p for p in self.par_regime if p.regime == nom), None)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["par_regime"] = [p.as_dict() for p in self.par_regime]
        return d

    def resume(self) -> str:
        l = [f"{self.address[:10]}...  {self.n_total} trades, "
             f"{self.n_sans_regime} sans regime connu"]
        for p in self.par_regime:
            if p.suffisant:
                l.append(f"    {p.regime:<26} n={p.n_trades:<4} pnl={p.pnl_net_total:>10.2f} "
                         f"wr={p.win_rate:.2f} [{p.win_rate_bas:.2f}-{p.win_rate_haut:.2f}] "
                         f"dd={p.max_drawdown:.2f}")
            else:
                l.append(f"    {p.regime:<26} n={p.n_trades:<4} — {p.raison}")
        if self.commentaire:
            l.append(f"    => {self.commentaire}")
        return "\n".join(l)


def _pnl(t: Mapping[str, Any]) -> float | None:
    v = t.get("realizedPnlNetUsd")
    if v is None:
        v = t.get("realizedPnlUsd")
    return float(v) if v is not None else None


def _ms(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def analyser(address: str,
             trades: Sequence[Mapping[str, Any]],
             regimes: Sequence[Mapping[str, Any]],
             *,
             asof: datetime | None = None,
             min_trades: int = MIN_TRADES_PAR_REGIME) -> AnalyseConditionnelle:
    """
    Croise les trades d'un wallet avec une chronologie de regimes.

    `regimes` : sequence de dicts portant `debut`, `fin` (datetime ou epoch ms) et
    `etiquette`. Un trade est attribue au regime contenant son `closeTime`. Un trade
    hors de toute fenetre est compte separement — jamais rattache au regime le plus
    proche, ce qui inventerait une correspondance.
    """
    from .probability import wilson_proportion

    require(bool(address), "adresse vide")
    asof = asof or datetime.now(timezone.utc)
    fenetres = []
    for r in regimes:
        d, f = _ms(r.get("debut")), _ms(r.get("fin"))
        if d is None or f is None or f < d:
            continue
        fenetres.append((d, f, str(r.get("etiquette") or "INCONNU")))
    require(bool(fenetres), "aucune fenetre de regime exploitable")

    par_regime: dict[str, list[float]] = {}
    sans = 0
    n_tot = 0
    for t in trades:
        p = _pnl(t)
        tc = _ms(t.get("closeTime"))
        if p is None or tc is None:
            continue
        n_tot += 1
        etiq = next((e for d, f, e in fenetres if d <= tc <= f), None)
        if etiq is None:
            sans += 1
            continue
        par_regime.setdefault(etiq, []).append(p)

    sorties, insuffisants = [], []
    for etiq, pnls in sorted(par_regime.items()):
        n = len(pnls)
        if n < min_trades:
            insuffisants.append(etiq)
            sorties.append(PerfRegime(
                regime=etiq, n_trades=n, pnl_net_total=sum(pnls),
                pnl_moyen=statistics.fmean(pnls) if pnls else 0.0,
                win_rate=0.0, win_rate_bas=0.0, win_rate_haut=1.0,
                max_drawdown=0.0, ecart_type=0.0, suffisant=False,
                raison=f"{n}/{min_trades} trades : aucune statistique emise"))
            continue
        gains = sum(1 for p in pnls if p > 0)
        est = wilson_proportion(gains, n, asof=asof, min_trials=min_trades)
        cum = pic = dd = 0.0
        for p in pnls:
            cum += p
            pic = max(pic, cum)
            dd = max(dd, pic - cum)
        sorties.append(PerfRegime(
            regime=etiq, n_trades=n, pnl_net_total=sum(pnls),
            pnl_moyen=statistics.fmean(pnls), win_rate=float(est.mean),
            win_rate_bas=float(est.lower), win_rate_haut=float(est.upper),
            max_drawdown=dd, ecart_type=statistics.stdev(pnls) if n > 1 else 0.0,
            suffisant=True))

    # Un ecart n'est retenu que si les intervalles de credibilite ne se CHEVAUCHENT
    # PAS. Comparer des points serait trouver une difference a tous les coups.
    exploitables = [p for p in sorties if p.suffisant]
    signif = False
    com = ""
    if len(exploitables) >= 2:
        hi = max(exploitables, key=lambda p: p.win_rate)
        lo = min(exploitables, key=lambda p: p.win_rate)
        if hi.win_rate_bas > lo.win_rate_haut:
            signif = True
            com = (f"win rate distinguable entre {hi.regime} "
                   f"[{hi.win_rate_bas:.2f}-{hi.win_rate_haut:.2f}] et {lo.regime} "
                   f"[{lo.win_rate_bas:.2f}-{lo.win_rate_haut:.2f}]")
        else:
            com = ("aucun ecart distinguable entre regimes : les intervalles de "
                   "credibilite se chevauchent")
    elif exploitables:
        com = (f"un seul regime exploitable ({exploitables[0].regime}) : "
               "aucune comparaison possible")
    else:
        com = "aucun regime n'atteint le minimum de trades"

    return AnalyseConditionnelle(
        address=address, par_regime=sorties, n_total=n_tot, n_sans_regime=sans,
        regimes_insuffisants=tuple(insuffisants), ecart_significatif=signif,
        commentaire=com)
