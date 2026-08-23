"""
Plan de collecte sous quota contraint.

Le quota FREE est de 100 requetes par JOUR. La question n'est donc pas "que peut-on
telecharger" mais "quelle est la requete la plus irremplacable a depenser maintenant".

Deux proprietes classent les endpoints, et elles ne se confondent pas :

  IRREMPLACABILITE — ce qui est perdu si on ne le prend pas aujourd'hui.
    Les leaderboards n'ont AUCUN parametre as-of et aucun endpoint historique : le
    classement du jour n'existera plus jamais. Meme chose pour /wallets et les
    resumes de cohorte, dont l'appartenance est recalculee toutes les 3-4 h en amont.
    A l'oppose, l'archive de snapshots va du 19 janvier au 12 mars, bornes FIXES :
    elle coutera exactement une requete par creneau dans six mois comme aujourd'hui.

  DENSITE — information obtenue par requete.
    /closed-trades/summary rend en UNE requete winRate, profitFactor, payoffRatio et
    expectancy sur six intervalles (all/365d/180d/90d/30d/last50). C'est de loin le
    meilleur rapport pour alimenter le ranking, tres au-dessus de /closed-trades brut
    qui exige une requete par fenetre de 30 jours et par wallet.

D'ou l'ordre retenu : perissable d'abord, puis dense, puis l'archive avec le reliquat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

QUOTA_FREE_PAR_JOUR = 100

# Bornes mesurees, pas supposees.
ARCHIVE_CRENEAUX_RESTANTS = 15_124
WALLETS_TOTAL = 296_781
WALLETS_PAR_PAGE = 500


@dataclass(frozen=True)
class Requete:
    path: str
    but: str
    irremplacable: bool
    cout: int = 1

    def __str__(self) -> str:
        marque = "PERISSABLE" if self.irremplacable else "rattrapable"
        return f"[{marque:<11}] {self.path}  — {self.but}"


@dataclass
class Plan:
    budget: int
    requetes: list[Requete] = field(default_factory=list)
    reste_pour_archive: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def cout(self) -> int:
        return sum(r.cout for r in self.requetes)

    def resume(self) -> str:
        l = [f"budget={self.budget}  depense={self.cout}  archive={self.reste_pour_archive}"]
        l += [f"  {r}" for r in self.requetes]
        l += [f"  note: {n}" for n in self.notes]
        return "\n".join(l)


# --------------------------------------------------------------------------- perissable
def requetes_perissables() -> list[Requete]:
    """
    Ce qui disparait si on ne le capture pas aujourd'hui. Dix requetes au total.

    Les quatre `rankBy` des leaderboards ne sont pas redondants : pnlDay selectionne
    les gagnants du jour, pnlAllTime selectionne les survivants de long terme. Croiser
    les deux est exactement ce qui distingue un wallet persistant d'un wallet chanceux —
    et c'est la seule mesure de persistance disponible avant d'avoir des trades clos.
    """
    reqs: list[Requete] = []
    for ep in ("all-pnl", "perp-pnl"):
        for rank in ("pnlDay", "pnlWeek", "pnlMonth", "pnlAllTime"):
            reqs.append(Requete(
                f"/api/external/leaderboards/{ep}?limit=100&rankBy={rank}&orderBy={rank}&order=desc",
                f"top 100 par {rank} — aucun as-of, perdu a jamais si non capture",
                irremplacable=True))
    reqs.append(Requete("/api/external/segments",
                        "16 cohortes ; appartenance recalculee toutes les 3-4 h en amont",
                        irremplacable=True))
    reqs.append(Requete("/api/external/hypertracker/state/status",
                        "instant de fraicheur amont : fixe knowable_at pour la journee",
                        irremplacable=True))
    return reqs


# --------------------------------------------------------------------------- dense
def requetes_resumes(adresses: Sequence[str], budget: int) -> list[Requete]:
    """
    Un resume de trades clos par wallet. La requete la plus dense de l'API : elle rend
    directement quatre des six dimensions exigees par le ranking (performance, win rate,
    payoff, taille d'echantillon) sur six intervalles, sans pagination.
    """
    return [Requete(f"/api/external/closed-trades/summary?address={a}&interval=all",
                    "winRate/profitFactor/payoffRatio/expectancy — 6 intervalles en 1 requete",
                    irremplacable=False)
            for a in adresses[:max(0, budget)]]


# --------------------------------------------------------------------------- plan
def plan_journalier(adresses_connues: Iterable[str] = (),
                    budget: int = QUOTA_FREE_PAR_JOUR,
                    *, premier_jour: bool = True) -> Plan:
    """
    Construit le plan d'une journee de quota.

    Jour 1 : 10 requetes perissables, puis l'archive avec les 90 restantes — on n'a
    pas encore d'adresses a resumer, elles sortiront des leaderboards du jour meme.
    Jours suivants : 10 perissables, puis les resumes des wallets identifies, l'archive
    ne recuperant que ce qui reste.
    """
    p = Plan(budget=budget)
    adresses = list(dict.fromkeys(adresses_connues))

    for r in requetes_perissables():
        if p.cout + r.cout > budget:
            break
        p.requetes.append(r)

    reste = budget - p.cout
    if not premier_jour and adresses:
        # On plafonne les resumes a la moitie du reliquat : l'archive doit continuer
        # d'avancer, sinon 15 124 creneaux a zero par jour n'arrivent jamais.
        quota_resumes = min(len(adresses), reste // 2)
        resumes = requetes_resumes(adresses, quota_resumes)
        p.requetes.extend(resumes)
        reste -= len(resumes)

    p.reste_pour_archive = max(0, reste)

    jours = (ARCHIVE_CRENEAUX_RESTANTS / p.reste_pour_archive) if p.reste_pour_archive else float("inf")
    p.notes.append(
        f"archive: {ARCHIVE_CRENEAUX_RESTANTS} creneaux restants a {p.reste_pour_archive}/jour "
        f"-> {jours:.0f} jours au tier FREE"
    )
    p.notes.append(
        f"univers wallets: {WALLETS_TOTAL} adresses a {WALLETS_PAR_PAGE}/page = "
        f"{-(-WALLETS_TOTAL // WALLETS_PAR_PAGE)} requetes pour un balayage complet "
        f"({-(-WALLETS_TOTAL // WALLETS_PAR_PAGE) / budget:.1f} jours de quota) : "
        "a ne PAS tenter au tier FREE, les leaderboards donnent directement le haut du panier"
    )
    p.notes.append(
        "les 4 rankBy croises (jour/semaine/mois/all-time) sont la seule mesure de "
        "persistance disponible tant qu'aucun trade clos n'est collecte"
    )
    return p


def adresses_depuis_leaderboards(lignes: Iterable[dict]) -> list[str]:
    """Union dedupliquee des adresses vues dans les leaderboards, ordre stable.
    C'est la liste d'entree du suivi longitudinal : ces wallets seront re-resumes
    a intervalle regulier pour mesurer leur persistance reelle."""
    vues: dict[str, None] = {}
    for l in lignes:
        a = l.get("address") or l.get("user") or l.get("wallet")
        if isinstance(a, str) and a.startswith("0x") and len(a) == 42:
            vues.setdefault(a, None)
    return list(vues)
