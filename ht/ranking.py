#!/usr/bin/env python3
"""
A — Elite Wallet Ranking : classement multi-criteres des wallets.

Principe non negociable : le PnL seul n'est PAS un critere de selection. Un wallet
n'est classe que si SIX dimensions sont toutes calculables sur des donnees reelles :

  1. performance      : PnL NET (realizedPnlUsd + fundingUsd - feeUsd) rapporte au
                        capital reellement engage, jamais le PnL brut.
  2. persistance      : proportion de sous-periodes (mois) gagnantes ET longueur de la
                        plus longue serie de mois perdants.
  3. drawdown         : max drawdown de la courbe de PnL net cumule, et ratio PnL/maxDD.
  4. winrate_payoff   : win rate TOUJOURS accompagne du payoff ratio, agreges en
                        esperance par trade exprimee en R (unites de perte moyenne).
  5. echantillon      : nombre de trades clos. Sous le seuil, le wallet n'est PAS mal
                        classe : il n'est pas classe du tout (statut insufficient_sample).
  6. stabilite        : dispersion des rendements par trade (Sharpe par trade) penalisee
                        par la concentration du profit sur un seul coup.

Si une seule dimension obligatoire n'est pas calculable, AUCUN score n'est produit :
le wallet ressort en non_classes avec la liste precise des criteres manquants.
Aucune valeur par defaut n'est jamais substituee a une donnee absente.

Point-in-time : rank(asof=...) n'utilise que des lignes dont
knowable_at_for("closed_trades", closeTime) <= asof. Aucune colonne post_hoc
(CLOSED_TRADES.post_hoc = {"partial"}) n'est lue.

Biais connus, traites explicitement ici :
  - Filtre de survie : ce module ne consomme JAMAIS les cohortes de performance de
    /wallets (champ segments), recalculees toutes les 3-4 h sur le PnL all-time et donc
    retro-attribuees. Toute cohorte utilisee ici est reconstruite a l'instant asof a
    partir des seuls wallets presents dans closed_trades.
  - Les leaderboards n'ont aucun parametre as-of : ils ne sont pas une entree de rank().
  - Les executions TWAP sont attribuees a une pseudo-adresse de 64 hex, exclue de toute
    agregation par wallet (TWAP_PSEUDO_ADDRESS).
  - Une rupture structurelle est connue au 2026-09-02 sur les prix de liquidation : aucune
    variable de distance a la liquidation n'entre dans le score.
"""
from __future__ import annotations

import glob
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .schema import (
    CLOSED_TRADES,
    WALLETS,
    InsufficientData,
    knowable_at_for,
    require,
)

# --------------------------------------------------------------------------- exclusions

# Les executions TWAP sont attribuees a cette pseudo-adresse (64 hex, pas une adresse
# EVM valide). Elle agrege des flux de multiples wallets : l'inclure fabriquerait un
# "super wallet" inexistant.
TWAP_PSEUDO_ADDRESS = "0x" + "0" * 64

# --------------------------------------------------------------------------- seuils

# En dessous, le wallet n'est PAS classe (statut insufficient_sample). Ce n'est pas une
# penalite : c'est un refus de conclure.
MIN_TRADES_FOR_RANKING = 30

# Nombre minimal de mois distincts pour que la persistance ait un sens.
MIN_PERIODS_FOR_PERSISTENCE = 3

# Part maximale de trades inexploitables (notionnel non derivable) toleree avant de
# declarer les dimensions dependantes du rendement non calculables.
MAX_UNUSABLE_TRADE_SHARE = 0.20

# Variation de prix relative en dessous de laquelle le notionnel implicite
# (|pnl| / |variation|) explose : le trade est declare inexploitable.
MIN_ABS_PRICE_RETURN = 1e-6

# --------------------------------------------------------------------------- shrinkage

# Force du retrecissement bayesien, exprimee en "pseudo-trades" de cohorte.
# Voir shrink() pour la formule.
SHRINKAGE_PSEUDO_TRADES = 40.0

# Nombre minimal de wallets eligibles pour que la mediane de cohorte soit un ancrage
# credible. En dessous, le shrinkage est toujours applique mais signale comme fragile.
MIN_COHORT_FOR_STABLE_SHRINKAGE = 5

# --------------------------------------------------------------------------- echelles

# Chaque dimension est ramenee dans [0, 1] par une transformation monotone bornee dont
# l'echelle est nommee ici. Aucun nombre magique dans les expressions.
PERF_RETURN_SCALE = 0.20            # rendement net sur capital engage donnant ~0.75
DD_RATIO_SCALE = 3.0                # ratio PnL/maxDD donnant 0.50
EXPECTANCY_R_SCALE = 0.50           # esperance par trade en R donnant ~0.75
SHARPE_PER_TRADE_SCALE = 0.25       # Sharpe par trade donnant ~0.75
SAMPLE_HALF_TRADES = 60.0           # nombre de trades donnant 0.50 sur la dimension taille
STREAK_TOLERANCE_PERIODS = 2.0      # longueur de serie perdante donnant 0.50

# Bornes explicites pour les cas degeneres. Ce ne sont PAS des substituts a une donnee
# manquante : ce sont des plafonds sur des quantites reellement infinies.
MAX_PNL_TO_DD_RATIO = 20.0          # applique quand maxDD == 0 et PnL net > 0
MAX_SHARPE_PER_TRADE = 5.0          # applique quand l'ecart-type des rendements est nul

# Ponderation interne de la persistance.
PERSISTENCE_WIN_RATIO_WEIGHT = 0.60
PERSISTENCE_STREAK_WEIGHT = 0.40

# Penalite de concentration appliquee a la stabilite : part du profit brut portee par le
# meilleur trade unique.
CONCENTRATION_PENALTY_WEIGHT = 0.50

# --------------------------------------------------------------------------- poids

DIMENSIONS: tuple[str, ...] = (
    "performance",
    "persistance",
    "drawdown",
    "winrate_payoff",
    "echantillon",
    "stabilite",
)

# Poids d'agregation. Modifiables : ce sont des constantes nommees, pas des litteraux
# noyes dans une formule. La somme doit valoir 1.0 (verifie par check_weights()).
DEFAULT_WEIGHTS: dict[str, float] = {
    "performance": 0.25,
    "persistance": 0.20,
    "drawdown": 0.20,
    "winrate_payoff": 0.10,
    "echantillon": 0.10,
    "stabilite": 0.15,
}

# Toutes obligatoires : aucun score n'est produit si l'une manque.
MANDATORY_DIMENSIONS: tuple[str, ...] = DIMENSIONS

# Colonnes de closed_trades strictement necessaires. 'partial' (post_hoc) en est absent
# et le restera : voir _forbid_post_hoc().
REQUIRED_TRADE_COLUMNS: tuple[str, ...] = (
    "address", "hash", "realizedPnlUsd", "avgEntry", "avgExit", "closeTime",
    "feeUsd", "fundingUsd",
)

# Statuts possibles d'un wallet en sortie de rank().
STATUS_RANKED = "ranked"
STATUS_INSUFFICIENT_SAMPLE = "insufficient_sample"
STATUS_MISSING_DIMENSION = "missing_dimension"
STATUS_EXCLUDED_TWAP = "excluded_twap"

BIAIS_DOCUMENTES: tuple[str, ...] = (
    "survie: les wallets ruines qui cessent de trader disparaissent des captures /wallets ; "
    "ce classement ne corrige pas ce biais, il refuse seulement de s'appuyer sur les cohortes amont.",
    "cohortes retro-attribuees: /wallets.segments est recalcule toutes les 3-4h sur le PnL "
    "all-time et n'est jamais lu ici.",
    "leaderboards: aucun parametre as-of, selection mecanique des survivants, exclus des entrees.",
    "liquidation: rupture structurelle au 2026-09-02 sur les prix de liquidation, aucune "
    "variable de distance a la liquidation dans le score.",
    "TWAP: pseudo-adresse 64 hex exclue de toute agregation par wallet.",
)


def check_weights(weights: Mapping[str, float]) -> None:
    """Refuse un jeu de poids incomplet, negatif ou de somme differente de 1."""
    manquants = [d for d in DIMENSIONS if d not in weights]
    require(not manquants, f"poids manquants pour les dimensions {manquants}")
    inconnus = [d for d in weights if d not in DIMENSIONS]
    require(not inconnus, f"poids inconnus: {inconnus}")
    require(all(weights[d] >= 0.0 for d in DIMENSIONS), "poids negatif interdit")
    total = sum(weights[d] for d in DIMENSIONS)
    require(abs(total - 1.0) < 1e-9, f"la somme des poids vaut {total}, elle doit valoir 1.0")


def _forbid_post_hoc(champs_utilises: Iterable[str], source=CLOSED_TRADES) -> None:
    """Garde-fou : interdit qu'une colonne post_hoc alimente une variable point-in-time."""
    fautifs = sorted(set(champs_utilises) & set(source.post_hoc))
    require(not fautifs, f"colonnes post_hoc interdites dans une variable point-in-time: {fautifs}")


_forbid_post_hoc(REQUIRED_TRADE_COLUMNS)


# --------------------------------------------------------------------------- utilitaires

def _to_utc(v: Any, champ: str, ctx: str) -> datetime:
    """Convertit un horodatage (datetime, epoch s/ms, ISO 8601) en datetime UTC.

    Leve InsufficientData si la valeur est absente ou inintelligible : un horodatage
    devine serait une fuite de futur potentielle.
    """
    require(v is not None, f"{ctx}: horodatage '{champ}' absent")
    if isinstance(v, datetime):
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
    if isinstance(v, bool):
        raise InsufficientData(f"{ctx}: horodatage '{champ}' booleen, inintelligible")
    if isinstance(v, (int, float)):
        x = float(v)
        require(math.isfinite(x), f"{ctx}: horodatage '{champ}' non fini")
        # Au-dela de 1e11 la valeur ne peut etre que des millisecondes (1e11 s = an 5138).
        secondes = x / 1000.0 if abs(x) >= 1e11 else x
        return datetime.fromtimestamp(secondes, tz=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        require(bool(s), f"{ctx}: horodatage '{champ}' vide")
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as e:
            raise InsufficientData(f"{ctx}: horodatage '{champ}' illisible ({s!r})") from e
        return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)
    raise InsufficientData(f"{ctx}: horodatage '{champ}' de type {type(v).__name__} non supporte")


def _num(row: Mapping[str, Any], champ: str, ctx: str) -> float:
    """Lit un champ numerique obligatoire. Aucune valeur par defaut, aucun NaN tolere."""
    require(champ in row, f"{ctx}: colonne '{champ}' absente")
    v = row[champ]
    require(v is not None, f"{ctx}: colonne '{champ}' nulle")
    if isinstance(v, bool):
        raise InsufficientData(f"{ctx}: colonne '{champ}' booleenne au lieu de numerique")
    try:
        x = float(v)
    except (TypeError, ValueError) as e:
        raise InsufficientData(f"{ctx}: colonne '{champ}' non numerique ({v!r})") from e
    require(math.isfinite(x), f"{ctx}: colonne '{champ}' non finie ({v!r})")
    return x


def _map_signed(x: float, echelle: float) -> float:
    """Applique x -> 0.5 * (1 + x / (|x| + echelle)). Monotone, bornee dans ]0, 1[, 0 -> 0.5."""
    return 0.5 * (1.0 + x / (abs(x) + echelle))


def _map_positive(x: float, echelle: float) -> float:
    """Applique x -> x / (x + echelle) pour x > 0, 0 sinon. Monotone, bornee dans [0, 1[."""
    if x <= 0.0:
        return 0.0
    return x / (x + echelle)


def shrink(valeur_brute: float, n: float, ancre_cohorte: float,
           pseudo_trades: float = SHRINKAGE_PSEUDO_TRADES) -> float:
    """Retrecissement bayesien vers l'ancrage de cohorte.

    Formule (credibilite lineaire, forme Buhlmann) :

        w        = n / (n + K)
        shrunk   = w * valeur_brute + (1 - w) * ancre_cohorte
                 = (n * valeur_brute + K * ancre_cohorte) / (n + K)

    n = nombre de trades clos du wallet, K = SHRINKAGE_PSEUDO_TRADES : le nombre de
    trades fictifs de cohorte que l'on ajoute a chaque wallet. Interpretation : avec
    K = 40, un wallet de 8 trades ne pese que 8/48 = 17 % de sa propre statistique et
    83 % de la mediane de cohorte, tandis qu'un wallet de 400 trades pese 91 % de la
    sienne. Un coup de chance sur un petit echantillon ne peut donc pas depasser un
    historique long et solide.

    L'ancrage est la MEDIANE de cohorte (robuste aux extremes), et la cohorte est
    reconstruite a l'instant asof a partir des seuls wallets eligibles - jamais lue dans
    /wallets.segments, qui est retro-attribue.
    """
    require(n >= 0.0, "shrink: n negatif")
    require(pseudo_trades > 0.0, "shrink: pseudo_trades doit etre > 0")
    w = n / (n + pseudo_trades)
    return w * valeur_brute + (1.0 - w) * ancre_cohorte


def _median(xs: Sequence[float]) -> float:
    require(len(xs) > 0, "mediane sur une sequence vide")
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else 0.5 * (s[m - 1] + s[m])


# --------------------------------------------------------------------------- structures

@dataclass(frozen=True)
class Trade:
    """Un trade clos, deja filtre point-in-time et normalise."""
    address: str
    hash: str
    close_time: datetime
    knowable_at: datetime
    pnl_realise: float          # realizedPnlUsd, tel que servi
    fee_usd: float
    funding_usd: float
    pnl_net: float              # realizedPnlUsd + fundingUsd - feeUsd
    prix_entree: float
    prix_sortie: float
    rendement_prix: float       # (sortie - entree) / entree, non signe par la direction
    notionnel: float | None     # |pnl_realise| / |rendement_prix|, None si non derivable
    rendement_net: float | None  # pnl_net / notionnel, None si notionnel non derivable


@dataclass
class WalletRanking:
    address: str
    statut: str
    n_trades: int
    score: float | None = None
    scores_dimensions: dict[str, float] = field(default_factory=dict)   # apres shrinkage
    scores_bruts: dict[str, float] = field(default_factory=dict)        # avant shrinkage
    criteres_calcules: list[str] = field(default_factory=list)
    criteres_manquants: list[str] = field(default_factory=list)
    metriques: dict[str, Any] = field(default_factory=dict)
    credibilite: float | None = None
    detail: str = ""


@dataclass
class RankingResult:
    asof: datetime
    classes: list[WalletRanking]
    non_classes: list[WalletRanking]
    cohorte: dict[str, float]
    taille_cohorte: int
    poids: dict[str, float]
    biais: tuple[str, ...]
    n_trades_retenus: int
    n_trades_ecartes_futur: int
    n_trades_twap: int
    shrinkage_fragile: bool

    def top(self, k: int) -> list[WalletRanking]:
        return self.classes[:k]

    def par_adresse(self, address: str) -> WalletRanking:
        for w in self.classes + self.non_classes:
            if w.address == address:
                return w
        raise InsufficientData(f"adresse absente du classement: {address}")


# --------------------------------------------------------------------------- preparation

def prepare_trades(rows: Iterable[Mapping[str, Any]], asof: datetime,
                   publication_lag_s: float | None = None
                   ) -> tuple[dict[str, list[Trade]], dict[str, int]]:
    """Filtre point-in-time et normalise les trades clos.

    Ne conserve QUE les lignes dont knowable_at_for('closed_trades', closeTime) <= asof.
    Exclut la pseudo-adresse TWAP. Leve InsufficientData si une colonne obligatoire
    manque : mieux vaut refuser de calculer que de completer un trou.
    """
    require(asof.tzinfo is not None, "asof doit etre timezone-aware (UTC)")
    par_wallet: dict[str, list[Trade]] = {}
    compte = {"lus": 0, "retenus": 0, "futur": 0, "twap": 0}

    for i, row in enumerate(rows):
        compte["lus"] += 1
        ctx = f"closed_trades[{i}]"
        manquantes = [c for c in REQUIRED_TRADE_COLUMNS if c not in row]
        require(not manquantes, f"{ctx}: colonnes obligatoires absentes {manquantes} "
                                f"(schema closed_trades est DOCUMENTED, presence a verifier a l'execution)")

        address = row["address"]
        require(isinstance(address, str) and address.strip() != "", f"{ctx}: address vide")
        address = address.strip().lower()
        if address == TWAP_PSEUDO_ADDRESS:
            compte["twap"] += 1
            continue

        close_time = _to_utc(row["closeTime"], "closeTime", ctx)
        knowable = knowable_at_for(CLOSED_TRADES.name, close_time, publication_lag_s)
        if knowable > asof:
            compte["futur"] += 1
            continue

        pnl = _num(row, "realizedPnlUsd", ctx)
        fee = _num(row, "feeUsd", ctx)
        funding = _num(row, "fundingUsd", ctx)
        entree = _num(row, "avgEntry", ctx)
        sortie = _num(row, "avgExit", ctx)
        require(entree > 0.0, f"{ctx}: avgEntry doit etre > 0 (recu {entree})")

        r_prix = (sortie - entree) / entree
        # Le schema closed_trades ne porte AUCUNE taille de position. Le notionnel est
        # deduit du couple (pnl realise, variation de prix) : |pnl| = notionnel * |r_prix|.
        # Ce raisonnement n'a pas besoin de 'side' : le signe du pnl porte deja la
        # direction. Si l'un des deux est nul, le notionnel est indeterminable et le
        # trade est marque inexploitable plutot que complete par une valeur inventee.
        if abs(r_prix) < MIN_ABS_PRICE_RETURN or pnl == 0.0:
            notionnel = None
            rendement_net = None
        else:
            notionnel = abs(pnl) / abs(r_prix)
            rendement_net = (pnl + funding - fee) / notionnel

        h = row["hash"]
        require(h is not None and str(h) != "", f"{ctx}: hash vide")

        par_wallet.setdefault(address, []).append(Trade(
            address=address, hash=str(h), close_time=close_time, knowable_at=knowable,
            pnl_realise=pnl, fee_usd=fee, funding_usd=funding,
            pnl_net=pnl + funding - fee,
            prix_entree=entree, prix_sortie=sortie, rendement_prix=r_prix,
            notionnel=notionnel, rendement_net=rendement_net,
        ))
        compte["retenus"] += 1

    for trades in par_wallet.values():
        # Dedoublonnage sur la cle de CLOSED_TRADES (hash) et tri chronologique :
        # la courbe de PnL cumule et les series mensuelles en dependent.
        trades.sort(key=lambda t: (t.close_time, t.hash))
    return par_wallet, compte


def _dedoublonne(trades: list[Trade]) -> list[Trade]:
    vus: set[str] = set()
    out: list[Trade] = []
    for t in trades:
        if t.hash in vus:
            continue
        vus.add(t.hash)
        out.append(t)
    return out


# --------------------------------------------------------------------------- dimensions

def _periode_mensuelle(d: datetime) -> tuple[int, int]:
    return (d.year, d.month)


def compute_metrics(trades: Sequence[Trade]) -> tuple[dict[str, Any], dict[str, str]]:
    """Calcule les metriques brutes d'un wallet.

    Retourne (metriques, manquants) ou 'manquants' associe chaque dimension non
    calculable au motif precis. Ne fabrique jamais de valeur de remplacement.
    """
    metriques: dict[str, Any] = {}
    manquants: dict[str, str] = {}
    n = len(trades)
    metriques["n_trades"] = n

    nets = [t.pnl_net for t in trades]
    pnl_net_total = math.fsum(nets)
    metriques["pnl_net_total"] = pnl_net_total
    metriques["pnl_brut_total"] = math.fsum(t.pnl_realise for t in trades)
    metriques["frais_total"] = math.fsum(t.fee_usd for t in trades)
    metriques["funding_total"] = math.fsum(t.funding_usd for t in trades)

    exploitables = [t for t in trades if t.rendement_net is not None and t.notionnel is not None]
    part_inexploitable = 1.0 - (len(exploitables) / n) if n else 1.0
    metriques["part_trades_inexploitables"] = part_inexploitable

    # ---- 1. performance : rendement net sur capital engage
    if part_inexploitable > MAX_UNUSABLE_TRADE_SHARE:
        motif = (f"{part_inexploitable:.0%} des trades sans notionnel derivable "
                 f"(pnl nul ou variation de prix < {MIN_ABS_PRICE_RETURN}), "
                 f"seuil {MAX_UNUSABLE_TRADE_SHARE:.0%}")
        manquants["performance"] = motif
        manquants["stabilite"] = motif
    else:
        capital_engage = math.fsum(t.notionnel for t in exploitables)  # type: ignore[arg-type]
        if capital_engage <= 0.0:
            motif = "capital engage cumule nul, rendement non calculable"
            manquants["performance"] = motif
            manquants["stabilite"] = motif
        else:
            net_exploitable = math.fsum(t.pnl_net for t in exploitables)
            metriques["capital_engage"] = capital_engage
            metriques["notionnel_median"] = _median([t.notionnel for t in exploitables])  # type: ignore[misc]
            metriques["rendement_sur_capital_engage"] = net_exploitable / capital_engage

    # ---- 2. persistance : mois gagnants et plus longue serie perdante
    par_periode: dict[tuple[int, int], float] = {}
    for t in trades:
        cle = _periode_mensuelle(t.close_time)
        par_periode[cle] = par_periode.get(cle, 0.0) + t.pnl_net
    periodes = sorted(par_periode)
    metriques["n_periodes"] = len(periodes)
    if len(periodes) < MIN_PERIODS_FOR_PERSISTENCE:
        manquants["persistance"] = (f"{len(periodes)} mois distincts couverts, "
                                    f"minimum {MIN_PERIODS_FOR_PERSISTENCE}")
    else:
        gagnants = sum(1 for p in periodes if par_periode[p] > 0.0)
        serie, pire_serie = 0, 0
        for p in periodes:
            if par_periode[p] <= 0.0:
                serie += 1
                pire_serie = max(pire_serie, serie)
            else:
                serie = 0
        metriques["ratio_mois_gagnants"] = gagnants / len(periodes)
        metriques["plus_longue_serie_perdante"] = pire_serie
        metriques["pnl_par_mois"] = {f"{y:04d}-{m:02d}": v for (y, m), v in sorted(par_periode.items())}

    # ---- 3. drawdown sur la courbe de PnL net cumule
    cumul, sommet, maxdd = 0.0, 0.0, 0.0
    for x in nets:
        cumul += x
        sommet = max(sommet, cumul)
        maxdd = max(maxdd, sommet - cumul)
    metriques["max_drawdown_usd"] = maxdd
    if maxdd > 0.0:
        metriques["ratio_pnl_maxdd"] = pnl_net_total / maxdd
    elif pnl_net_total > 0.0:
        # Aucun repli enregistre : le ratio est infini, on le plafonne explicitement.
        metriques["ratio_pnl_maxdd"] = MAX_PNL_TO_DD_RATIO
        metriques["ratio_pnl_maxdd_plafonne"] = True
    else:
        manquants["drawdown"] = "aucun drawdown et aucun profit : courbe de PnL degeneree"

    # ---- 4. win rate + payoff ratio
    gains = [x for x in nets if x > 0.0]
    pertes = [x for x in nets if x < 0.0]
    metriques["n_gains"] = len(gains)
    metriques["n_pertes"] = len(pertes)
    if not gains and not pertes:
        manquants["winrate_payoff"] = "tous les trades ont un PnL net exactement nul"
    else:
        win_rate = len(gains) / n
        metriques["win_rate"] = win_rate
        gain_moyen = (math.fsum(gains) / len(gains)) if gains else 0.0
        perte_moyenne = (abs(math.fsum(pertes)) / len(pertes)) if pertes else 0.0
        metriques["gain_moyen"] = gain_moyen
        metriques["perte_moyenne"] = perte_moyenne
        if pertes:
            payoff = gain_moyen / perte_moyenne
        else:
            # Aucune perte : payoff infini, plafonne. Le win rate vaut alors 1 et la
            # dimension echantillon reste le garde-fou contre les series courtes.
            payoff = MAX_PNL_TO_DD_RATIO
            metriques["payoff_plafonne"] = True
        metriques["payoff_ratio"] = payoff
        # Esperance par trade exprimee en R (unites de perte moyenne) : le win rate seul
        # ne dit rien, c'est le couple (win rate, payoff) qui porte l'edge.
        metriques["esperance_R"] = win_rate * payoff - (1.0 - win_rate)

    # ---- 5. taille d'echantillon (toujours calculable)
    metriques["credibilite"] = n / (n + SHRINKAGE_PSEUDO_TRADES)

    # ---- 6. stabilite : Sharpe par trade + concentration du profit
    if "stabilite" not in manquants:
        rendements = [t.rendement_net for t in exploitables]  # type: ignore[misc]
        if len(rendements) < 2:
            manquants["stabilite"] = f"{len(rendements)} rendement(s) par trade exploitable(s), minimum 2"
        else:
            moyenne = math.fsum(rendements) / len(rendements)
            var = math.fsum((r - moyenne) ** 2 for r in rendements) / (len(rendements) - 1)
            ecart_type = math.sqrt(var)
            metriques["rendement_moyen_par_trade"] = moyenne
            metriques["ecart_type_rendement_par_trade"] = ecart_type
            if ecart_type > 0.0:
                metriques["sharpe_par_trade"] = moyenne / ecart_type
            else:
                # Rendements strictement identiques : ratio infini, plafonne avec le
                # signe de la moyenne.
                signe = 0.0 if moyenne == 0.0 else math.copysign(1.0, moyenne)
                metriques["sharpe_par_trade"] = signe * MAX_SHARPE_PER_TRADE
                metriques["sharpe_plafonne"] = True
            profits = [x for x in nets if x > 0.0]
            total_profit = math.fsum(profits)
            if total_profit > 0.0:
                metriques["part_meilleur_trade"] = max(profits) / total_profit
            else:
                # Aucun profit a concentrer : la penalite de concentration ne s'applique
                # pas (le Sharpe negatif suffit a sanctionner).
                metriques["part_meilleur_trade"] = 0.0
                metriques["concentration_non_applicable"] = True

    return metriques, manquants


def compute_dimension_scores(metriques: Mapping[str, Any]) -> dict[str, float]:
    """Traduit les metriques brutes en scores de dimension dans [0, 1].

    Chaque transformation est monotone et bornee, d'echelle nommee en constante.
    N'est appelee que si toutes les dimensions obligatoires sont calculables.
    """
    scores: dict[str, float] = {}

    scores["performance"] = _map_signed(
        float(metriques["rendement_sur_capital_engage"]), PERF_RETURN_SCALE)

    ratio_mois = float(metriques["ratio_mois_gagnants"])
    serie = float(metriques["plus_longue_serie_perdante"])
    score_serie = 1.0 / (1.0 + serie / STREAK_TOLERANCE_PERIODS)
    scores["persistance"] = (PERSISTENCE_WIN_RATIO_WEIGHT * ratio_mois
                             + PERSISTENCE_STREAK_WEIGHT * score_serie)

    scores["drawdown"] = _map_positive(float(metriques["ratio_pnl_maxdd"]), DD_RATIO_SCALE)

    scores["winrate_payoff"] = _map_signed(float(metriques["esperance_R"]), EXPECTANCY_R_SCALE)

    n = float(metriques["n_trades"])
    scores["echantillon"] = n / (n + SAMPLE_HALF_TRADES)

    base_stab = _map_signed(float(metriques["sharpe_par_trade"]), SHARPE_PER_TRADE_SCALE)
    penalite = 1.0 - CONCENTRATION_PENALTY_WEIGHT * float(metriques["part_meilleur_trade"])
    scores["stabilite"] = base_stab * penalite

    return scores


# --------------------------------------------------------------------------- classement

def rank(asof: datetime,
         closed_trades: Iterable[Mapping[str, Any]],
         wallets: Iterable[Mapping[str, Any]] | None = None,
         weights: Mapping[str, float] | None = None,
         min_trades: int = MIN_TRADES_FOR_RANKING,
         publication_lag_s: float | None = None,
         shrinkage_pseudo_trades: float = SHRINKAGE_PSEUDO_TRADES) -> RankingResult:
    """Classe les wallets a l'instant asof, sur six dimensions, avec shrinkage bayesien.

    asof           : instant de decision. Aucune ligne dont knowable_at > asof n'est lue.
    closed_trades  : iterable de mappings aux colonnes de schema.CLOSED_TRADES.
    wallets        : optionnel, captures /wallets. Seuls perpEquity et exposureRatio sont
                     lus, pour CONTEXTE d'exposition ; 'segments' est ignore (cohorte
                     retro-attribuee). N'influence jamais le score.
    weights        : poids d'agregation ; DEFAULT_WEIGHTS si None. Somme = 1 exigee.
    min_trades     : sous ce seuil, statut insufficient_sample (non classe, pas mal classe).

    Leve InsufficientData si aucune donnee exploitable n'existe a asof.
    """
    require(asof.tzinfo is not None, "asof doit etre timezone-aware (UTC)")
    poids = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
    check_weights(poids)
    require(min_trades >= 2, "min_trades doit valoir au moins 2")

    par_wallet, compte = prepare_trades(closed_trades, asof, publication_lag_s)
    require(compte["retenus"] > 0,
            f"aucun trade clos connaissable a {asof.isoformat()} "
            f"(lus={compte['lus']}, ecartes_futur={compte['futur']}, twap={compte['twap']}) : "
            f"closed_trades n'a pas encore ete collecte")

    exposition = _index_wallets(wallets, asof) if wallets is not None else {}

    # --- passe 1 : metriques et eligibilite
    candidats: list[tuple[str, dict[str, Any], dict[str, float]]] = []
    non_classes: list[WalletRanking] = []

    for address in sorted(par_wallet):
        trades = _dedoublonne(par_wallet[address])
        n = len(trades)
        if n < min_trades:
            non_classes.append(WalletRanking(
                address=address, statut=STATUS_INSUFFICIENT_SAMPLE, n_trades=n,
                criteres_manquants=["echantillon"],
                detail=f"{n} trades clos connaissables a asof, minimum {min_trades}",
                metriques={"n_trades": n},
            ))
            continue

        metriques, manquants = compute_metrics(trades)
        if exposition.get(address) is not None:
            metriques["exposition_wallet"] = exposition[address]
        absents = [d for d in MANDATORY_DIMENSIONS if d in manquants]
        if absents:
            non_classes.append(WalletRanking(
                address=address, statut=STATUS_MISSING_DIMENSION, n_trades=n,
                criteres_calcules=[d for d in DIMENSIONS if d not in manquants],
                criteres_manquants=absents,
                detail="; ".join(f"{d}: {manquants[d]}" for d in absents),
                metriques=metriques,
                credibilite=metriques.get("credibilite"),
            ))
            continue

        bruts = compute_dimension_scores(metriques)
        candidats.append((address, metriques, bruts))

    require(len(candidats) > 0,
            f"aucun wallet eligible a {asof.isoformat()} : "
            f"{len(non_classes)} wallet(s) ecarte(s) faute d'echantillon ou de dimension "
            f"calculable ; impossible de construire une cohorte de reference")

    # --- passe 2 : cohorte reconstruite a asof, puis shrinkage
    cohorte = {d: _median([b[d] for _, _, b in candidats]) for d in DIMENSIONS}
    fragile = len(candidats) < MIN_COHORT_FOR_STABLE_SHRINKAGE

    classes: list[WalletRanking] = []
    for address, metriques, bruts in candidats:
        n = float(metriques["n_trades"])
        shrunk: dict[str, float] = {}
        for d in DIMENSIONS:
            if d == "echantillon":
                # La dimension taille d'echantillon EST la credibilite : la retrecir vers
                # la cohorte reviendrait a effacer l'information qu'elle porte.
                shrunk[d] = bruts[d]
            else:
                shrunk[d] = shrink(bruts[d], n, cohorte[d], shrinkage_pseudo_trades)
        score = math.fsum(poids[d] * shrunk[d] for d in DIMENSIONS)
        classes.append(WalletRanking(
            address=address, statut=STATUS_RANKED, n_trades=int(n), score=score,
            scores_dimensions=shrunk, scores_bruts=bruts,
            criteres_calcules=list(DIMENSIONS), criteres_manquants=[],
            metriques=metriques, credibilite=n / (n + shrinkage_pseudo_trades),
        ))

    classes.sort(key=lambda w: (-(w.score or 0.0), -w.n_trades, w.address))

    return RankingResult(
        asof=asof, classes=classes, non_classes=non_classes,
        cohorte=cohorte, taille_cohorte=len(candidats), poids=poids,
        biais=BIAIS_DOCUMENTES,
        n_trades_retenus=compte["retenus"],
        n_trades_ecartes_futur=compte["futur"],
        n_trades_twap=compte["twap"],
        shrinkage_fragile=fragile,
    )


def _index_wallets(rows: Iterable[Mapping[str, Any]], asof: datetime) -> dict[str, dict[str, Any]]:
    """Derniere capture /wallets connaissable a asof, par adresse.

    Seuls perpEquity, perpEquity et exposureRatio sont conserves, a titre de CONTEXTE.
    'segments' est deliberement ignore : la cohorte amont est recalculee toutes les 3-4 h
    sur le PnL all-time, la relire a posteriori serait une appartenance retro-attribuee.
    """
    dernier: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for i, row in enumerate(rows):
        ctx = f"wallets[{i}]"
        require("address" in row, f"{ctx}: colonne 'address' absente")
        require(WALLETS.valid_time in row, f"{ctx}: colonne '{WALLETS.valid_time}' absente")
        addr = str(row["address"]).strip().lower()
        if addr == TWAP_PSEUDO_ADDRESS:
            continue
        vt = _to_utc(row[WALLETS.valid_time], WALLETS.valid_time, ctx)
        if knowable_at_for(WALLETS.name, vt) > asof:
            continue
        info = {k: row[k] for k in ("perpEquity", "totalEquity", "exposureRatio") if k in row}
        info["observed_at"] = vt
        prev = dernier.get(addr)
        if prev is None or vt > prev[0]:
            dernier[addr] = (vt, info)
    return {a: v for a, (_, v) in dernier.items()}


# --------------------------------------------------------------------------- chargement

def load_closed_trades_parquet(root: str, asof: datetime | None = None) -> list[dict[str, Any]]:
    """Charge closed_trades depuis <root>/closed_trades/dt=*/*.parquet.

    Leve InsufficientData si rien n'a encore ete collecte : c'est l'etat reel du depot
    aujourd'hui (seuls 7 snapshots orders_5m existent). Ne retourne JAMAIS une liste vide
    silencieuse, qui serait interpretee a tort comme "aucun wallet performant".
    """
    motif = os.path.join(root, CLOSED_TRADES.name, "dt=*", "*.parquet")
    fichiers = sorted(glob.glob(motif))
    require(bool(fichiers),
            f"aucun fichier closed_trades sous {motif} : la source est DOCUMENTED et "
            f"n'a pas encore ete collectee (quota API epuise). Le ranking est impossible "
            f"tant que ces donnees n'existent pas.")
    try:
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - depend de l'environnement
        raise InsufficientData("pyarrow indisponible, lecture parquet impossible") from e

    lignes: list[dict[str, Any]] = []
    for f in fichiers:
        table = pq.read_table(f)
        manquantes = [c for c in REQUIRED_TRADE_COLUMNS if c not in table.column_names]
        require(not manquantes,
                f"{f}: colonnes obligatoires absentes {manquantes} — le schema "
                f"closed_trades est DOCUMENTED, la doc s'est deja revelee fausse")
        lignes.extend(table.to_pylist())
    if asof is not None:
        # Filtrage effectif fait par prepare_trades ; ici on ne fait que remonter le compte.
        prepare_trades(lignes, asof)
    return lignes


__all__ = [
    "TWAP_PSEUDO_ADDRESS", "MIN_TRADES_FOR_RANKING", "MIN_PERIODS_FOR_PERSISTENCE",
    "SHRINKAGE_PSEUDO_TRADES", "DEFAULT_WEIGHTS", "DIMENSIONS", "MANDATORY_DIMENSIONS",
    "REQUIRED_TRADE_COLUMNS", "BIAIS_DOCUMENTES",
    "STATUS_RANKED", "STATUS_INSUFFICIENT_SAMPLE", "STATUS_MISSING_DIMENSION",
    "Trade", "WalletRanking", "RankingResult",
    "check_weights", "shrink", "prepare_trades", "compute_metrics",
    "compute_dimension_scores", "rank", "load_closed_trades_parquet",
]
