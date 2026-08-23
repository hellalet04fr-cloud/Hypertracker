"""
Protocole Elite : classement S+/S/A/B/C/D, declenche automatiquement des que des
trades clos sont disponibles.

Deux regles non negociables :

1. AUCUN CLASSEMENT DEFINITIF SOUS LE SEUIL. Un palier attribue sur 40 trades et
   3 wallets ne vaut rien : il decrit le bruit d'echantillonnage, pas un edge. Sous
   les seuils, `classer` leve InsufficientData en indiquant exactement ce qui manque.
   Un classement provisoire est disponible via `provisoire=True`, mais chaque entree
   porte alors `definitif=False` et le palier est prefixe "?" — impossible a confondre.

2. LE PALIER N'EST PAS UNE FONCTION DU SEUL SCORE. Il combine le score multi-critere
   du ranking ET la credibilite (rétrécissement bayesien fonction de la taille
   d'echantillon). Un score de 0,9 sur 32 trades ne peut pas atteindre S+ : le
   plafond de palier est borne par la credibilite. C'est ce qui empeche un wallet
   chanceux de decrocher le meme rang qu'un wallet demontre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from .schema import DERIVED, InsufficientData, require

# --------------------------------------------------------------------------- seuils
# Sous ces valeurs, aucun palier definitif n'est attribue.
MIN_TRADES_PAR_WALLET = 30          # aligne sur ranking.rank(min_trades=30)
MIN_WALLETS_COHORTE = 10            # en dessous, la mediane de cohorte est du bruit
MIN_TRADES_TOTAL = 500              # masse minimale pour que les paliers separent
MIN_MOIS_DISTINCTS = 3              # exige par la dimension persistance

PALIERS = ("S+", "S", "A", "B", "C", "D")

# Seuils de score par palier, du plus haut au plus bas.
SEUILS_SCORE = {"S+": 0.85, "S": 0.72, "A": 0.60, "B": 0.48, "C": 0.35, "D": 0.0}

# Palier maximal atteignable selon la credibilite (fonction croissante de n_trades).
# Un wallet peu documente ne peut pas monter, quel que soit son score.
PLAFOND_PAR_CREDIBILITE = ((0.85, "S+"), (0.70, "S"), (0.55, "A"), (0.40, "B"), (0.0, "C"))


@dataclass(frozen=True)
class EntreeElite:
    address: str
    palier: str
    definitif: bool
    score: float
    confiance: float
    n_trades: int
    # metriques exigees explicitement par le commanditaire
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    max_drawdown_usd: float | None
    roi: float | None
    persistance: float | None
    palier_plafonne: bool
    criteres_manquants: tuple[str, ...]

    @property
    def libelle(self) -> str:
        return self.palier if self.definitif else f"?{self.palier}"


@dataclass
class ClassementElite:
    asof: datetime
    entrees: list[EntreeElite] = field(default_factory=list)
    definitif: bool = False
    n_wallets_examines: int = 0
    n_trades_total: int = 0
    n_mois_distincts: int = 0
    raisons_non_definitif: tuple[str, ...] = ()
    taille_cohorte: int = 0

    def par_palier(self) -> dict[str, list[str]]:
        d: dict[str, list[str]] = {p: [] for p in PALIERS}
        for e in self.entrees:
            d[e.palier].append(e.address)
        return d

    def resume(self) -> str:
        etat = "DEFINITIF" if self.definitif else "PROVISOIRE"
        l = [f"Elite {etat} asof={self.asof.isoformat()} "
             f"({self.n_wallets_examines} wallets, {self.n_trades_total} trades, "
             f"{self.n_mois_distincts} mois)"]
        for r in self.raisons_non_definitif:
            l.append(f"  manque: {r}")
        for p in PALIERS:
            n = sum(1 for e in self.entrees if e.palier == p)
            if n:
                l.append(f"  {p:<2} : {n}")
        return "\n".join(l)


# --------------------------------------------------------------------------- interne
def _profit_factor(m: Mapping[str, Any]) -> float | None:
    """gains cumules / pertes cumulees. Non defini sans aucune perte : on rend None
    plutot qu'un infini deguise en performance."""
    n_g, n_p = m.get("n_gains"), m.get("n_pertes")
    g_moy, p_moy = m.get("gain_moyen"), m.get("perte_moyenne")
    if None in (n_g, n_p, g_moy, p_moy):
        return None
    pertes = abs(float(n_p) * float(p_moy))
    if pertes <= 0.0:
        return None
    return float(n_g) * float(g_moy) / pertes


def _plafond(credibilite: float) -> str:
    for seuil, palier in PLAFOND_PAR_CREDIBILITE:
        if credibilite >= seuil:
            return palier
    return "C"


def _palier_brut(score: float) -> str:
    for p in PALIERS:
        if score >= SEUILS_SCORE[p]:
            return p
    return "D"


def _min_palier(a: str, b: str) -> str:
    """Le plus bas des deux paliers (PALIERS est ordonne du meilleur au pire)."""
    return a if PALIERS.index(a) >= PALIERS.index(b) else b


def _diagnostic(n_wallets: int, n_trades: int, n_mois: int) -> tuple[str, ...]:
    r = []
    if n_wallets < MIN_WALLETS_COHORTE:
        r.append(f"{n_wallets}/{MIN_WALLETS_COHORTE} wallets classables")
    if n_trades < MIN_TRADES_TOTAL:
        r.append(f"{n_trades}/{MIN_TRADES_TOTAL} trades clos au total")
    if n_mois < MIN_MOIS_DISTINCTS:
        r.append(f"{n_mois}/{MIN_MOIS_DISTINCTS} mois distincts couverts")
    return tuple(r)


# --------------------------------------------------------------------------- API
def classer(asof: datetime,
            closed_trades: Iterable[Mapping[str, Any]],
            wallets: Iterable[Mapping[str, Any]] | None = None,
            *,
            provisoire: bool = False,
            min_trades: int = MIN_TRADES_PAR_WALLET,
            **kw_ranking) -> ClassementElite:
    """
    Calcule le classement Elite. Leve InsufficientData si les seuils ne sont pas
    atteints, sauf si `provisoire=True` — auquel cas chaque entree est marquee
    `definitif=False` et son palier prefixe "?".
    """
    from . import ranking as R

    trades = list(closed_trades)
    require(bool(trades), "aucun trade clos fourni : rien a classer")

    # Un seul trade DERIVED suffit a interdire le definitif. Les donnees reconstruites
    # portent, en plus des erreurs de la source, celles de notre machine a etats : tant
    # que la validation croisee contre des natifs n'a pas eu lieu, aucun palier ne peut
    # etre presente comme etabli.
    sources = {str(t.get("source")) for t in trades if t.get("source")}
    classifications = {str(t.get("classification")) for t in trades if t.get("classification")}
    derive = DERIVED in classifications or any(s and s != "hypertracker" for s in sources)

    res = R.rank(asof, trades, wallets, min_trades=min_trades, **kw_ranking)

    mois = {str(t.get("closeTime", ""))[:7] for t in trades if t.get("closeTime")}
    mois.discard("")
    n_mois = len(mois)
    n_wallets = len(res.classes)
    n_trades = res.n_trades_retenus

    raisons = list(_diagnostic(n_wallets, n_trades, n_mois))
    if derive:
        raisons.append(
            f"donnees DERIVED ({', '.join(sorted(sources)) or DERIVED}) : un classement "
            "definitif exige des closed_trades natifs, jamais des trades reconstruits"
        )
    raisons = tuple(raisons)
    definitif = not raisons
    if raisons and not provisoire:
        raise InsufficientData(
            "classement Elite refuse — donnees insuffisantes pour un palier definitif : "
            + " ; ".join(raisons)
            + ". Relancer avec provisoire=True pour un classement explicitement marque."
        )

    entrees = []
    for c in res.classes:
        m = c.metriques
        plafond = _plafond(float(c.credibilite))
        brut = _palier_brut(float(c.score))
        palier = _min_palier(brut, plafond)
        entrees.append(EntreeElite(
            address=c.address,
            palier=palier,
            definitif=definitif,
            score=float(c.score),
            confiance=float(c.credibilite),
            n_trades=int(c.n_trades),
            win_rate=m.get("win_rate"),
            profit_factor=_profit_factor(m),
            expectancy=m.get("esperance_R"),
            max_drawdown_usd=m.get("max_drawdown_usd"),
            roi=m.get("rendement_sur_capital_engage"),
            persistance=m.get("ratio_mois_gagnants"),
            palier_plafonne=palier != brut,
            criteres_manquants=tuple(c.criteres_manquants),
        ))
    entrees.sort(key=lambda e: (-e.score, -e.confiance, e.address))

    return ClassementElite(asof=asof, entrees=entrees, definitif=definitif,
                           n_wallets_examines=n_wallets, n_trades_total=n_trades,
                           n_mois_distincts=n_mois, raisons_non_definitif=raisons,
                           taille_cohorte=res.taille_cohorte)


def pret(closed_trades: Iterable[Mapping[str, Any]]) -> tuple[bool, tuple[str, ...]]:
    """Sonde bon marche : a-t-on assez de matiere pour un classement definitif ?
    Utilisable par le collecteur pour declencher le protocole automatiquement, sans
    payer le cout complet du ranking."""
    trades = list(closed_trades)
    if not trades:
        return False, ("aucun trade clos",)
    par_wallet: dict[str, int] = {}
    for t in trades:
        a = t.get("address")
        if a:
            par_wallet[a] = par_wallet.get(a, 0) + 1
    eligibles = sum(1 for n in par_wallet.values() if n >= MIN_TRADES_PAR_WALLET)
    mois = {str(t.get("closeTime", ""))[:7] for t in trades if t.get("closeTime")}
    mois.discard("")
    raisons = _diagnostic(eligibles, len(trades), len(mois))
    return (not raisons), raisons


def depuis_pipeline(rapport, **kw) -> ClassementElite:
    """
    Branchement automatique : consomme le rapport de ht.pipeline et rend le classement
    Elite. Si l'etage `ranking` n'est pas OK, on refuse en reprenant sa raison exacte —
    jamais un classement construit sur un etage degrade.
    """
    e = rapport.par_nom("ranking")
    if e is None or not e.ok:
        raise InsufficientData(
            f"classement Elite impossible : etage ranking="
            f"{e.statut if e else 'absent'}" + (f" — {e.detail}" if e else "")
        )
    if not rapport.closed_trades:
        raise InsufficientData(
            "l'etage ranking est OK mais le rapport ne transporte aucun trade brut : "
            "appeler pipeline.run(..., closed_trades=...) pour que le classement "
            "puisse etre recalcule"
        )
    return classer(rapport.asof, rapport.closed_trades,
                   rapport.wallets or None, **kw)
