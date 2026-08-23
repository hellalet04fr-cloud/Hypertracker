#!/usr/bin/env python3
"""
Wallet Intelligence — score decomposable.

Aucun score opaque : chaque composante est calculee separement, exposee avec sa valeur
brute, sa valeur normalisee, son poids et son statut. Un score sans sa decomposition
n'est pas exploitable pour repondre a « pourquoi ce wallet est-il classe ici ».

Deux principes qui gouvernent tout le module :

1. UNE COMPOSANTE NON CALCULABLE N'EST PAS ZERO. Elle est absente, et le score final
   est marque incomplet. Remplacer une donnee manquante par une valeur neutre ferait
   passer l'ignorance pour de la mediocrite — ou pire, pour de la qualite.

2. LA QUALITE DES DONNEES EST UNE COMPOSANTE DU SCORE, PAS UN FILTRE PREALABLE. Un
   wallet dont l'historique est tronque ou dont le rythme depasse ce que la source
   conserve voit son score baisser explicitement, avec la raison — plutot que d'etre
   ecarte en silence ou, pire, note comme les autres.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .schema import DERIVED, InsufficientData, require

# --------------------------------------------------------------------------- seuils
MIN_TRADES = 30                 # aligne sur ht.ranking et ht.elite
K_SHRINK = 40.0                 # pseudo-effectif du retrecissement, aligne sur le ranking
RYTHME_REFERENCE = 50.0         # aligne sur ht.reconstruct.ponderer
PROFONDEUR_REFERENCE = 365.0

# Poids par defaut. Ce sont des a priori NOMMES, jamais valides hors echantillon :
# aucune ponderation ne peut etre declaree optimale avant une validation OOS.
POIDS_DEFAUT = {
    "rendement_net": 0.22,
    "stabilite": 0.16,
    "drawdown": 0.16,
    "robustesse": 0.14,
    "echantillon_effectif": 0.12,
    "couverture": 0.10,
    "fraicheur": 0.06,
    "cout_funding": 0.04,
}


@dataclass(frozen=True)
class Composante:
    nom: str
    valeur: float | None            # valeur brute, unite naturelle
    score: float | None             # normalise dans [0,1]
    poids: float
    calculable: bool
    raison: str = ""
    unite: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoreWallet:
    address: str
    score: float | None
    complet: bool
    n_trades: int
    n_effectif: float
    composantes: list[Composante] = field(default_factory=list)
    manquantes: tuple[str, ...] = ()
    classification: str = DERIVED
    alertes: tuple[str, ...] = ()

    def par_nom(self, nom: str) -> Composante | None:
        return next((c for c in self.composantes if c.nom == nom), None)

    def contributions(self) -> list[tuple[str, float]]:
        """Contribution absolue de chaque composante au score final, triee.
        C'est la reponse directe a « pourquoi ce wallet est-il classe ici »."""
        out = [(c.nom, (c.score or 0.0) * c.poids)
               for c in self.composantes if c.calculable]
        return sorted(out, key=lambda x: -x[1])

    def as_dict(self) -> dict:
        d = asdict(self)
        d["composantes"] = [c.as_dict() for c in self.composantes]
        return d

    def resume(self) -> str:
        s = f"{self.address[:10]}...  score="
        s += "n/a" if self.score is None else f"{self.score:.4f}"
        s += f"  n={self.n_trades} n_eff={self.n_effectif:.1f}"
        s += "" if self.complet else "  [INCOMPLET]"
        lignes = [s]
        for c in self.composantes:
            if c.calculable:
                lignes.append(f"    {c.nom:<22} {c.valeur:>12.4f} {c.unite:<6} "
                              f"-> {c.score:.3f} x{c.poids:.2f} = {c.score*c.poids:.4f}")
            else:
                lignes.append(f"    {c.nom:<22} {'ABSENTE':>12}        — {c.raison}")
        for a in self.alertes:
            lignes.append(f"    ! {a}")
        return "\n".join(lignes)


# --------------------------------------------------------------------------- outils
def _borne(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _sature(x: float, echelle: float) -> float:
    """Normalisation saturante et monotone sur [0,1[. Pas de seuil arbitraire :
    `echelle` est la valeur qui donne 0,5, et la fonction est continue partout."""
    if echelle <= 0:
        return 0.0
    return abs(x) / (abs(x) + echelle) if x >= 0 else 0.0


def _pnl_net(t: Mapping[str, Any]) -> float | None:
    """PnL net si RECON_V2 l'a calcule, sinon le brut. Ne recalcule rien : ce module
    ne redefinit pas la convention, il consomme ce que la reconstruction a etabli."""
    v = t.get("realizedPnlNetUsd")
    if v is not None:
        return float(v)
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


# --------------------------------------------------------------------------- composantes
def _c(nom, valeur, score, poids, unite="", raison=""):
    ok = valeur is not None and score is not None
    return Composante(nom=nom, valeur=valeur, score=score, poids=poids,
                      calculable=ok, raison=raison if not ok else "", unite=unite)


def evaluer_wallet(address: str,
                   trades: Sequence[Mapping[str, Any]],
                   couverture: Mapping[str, Any] | None = None,
                   *,
                   asof: datetime | None = None,
                   poids: Mapping[str, float] | None = None,
                   min_trades: int = MIN_TRADES,
                   seed: int = 1,
                   n_tirages: int = 400,
                   n_essais_correction: int = 1) -> ScoreWallet:
    """
    Score decomposable d'un wallet.

    `trades` : trades clos de CE wallet, deja filtres par l'appelant (tronques exclus).
    `couverture` : ligne du rapport de couverture (ht.reconstruct.Couverture). Absente,
                   les composantes de qualite de donnees sont marquees non calculables —
                   jamais supposees bonnes.
    """
    require(bool(address), "adresse vide")
    P = dict(POIDS_DEFAUT)
    if poids:
        P.update(poids)
    asof = asof or datetime.now(timezone.utc)
    comps: list[Composante] = []
    alertes: list[str] = []

    pnls = [p for p in (_pnl_net(t) for t in trades) if p is not None]
    n = len(pnls)

    if n < min_trades:
        return ScoreWallet(address=address, score=None, complet=False, n_trades=n,
                           n_effectif=0.0, composantes=[],
                           manquantes=(f"echantillon {n}/{min_trades}",),
                           alertes=("echantillon insuffisant : aucun score emis",))

    # -- rendement net -------------------------------------------------------
    capital = [abs(float(t.get("totalUsd") or 0)) for t in trades]
    capital = [c for c in capital if c > 0]
    if capital:
        engage = statistics.median(capital)
        rendement = sum(pnls) / (engage * n)
        comps.append(_c("rendement_net", rendement, _sature(rendement, 0.01),
                        P["rendement_net"], "par trade"))
    else:
        # Sans notionnel, un rendement n'a pas de denominateur : on ne le fabrique pas.
        comps.append(_c("rendement_net", None, None, P["rendement_net"],
                        raison="aucun notionnel (totalUsd) disponible"))

    # -- stabilite : Sharpe par trade ---------------------------------------
    sd = statistics.stdev(pnls) if n > 1 else 0.0
    if sd > 0:
        sharpe = statistics.fmean(pnls) / sd
        comps.append(_c("stabilite", sharpe, _borne(0.5 + sharpe / 2.0),
                        P["stabilite"], "sharpe/trade"))
    else:
        comps.append(_c("stabilite", None, None, P["stabilite"],
                        raison="ecart-type nul : le Sharpe est indefini, pas infini"))

    # -- drawdown -----------------------------------------------------------
    cum, pic, dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        pic = max(pic, cum)
        dd = max(dd, pic - cum)
    total = sum(pnls)
    if dd > 0:
        ratio = total / dd
        comps.append(_c("drawdown", ratio, _borne(0.5 + ratio / 10.0),
                        P["drawdown"], "pnl/maxDD"))
    elif total > 0:
        # Aucun drawdown ET un gain : le ratio est infini. On plafonne EXPLICITEMENT
        # a 1 en le signalant, plutot que de laisser passer un infini deguise.
        comps.append(_c("drawdown", float("inf"), 1.0, P["drawdown"], "pnl/maxDD"))
        alertes.append("aucun drawdown observe : ratio plafonne, pas mesure")
    else:
        comps.append(_c("drawdown", None, None, P["drawdown"],
                        raison="ni drawdown ni gain : ratio indefini"))

    # -- robustesse Monte-Carlo ---------------------------------------------
    try:
        from . import montecarlo as MC
        perm = MC.test_permutation_signe(pnls, seed=seed, n_permutations=n_tirages)
        # 1 - p : plus la p-value est basse, plus la performance resiste au hasard
        comps.append(_c("robustesse", perm.p_value, _borne(1.0 - perm.p_value),
                        P["robustesse"], "1-p"))
        if n_essais_correction > 1:
            try:
                deg = MC.sharpe_degonfle(pnls, n_essais=n_essais_correction)
                if not deg.significatif:
                    alertes.append(
                        f"Sharpe non significatif apres correction pour "
                        f"{n_essais_correction} essais (seuil {deg.sharpe_seuil:.3f})")
            except InsufficientData:
                pass
    except InsufficientData as e:
        comps.append(_c("robustesse", None, None, P["robustesse"], raison=str(e)[:70]))

    # -- couverture et rythme (qualite des donnees) --------------------------
    n_eff = float(n)
    if couverture:
        taux_tr = float(couverture.get("taux_troncature") or 0.0)
        rythme = float(couverture.get("fills_par_jour") or 0.0)
        jours = float(couverture.get("jours_couverts") or 0.0)
        w_tr = max(0.0, 1.0 - taux_tr)
        w_ry = RYTHME_REFERENCE / (rythme + RYTHME_REFERENCE)
        w_pr = min(1.0, jours / PROFONDEUR_REFERENCE) if jours > 0 else 0.0
        q = w_tr * w_ry * w_pr
        n_eff = n * q
        comps.append(_c("couverture", q, _borne(q), P["couverture"], "produit"))
        if taux_tr > 0.2:
            alertes.append(f"troncature {taux_tr:.0%} : historique ampute")
        if rythme > 100:
            alertes.append(f"rythme {rythme:.0f} fills/j : la source ne conserve "
                           "qu'une fraction de l'historique")
    else:
        comps.append(_c("couverture", None, None, P["couverture"],
                        raison="rapport de couverture absent : qualite non evaluable"))

    # -- taille d'echantillon EFFECTIVE --------------------------------------
    comps.append(_c("echantillon_effectif", n_eff, n_eff / (n_eff + K_SHRINK),
                    P["echantillon_effectif"], "trades"))

    # -- fraicheur -----------------------------------------------------------
    fins = [_ms(t.get("closeTime")) for t in trades]
    fins = [x for x in fins if x]
    if fins:
        age_j = (asof.timestamp() * 1000 - max(fins)) / 86_400_000
        comps.append(_c("fraicheur", age_j, _borne(1.0 - age_j / 90.0),
                        P["fraicheur"], "jours"))
        if age_j > 60:
            alertes.append(f"dernier trade il y a {age_j:.0f} jours")
    else:
        comps.append(_c("fraicheur", None, None, P["fraicheur"],
                        raison="aucun horodatage de cloture exploitable"))

    # -- cout du funding -----------------------------------------------------
    fs = [float(t["fundingUsd"]) for t in trades
          if t.get("funding_couvert") and t.get("fundingUsd") is not None]
    if fs and abs(total) > 1e-9:
        part = sum(fs) / abs(total)
        comps.append(_c("cout_funding", part, _borne(0.5 + part * 5.0),
                        P["cout_funding"], "part du pnl"))
    else:
        comps.append(_c("cout_funding", None, None, P["cout_funding"],
                        raison="funding non mesure sur ces trades"))

    manquantes = tuple(c.nom for c in comps if not c.calculable)
    dispo = [c for c in comps if c.calculable]
    somme_poids = sum(c.poids for c in dispo)
    # Renormalisation sur les seules composantes disponibles, et le score est marque
    # INCOMPLET : comparer un score a 6 composantes a un score a 8 reste risque, et
    # l'appelant doit le savoir.
    score = (sum(c.score * c.poids for c in dispo) / somme_poids) if somme_poids > 0 else None
    return ScoreWallet(address=address, score=score, complet=not manquantes,
                       n_trades=n, n_effectif=round(n_eff, 1), composantes=comps,
                       manquantes=manquantes, alertes=tuple(alertes))


def evaluer_tous(trades_par_wallet: Mapping[str, Sequence[Mapping[str, Any]]],
                 couvertures: Mapping[str, Mapping[str, Any]] | None = None,
                 **kw) -> list[ScoreWallet]:
    """Evalue plusieurs wallets. `n_essais_correction` est renseigne automatiquement
    au nombre de wallets examines : c'est la correction pour tests multiples, et la
    sous-declarer reviendrait a se mentir."""
    cs = couvertures or {}
    kw.setdefault("n_essais_correction", max(1, len(trades_par_wallet)))
    out = []
    for a, ts in trades_par_wallet.items():
        try:
            out.append(evaluer_wallet(a, ts, cs.get(a), **kw))
        except InsufficientData:
            continue
    return sorted(out, key=lambda s: (s.score is None, -(s.score or 0.0)))
