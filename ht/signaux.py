"""
Moteur de signal : transforme une estimation de probabilite en decision exploitable.

Sortie : direction (LONG / SHORT / NO TRADE), probabilite, confiance, taille
d'echantillon, raisons, invalidation.

Quatre garde-fous, dans cet ordre — chacun peut a lui seul imposer NO TRADE :

1. ECHANTILLON. En dessous de MIN_ECHANTILLON observations, aucune direction n'est
   emise. Une proportion sur 20 issues a un intervalle si large qu'elle ne distingue
   rien.

2. CALIBRATION. Une probabilite non calibree n'est pas une probabilite, c'est un
   score. Sans preuve de calibration (ECE mesuree hors echantillon), le moteur refuse
   d'emettre. C'est la traduction directe de « ne jamais presenter la probabilite
   comme une certitude » : on n'annonce un pourcentage que si ce pourcentage a ete
   confronte a la frequence reelle.

3. INTERVALLE. La decision porte sur la BORNE de l'intervalle de credibilite, jamais
   sur le point. Si l'intervalle englobe le seuil de decision, l'edge n'est pas
   distinguable de zero et la reponse est NO TRADE — meme si le point est flatteur.

4. MARGE. Au-dela de la significativite statistique, il faut une marge economique :
   une probabilite de 51 % ne paie ni les frais ni le funding. Le seuil est explicite
   et modifiable, jamais implicite.

Le moteur ne lit aucun prix et ne dimensionne aucune position : il rend une direction
et une probabilite calibree, rien de plus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from .schema import InsufficientData, require

LONG = "LONG"
SHORT = "SHORT"
NO_TRADE = "NO TRADE"

# --------------------------------------------------------------------------- seuils
MIN_ECHANTILLON = 100          # sous ce seuil, aucune direction n'est emise
SEUIL_NEUTRE = 0.50            # probabilite d'un tirage sans edge
MARGE_MINIMALE = 0.03          # 3 points au-dessus du neutre : couvre frais et funding
ECE_MAXIMALE = 0.10            # au-dela, la probabilite est jugee non fiable
LARGEUR_IC_MAXIMALE = 0.30     # un intervalle plus large ne decide rien


@dataclass(frozen=True)
class Signal:
    """Un signal. `probability` et `confidence` sont en POURCENTAGE (0-100)."""
    asof: datetime
    direction: str
    probability: float | None
    confidence: float | None
    sample_size: int
    reasons: tuple[str, ...]
    invalidation: tuple[str, ...]
    interval: tuple[float, float] | None = None
    ece: float | None = None
    refus: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def actionable(self) -> bool:
        return self.direction in (LONG, SHORT)

    def resume(self) -> str:
        if not self.actionable:
            l = [f"{NO_TRADE} (n={self.sample_size})"]
            l += [f"  refus: {r}" for r in self.refus]
            return "\n".join(l)
        ic = f"[{self.interval[0]*100:.1f}–{self.interval[1]*100:.1f}%]" if self.interval else ""
        l = [f"{self.direction}  p={self.probability:.1f}% {ic}  "
             f"confiance={self.confidence:.0f}%  n={self.sample_size}"]
        l += [f"  raison: {r}" for r in self.reasons]
        l += [f"  invalide si: {i}" for i in self.invalidation]
        return "\n".join(l)


def _confiance(n: int, largeur: float, ece: float) -> float:
    """
    Confiance en pourcentage, produit de trois facteurs bornes a [0,1] :
      - masse d'echantillon  : n / (n + MIN_ECHANTILLON), saturant vers 1
      - precision            : 1 - largeur/LARGEUR_IC_MAXIMALE, nul si l'IC est au max
      - fiabilite            : 1 - ece/ECE_MAXIMALE, nul si la calibration est au max
    Le produit, et non la moyenne : un seul facteur effondre doit effondrer la
    confiance. Une moyenne laisserait une calibration catastrophique se faire
    compenser par un gros echantillon.
    """
    f_n = n / (n + MIN_ECHANTILLON)
    f_prec = max(0.0, 1.0 - largeur / LARGEUR_IC_MAXIMALE)
    f_cal = max(0.0, 1.0 - ece / ECE_MAXIMALE)
    return round(100.0 * f_n * f_prec * f_cal, 1)


def evaluer(asof: datetime,
            successes: int,
            trials: int,
            *,
            ece: float | None = None,
            cohorte: tuple[int, int] | None = None,
            seuil: float = SEUIL_NEUTRE,
            marge: float = MARGE_MINIMALE,
            min_echantillon: int = MIN_ECHANTILLON,
            level: float = 0.90,
            contexte: Mapping[str, Any] | None = None) -> Signal:
    """
    Emet un signal a partir d'un comptage d'issues binaires.

    `successes` / `trials` : issues favorables au LONG sur l'ensemble des issues.
    `ece` : erreur de calibration attendue, MESUREE hors echantillon. None = non
            mesuree, ce qui impose NO TRADE (on ne publie pas un pourcentage dont on
            ignore s'il correspond a la realite).
    `cohorte` : (successes, trials) de la cohorte de reference, pour le prior
            hierarchique. Sans elle, un prior uniforme est utilise et signale.

    Ne leve pas : un signal refuse est une reponse legitime, porteuse de ses raisons.
    """
    from .probability import BetaPrior, beta_binomial_proportion, fit_cohort_prior

    require(trials >= 0 and successes >= 0, "comptages negatifs")
    require(successes <= trials, f"successes ({successes}) > trials ({trials})")

    refus: list[str] = []
    raisons: list[str] = []
    ctx = dict(contexte or {})

    # -- garde-fou 1 : echantillon
    if trials < min_echantillon:
        refus.append(f"echantillon insuffisant : {trials}/{min_echantillon} issues")

    # -- garde-fou 2 : calibration
    if ece is None:
        refus.append("calibration non mesuree : une probabilite non confrontee a la "
                     "frequence reelle ne peut pas etre publiee")
    elif ece > ECE_MAXIMALE:
        refus.append(f"calibration insuffisante : ECE={ece:.3f} > {ECE_MAXIMALE}")

    if refus:
        return Signal(asof=asof, direction=NO_TRADE, probability=None, confidence=None,
                      sample_size=trials, reasons=(), invalidation=(),
                      ece=ece, refus=tuple(refus), detail=ctx)

    # -- estimation
    # `cohorte` peut etre un couple agrege (s, t) ou une liste de groupes. Le prior
    # empirique exige au moins 20 groupes : avec moins, on retombe explicitement sur
    # Jeffreys Beta(1/2, 1/2), non informatif, plutot que d'inventer un prior.
    prior = None
    if cohorte:
        groupes = list(cohorte) if isinstance(cohorte, (list, tuple)) and \
            cohorte and isinstance(cohorte[0], (list, tuple)) else [tuple(cohorte)]
        try:
            prior = fit_cohort_prior(groupes, asof=asof)
            raisons.append(f"prior empirique ajuste sur {len(groupes)} groupe(s) de cohorte")
        except Exception as e:
            raisons.append(f"prior de cohorte inutilisable ({type(e).__name__}) -> Jeffreys")
    if prior is None:
        prior = BetaPrior(alpha=0.5, beta=0.5,
                          justification="Jeffreys, non informatif : aucune cohorte de "
                                        "reference exploitable a cet asof",
                          source="defaut")
        if not any("Jeffreys" in r for r in raisons):
            raisons.append("prior de Jeffreys (aucune cohorte de reference)")

    est = beta_binomial_proportion(successes, trials, asof=asof, level=level,
                                   prior=prior, min_trials=min_echantillon)
    bas, haut = float(est.lower), float(est.upper)
    largeur = haut - bas

    # -- garde-fou 3 : l'intervalle doit trancher
    if bas <= seuil <= haut:
        refus.append(f"intervalle [{bas:.3f}, {haut:.3f}] englobe le seuil {seuil:.2f} : "
                     "edge non distinguable de zero")
    if largeur > LARGEUR_IC_MAXIMALE:
        refus.append(f"intervalle trop large ({largeur:.3f} > {LARGEUR_IC_MAXIMALE})")

    # -- garde-fou 4 : marge economique, evaluee sur la BORNE, pas sur le point
    direction = NO_TRADE
    if not refus:
        if bas >= seuil + marge:
            direction = LONG
            raisons.append(f"borne basse {bas:.3f} depasse le seuil {seuil:.2f} "
                           f"de plus que la marge {marge:.2f}")
        elif haut <= seuil - marge:
            direction = SHORT
            raisons.append(f"borne haute {haut:.3f} sous le seuil {seuil:.2f} "
                           f"de plus que la marge {marge:.2f}")
        else:
            refus.append(f"marge insuffisante : IC [{bas:.3f}, {haut:.3f}] "
                         f"ne s'ecarte pas de {marge:.2f} du seuil")

    if direction == NO_TRADE:
        return Signal(asof=asof, direction=NO_TRADE, probability=None, confidence=None,
                      sample_size=trials, reasons=tuple(raisons), invalidation=(),
                      interval=(bas, haut), ece=ece, refus=tuple(refus), detail=ctx)

    p = float(est.mean)
    conf = _confiance(trials, largeur, ece)
    raisons.append(f"{successes}/{trials} issues favorables observees")
    if est.shrinkage_to_prior:
        raisons.append(f"retrecissement vers le prior : {est.shrinkage_to_prior:.2f}")

    invalidation = (
        f"la borne {'basse' if direction == LONG else 'haute'} repasse du cote du "
        f"seuil {seuil:.2f}",
        f"l'ECE hors echantillon depasse {ECE_MAXIMALE}",
        f"l'echantillon retombe sous {min_echantillon} issues",
        "la population change (PSI > 0,25 entre la fenetre de reference et la courante)",
    )
    return Signal(asof=asof, direction=direction, probability=round(p * 100, 1),
                  confidence=conf, sample_size=trials, reasons=tuple(raisons),
                  invalidation=invalidation, interval=(bas, haut), ece=ece,
                  refus=(), detail=ctx)


@dataclass(frozen=True)
class ContexteSignal:
    """
    Interface d'entree du futur moteur de signal. Elle transporte tout ce qui doit
    peser sur une decision, et refuse par defaut.

    Le champ decisif est `classification` : tant qu'il ne vaut pas OBSERVED, aucune
    direction n'est emise, quelles que soient les autres valeurs. C'est le meme
    verrou que l'ECE, place a l'entree plutot qu'a la sortie.
    """
    wallet: str
    score_wallet: float | None          # ht.wallet_intel.ScoreWallet.score
    score_complet: bool
    regime: str | None                  # ht.regime.Regime.etiquette
    perf_conditionnelle: Any = None     # ht.conditional.PerfRegime du regime courant
    ece: float | None = None            # mesuree hors echantillon, sur OBSERVED
    classification: str = "DERIVED"
    n_effectif: float = 0.0
    alertes: tuple[str, ...] = ()

    def blocages(self) -> tuple[str, ...]:
        """Toutes les raisons de ne pas emettre. Vide = rien ne s'oppose a l'evaluation."""
        from .schema import OBSERVED
        r = []
        if self.classification != OBSERVED:
            r.append(f"donnees {self.classification} : une direction exige des issues "
                     "OBSERVED validees")
        if self.score_wallet is None:
            r.append("score de wallet indisponible")
        elif not self.score_complet:
            r.append("score de wallet incomplet : composantes manquantes")
        if self.regime is None:
            r.append("regime de marche inconnu")
        if self.perf_conditionnelle is None:
            r.append("aucune performance mesuree dans ce regime")
        elif not getattr(self.perf_conditionnelle, "suffisant", False):
            r.append("echantillon insuffisant dans ce regime")
        if self.ece is None:
            r.append("ECE non mesuree hors echantillon")
        return tuple(r)


def evaluer_avec_contexte(asof: datetime, ctx: ContexteSignal,
                          successes: int | None = None, trials: int | None = None,
                          **kw) -> Signal:
    """
    Point d'entree du futur moteur de signal.

    NO TRADE reste le defaut : tout blocage du contexte suffit a le produire, AVANT
    meme de regarder les comptages. Les blocages sont reportes tels quels dans
    `refus`, de sorte qu'un NO TRADE soit toujours explicable.
    """
    bl = ctx.blocages()
    if bl:
        return Signal(asof=asof, direction=NO_TRADE, probability=None, confidence=None,
                      sample_size=int(trials or 0), reasons=(), invalidation=(),
                      ece=ctx.ece, refus=bl,
                      detail={"wallet": ctx.wallet, "regime": ctx.regime,
                              "classification": ctx.classification})
    if successes is None or trials is None:
        return Signal(asof=asof, direction=NO_TRADE, probability=None, confidence=None,
                      sample_size=0, reasons=(), invalidation=(), ece=ctx.ece,
                      refus=("aucune issue fournie",),
                      detail={"wallet": ctx.wallet, "regime": ctx.regime})
    s = evaluer(asof, successes, trials, ece=ctx.ece,
                contexte={"wallet": ctx.wallet, "regime": ctx.regime,
                          "score_wallet": ctx.score_wallet}, **kw)
    return s


def depuis_issues(asof: datetime,
                  issues: Sequence[Mapping[str, Any]],
                  *,
                  champ: str = "realizedPnlUsd",
                  **kw) -> Signal:
    """
    Confort : compte les issues favorables depuis une liste de trades clos.
    Une issue est favorable si `champ` est strictement positif.

    Aucun trade clos n'ayant encore ete collecte, cette fonction n'a jamais tourne
    sur des donnees reelles.
    """
    vals = [t.get(champ) for t in issues]
    utilisables = [v for v in vals if isinstance(v, (int, float))]
    if len(utilisables) < len(vals):
        raise InsufficientData(
            f"{len(vals) - len(utilisables)} issue(s) sans champ '{champ}' exploitable : "
            "compter dessus fausserait la proportion"
        )
    return evaluer(asof, sum(1 for v in utilisables if v > 0), len(utilisables), **kw)
