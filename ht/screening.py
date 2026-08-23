#!/usr/bin/env python3
"""
Campagne de criblage adaptative — Hyperliquid uniquement, 0 requete HyperTracker.

Deux etages, parce que le second coute quatre fois le premier :

  TRIAGE (1 requete)  `userFills` rend les 2000 fills les plus recents. Leur etendue
                      donne le taux quotidien, donc l'horizon estime par 10 000/taux.
                      Correlation de rang mesuree avec l'horizon reel : 0,748.
                      Ecarte 67 % des wallets pour le prix d'une requete.

  RECONSTRUCTION      Pagination complete puis machine a etats, ~4,1 requetes.
                      N'est payee que pour les survivants du triage — et pas du tout
                      si le triage a deja rendu moins de 2000 fills, auquel cas sa
                      charge utile EST l'historique complet.

Arret adaptatif : la campagne s'arrete des que la cible de candidats est atteinte.
La regle d'arret porte sur le NOMBRE de candidats, jamais sur leur performance :
elle ne peut donc pas biaiser lesquels sont retenus. Le nombre total examine est
conserve et doit etre passe comme `n_essais` au Sharpe degonfle — le sous-declarer
reviendrait a se mentir sur l'ampleur de la recherche.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Sequence

from .schema import DERIVED, InsufficientData

PLAFOND_FILLS = 2000
HORIZON_SERVEUR = 10_000            # fills conserves par wallet, mesure
SEUIL_HORIZON_TRIAGE = 120.0        # jours estimes en dessous desquels on ecarte
TAILLE_VAGUE = 40                   # optimum mesure du rapport P(succes)/cout

# Plancher de VOLUME — mesure, pas suppose. Un trade clos exige au moins deux fills
# (une ouverture, une fermeture), donc MIN_TRADES=30 en exige 60 au strict minimum, et
# davantage des qu'il y a des fermetures partielles. Sur la vague de validation, le
# seuil d'horizon laissait passer 39 wallets sur 40 : calibre sur des wallets actifs,
# il ne discrimine plus rien sur une population de carnet. Le volume, lui, discrimine :
# il garde 28/40 et evite 55 requetes de reconstruction par vague de 40.
MIN_FILLS_TRIAGE = 100

# Criteres de candidature — pre-enregistres, identiques a selection_preenregistree.json
MIN_TRADES = 30
MIN_JOURS = 130.0
MAX_CONCENTRATION = 0.40
MAX_TRONCATURE = 0.20


@dataclass
class Sonde:
    address: str
    n_fills: int
    taux_par_jour: float | None
    horizon_estime: float | None
    passe_triage: bool
    sous_plafond: bool
    raison: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidat:
    address: str
    n_trades: int
    jours: float
    concentration: float | None
    p_permutation: float | None
    pnl_net: float
    taux_troncature: float
    # p95 des durees de trade : c'est LUI qui fixe la largeur de purge du decoupage
    # hors echantillon, donc l'etendue OBSERVED a acheter, donc le cout HyperTracker.
    # Un wallet rapide coute plusieurs fois moins cher a certifier qu'un wallet lent.
    duree_p95_j: float | None = None
    classification: str = DERIVED

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Campagne:
    sondes: list[Sonde] = field(default_factory=list)
    candidats: list[Candidat] = field(default_factory=list)
    n_examines: int = 0
    n_triage_positifs: int = 0
    n_reconstruits: int = 0
    requetes_hl: int = 0
    economies_plafond: int = 0
    arretee: bool = False

    def resume(self) -> str:
        return (f"campagne : {self.n_examines} examines, "
                f"{self.n_triage_positifs} positifs au triage, "
                f"{self.n_reconstruits} reconstruits, "
                f"{len(self.candidats)} candidat(s) | "
                f"{self.requetes_hl} requetes Hyperliquid, "
                f"{self.economies_plafond} reconstruction(s) evitee(s)")


def univers_par_hash(adresses: Iterable[str], *, exclure: Iterable[str] = ()) -> list[str]:
    """Ordre deterministe par SHA256 : reproductible et independant de toute metrique
    de performance, passee comme future."""
    ex = {a.lower() for a in exclure}
    uniq = {a.lower() for a in adresses
            if isinstance(a, str) and len(a) == 42 and a.lower() not in ex}
    return sorted(uniq, key=lambda a: hashlib.sha256(a.encode()).hexdigest())


def trier(address: str, *, client=None) -> tuple[Sonde, list[dict]]:
    """Etage 1. Retourne la sonde ET la charge utile, pour ne pas la repayer."""
    from . import hl_public

    cli = client or hl_public
    try:
        fills = cli.user_fills(address)
    except InsufficientData as e:
        return Sonde(address, 0, None, None, False, False, str(e)[:60]), []
    if not fills:
        return Sonde(address, 0, None, None, False, True, "aucun fill"), []
    ts = [int(f["time"]) for f in fills]
    span = (max(ts) - min(ts)) / 86_400_000
    if span <= 0:
        return Sonde(address, len(fills), None, None, False, len(fills) < PLAFOND_FILLS,
                     "etendue nulle"), fills
    taux = len(fills) / span
    horizon = HORIZON_SERVEUR / taux if taux > 0 else 0.0
    sous = len(fills) < PLAFOND_FILLS

    # Trois refus, tous lus dans la MEME requete, donc gratuits.
    if len(fills) < MIN_FILLS_TRIAGE:
        return Sonde(address, len(fills), taux, horizon, False, sous,
                     f"volume insuffisant ({len(fills)} fills < {MIN_FILLS_TRIAGE})"), fills
    if sous and span < MIN_JOURS:
        # Sous le plafond, la charge utile EST l'historique complet : cette etendue
        # n'est pas une estimation mais une mesure. Le rejet est donc exact, sans
        # faux negatif possible.
        return Sonde(address, len(fills), taux, horizon, False, sous,
                     f"historique complet trop court ({span:.0f} j < {MIN_JOURS:.0f})"), fills
    if horizon < SEUIL_HORIZON_TRIAGE:
        return Sonde(address, len(fills), taux, horizon, False, sous,
                     f"horizon estime {horizon:.0f} j < {SEUIL_HORIZON_TRIAGE:.0f}"), fills
    return Sonde(address, len(fills), taux, horizon, True, sous), fills


def _evaluer(address: str, fills: Sequence[dict]) -> Candidat | None:
    from . import montecarlo as MC
    from . import reconstruct as R

    rec = R.reconstruire_wallet(address, fills)
    R.appliquer_convention_nette(rec.trades)
    ok = [t for t in rec.trades if not t.tronque and not t.position_ouverte]
    cov = rec.couvertures[0]
    pnls = [t.realizedPnlNetUsd if t.realizedPnlNetUsd is not None else t.realizedPnlUsd
            for t in ok]
    if len(pnls) < MIN_TRADES or cov.jours_couverts < MIN_JOURS \
            or cov.taux_troncature > MAX_TRONCATURE:
        return None
    tot = sum(pnls)
    conc = (max(pnls) / tot) if tot > 0 else None
    if conc is None or conc > MAX_CONCENTRATION:
        return None
    try:
        p = MC.test_permutation_signe(pnls, seed=1, n_permutations=400).p_value
    except InsufficientData:
        p = None
    d = sorted((t.closeTime - t.openTime) / 86_400_000 for t in ok)
    return Candidat(address=address, n_trades=len(ok), jours=cov.jours_couverts,
                    concentration=round(conc, 4), p_permutation=p,
                    pnl_net=round(tot, 2), taux_troncature=cov.taux_troncature,
                    duree_p95_j=round(d[int(0.95 * (len(d) - 1))], 3))


def executer(adresses: Sequence[str], *, cible: int = 5,
             taille_vague: int = TAILLE_VAGUE, max_examines: int | None = None,
             client=None, journal: str | None = None,
             verbeux: bool = True) -> Campagne:
    """
    Campagne adaptative. S'arrete des que `cible` candidats sont trouves.

    `journal` : chemin ou l'etat est persiste apres chaque vague, pour qu'une
    interruption ne coute jamais plus d'une vague.
    """
    from . import hl_public

    cli = client or hl_public
    c = Campagne()
    plafond = max_examines or len(adresses)
    i = 0
    while i < min(plafond, len(adresses)) and len(c.candidats) < cible:
        vague = adresses[i:i + taille_vague]
        i += len(vague)
        for a in vague:
            sonde, fills = trier(a, client=cli)
            c.sondes.append(sonde)
            c.n_examines += 1
            c.requetes_hl += 1
            if not sonde.passe_triage:
                continue
            c.n_triage_positifs += 1
            if sonde.sous_plafond:
                # la charge du triage EST l'historique complet : rien de plus a payer
                c.economies_plafond += 1
                complet = fills
            else:
                try:
                    complet = cli.user_fills_by_time(a, start_ms=0, pages_max=5)
                    c.requetes_hl += 5
                except InsufficientData:
                    continue
            c.n_reconstruits += 1
            cand = _evaluer(a, complet)
            if cand:
                c.candidats.append(cand)
                if verbeux:
                    print(f"    CANDIDAT {a[:10]}.. n={cand.n_trades} "
                          f"{cand.jours:.0f}j conc={cand.concentration:.2f} "
                          f"p={cand.p_permutation}")
        if verbeux:
            print(f"  vague {i//max(1,taille_vague)}: {c.resume()}")
        if journal:
            with open(journal, "w") as f:
                json.dump({"sondes": [s.as_dict() for s in c.sondes],
                           "candidats": [x.as_dict() for x in c.candidats],
                           "n_examines": c.n_examines,
                           "requetes_hl": c.requetes_hl}, f, indent=1)
    c.arretee = len(c.candidats) >= cible
    return c
