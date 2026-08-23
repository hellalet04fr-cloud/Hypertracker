"""
Orchestration end-to-end : store -> behavior -> features -> ranking -> validation
-> Monte-Carlo -> calibration.

Principe unique : chaque etage rend un `Etape` portant son statut. Un etage qui manque
de donnees est marque INSUFFISANT avec la raison exacte, et les etages en aval sont
marques BLOQUE — jamais executes sur un substitut. Le pipeline ne renvoie donc jamais
un resultat complet a partir de donnees incompletes : il renvoie une carte precise de
ce qui a pu etre calcule et de ce qui manque.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .schema import InsufficientData, utcnow

OK = "OK"
INSUFFISANT = "INSUFFISANT"
BLOQUE = "BLOQUE"


@dataclass
class Etape:
    nom: str
    statut: str
    detail: str = ""
    valeur: Any = field(default=None, repr=False)
    n: int | None = None

    @property
    def ok(self) -> bool:
        return self.statut == OK


@dataclass
class Rapport:
    asof: datetime
    etapes: list[Etape] = field(default_factory=list)
    # Les entrees brutes sont conservees pour que les consommateurs aval (ht.elite,
    # ht.signaux) puissent recalculer sans re-parametrer toute la chaine.
    closed_trades: list = field(default_factory=list, repr=False)
    wallets: list = field(default_factory=list, repr=False)

    def ajouter(self, e: Etape) -> Etape:
        self.etapes.append(e)
        return e

    def par_nom(self, nom: str) -> Etape | None:
        return next((e for e in self.etapes if e.nom == nom), None)

    @property
    def complet(self) -> bool:
        return all(e.ok for e in self.etapes)

    def manquants(self) -> list[str]:
        return [f"{e.nom}: {e.detail}" for e in self.etapes if not e.ok]

    def resume(self) -> str:
        lignes = [f"pipeline asof={self.asof.isoformat()}"]
        for e in self.etapes:
            n = f" n={e.n}" if e.n is not None else ""
            lignes.append(f"  [{e.statut:<11}] {e.nom}{n}"
                          + (f" — {e.detail}" if e.detail else ""))
        return "\n".join(lignes)


def _tenter(rapport: Rapport, nom: str, fn, *, depend: Sequence[str] = ()) -> Etape:
    """Execute un etage, sauf si une dependance a echoue. Toute InsufficientData est
    convertie en statut, jamais en valeur de remplacement."""
    for d in depend:
        amont = rapport.par_nom(d)
        if amont is None or not amont.ok:
            return rapport.ajouter(Etape(nom, BLOQUE, f"depend de '{d}' qui n'est pas OK"))
    try:
        valeur, n, detail = fn()
        return rapport.ajouter(Etape(nom, OK, detail, valeur, n))
    except InsufficientData as e:
        return rapport.ajouter(Etape(nom, INSUFFISANT, str(e)))
    except Exception as e:                    # une panne technique n'est pas un manque
        return rapport.ajouter(Etape(nom, INSUFFISANT, f"{type(e).__name__}: {e}"))


def run(asof: datetime | None = None, *,
        racine: str | None = None,
        closed_trades: Iterable[Mapping[str, Any]] | None = None,
        wallets: Iterable[Mapping[str, Any]] | None = None,
        max_entites: int = 50,
        seed: int = 1,
        n_tirages: int = 400) -> Rapport:
    """
    Traverse toute la chaine pour un `asof` donne.

    `closed_trades` / `wallets` sont optionnels : s'ils sont absents, les etages qui en
    dependent sont marques INSUFFISANT — ce qui est aujourd'hui le cas reel, aucune de
    ces deux sources n'ayant encore ete collectee.
    """
    import numpy as np

    from . import behavior as bh
    from . import features as F
    from . import ranking as R
    from . import validation as V
    from . import montecarlo as MC
    from . import calibration as CAL
    from .schema import ORDERS_5M

    asof = asof or utcnow()
    closed_trades = list(closed_trades) if closed_trades is not None else None
    wallets = list(wallets) if wallets is not None else None
    rap = Rapport(asof=asof, closed_trades=closed_trades or [], wallets=wallets or [])

    # ---- 1. comportement (source reellement collectee) --------------------
    def _behavior():
        p = bh.profil_comportemental(asof, racine, min_ordres=1) if racine \
            else bh.profil_comportemental(asof, min_ordres=1)
        if len(p) == 0:
            raise InsufficientData("aucun wallet dans les snapshots visibles a cet asof")
        return p, len(p), f"{p.shape[1]} variables comportementales"

    _tenter(rap, "behavior", _behavior)

    # ---- 2. variables point-in-time ---------------------------------------
    def _features():
        F.install_builtin_specs()
        ld = F.ParquetLoader(root=racine) if racine else F.ParquetLoader()
        ents = F.discover_entities(ORDERS_5M.name, asof, loader=ld, limit=max_entites)
        if not ents:
            raise InsufficientData("aucune entite resolvable dans orders_5m")
        t = F.build(asof, ents, loader=ld)
        complets = sum(1 for r in t.to_pylist() if r.get("complete", True))
        return t, t.num_rows, f"{complets}/{t.num_rows} lignes completes"

    _tenter(rap, "features", _features, depend=("behavior",))

    # ---- 3. absence de fuite ----------------------------------------------
    def _leak():
        ld = F.ParquetLoader(root=racine) if racine else F.ParquetLoader()
        ents = F.discover_entities(ORDERS_5M.name, asof, loader=ld, limit=25)
        specs = [s for s in F.REGISTRY.values() if s.source == ORDERS_5M.name]
        if not specs:
            raise InsufficientData("aucune spec integree enregistree")
        rapports = F.leak_check_all(specs, asof, ents, loader=ld, strict=False)
        fuites = {n: len(r.ecarts) for n, r in rapports.items() if r.ecarts}
        if fuites:
            raise InsufficientData(f"fuite detectee au replay differentiel: {fuites}")
        return rapports, len(rapports), "aucun ecart au replay differentiel"

    _tenter(rap, "leak_check", _leak, depend=("features",))

    # ---- 4. classement ----------------------------------------------------
    def _ranking():
        if closed_trades is None:
            raise InsufficientData(
                "closed_trades absent : aucune issue etiquetee collectee a ce jour "
                "(address obligatoire, fenetre 30 j, quota FREE 100 req/jour)"
            )
        res = R.rank(asof, closed_trades, wallets)
        if not res.classes:
            raise InsufficientData(
                f"aucun wallet classable ({len(res.non_classes)} ecarte(s))"
            )
        return res, len(res.classes), f"cohorte={res.taille_cohorte}"

    e_rank = _tenter(rap, "ranking", _ranking)

    # ---- 5. validation temporelle -----------------------------------------
    def _validation():
        dates = sorted({datetime.fromisoformat(t["closeTime"])
                        for t in closed_trades})
        plan = V.walk_forward(dates,
                              train_window=timedelta(days=20), test_window=timedelta(days=5),
                              step=timedelta(days=5), purge=timedelta(days=1),
                              embargo=timedelta(days=1))
        return plan, len(plan.folds), "purge et embargo appliques"

    _tenter(rap, "validation", _validation, depend=("ranking",))

    # ---- 6. significativite ------------------------------------------------
    def _montecarlo():
        res = e_rank.valeur
        top = res.classes[0]
        rend = np.array([float(t["realizedPnlUsd"]) for t in closed_trades
                         if t["address"] == top.address])
        r = MC.rapport_significativite(rend, seed=seed,
                                       n_essais=len(res.classes), n_tirages=n_tirages)
        return r, len(rend), (f"p_permutation={r['permutation_p']:.4f} "
                              f"ic_exclut_zero={r['moyenne_ic_exclut_zero']}")

    _tenter(rap, "montecarlo", _montecarlo, depend=("ranking",))

    # ---- 7. calibration ----------------------------------------------------
    def _calibration():
        y = np.array([1.0 if float(t["realizedPnlUsd"]) > 0 else 0.0
                      for t in closed_trades])
        if len(y) < CAL.MIN_OBS_CALIBRATION:
            raise InsufficientData(
                f"{len(y)} issues binaires, minimum {CAL.MIN_OBS_CALIBRATION}"
            )
        p = np.full(len(y), float(y.mean()))          # temoin : taux de base
        c = CAL.courbe_fiabilite(y, p)
        return c, len(y), f"ECE temoin={c.ece:.4f} (baseline a battre)"

    _tenter(rap, "calibration", _calibration, depend=("ranking",))

    return rap


def donnees_manquantes(rap: Rapport) -> list[str]:
    """Traduit les etages non-OK en besoins de collecte concrets."""
    besoins = []
    for e in rap.etapes:
        if e.ok:
            continue
        if e.nom == "ranking":
            besoins.append("closed_trades par wallet (/api/external/closed-trades, "
                           "address obligatoire, 30 j/requete)")
            besoins.append("closed-trades/summary par wallet (1 requete = winRate, "
                           "profitFactor, payoffRatio, expectancy sur 6 intervalles)")
        elif e.nom in ("validation", "montecarlo", "calibration"):
            besoins.append(f"{e.nom}: debloque par closed_trades")
        elif e.nom in ("behavior", "features"):
            besoins.append("snapshots d'ordres supplementaires (archive Jan19->Mar12)")
    return list(dict.fromkeys(besoins))
