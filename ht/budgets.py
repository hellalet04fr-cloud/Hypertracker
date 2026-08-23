#!/usr/bin/env python3
"""
Budgets centralises. Une tache est REFUSEE si son cout depasse ce qui est disponible,
ou si son cout depasse son rendement attendu.

Le projet a deja perdu une fenetre de quota entiere parce qu'un planificateur heritant
d'un ancien objectif a consomme 73 requetes sur 100 en trente-huit secondes. Un budget
qui se contente de compter apres coup ne sert a rien : celui-ci REFUSE avant.

Quatre ressources, chacune avec sa propre horloge :

  HYPERTRACKER  100 requetes par fenetre, reset 03:00 UTC mesure. Le seul signal fiable
                est le 429 : le compteur local a diverge trois fois (100, 98, 76).
  HYPERLIQUID   gratuit mais limite a ~30 requetes/minute cote serveur. Le cout se paie
                en temps, pas en argent.
  CPU           plafond par tache, pour qu'un balayage mal borne ne monopolise pas la
                machine.
  TOKENS        approximatif et declaratif : on ne peut pas le mesurer depuis ici, mais
                une tache qui s'annonce couteuse doit le dire pour etre arbitree.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

QUOTA_HT_PAR_FENETRE = 100
HL_PAR_MINUTE = 30
CPU_MAX_PAR_TACHE_S = 1800          # 30 min : au-dela, la tache est mal decoupee
ROI_MINIMAL = 1.0                   # rendement attendu / cout normalise


@dataclass(frozen=True)
class Cout:
    """Ce qu'une tache annonce consommer. Declaratif et verifiable a posteriori."""
    hypertracker: int = 0
    hyperliquid: int = 0
    cpu_s: float = 0.0
    tokens_k: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Etat:
    ht_restant: int
    ht_epuise: bool
    hl_par_minute: int
    cpu_max_s: float

    def as_dict(self) -> dict:
        return asdict(self)


def etat() -> Etat:
    """Disponibilite REELLE, pas theorique."""
    from . import quota as Q
    b = Q.bilan()
    epuise = b["epuise"]
    # tant qu'aucun 429 n'est tombe, on estime le reliquat par les succes constates ;
    # des qu'il tombe, le reliquat est zero, quoi que dise le compteur local.
    restant = 0 if epuise else max(0, QUOTA_HT_PAR_FENETRE - b["reussies"])
    return Etat(ht_restant=restant, ht_epuise=epuise,
                hl_par_minute=HL_PAR_MINUTE, cpu_max_s=CPU_MAX_PAR_TACHE_S)


def _normaliser(c: Cout) -> float:
    """Cout unique et comparable. La requete HyperTracker est la ressource RARE :
    100 par jour contre 43 200 requetes Hyperliquid, d'ou un poids sans commune mesure."""
    return (c.hypertracker * 1.0
            + c.hyperliquid * 0.002
            + c.cpu_s / CPU_MAX_PAR_TACHE_S * 0.5
            + c.tokens_k * 0.01)


def autorise(cout: Cout, roi: float, *, e: Etat | None = None) -> tuple[bool, str]:
    """
    Deux questions, dans cet ordre.

    1. La ressource est-elle DISPONIBLE ? Sinon la tache attend, elle n'echoue pas.
    2. Le rendement attendu justifie-t-il la depense ? Sinon on refuse, meme si on peut
       se le permettre — c'est la difference entre un budget et un solde.
    """
    e = e or etat()
    if cout.hypertracker > 0:
        if e.ht_epuise:
            return False, "quota HyperTracker refuse par le serveur dans cette fenetre"
        if cout.hypertracker > e.ht_restant:
            return False, (f"{cout.hypertracker} requetes HyperTracker demandees, "
                           f"{e.ht_restant} disponibles")
    if cout.cpu_s > e.cpu_max_s:
        return False, f"{cout.cpu_s:.0f}s de CPU demandes, plafond {e.cpu_max_s:.0f}s"
    n = _normaliser(cout)
    if n > 0 and roi / n < ROI_MINIMAL:
        return False, (f"rendement insuffisant : ROI {roi:.2f} pour un cout normalise "
                       f"{n:.2f} (minimum {ROI_MINIMAL})")
    return True, f"cout normalise {n:.2f}, ROI {roi:.2f}"
