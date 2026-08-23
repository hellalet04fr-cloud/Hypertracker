#!/usr/bin/env python3
"""
GARDE-FOUS. Le seul module qui a le droit de dire NON.

Un systeme autonome n'est pas dangereux parce qu'il se trompe : il est dangereux parce
qu'il se trompe VITE et sans temoin. Ces controles sont mecaniques et executables — pas
des consignes en commentaire qu'un agent presse contournerait sans s'en apercevoir.

Quatre familles, dans l'ordre de gravite :

  DERIVE      la tache ramene-t-elle vers une branche abandonnee ? Le projet a deja
              derive une fois vers la certification d'un signal de trading ; six
              experiences y ont ete brulees avant le recadrage. Ce controle existe pour
              que cela ne se reproduise pas sans qu'on le voie.
  SCELLES     un pre-enregistrement modifie apres coup annule sa valeur de preuve. On
              verifie que chaque fichier scelle hache toujours a la valeur qu'il declare.
  SEUILS      les constantes scientifiques sont figees ici en dur. Si l'une bouge, la
              garde le dit, meme si le test passe — surtout si le test passe.
  PROVENANCE  du DERIVED ne devient jamais de l'OBSERVED, quelle que soit la pression
              sur le calendrier.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")

OBJECTIF = ("identifier, classer et suivre les wallets Hyperliquid les plus performants, "
            "avec un score statistique robuste et une confiance calibree")

# Marqueurs des branches DEFINITIVEMENT abandonnees. Une tache qui les evoque est
# refusee, meme formulee habilement.
BRANCHES_ABANDONNEES = frozenset({
    "liquidity sweep", "liquidity_sweep", "sweep", "edge de trading", "signal de trading",
    "maker/taker", "execution maker", "taker", "backtest de strategie", "tp/sl",
    "take profit", "stop loss", "bot de trading", "strategie d'execution",
    "recherche d'edge", "alpha", "meta-labeling", "triple barrier",
})

# Ce qui rapproche VRAIMENT du produit. Une tache doit toucher au moins un de ces themes.
THEMES_PRODUIT = frozenset({
    "wallet", "classement", "ranking", "score", "calibration", "observed", "derived",
    "quota", "collecte", "reconstruction", "segmentation", "confiance", "produit",
    "dashboard", "audit", "test", "etat", "budget", "orchestrateur", "garde",
})

# Constantes scientifiques FIGEES. Toute divergence est une alerte, pas un detail.
SEUILS_ATTENDUS = {
    "ht.gate.MIN_PAIRES_APPARIEES": 100,
    "ht.gate.MAX_TAUX_NON_RECONCILIABLE": 0.20,
    "ht.gate.MIN_CONCORDANCE_PNL": 0.90,
    "ht.gate.MAX_MAE_PNL_RELATIVE": 0.02,
    "ht.gate.MAX_ECART_TEMPS_MS": 60_000,
    "ht.gate.MAX_ECE_CERTIFIEE": 0.10,
    "ht.final_gate.MAX_PART_MEILLEUR_TRADE": 0.40,
    "ht.final_gate.MAX_DEGRADATION_RELATIVE": 0.50,
    "ht.final_gate.MAX_PART_FRAIS": 0.50,
    "ht.oos.MIN_PAR_BLOC": 50,
    "ht.calibration.MIN_OBS_CALIBRATION": 50,
    "ht.ranking.MIN_TRADES_FOR_RANKING": 30,
}

# Pre-enregistrements scelles : le fichier porte lui-meme son sha256.
FICHIERS_SCELLES = (
    ("specification_score_wallets.json", "sha256_du_contenu"),
    ("preenregistrement_calibration.json", "sha256"),
    ("preenregistrement_observed.json", "sha256"),
)


@dataclass
class Verdict:
    autorise: bool
    motifs: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.autorise

    def resume(self) -> str:
        t = "AUTORISE" if self.autorise else "REFUSE"
        return f"[{t}] " + (" | ".join(self.motifs) if self.motifs else "aucune objection")


# ------------------------------------------------------------------------- derive
def verifier_derive(objectif: str) -> Verdict:
    """La tache sert-elle le produit, et ne ramene-t-elle pas vers l'abandonne ?"""
    t = (objectif or "").lower()
    trouves = sorted(m for m in BRANCHES_ABANDONNEES if m in t)
    if trouves:
        return Verdict(False, [f"branche abandonnee evoquee : {', '.join(trouves)}"])
    if not any(m in t for m in THEMES_PRODUIT):
        return Verdict(False, ["aucun lien explicite avec le produit "
                               "(classement de wallets) : formuler la tache autrement "
                               "ou l'abandonner"])
    return Verdict(True, ["sert le produit"])


# ------------------------------------------------------------------------- scelles
def verifier_scelles(racine: str | None = None) -> Verdict:
    """Un pre-enregistrement modifie apres coup n'est plus une preuve."""
    r = racine or DATA
    motifs, ok = [], True
    for nom, cle in FICHIERS_SCELLES:
        p = os.path.join(r, nom)
        if not os.path.exists(p):
            motifs.append(f"{nom} : absent")
            continue
        try:
            d = json.load(open(p))
        except Exception as e:
            ok = False
            motifs.append(f"{nom} : illisible ({type(e).__name__})")
            continue
        declare = d.get(cle)
        if not declare:
            ok = False
            motifs.append(f"{nom} : aucun sceau {cle}")
            continue
        corps = json.dumps({k: v for k, v in d.items() if k != cle},
                           indent=1, ensure_ascii=True, sort_keys=True)
        calcule = hashlib.sha256(corps.encode()).hexdigest()
        if calcule != declare:
            ok = False
            motifs.append(f"{nom} : SCEAU ROMPU (declare {declare[:12]}…, "
                          f"calcule {calcule[:12]}…)")
        else:
            motifs.append(f"{nom} : intact")
    return Verdict(ok, motifs)


# ------------------------------------------------------------------------- seuils
def verifier_seuils() -> Verdict:
    """Les constantes scientifiques n'ont-elles pas bouge ?"""
    import importlib
    motifs, ok = [], True
    for chemin, attendu in SEUILS_ATTENDUS.items():
        mod, nom = chemin.rsplit(".", 1)
        try:
            v = getattr(importlib.import_module(mod), nom)
        except Exception as e:
            ok = False
            motifs.append(f"{chemin} : introuvable ({type(e).__name__})")
            continue
        if v != attendu:
            ok = False
            motifs.append(f"{chemin} : {v} au lieu de {attendu} — SEUIL DEPLACE")
    if ok:
        motifs.append(f"{len(SEUILS_ATTENDUS)} seuils conformes")
    return Verdict(ok, motifs)


# --------------------------------------------------------------------- provenance
def verifier_provenance(classification: str, usage: str) -> Verdict:
    """Du DERIVED ne certifie jamais. C'est la regle la plus simple et la plus violee."""
    from .schema import DERIVED, OBSERVED
    if usage == "certification" and classification != OBSERVED:
        return Verdict(False, [f"classification {classification} employee pour certifier : "
                               f"seul {OBSERVED} le peut"])
    return Verdict(True, [f"provenance {classification} coherente avec l'usage {usage}"])


# ------------------------------------------------------------------------- global
def controler(objectif: str, *, racine: str | None = None) -> Verdict:
    """Tous les controles. Un seul refus suffit a bloquer la tache."""
    parts = [verifier_derive(objectif), verifier_scelles(racine), verifier_seuils()]
    motifs = []
    for v in parts:
        motifs.extend(v.motifs)
    return Verdict(all(bool(v) for v in parts), motifs)
