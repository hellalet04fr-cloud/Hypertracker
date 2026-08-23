#!/usr/bin/env python3
"""
Portail de verification : le seul endroit qui autorise le passage DERIVED -> VERIFIED.

Tant que ce portail ne rend pas VERIFIED, aucun classement definitif ni aucune
probabilite certifiee n'est permis. Il ne fait aucune requete : il constate.

Trois etats, jamais autre chose :
  NOT_READY         — les donnees natives n'existent pas encore, ou pas sur les memes
                      wallets que les reconstruites. Il n'y a rien a comparer.
  INSUFFICIENT_DATA — la comparaison a eu lieu mais ne tranche pas : trop peu de paires
                      appariees, ou les seuils statistiques du projet ne sont pas
                      atteints. C'est un echec mesure, pas une absence de mesure.
  VERIFIED          — toutes les conditions sont reunies. Le seul etat qui debloque
                      un classement definitif et une probabilite certifiee.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from .schema import DERIVED, OBSERVED, InsufficientData, utcnow

NOT_READY = "NOT_READY"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
VERIFIED = "VERIFIED"

# --------------------------------------------------------------------------- seuils
# Repris des regles deja fixees dans le projet, pas reinventes ici.
MIN_PAIRES_APPARIEES = 100          # sous ce seuil, un taux de concordance est du bruit
MAX_TAUX_NON_RECONCILIABLE = 0.20   # au-dela, l'appariement lui-meme est douteux
MIN_CONCORDANCE_PNL = 0.90          # 90 % des paires a l'euro pres
MAX_MAE_PNL_RELATIVE = 0.02         # erreur moyenne < 2 % du |PnL| median
MAX_ECART_TEMPS_MS = 60_000         # 1 minute sur openTime / closeTime
MAX_ECE_CERTIFIEE = 0.10            # aligne sur ht.signaux.ECE_MAXIMALE


# --------------------------------------------------------------------------- causes
CAUSES = {
    "tronque": "trade reconstruit tronque : ouverture hors fenetre Hyperliquid",
    "funding_non_couvert": "funding non mesure sur ce trade",
    "fills_manquants": "countFills reconstruit < natif : fills absents de la fenetre "
                       "des ~10 000 derniers",
    "fills_excedentaires": "countFills reconstruit > natif : decoupage de position "
                           "different entre les deux sources",
    "frais_non_usdc": "ecart de frais sans ecart de PnL : frais preleves dans un "
                      "token autre que USDC",
    "convention_pnl": "ecart de PnL systematique et de meme signe : convention brut "
                      "contre net differente entre les sources",
    "decalage_temporel": "openTime ou closeTime decale au-dela de la tolerance",
    "inexplique": "aucune cause identifiee",
}


def diagnostiquer_ecarts(paires: Sequence[tuple[Mapping, Mapping]]) -> dict[str, Any]:
    """
    Classe chaque paire (natif, reconstruit) discordante par cause probable.

    Une cause n'est pas une excuse : elle sert a decider si l'ecart est structurel
    (donc corrigeable) ou aleatoire (donc disqualifiant). Un ecart systematique de
    meme signe sur le PnL revele une convention differente ; un ecart de signe
    variable revele une reconstruction fausse.
    """
    compte: dict[str, int] = {c: 0 for c in CAUSES}
    ecarts_pnl_signes: list[float] = []
    n_discordantes = 0

    for nat, rec in paires:
        e_pnl = _f(rec.get("realizedPnlUsd")) - _f(nat.get("realizedPnlUsd"))
        e_fee = _f(rec.get("feeUsd")) - _f(nat.get("feeUsd"))
        e_fills = int(_f(rec.get("countFills"))) - int(_f(nat.get("countFills")))
        e_t = max(abs(_ms(rec.get("openTime")) - _ms(nat.get("openTime"))),
                  abs(_ms(rec.get("closeTime")) - _ms(nat.get("closeTime"))))

        if abs(e_pnl) <= 1e-6 and abs(e_fee) <= 1e-6 and e_fills == 0 \
                and e_t <= MAX_ECART_TEMPS_MS:
            continue
        n_discordantes += 1

        if rec.get("tronque"):
            compte["tronque"] += 1
            continue
        if rec.get("funding_couvert") is False:
            compte["funding_non_couvert"] += 1
            continue
        if e_fills < 0:
            compte["fills_manquants"] += 1
            continue
        if e_fills > 0:
            compte["fills_excedentaires"] += 1
            continue
        if abs(e_fee) > 1e-6 and abs(e_pnl) <= 1e-6:
            compte["frais_non_usdc"] += 1
            continue
        if e_t > MAX_ECART_TEMPS_MS:
            compte["decalage_temporel"] += 1
            continue
        if abs(e_pnl) > 1e-6:
            ecarts_pnl_signes.append(e_pnl)
            continue
        compte["inexplique"] += 1

    # Un ecart de PnL est structurel si les signes concordent tres majoritairement.
    if ecarts_pnl_signes:
        positifs = sum(1 for e in ecarts_pnl_signes if e > 0)
        part = max(positifs, len(ecarts_pnl_signes) - positifs) / len(ecarts_pnl_signes)
        if part >= 0.90:
            compte["convention_pnl"] += len(ecarts_pnl_signes)
        else:
            compte["inexplique"] += len(ecarts_pnl_signes)

    return {
        "n_discordantes": n_discordantes,
        "causes": {k: v for k, v in compte.items() if v},
        "libelles": {k: CAUSES[k] for k, v in compte.items() if v},
        "ecart_pnl_median_signe": (statistics.median(ecarts_pnl_signes)
                                   if ecarts_pnl_signes else None),
    }


def _f(v, defaut=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def _ms(v) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


# --------------------------------------------------------------------------- ECE
@dataclass(frozen=True)
class DecoupageOOS:
    """Decoupage strict train / calibration / test. Les trois doivent etre disjoints :
    une intersection, meme partielle, invalide la mesure."""
    train: tuple
    calibration: tuple
    test: tuple


def ece_certifiee(decoupage: DecoupageOOS, *, classification: str,
                  n_bacs: int = 10) -> float:
    """
    ECE mesuree sur le SEUL jeu de test, apres recalibrage ajuste sur le jeu de
    calibration. Refuse toute classification autre que OBSERVED.

    Chaque jeu est un couple (y_true, y_prob).
    """
    from . import calibration as CAL

    if classification != OBSERVED:
        raise InsufficientData(
            f"ECE certifiee impossible sur des donnees {classification!r} : seules des "
            "issues OBSERVED peuvent certifier une probabilite."
        )
    y_tr, p_tr = decoupage.train
    y_ca, p_ca = decoupage.calibration
    y_te, p_te = decoupage.test
    for nom, (y, p) in (("train", decoupage.train), ("calibration", decoupage.calibration),
                        ("test", decoupage.test)):
        if len(y) != len(p) or len(y) == 0:
            raise InsufficientData(f"jeu '{nom}' vide ou incoherent")

    # Disjonction : on compare les empreintes, pas les objets — deux tableaux
    # identiques passes par des chemins differents restent le meme jeu.
    emp = lambda y, p: (len(y), round(float(sum(y)), 9), round(float(sum(p)), 9))
    e_tr, e_ca, e_te = emp(y_tr, p_tr), emp(y_ca, p_ca), emp(y_te, p_te)
    if len({e_tr, e_ca, e_te}) < 3:
        raise InsufficientData(
            "train, calibration et test doivent etre trois jeux DISTINCTS : "
            "un recouvrement rendrait l'ECE flatteuse et fausse."
        )

    iso = CAL.Isotonique().fit(y_ca, p_ca)
    iso.verifier_jeu_distinct(y_te, p_te)
    return CAL.ece_hors_echantillon(y_te, iso.predict(p_te),
                                    classification=classification, n_bacs=n_bacs)


# --------------------------------------------------------------------------- portail
@dataclass
class Verdict:
    etat: str
    raisons: tuple[str, ...] = ()
    validation: Any = None
    diagnostic: dict = field(default_factory=dict)
    ece: float | None = None
    n_paires: int = 0
    horodatage: str = ""

    @property
    def verifie(self) -> bool:
        return self.etat == VERIFIED

    def as_dict(self) -> dict:
        d = asdict(self)
        d["validation"] = (asdict(self.validation) if self.validation is not None else None)
        return d

    def resume(self) -> str:
        l = [f"GATE {self.etat} ({self.n_paires} paires appariees)"]
        l += [f"  - {r}" for r in self.raisons]
        if self.diagnostic.get("causes"):
            l.append("  causes des ecarts :")
            for c, n in sorted(self.diagnostic["causes"].items(), key=lambda x: -x[1]):
                l.append(f"    {n:>5}  {CAUSES.get(c, c)}")
        if self.ece is not None:
            l.append(f"  ECE certifiee : {self.ece:.4f}")
        return "\n".join(l)


def evaluer(reconstruits: Sequence[Mapping[str, Any]],
            natifs: Sequence[Mapping[str, Any]],
            *,
            decoupage_oos: DecoupageOOS | None = None,
            classification_oos: str = DERIVED) -> Verdict:
    """
    Unique point de decision du projet. Ne fait aucune requete.

    VERIFIED exige TOUTES les conditions :
      1. au moins MIN_PAIRES_APPARIEES paires natif/reconstruit sur les memes wallets
      2. taux de non-reconciliation sous MAX_TAUX_NON_RECONCILIABLE
      3. concordance exacte du PnL au-dessus de MIN_CONCORDANCE_PNL
      4. erreur moyenne de PnL sous MAX_MAE_PNL_RELATIVE du |PnL| median natif
      5. ecarts d'openTime et closeTime sous MAX_ECART_TEMPS_MS au p95
      6. une ECE certifiee, mesuree sur des donnees OBSERVED hors echantillon,
         sous MAX_ECE_CERTIFIEE
    """
    from . import reconstruct as R

    horodatage = utcnow().isoformat(timespec="seconds")
    if not natifs:
        return Verdict(NOT_READY, ("aucun closed_trade natif disponible",),
                       horodatage=horodatage)
    if not reconstruits:
        return Verdict(NOT_READY, ("aucun trade reconstruit a comparer",),
                       horodatage=horodatage)

    communs = ({str(r.get("address", "")).lower() for r in reconstruits}
               & {str(n.get("address", "")).lower() for n in natifs})
    if not communs:
        return Verdict(NOT_READY,
                       ("aucun wallet commun entre DERIVED et natif : rien a comparer",),
                       horodatage=horodatage)

    rec = [r for r in reconstruits if str(r.get("address", "")).lower() in communs]
    nat = [n for n in natifs if str(n.get("address", "")).lower() in communs]
    val = R.valider_contre_natifs(rec, nat)

    paires = _reapparier(rec, nat)
    diag = diagnostiquer_ecarts(paires)

    raisons: list[str] = []
    if val.n_apparies < MIN_PAIRES_APPARIEES:
        raisons.append(f"{val.n_apparies}/{MIN_PAIRES_APPARIEES} paires appariees")
    if val.taux_non_reconciliables > MAX_TAUX_NON_RECONCILIABLE:
        raisons.append(f"non-reconciliation {val.taux_non_reconciliables:.1%} > "
                       f"{MAX_TAUX_NON_RECONCILIABLE:.0%}")
    c_pnl = val.concordance_exacte.get("realizedPnlUsd")
    if c_pnl is None or c_pnl != c_pnl or c_pnl < MIN_CONCORDANCE_PNL:
        raisons.append(f"concordance PnL {c_pnl if c_pnl == c_pnl else 'n/a'} < "
                       f"{MIN_CONCORDANCE_PNL}")
    med_abs = statistics.median([abs(_f(n.get("realizedPnlUsd"))) for n in nat]) or 1.0
    mae = val.erreur_moyenne.get("realizedPnlUsd")
    if mae is None or mae != mae or (mae / med_abs) > MAX_MAE_PNL_RELATIVE:
        raisons.append(f"MAE PnL relative {(mae / med_abs) if mae == mae else float('nan'):.3f} "
                       f"> {MAX_MAE_PNL_RELATIVE}")
    for champ in ("openTime", "closeTime"):
        p95 = val.erreur_p95.get(champ)
        if p95 is None or p95 != p95 or p95 > MAX_ECART_TEMPS_MS:
            raisons.append(f"p95 {champ} {p95} ms > {MAX_ECART_TEMPS_MS} ms")

    ece = None
    if decoupage_oos is None:
        raisons.append("aucun decoupage hors echantillon fourni : ECE non mesurable")
    else:
        try:
            ece = ece_certifiee(decoupage_oos, classification=classification_oos)
            if ece > MAX_ECE_CERTIFIEE:
                raisons.append(f"ECE {ece:.4f} > {MAX_ECE_CERTIFIEE}")
        except InsufficientData as e:
            raisons.append(f"ECE non certifiable : {e}")

    etat = VERIFIED if not raisons else INSUFFICIENT_DATA
    return Verdict(etat, tuple(raisons), validation=val, diagnostic=diag,
                   ece=ece, n_paires=val.n_apparies, horodatage=horodatage)


def _reapparier(rec: Sequence[Mapping], nat: Sequence[Mapping],
                tolerance_ms: int = 120_000) -> list[tuple[Mapping, Mapping]]:
    """Meme regle d'appariement que le cross-validator : (address, coin) puis
    proximite de closeTime. Duplique ici pour que le diagnostic travaille sur les
    paires elles-memes, que le rapport de validation n'expose pas."""
    from collections import defaultdict

    index = defaultdict(list)
    for r in rec:
        index[(str(r.get("address", "")).lower(), r.get("coin"))].append(r)
    paires = []
    for n in nat:
        cands = index.get((str(n.get("address", "")).lower(), n.get("coin"))) or []
        t_n = _ms(n.get("closeTime"))
        meilleur, ecart = None, None
        for c in cands:
            e = abs(_ms(c.get("closeTime")) - t_n)
            if e <= tolerance_ms and (ecart is None or e < ecart):
                meilleur, ecart = c, e
        if meilleur is not None:
            paires.append((n, meilleur))
            cands.remove(meilleur)
    return paires


# --------------------------------------------------------------------------- automatisation
def executer_si_pret(natifs: Sequence[Mapping[str, Any]],
                     reconstruits: Sequence[Mapping[str, Any]],
                     wallets: Sequence[Mapping[str, Any]] | None = None,
                     *, decoupage_oos: DecoupageOOS | None = None,
                     classification_oos: str = DERIVED,
                     asof: datetime | None = None) -> dict[str, Any]:
    """
    Enchainement automatique : validation croisee -> ECE -> classement.

    Aucune intervention manuelle si les donnees suffisent. Si le portail ne rend pas
    VERIFIED, le classement reste PROVISOIRE — l'enchainement ne s'interrompt pas,
    il degrade explicitement.
    """
    from . import elite as E

    asof = asof or utcnow()
    verdict = evaluer(reconstruits, natifs, decoupage_oos=decoupage_oos,
                      classification_oos=classification_oos)
    sortie: dict[str, Any] = {"verdict": verdict, "classement": None,
                              "definitif": False, "note": ""}

    source = natifs if verdict.verifie else (list(natifs) + list(reconstruits))
    try:
        cl = E.classer(asof, source, wallets, provisoire=not verdict.verifie)
        sortie["classement"] = cl
        sortie["definitif"] = cl.definitif
    except InsufficientData as e:
        sortie["note"] = f"classement impossible : {e}"
        return sortie

    sortie["note"] = ("classement DEFINITIF autorise par le portail"
                      if verdict.verifie else
                      f"classement PROVISOIRE : portail {verdict.etat}")
    return sortie
