#!/usr/bin/env python3
"""
FINAL_GATE — le seul point qui autorise un classement definitif et une probabilite
certifiee.

Neuf conditions INDEPENDANTES. VERIFIED exige les neuf ; une seule qui echoue suffit
a refuser, et le rapport dit laquelle. Aucune n'est ponderee ni compensable : on ne
rattrape pas une calibration douteuse par un bon Monte-Carlo.

Les seuils sont IMPORTES des modules qui les possedent — ht.gate, ht.calibration,
ht.montecarlo — jamais redefinis ici. Un seuil duplique finit toujours par diverger,
et la copie la plus permissive gagne.

Mode DRY-RUN : verifie que la chaine est cablee et que chaque condition sait dire
pourquoi elle refuse, SANS produire de resultat. Il ne peut jamais rendre VERIFIED.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .schema import DERIVED, OBSERVED, InsufficientData, utcnow

VERIFIED = "VERIFIED"
REFUSED = "REFUSED"
DRY_RUN = "DRY_RUN"

# Conditions, dans l'ordre de dependance. Le nom sert de cle dans le rapport.
SEGMENTATION = "segmentation_validee"
SOURCE = "source_observee"
DECOUPAGE = "decoupage_oos"
ECE = "ece_certifiee"
CALIBRATION = "calibration_amelioree"
ROBUSTESSE = "robustesse_monte_carlo"
SENSIBILITE = "sensibilite_frais_funding"
STABILITE = "stabilite_temporelle"
CONCENTRATION = "concentration_pnl"

ORDRE = (SEGMENTATION, SOURCE, DECOUPAGE, ECE, CALIBRATION,
         ROBUSTESSE, SENSIBILITE, STABILITE, CONCENTRATION)

# Dependances : une condition n'est evaluee que si toutes les siennes sont satisfaites.
# Ce qui n'a pas de dependance est PARALLELISABLE.
DEPENDANCES: dict[str, tuple[str, ...]] = {
    SEGMENTATION: (),
    SOURCE: (),
    DECOUPAGE: (SOURCE,),
    ECE: (DECOUPAGE,),
    CALIBRATION: (ECE,),
    ROBUSTESSE: (SOURCE,),
    SENSIBILITE: (SOURCE,),
    STABILITE: (SOURCE,),
    CONCENTRATION: (SOURCE,),
}

# Seuils propres au FINAL_GATE — ceux qui n'existent nulle part ailleurs.
MAX_PART_MEILLEUR_TRADE = 0.40      # concentration du PnL
MAX_DEGRADATION_RELATIVE = 0.50     # perte de performance hors echantillon toleree
MAX_PART_FRAIS = 0.50               # part des frais+funding dans le PnL brut


@dataclass
class Condition:
    nom: str
    satisfaite: bool
    detail: str = ""
    valeur: Any = None
    evaluee: bool = True
    dependances_manquantes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerdictFinal:
    etat: str
    conditions: list[Condition] = field(default_factory=list)
    horodatage: str = ""
    dry_run: bool = False

    @property
    def verifie(self) -> bool:
        return self.etat == VERIFIED

    def par_nom(self, nom: str) -> Condition | None:
        return next((c for c in self.conditions if c.nom == nom), None)

    def echecs(self) -> list[Condition]:
        return [c for c in self.conditions if not c.satisfaite]

    def as_dict(self) -> dict:
        return {"etat": self.etat, "dry_run": self.dry_run,
                "horodatage": self.horodatage,
                "conditions": [c.as_dict() for c in self.conditions]}

    def resume(self) -> str:
        l = [f"FINAL_GATE {self.etat}" + ("  [DRY-RUN]" if self.dry_run else "")]
        for c in self.conditions:
            if not c.evaluee:
                l.append(f"  [ - ] {c.nom:<26} non evaluee — depend de "
                         f"{', '.join(c.dependances_manquantes)}")
            else:
                l.append(f"  [{'OK' if c.satisfaite else '!!':<2}] {c.nom:<26} {c.detail}")
        return "\n".join(l)


# --------------------------------------------------------------------------- conditions
def _cond_segmentation(ctx) -> Condition:
    v = ctx.get("verdict_segmentation")
    if v is None:
        return Condition(SEGMENTATION, False, "aucun verdict de segmentation fourni")
    from . import gate as G
    ok = getattr(v, "etat", None) == G.VERIFIED
    return Condition(SEGMENTATION, ok,
                     f"gate segmentation = {getattr(v, 'etat', '?')}"
                     + ("" if ok else " — la reconstruction n'est pas validee"),
                     valeur=getattr(v, "etat", None))


def _cond_source(ctx) -> Condition:
    cl = ctx.get("classification")
    ok = cl == OBSERVED
    return Condition(SOURCE, ok,
                     f"classification = {cl}"
                     + ("" if ok else " — seules des issues OBSERVED peuvent certifier"),
                     valeur=cl)


def _cond_decoupage(ctx) -> Condition:
    d = ctx.get("decoupage")
    if d is None:
        return Condition(DECOUPAGE, False, "aucun decoupage OOS fourni")
    try:
        n = (d.train.n, d.calibration.n, d.test.n)
    except AttributeError:
        return Condition(DECOUPAGE, False, "decoupage de forme inattendue")
    ok = all(x > 0 for x in n)
    return Condition(DECOUPAGE, ok,
                     f"train/calib/test = {n[0]}/{n[1]}/{n[2]}, {d.n_purges} purges",
                     valeur=n)


def _cond_ece(ctx) -> Condition:
    from . import gate as G
    d = ctx.get("decoupage_oos")
    if d is None:
        return Condition(ECE, False, "aucun couple (y, p) hors echantillon fourni")
    try:
        e = G.ece_certifiee(d, classification=ctx.get("classification", DERIVED))
    except InsufficientData as ex:
        return Condition(ECE, False, str(ex)[:90])
    ok = e <= G.MAX_ECE_CERTIFIEE
    return Condition(ECE, ok, f"ECE = {e:.4f} (max {G.MAX_ECE_CERTIFIEE})", valeur=e)


def _cond_calibration(ctx) -> Condition:
    """
    Apres recalibrage ajuste sur le SEUL jeu de calibration, l'ECE mesuree sur le test
    doit tenir sous le meme seuil que l'ECE brute.

    Exiger une AMELIORATION serait un mauvais critere : un modele deja bien calibre ne
    peut pas etre ameliore, et le penaliser pour cela reviendrait a preferer un mauvais
    modele qu'on redresse a un bon qu'on ne redresse pas. Ce qui compte est la qualite
    FINALE de ce qui sera utilise en aval. Le sens de variation est reporte pour
    information, sans peser sur le verdict.
    """
    from . import calibration as CAL
    from . import gate as G
    d = ctx.get("decoupage_oos")
    if d is None:
        return Condition(CALIBRATION, False, "aucun decoupage fourni")
    try:
        y_ca, p_ca = d.calibration
        y_te, p_te = d.test
        avant = CAL.expected_calibration_error(y_te, p_te)
        iso = CAL.Isotonique().fit(y_ca, p_ca)
        apres = CAL.expected_calibration_error(y_te, iso.predict(p_te))
    except InsufficientData as ex:
        return Condition(CALIBRATION, False, str(ex)[:90])
    ok = apres <= G.MAX_ECE_CERTIFIEE
    sens = "ameliore" if apres < avant else ("stable" if abs(apres - avant) < 1e-9
                                             else "degrade")
    return Condition(CALIBRATION, ok,
                     f"ECE {avant:.4f} -> {apres:.4f} ({sens}, max "
                     f"{G.MAX_ECE_CERTIFIEE})",
                     valeur=(avant, apres))


def _cond_robustesse(ctx) -> Condition:
    """Bootstrap par blocs, permutation et Sharpe degonfle. Les trois doivent tenir :
    ce sont trois faiblesses differentes, pas trois mesures de la meme chose."""
    from . import montecarlo as MC
    r = ctx.get("rendements")
    if not r:
        return Condition(ROBUSTESSE, False, "aucune serie de rendements fournie")
    n_essais = int(ctx.get("n_essais", 1))
    seed = int(ctx.get("seed", 1))
    try:
        boot = MC.bootstrap_par_blocs(r, seed=seed, n_tirages=int(ctx.get("n_tirages", 800)))
        perm = MC.test_permutation_signe(r, seed=seed + 1,
                                         n_permutations=int(ctx.get("n_tirages", 800)))
        deg = MC.sharpe_degonfle(r, n_essais=n_essais)
    except InsufficientData as ex:
        return Condition(ROBUSTESSE, False, str(ex)[:90])
    ok = (not boot.contient(0.0)) and perm.significatif and deg.significatif
    return Condition(ROBUSTESSE, ok,
                     f"IC exclut 0 : {not boot.contient(0.0)} | p_perm = "
                     f"{perm.p_value:.4f} | Sharpe degonfle ({n_essais} essais) : "
                     f"{deg.significatif}",
                     valeur={"ic": (boot.ic_bas, boot.ic_haut), "p": perm.p_value,
                             "sharpe_significatif": deg.significatif})


def _cond_sensibilite(ctx) -> Condition:
    """L'avantage survit-il aux frais et au funding ? Un edge qui disparait une fois
    les couts payes n'est pas un edge, c'est une illusion comptable."""
    trades = ctx.get("trades") or ()
    brut = net = frais = 0.0
    n = 0
    for t in trades:
        b = t.get("realizedPnlUsd")
        if b is None:
            continue
        n += 1
        b = float(b)
        f = float(t.get("feeUsd") or 0.0)
        fu = float(t.get("fundingUsd") or 0.0) if t.get("funding_couvert") else 0.0
        brut += b
        frais += f - fu
        v = t.get("realizedPnlNetUsd")
        net += float(v) if v is not None else (b - f + fu)
    if n == 0:
        return Condition(SENSIBILITE, False, "aucun trade exploitable")
    if brut <= 0:
        return Condition(SENSIBILITE, False, f"PnL brut deja negatif ({brut:.2f})")
    part = frais / brut
    ok = net > 0 and part <= MAX_PART_FRAIS
    return Condition(SENSIBILITE, ok,
                     f"brut {brut:.2f} -> net {net:.2f} | couts = {part:.1%} du brut"
                     + ("" if ok else " — l'avantage ne survit pas aux couts"),
                     valeur={"brut": brut, "net": net, "part_couts": part})


def _cond_stabilite(ctx) -> Condition:
    """Degradation entre l'echantillon d'apprentissage et le hors echantillon."""
    tr, te = ctx.get("metrique_train"), ctx.get("metrique_oos")
    if tr is None or te is None:
        return Condition(STABILITE, False,
                         "metriques train/OOS absentes : degradation non mesurable")
    if tr == 0:
        return Condition(STABILITE, False, "metrique d'apprentissage nulle")
    deg = (float(tr) - float(te)) / abs(float(tr))
    ok = deg <= MAX_DEGRADATION_RELATIVE
    return Condition(STABILITE, ok,
                     f"degradation {deg:.1%} (max {MAX_DEGRADATION_RELATIVE:.0%})",
                     valeur=deg)


def _cond_concentration(ctx) -> Condition:
    """Un PnL porte par un seul trade n'est pas une performance reproductible."""
    r = ctx.get("rendements") or ()
    if not r:
        return Condition(CONCENTRATION, False, "aucune serie de rendements")
    tot = sum(r)
    if tot <= 0:
        return Condition(CONCENTRATION, False, f"PnL total non positif ({tot:.2f})")
    part = max(r) / tot
    ok = part <= MAX_PART_MEILLEUR_TRADE
    return Condition(CONCENTRATION, ok,
                     f"meilleur trade = {part:.1%} du PnL "
                     f"(max {MAX_PART_MEILLEUR_TRADE:.0%})", valeur=part)


EVALUATEURS: dict[str, Callable[[Mapping[str, Any]], Condition]] = {
    SEGMENTATION: _cond_segmentation, SOURCE: _cond_source, DECOUPAGE: _cond_decoupage,
    ECE: _cond_ece, CALIBRATION: _cond_calibration, ROBUSTESSE: _cond_robustesse,
    SENSIBILITE: _cond_sensibilite, STABILITE: _cond_stabilite,
    CONCENTRATION: _cond_concentration,
}


# --------------------------------------------------------------------------- portail
def evaluer(contexte: Mapping[str, Any] | None = None, *,
            dry_run: bool = False) -> VerdictFinal:
    """
    Evalue les neuf conditions. VERIFIED exige les neuf.

    En DRY-RUN, chaque evaluateur est bien execute — c'est le seul moyen de verifier
    que la chaine est cablee — mais l'etat rendu est DRY_RUN et ne peut JAMAIS valoir
    VERIFIED, quoi qu'il arrive.
    """
    ctx = dict(contexte or {})
    v = VerdictFinal(etat=REFUSED, horodatage=utcnow().isoformat(timespec="seconds"),
                     dry_run=dry_run)
    satisfaites: set[str] = set()
    for nom in ORDRE:
        manquantes = tuple(d for d in DEPENDANCES[nom] if d not in satisfaites)
        if manquantes:
            v.conditions.append(Condition(nom, False, evaluee=False,
                                          dependances_manquantes=manquantes))
            continue
        try:
            c = EVALUATEURS[nom](ctx)
        except Exception as e:                     # une panne n'est jamais un succes
            c = Condition(nom, False, f"{type(e).__name__}: {e}"[:90])
        v.conditions.append(c)
        if c.satisfaite:
            satisfaites.add(nom)

    toutes = all(c.satisfaite for c in v.conditions)
    v.etat = DRY_RUN if dry_run else (VERIFIED if toutes else REFUSED)
    return v


def independantes() -> list[str]:
    """Conditions sans dependance : elles peuvent etre evaluees en parallele."""
    return [n for n in ORDRE if not DEPENDANCES[n]]


def chaine_dependante() -> list[str]:
    """Conditions qui doivent etre evaluees en sequence."""
    return [n for n in ORDRE if DEPENDANCES[n]]
