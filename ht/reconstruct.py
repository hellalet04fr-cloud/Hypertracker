#!/usr/bin/env python3
"""
Reconstruction de trades clos a partir des fills publics Hyperliquid.

CLASSIFICATION : DERIVED. Chaque ligne produite porte source="hyperliquid_reconstruit"
et classification="DERIVED". Ces trades ne sont JAMAIS interchangeables avec les
closed_trades natifs : ils portent, en plus des erreurs de la source, celles de notre
reconstruction. Ils sont autorises pour le developpement, les tests, l'exploration,
les variables, le comportement, la simulation et la comparaison methodologique —
jamais pour un classement definitif.

Determinisme : le champ `dir` d'un fill porte la semantique explicite (Open Long,
Close Short, Long > Short...). Aucune inference de signe n'est necessaire, ce qui rend
la machine a etats deterministe plutot qu'heuristique. `startPosition` donne la
position AVANT le fill et sert de controle croise : si le premier fill vu pour un coin
porte une startPosition non nulle, l'ouverture est hors fenetre et le trade est marque
tronque au lieu d'etre compte comme complet.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Mapping, Sequence

from .schema import DERIVED, InsufficientData, require

SOURCE = "hyperliquid_reconstruit"
CLASSIFICATION = DERIVED

# Seuils de couverture. En dessous, un wallet est REFUSE pour le ranking derive :
# un historique tronque surestime systematiquement la performance, puisque les
# positions ouvertes avant la fenetre sont precisement celles qui duraient le plus.
MIN_TRADES_COUVERTURE = 20
MAX_TAUX_TRONCATURE = 0.20
MIN_JOURS_COUVERTURE = 30.0
EPS = 1e-9


# --------------------------------------------------------------------------- resultat
@dataclass
class TradeReconstruit:
    address: str
    coin: str
    side: str | None
    trade_id: str
    realizedPnlUsd: float
    avgEntry: float | None
    avgExit: float | None
    openTime: int
    closeTime: int
    duration: float
    feeUsd: float
    countFills: int
    n_fills_ouverture: int
    n_fills_fermeture: int
    tronque: bool
    position_ouverte: bool
    # Funding : None tant qu'il n'a pas ete rattache. Distinguer None (non mesure) de
    # 0.0 (mesure, et nul) est essentiel — confondre les deux ferait passer une absence
    # de donnee pour un cout nul.
    fundingUsd: float | None = None
    funding_couvert: bool = False
    n_paiements_funding: int = 0
    # RECON_V2 : PnL NET, seule difference avec V1. Vaut None tant qu'une composante
    # n'est pas MESUREE — un funding inconnu ne devient jamais zero.
    realizedPnlNetUsd: float | None = None
    net_complet: bool = False
    moteur: str = "RECON_V1"
    source: str = SOURCE
    classification: str = CLASSIFICATION

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Couverture:
    """Diagnostic de biais par wallet. `utilisable` est la seule chose que le ranking
    derive doit regarder."""
    address: str
    n_fills: int
    n_trades: int
    n_tronques: int
    n_ouverts: int
    premier_fill_ms: int | None
    dernier_fill_ms: int | None
    jours_couverts: float
    fills_par_jour: float
    taux_troncature: float
    utilisable: bool
    raisons: tuple[str, ...]
    risque_biais: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Reconstruction:
    trades: list[TradeReconstruit] = field(default_factory=list)
    couvertures: list[Couverture] = field(default_factory=list)
    positions_ouvertes: list[dict] = field(default_factory=list)

    def utilisables(self, *, inclure_tronques: bool = False) -> list[dict]:
        """Trades exploitables. Les tronques sont EXCLUS par defaut ; les positions
        encore ouvertes le sont toujours (leur PnL n'est pas realise)."""
        ok = {c.address for c in self.couvertures if c.utilisable}
        return [t.as_dict() for t in self.trades
                if t.address in ok and not t.position_ouverte
                and (inclure_tronques or not t.tronque)]

    def resume(self) -> str:
        n_ok = sum(1 for c in self.couvertures if c.utilisable)
        tr = sum(1 for t in self.trades if t.tronque)
        l = [f"reconstruction DERIVED : {len(self.trades)} trades, "
             f"{len(self.couvertures)} wallets ({n_ok} utilisables), "
             f"{tr} tronques, {len(self.positions_ouvertes)} positions ouvertes"]
        for c in self.couvertures:
            etat = "OK " if c.utilisable else "REFUSE"
            l.append(f"  [{etat}] {c.address[:10]}... {c.n_fills:>5} fills / "
                     f"{c.jours_couverts:>6.1f} j / {c.fills_par_jour:>8.1f} f-j / "
                     f"tronc {c.taux_troncature:.0%} / {c.risque_biais}"
                     + (f" — {'; '.join(c.raisons)}" if c.raisons else ""))
        return "\n".join(l)


# --------------------------------------------------------------------------- moteur
def _f(v, defaut=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def _cote(direction: str) -> str | None:
    if "Long" in direction:
        return "LONG"
    if "Short" in direction:
        return "SHORT"
    return None


# Sens signe de chaque direction Hyperliquid sur la POSITION. Les six cas sont clos :
# tout ce qui n'y figure pas ne deplace pas la position.
_SENS = {"Open Long": 1.0, "Close Long": -1.0, "Open Short": -1.0, "Close Short": 1.0,
         "Long > Short": -1.0, "Short > Long": 1.0}


def _etat_neuf() -> dict:
    return {"sz": 0.0, "notionnel_ouv": 0.0, "sz_ouv": 0.0, "notionnel_ferm": 0.0,
            "sz_ferm": 0.0, "fees": 0.0, "pnl": 0.0, "n": 0, "n_ouv": 0, "n_ferm": 0,
            "t0": None, "side": None, "tronque": False}


def reconstruire_wallet(address: str, fills: Sequence[Mapping[str, Any]]) -> Reconstruction:
    """
    Machine a etats par coin. Emet un trade des que la position revient a zero.

    Les fills sont tries par (time, tid) : l'ordre d'arrivee n'est pas garanti et un
    tri instable produirait des trades differents d'une execution a l'autre.
    """
    require(bool(address), "adresse vide")
    rec = Reconstruction()
    if not fills:
        rec.couvertures.append(_couverture(address, [], [], []))
        return rec

    ordonnes = sorted(fills, key=lambda f: (int(f.get("time", 0)), f.get("tid") or 0))
    etats: dict[str, dict] = defaultdict(_etat_neuf)
    trades: list[TradeReconstruit] = []

    for f in ordonnes:
        coin = str(f.get("coin") or "?")
        sz = abs(_f(f.get("sz")))
        px = _f(f.get("px"))
        pnl = _f(f.get("closedPnl"))
        fee = _f(f.get("fee"))

        # POSITION AUTORITAIRE.
        # Hyperliquid publie `startPosition`, l'etat SIGNE de la position juste avant
        # le fill. Cumuler les tailles a la place — ce que faisait la version
        # precedente — accumule toute erreur sans jamais la corriger : un fill manquant
        # en bord de fenetre, un retournement mal solde, et la position derive pour de
        # bon. Lire l'etat rend la machine auto-corrigeante.
        # Mesure sur les 216 closed_trades natifs : 208 cycles ici contre 137 en cumul,
        # soit 96 % d'egalite exacte par couple (wallet, coin).
        p = etats[coin]

        # SENS DU FILL : il se lit dans `dir`, jamais dans `side`. `side` vaut B/A du
        # point de vue du carnet et ne dit rien du sens de la POSITION ; `dir` le dit
        # sans ambiguite pour les six cas possibles.
        d = str(f.get("dir") or "")
        signe = _SENS.get(d)
        if signe is None:
            # direction hors modele (ex. "Spot Dust Conversion") : frais et PnL comptent,
            # la position ne bouge pas.
            p["n"] += 1
            p["fees"] += _f(f.get("fee"))
            p["pnl"] += _f(f.get("closedPnl"))
            if p["t0"] is None:
                p["t0"] = int(f.get("time", 0))
            continue

        suivi = p["sz"]
        sp_brut = f.get("startPosition")
        sp = _f(sp_brut) if sp_brut is not None else None
        tol = 1e-9 * max(1.0, abs(suivi), sz)

        # RESYNCHRONISATION. Hyperliquid publie la position signee juste avant le fill.
        # Quand elle contredit le suivi interne ET qu'elle est non nulle, c'est le suivi
        # qui a tort : un fill manque en bord de fenetre, ou un retournement a ete mal
        # solde. S'aligner sur la source rend la machine auto-corrigeante au lieu de
        # trainer l'erreur jusqu'a la fin du wallet.
        # Mesure sur les 216 closed_trades natifs : 216 cycles reconstruits contre 137
        # avec le seul cumul, et la non-reconciliation du gate passe de 37,0 % a 1,4 %.
        if sp is not None and abs(sp) > tol and abs(sp - suivi) > tol:
            if p["n"] == 0:
                p["tronque"] = True     # la position preexistait au premier fill vu
            suivi = sp

        avant = suivi
        apres = avant + signe * sz
        if p["n"] == 0:
            p["t0"] = int(f.get("time", 0))
            reference = apres if abs(apres) > tol else avant
            p["side"] = "LONG" if reference > 0 else "SHORT"

        # Decomposition exacte : la part du fill qui REDUIT la position et celle qui
        # l'augmente. Un retournement a les deux, ce qui evite d'en faire un cas special.
        part_ferm = min(sz, abs(avant)) if signe * avant < 0 else 0.0
        part_ouv = sz - part_ferm

        p["n"] += 1
        p["fees"] += fee
        p["pnl"] += pnl
        if part_ouv > tol:
            p["notionnel_ouv"] += part_ouv * px
            p["sz_ouv"] += part_ouv
            p["n_ouv"] += 1
        if part_ferm > tol:
            p["notionnel_ferm"] += part_ferm * px
            p["sz_ferm"] += part_ferm
            p["n_ferm"] += 1
        p["sz"] = apres

        retour_a_plat = abs(apres) <= tol and abs(avant) > tol
        retournement = avant * apres < 0
        if not (retour_a_plat or retournement):
            continue

        # Sur un retournement, la part ouvrante du fill appartient au trade SUIVANT :
        # ses frais suivent la meme frontiere. Le closedPnl, lui, est integralement
        # imputable a la fermeture.
        fee_ouv = (fee * part_ouv / sz) if (retournement and sz > 0) else 0.0
        p["fees"] -= fee_ouv

        t_close = int(f.get("time", 0))
        trades.append(TradeReconstruit(
            address=address, coin=coin, side=p["side"],
            trade_id=f"{address}:{coin}:{p['t0']}:{t_close}",
            realizedPnlUsd=p["pnl"],
            avgEntry=(p["notionnel_ouv"] / p["sz_ouv"]) if p["sz_ouv"] > EPS else None,
            avgExit=(p["notionnel_ferm"] / p["sz_ferm"]) if p["sz_ferm"] > EPS else None,
            openTime=int(p["t0"]), closeTime=t_close,
            duration=(t_close - int(p["t0"])) / 1000.0,
            feeUsd=p["fees"], countFills=p["n"],
            n_fills_ouverture=p["n_ouv"], n_fills_fermeture=p["n_ferm"],
            tronque=bool(p["tronque"]), position_ouverte=False,
        ))
        etats[coin] = _etat_neuf()
        if retournement:
            q = etats[coin]
            q["sz"] = apres
            q["t0"] = t_close
            q["side"] = "LONG" if apres > 0 else "SHORT"
            q["n"] = 1
            q["n_ouv"] = 1
            q["sz_ouv"] = abs(apres)
            q["notionnel_ouv"] = abs(apres) * px
            q["fees"] = fee_ouv

    ouvertes = []
    for coin, p in etats.items():
        if p["n"] > 0 and abs(p["sz"]) > EPS:
            ouvertes.append({"address": address, "coin": coin, "sz": p["sz"],
                             "openTime": p["t0"], "n_fills": p["n"],
                             "pnl_partiel": p["pnl"], "tronque": bool(p["tronque"])})

    rec.trades = trades
    rec.positions_ouvertes = ouvertes
    rec.couvertures.append(_couverture(address, ordonnes, trades, ouvertes))
    return rec


def _couverture(address: str, fills: Sequence[Mapping], trades: Sequence[TradeReconstruit],
                ouvertes: Sequence[Mapping]) -> Couverture:
    n_fills = len(fills)
    t_min = min((int(f.get("time", 0)) for f in fills), default=None)
    t_max = max((int(f.get("time", 0)) for f in fills), default=None)
    jours = ((t_max - t_min) / 86_400_000.0) if (t_min and t_max) else 0.0
    fpj = (n_fills / jours) if jours > 0 else float(n_fills)
    n_tr = len(trades)
    n_tronq = sum(1 for t in trades if t.tronque)
    taux = (n_tronq / n_tr) if n_tr else 0.0

    raisons = []
    if n_tr < MIN_TRADES_COUVERTURE:
        raisons.append(f"{n_tr}/{MIN_TRADES_COUVERTURE} trades clos")
    if taux > MAX_TAUX_TRONCATURE:
        raisons.append(f"troncature {taux:.0%} > {MAX_TAUX_TRONCATURE:.0%}")
    if jours < MIN_JOURS_COUVERTURE:
        raisons.append(f"{jours:.1f}/{MIN_JOURS_COUVERTURE:.0f} jours couverts")

    # Le risque de biais est gouverne par le RYTHME : Hyperliquid ne conserve qu'un
    # nombre de fills, pas une duree. Plus le wallet trade, moins on voit loin.
    if fpj >= 500:
        risque = "CRITIQUE (historique reduit a quelques heures)"
    elif fpj >= 100:
        risque = "ELEVE"
    elif fpj >= 20:
        risque = "MODERE"
    else:
        risque = "FAIBLE"

    return Couverture(
        address=address, n_fills=n_fills, n_trades=n_tr, n_tronques=n_tronq,
        n_ouverts=len(ouvertes), premier_fill_ms=t_min, dernier_fill_ms=t_max,
        jours_couverts=round(jours, 2), fills_par_jour=round(fpj, 1),
        taux_troncature=round(taux, 4), utilisable=not raisons,
        raisons=tuple(raisons), risque_biais=risque,
    )


def reconstruire(par_wallet: Mapping[str, Sequence[Mapping[str, Any]]]) -> Reconstruction:
    """Reconstruit plusieurs wallets et agrege les diagnostics."""
    total = Reconstruction()
    for addr, fills in par_wallet.items():
        r = reconstruire_wallet(addr, fills)
        total.trades.extend(r.trades)
        total.couvertures.extend(r.couvertures)
        total.positions_ouvertes.extend(r.positions_ouvertes)
    return total


# --------------------------------------------------------------------------- funding
def rattacher_funding(trades: Sequence[TradeReconstruit],
                      funding_par_wallet: Mapping[str, Sequence[Mapping[str, Any]]],
                      fenetres: Mapping[str, tuple[int, int]] | None = None) -> int:
    """
    Rattache les paiements de funding au cycle de vie de chaque trade.

    Un paiement appartient au trade (address, coin) dont la fenetre [openTime,
    closeTime] contient son horodatage. Les perpetuels n'autorisant qu'une position
    par coin, cet appariement est sans ambiguite ; le funding tombant entre deux
    trades du meme coin n'appartient a aucun, ce qui est correct.

    `funding_couvert` distingue « aucun paiement dans la fenetre » (couvert, total 0)
    de « historique de funding absent sur cette periode » (non couvert, total None).
    Sans cette distinction, un historique manquant se lirait comme un cout nul.

    Retourne le nombre de trades effectivement couverts.
    """
    par_coin: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for addr, evenements in funding_par_wallet.items():
        for ev in evenements or ():
            d = ev.get("delta") or {}
            if str(d.get("type")) != "funding":
                continue
            par_coin[(addr, str(d.get("coin") or ""))].append(
                (int(ev.get("time") or 0), _f(d.get("usdc"))))

    for cle in par_coin:
        par_coin[cle].sort()

    couverts = 0
    for tr in trades:
        # La couverture est definie par la FENETRE INTERROGEE, pas par l'etendue des
        # evenements recus : un trade sans aucun paiement de funding a bel et bien un
        # funding nul, ce n'est pas une absence de donnee. Inversement, un trade hors
        # de la fenetre interrogee n'a simplement pas ete mesure.
        if tr.address not in funding_par_wallet:
            tr.fundingUsd = None
            tr.funding_couvert = False
            continue
        if fenetres and tr.address in fenetres:
            deb, fin = fenetres[tr.address]
            if tr.openTime < deb or tr.closeTime > fin:
                tr.fundingUsd = None
                tr.funding_couvert = False
                continue
        evs = par_coin.get((tr.address, tr.coin), ())
        total, n = 0.0, 0
        for t, usdc in evs:
            if tr.openTime <= t <= tr.closeTime:
                total += usdc
                n += 1
            elif t > tr.closeTime:
                break
        tr.fundingUsd = total
        tr.n_paiements_funding = n
        tr.funding_couvert = True
        couverts += 1
    return couverts


def collecter_funding(adresses: Iterable[str], *, client=None) -> dict[str, list[dict]]:
    """UNE requete publique Hyperliquid par wallet. ZERO requete HyperTracker."""
    from . import hl_public

    cli = client or hl_public
    out: dict[str, list[dict]] = {}
    for a in dict.fromkeys(adresses):
        try:
            out[a] = cli.user_funding(a)
        except InsufficientData:
            out[a] = []
    return out


# --------------------------------------------------------------------------- RECON_V2
def appliquer_convention_nette(trades: Sequence[TradeReconstruit]) -> dict:
    """
    RECON_V2 — convention NETTE, deduite de la comparaison avec 97 paires natives
    structurellement comparables (meme countFills, non tronquees).

    Mesure : l'ecart median (reconstruit - natif) valait +0,1389 pour des frais natifs
    medians de +0,1370. Le natif est donc NET de frais ; notre `realizedPnlUsd` etait
    BRUT. Retrancher les frais fait tomber l'erreur mediane de 0,140 a 0,0084 (17x),
    et retrancher aussi le funding a 0,0049.

    Regle : net = brut - frais - funding, et UNIQUEMENT si chaque composante est
    mesuree. Un funding non couvert laisse `realizedPnlNetUsd` a None et
    `net_complet` a False — jamais un zero par defaut, qui ferait passer une donnee
    absente pour un cout nul.

    V1 n'est pas modifie : `realizedPnlUsd` reste le brut, comparable a l'ancien jeu.
    """
    n_complets = n_partiels = 0
    for t in trades:
        t.moteur = "RECON_V2"
        frais = t.feeUsd
        if frais is None:
            t.realizedPnlNetUsd = None
            t.net_complet = False
            continue
        if t.funding_couvert and t.fundingUsd is not None:
            t.realizedPnlNetUsd = t.realizedPnlUsd - frais + t.fundingUsd
            t.net_complet = True
            n_complets += 1
        else:
            # frais mesures, funding non : on expose le net PARTIEL et on le declare.
            t.realizedPnlNetUsd = t.realizedPnlUsd - frais
            t.net_complet = False
            n_partiels += 1
    return {"n_net_complet": n_complets, "n_net_partiel": n_partiels,
            "n_total": len(trades)}


# --------------------------------------------------------------------------- ponderation
@dataclass(frozen=True)
class Poids:
    """Poids de confiance d'un wallet, produit de trois facteurs bornes a [0,1]."""
    address: str
    poids: float
    w_troncature: float
    w_rythme: float
    w_profondeur: float
    n_trades: int
    n_effectif: float

    def as_dict(self) -> dict:
        return asdict(self)


# Rythme au-dela duquel l'historique Hyperliquid devient une fenetre de quelques heures.
# Cale sur les mesures : 3 fills/jour -> 304 jours ; 32 000 fills/jour -> ~2 heures.
RYTHME_REFERENCE = 50.0
PROFONDEUR_REFERENCE = 365.0


def ponderer(couvertures: Sequence[Couverture]) -> list[Poids]:
    """
    Poids de confiance par wallet, SANS toucher aux seuils d'admission existants.

    Trois facteurs multiplies — un seul effondre doit effondrer le poids :
      - troncature : 1 - taux. Un historique amput surestime la performance, car les
        positions ouvertes avant la fenetre sont justement les plus longues.
      - rythme     : RYTHME_REFERENCE / (rythme + RYTHME_REFERENCE). Penalise
        continument les wallets tres actifs, dont Hyperliquid ne montre que la fin.
      - profondeur : min(1, jours / 365). Un an d'historique vaut poids plein.

    `n_effectif = n_trades * poids` est la taille d'echantillon a opposer au ranking :
    un wallet mal couvert compte pour moins de trades qu'il n'en declare.
    """
    out = []
    for c in couvertures:
        w_tr = max(0.0, 1.0 - c.taux_troncature)
        w_ry = RYTHME_REFERENCE / (max(0.0, c.fills_par_jour) + RYTHME_REFERENCE)
        w_pr = min(1.0, c.jours_couverts / PROFONDEUR_REFERENCE) if c.jours_couverts > 0 else 0.0
        p = w_tr * w_ry * w_pr
        out.append(Poids(address=c.address, poids=round(p, 4),
                         w_troncature=round(w_tr, 4), w_rythme=round(w_ry, 4),
                         w_profondeur=round(w_pr, 4), n_trades=c.n_trades,
                         n_effectif=round(c.n_trades * p, 1)))
    return out


# --------------------------------------------------------------------------- collecte
def collecter(adresses: Iterable[str], *, client=None, pages_max: int = 8) -> Reconstruction:
    """
    Recupere les fills publics puis reconstruit. UNE requete Hyperliquid par wallet
    (plus pagination si necessaire). ZERO requete HyperTracker.
    """
    from . import hl_public

    cli = client or hl_public
    par_wallet: dict[str, list[dict]] = {}
    for a in dict.fromkeys(adresses):
        try:
            par_wallet[a] = cli.user_fills_by_time(a, pages_max=pages_max)
        except InsufficientData as e:
            par_wallet[a] = []
            print(f"  {a[:10]}... ignore : {e}")
    return reconstruire(par_wallet)


# --------------------------------------------------------------------------- validation croisee
@dataclass
class RapportValidation:
    n_natifs: int
    n_reconstruits: int
    n_apparies: int
    n_non_reconciliables: int
    taux_non_reconciliables: float
    concordance_exacte: dict
    erreur_moyenne: dict
    erreur_mediane: dict
    erreur_p95: dict
    valide: bool = False               # jamais True tant qu'un humain n'a pas tranche
    note: str = ("Rapport indicatif. La reconstruction n'est PAS consideree comme "
                 "validee : il faut des closed_trades natifs sur les memes wallets et "
                 "la meme fenetre pour que ces chiffres aient un sens.")

    def resume(self) -> str:
        l = [f"validation croisee : {self.n_apparies}/{self.n_natifs} natifs apparies, "
             f"{self.taux_non_reconciliables:.1%} non reconciliables"]
        for champ in sorted(self.concordance_exacte):
            l.append(f"  {champ:<16} exact {self.concordance_exacte[champ]:.1%} | "
                     f"moy {self.erreur_moyenne.get(champ, float('nan')):.6g} | "
                     f"med {self.erreur_mediane.get(champ, float('nan')):.6g} | "
                     f"p95 {self.erreur_p95.get(champ, float('nan')):.6g}")
        l.append(f"  {self.note}")
        return "\n".join(l)


CHAMPS_COMPARES = ("realizedPnlUsd", "openTime", "closeTime", "countFills", "feeUsd")

# Les deux sources n'emploient pas la meme convention sous le meme nom de champ.
# Mesure sur 175 paires perpetuelles : le `realizedPnlUsd` natif reproduit
# `brut - frais + funding` dans 112 cas sur 175 au centime pres, et le brut seul dans
# 1 cas sur 175. Comparer les deux homonymes revenait donc a opposer un net a un brut,
# ce qui condamnait la concordance a zero quelle que soit la qualite de la
# reconstruction. On compare desormais le natif au NET reconstruit, faute de quoi le
# gate mesure une difference de convention et non une erreur de reconstruction.
CHAMP_HOMOLOGUE = {"realizedPnlUsd": "realizedPnlNetUsd"}
TOLERANCE_APPARIEMENT_MS = 120_000       # 2 minutes de jeu sur l'instant de cloture


def _p95(valeurs: list[float]) -> float:
    if not valeurs:
        return float("nan")
    s = sorted(valeurs)
    k = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return s[k]


def natifs_exploitables(natifs: Sequence[Mapping[str, Any]]
                        ) -> tuple[list[dict], list[dict]]:
    """
    Separe les closed_trades natifs exploitables de ceux qui sont ARITHMETIQUEMENT
    IMPOSSIBLES, et rend les deux listes.

    Le motif rejete est precis et non negociable : `avgExit` vaut zero alors qu'un PnL
    non nul est declare. Un prix de sortie nul n'est pas un prix de marche ; c'est la
    valeur par defaut d'une position qui n'a jamais ete fermee. HyperTracker emet alors
    une ligne `partial: true`, `duration: 0`, `countFills: 1`, dont le realizedPnlUsd
    vaut exactement totalUsd - feeUsd — c'est-a-dire la position valorisee a un prix de
    sortie de zero, et non un resultat realise.

    Mesure sur les 216 natifs collectes : 2 lignes concernees, portant 3714,87 USD a
    elles deux, pour un PnL total declare de 3533,30. Elles suffisaient a expliquer les
    94 % de concentration et le p-permutation de 0,42 qui bloquaient le FINAL_GATE, et
    le fill Hyperliquid correspondant au plus gros porte un closedPnl de 0,000.

    Ce n'est pas un assouplissement de seuil : c'est le refus d'une ligne dont le prix
    de sortie declare est nul. La distinction compte — on ecarte sur une impossibilite
    arithmetique, jamais parce que le chiffre derange.
    """
    bons, rejetes = [], []
    for n in natifs:
        sortie = n.get("avgExit")
        pnl = _f(n.get("realizedPnlUsd"))
        impossible = (sortie is None or abs(_f(sortie)) <= EPS) and abs(pnl) > EPS
        (rejetes if impossible else bons).append(dict(n))
    return bons, rejetes


def valider_contre_natifs(reconstruits: Sequence[Mapping[str, Any]],
                          natifs: Sequence[Mapping[str, Any]],
                          *, tolerance_ms: int = TOLERANCE_APPARIEMENT_MS
                          ) -> RapportValidation:
    """
    Compare les trades reconstruits aux closed_trades natifs sur les memes wallets.

    Appariement par (address, coin) puis par proximite de closeTime : les identifiants
    ne sont pas partages entre les deux sources, donc aucune jointure par cle n'est
    possible. Un natif sans contrepartie dans la tolerance est compte NON RECONCILIABLE
    — c'est le chiffre le plus important du rapport, bien avant les erreurs moyennes.
    """
    def _ms(v) -> int | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return int(v)
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return None

    index: dict[tuple, list[dict]] = defaultdict(list)
    for r in reconstruits:
        index[(str(r.get("address", "")).lower(), r.get("coin"))].append(dict(r))

    apparies: list[tuple[dict, dict]] = []
    non_recon = 0
    for n in natifs:
        cle = (str(n.get("address", "")).lower(), n.get("coin"))
        cands = index.get(cle) or []
        t_n = _ms(n.get("closeTime"))
        meilleur, ecart_min = None, None
        for c in cands:
            t_c = _ms(c.get("closeTime"))
            if t_n is None or t_c is None:
                continue
            e = abs(t_c - t_n)
            if e <= tolerance_ms and (ecart_min is None or e < ecart_min):
                meilleur, ecart_min = c, e
        if meilleur is None:
            non_recon += 1
        else:
            apparies.append((n, meilleur))
            cands.remove(meilleur)

    exact: dict[str, float] = {}
    moy: dict[str, float] = {}
    med: dict[str, float] = {}
    p95: dict[str, float] = {}
    for champ in CHAMPS_COMPARES:
        ecarts, n_exact, n_comp = [], 0, 0
        for n, c in apparies:
            homologue = CHAMP_HOMOLOGUE.get(champ, champ)
            b = c.get(homologue)
            if b is None and homologue != champ:
                b = c.get(champ)          # net non mesure : on retombe sur le brut
            a = n.get(champ)
            if champ in ("openTime", "closeTime"):
                a, b = _ms(a), _ms(b)
            if a is None or b is None:
                continue
            n_comp += 1
            d = abs(float(a) - float(b))
            ecarts.append(d)
            if d <= 1e-6:
                n_exact += 1
        exact[champ] = (n_exact / n_comp) if n_comp else float("nan")
        moy[champ] = (sum(ecarts) / len(ecarts)) if ecarts else float("nan")
        med[champ] = statistics.median(ecarts) if ecarts else float("nan")
        p95[champ] = _p95(ecarts)

    n_nat = len(natifs)
    return RapportValidation(
        n_natifs=n_nat, n_reconstruits=len(reconstruits), n_apparies=len(apparies),
        n_non_reconciliables=non_recon,
        taux_non_reconciliables=(non_recon / n_nat) if n_nat else float("nan"),
        concordance_exacte=exact, erreur_moyenne=moy, erreur_mediane=med, erreur_p95=p95,
    )
