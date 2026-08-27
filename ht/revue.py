#!/usr/bin/env python3
"""
AGENTS DE REVUE — ils cherchent les defauts que les controles automatiques ne
peuvent pas voir, et proposent des corrections que rien n'accepte sans preuve.

POURQUOI DES AGENTS ALORS QU'IL Y A DEJA CINQ CONTROLES

`ht.verifier` verifie ce qu'on a PENSE a verifier. Un test compare une valeur a
une valeur attendue ; il ne remarque pas qu'un libelle ment, qu'une explication
contredit le chiffre au-dessus, ou qu'une metrique a ete inventee sous un nom
plausible. Ces defauts-la demandent du jugement. Tous les vrais defauts de ce
projet sont de cette famille : le gate comparait net contre brut sous le meme
nom de champ, la courbe finissait ailleurs que sur le PnL affiche a cote, le
seuil d'anciennete portait sur une grandeur qui n'etait pas la sienne.

TROIS GARDES, ET C'EST CE QUI REND LA CHOSE ACCEPTABLE

  1. AVANT   la consigne passe par ht.garde (deja fait par ht.delegation) : une
             instruction qui evoque une branche abandonnee n'est jamais envoyee.
  2. APRES   la reponse repasse par ht.garde avant d'etre lue.
  3. CONTRE  chaque constat est soumis a un REFUTEUR independant, instruit de
             chercher pourquoi le constat est FAUX. Un constat qui survit a sa
             refutation est retenu ; les autres sont jetes.

La troisieme garde est la plus importante. Un agent qui cherche des defauts en
trouve toujours : sans refutation, on remplace un produit mesure par une liste
d'opinions. Le projet s'est deja fait prendre — deux « anomalies » d'audit
etaient des faux positifs, et une troisieme un vrai angle mort. Il a fallu les
distinguer une par une.

AUCUNE CORRECTION N'EST APPLIQUEE AUTOMATIQUEMENT. Les revues sont en lecture
seule. Une correction se propose, se lit, et se verifie par `ht.verifier` avant
d'etre acceptee — c'est-a-dire par un humain.

    python -m ht.revue                 les cinq lentilles
    python -m ht.revue --lentille ui
    python -m ht.revue --sans-refutation      (deconseille, pour mise au point)
"""
from __future__ import annotations

import argparse
import json
import os
import time

from . import delegation as DEL

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
JOURNAL = os.path.join(DATA, "revues.json")

# Format impose a chaque agent. Sans lui, on recupere de la prose qu'il faut
# relire ; avec lui, des constats qu'on peut trier.
FORMAT = """
Rends UNIQUEMENT une liste de constats, un par bloc, dans ce format exact :

CONSTAT: <une phrase, le defaut>
FICHIER: <chemin:ligne>
PREUVE: <ce qu'on observe, cite ou mesure — pas une impression>
EFFET: <ce que l'utilisateur voit de faux, ou ce qui casse>
CORRECTION: <la modification minimale>
---

Si tu ne trouves rien de solide, ecris exactement : AUCUN CONSTAT.
Ne signale JAMAIS un defaut que tu n'as pas verifie dans le code ou les donnees.
Une reformulation de style n'est pas un constat.
"""

LENTILLES = {
    "donnees": (
        "verifier qu'aucune donnee affichee du classement de wallets n'est fabriquee",
        """Cherche dans app/ et ht/ toute valeur AFFICHEE qui ne remonte pas a une
mesure reelle : une valeur par defaut qui remplace une donnee absente, un zero
mis a la place d'un None, une moyenne substituee, un champ recopie sous un autre
nom, une unite implicite qui change le sens. Le projet exige N/D partout ou la
donnee n'existe pas. Lis app/prepare_donnees.py et app/generer_app.py.
Procede par recherche ciblee — grep sur les motifs pertinents — plutot que par lecture integrale : app/generer_app.py fait 1 800 lignes."""),
    "science": (
        "verifier que le score des wallets respecte ses regles scientifiques",
        """Cherche toute entorse aux invariants : un seuil recopie au lieu d'etre
importe, une metrique recalculee differemment de sa definition d'origine, une
grandeur DERIVED presentee comme OBSERVED, un critere de qualification qui
utiliserait le score. Compare ht/lifecycle.py et ht/classement.py aux seuils de
ht/screening.py et ht/garde.py. Ne propose AUCUN changement de seuil.
Procede par recherche ciblee — grep sur les motifs pertinents — plutot que par lecture integrale : app/generer_app.py fait 1 800 lignes."""),
    "coherence": (
        "verifier que les libelles du classement de wallets disent ce que les valeurs sont",
        """Cherche les endroits ou le TEXTE contredit le CHIFFRE : un libelle qui
nomme une grandeur pour une autre, une unite absente ou fausse, une periode non
precisee, deux grandeurs differentes portant le meme mot. Le projet a deja eu
« confiance 30 % — confiance elevee » pour deux grandeurs distinctes. Lis les
libelles de app/generer_app.py et confronte-les aux champs de app_data.json.
Procede par recherche ciblee — grep sur les motifs pertinents — plutot que par lecture integrale : app/generer_app.py fait 1 800 lignes."""),
    "ui": (
        "verifier que la fiche wallet n'affiche rien de coupe ni de trompeur",
        """Cherche dans le CSS et le balisage de app/generer_app.py ce qui peut
tronquer ou masquer une MESURE : text-overflow sur une valeur, white-space
nowrap sans largeur garantie, un conteneur flex sans min-width:0, un champ
supprime par media query qui n'est pas optionnel, un etat vide manquant. Le
projet tolere de tronquer une ETIQUETTE, jamais une mesure.
Procede par recherche ciblee — grep sur les motifs pertinents — plutot que par lecture integrale : app/generer_app.py fait 1 800 lignes."""),
    "regression": (
        "verifier qu'une fonctionnalite du classement de wallets n'a pas disparu",
        """Compare l'interface actuelle (app/generer_app.py) a l'historique git
recent. Cherche ce qui EXISTAIT et n'existe plus alors que la donnee est
toujours chargee : un ecran retire, une action supprimee, un champ qui n'est
plus affiche. Utilise `git log --oneline` et `git show`."""),
}

REFUTATION = """
Voici un constat produit par un autre agent sur le depot HyperTracker.

{constat}

Ta tache est de le REFUTER. Va lire le code et les donnees concernes, puis
reponds par UNE SEULE LIGNE :

REFUTE: <pourquoi le constat est faux, incomplet, ou deja traite ailleurs>
ou
CONFIRME: <ce que tu as verifie toi-meme qui le rend certain>

Par defaut, REFUTE. Ne confirme que si tu as vu de tes propres yeux, dans le
code, ce que le constat affirme. Un constat plausible mais non verifie est un
constat refute.
"""


def _constats(texte: str) -> list[dict]:
    """Decoupe la reponse en constats structures. Ce qui ne suit pas le format
    est ignore : on prefere perdre un constat mal ecrit qu'en inventer un."""
    if not texte or "AUCUN CONSTAT" in texte.upper():
        return []
    out = []
    for bloc in texte.split("---"):
        d = {}
        for ligne in bloc.splitlines():
            for cle in ("CONSTAT", "FICHIER", "PREUVE", "EFFET", "CORRECTION"):
                if ligne.strip().upper().startswith(cle + ":"):
                    d[cle.lower()] = ligne.split(":", 1)[1].strip()
        if d.get("constat") and d.get("preuve"):
            out.append(d)
    return out


# Budgets de tours, MESURES. Une revue doit LIRE avant de conclure :
# app/generer_app.py fait 1 800 lignes, et les 12 tours par defaut de
# ht.delegation s'epuisaient sur la seule lecture — « Reached max turns (12) »,
# zero constat produit en 183 s. Le refuteur, lui, a une cible precise et en
# demande beaucoup moins.
TOURS_REVUE = 40
TOURS_REFUTATION = 14
DELAI_REVUE_S = 1500


def revoir(lentille: str, *, refuter: bool = True, verbeux: bool = True,
           tours: int = TOURS_REVUE) -> dict:
    objectif, consigne = LENTILLES[lentille]
    if verbeux:
        print(f"\n▌ LENTILLE « {lentille} » — {objectif}")
    d = DEL.deleguer(objectif, consigne + FORMAT, ecriture=False,
                     max_tours=tours, delai_s=DELAI_REVUE_S)
    if not d.accepte:
        if verbeux:
            print(f"  refusee : {d.motif}")
        return {"lentille": lentille, "refusee": d.motif, "constats": []}

    bruts = _constats(d.sortie or "")
    if verbeux:
        print(f"  {len(bruts)} constat(s) brut(s)")
    retenus = []
    for c in bruts:
        if not refuter:
            c["verdict"] = "non refute"
            retenus.append(c)
            continue
        txt = "\n".join(f"{k.upper()}: {v}" for k, v in c.items())
        r = DEL.deleguer("refuter un constat de revue sur le classement de wallets",
                         REFUTATION.format(constat=txt), ecriture=False,
                         max_tours=TOURS_REFUTATION, delai_s=DELAI_REVUE_S)
        rep = (r.sortie or "").strip()
        confirme = r.accepte and rep.upper().startswith("CONFIRME")
        c["verdict"] = rep.splitlines()[0][:200] if rep else "sans reponse"
        if confirme:
            retenus.append(c)
        if verbeux:
            print(f"    {'RETENU ' if confirme else 'ecarte '} {c['constat'][:66]}")
    return {"lentille": lentille, "constats": retenus,
            "brut": len(bruts), "retenus": len(retenus)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agents de revue HyperTracker")
    ap.add_argument("--lentille", choices=sorted(LENTILLES))
    ap.add_argument("--sans-refutation", action="store_true",
                    help="ne pas soumettre les constats a un refuteur (deconseille)")
    ap.add_argument("--tours", type=int, default=TOURS_REVUE,
                    help="budget de tours par agent de revue")
    a = ap.parse_args(argv)

    if not DEL.disponible():
        print("Claude Code headless indisponible : la revue par agents demande le CLI "
              "`claude` dans le PATH.")
        return 2

    lentilles = [a.lentille] if a.lentille else sorted(LENTILLES)
    print("=" * 72)
    print("REVUE PAR AGENTS — lecture seule, aucune correction appliquee")
    print("=" * 72)
    t0 = time.time()
    res = [revoir(l, refuter=not a.sans_refutation, tours=a.tours) for l in lentilles]

    tous = [c for r in res for c in r.get("constats", [])]
    print("\n" + "=" * 72)
    if tous:
        print(f"{len(tous)} CONSTAT(S) AYANT SURVECU A LEUR REFUTATION")
        for c in tous:
            print(f"\n  · {c['constat']}")
            print(f"    fichier    : {c.get('fichier', '—')}")
            print(f"    preuve     : {c.get('preuve', '—')[:150]}")
            print(f"    effet      : {c.get('effet', '—')[:150]}")
            print(f"    correction : {c.get('correction', '—')[:150]}")
    else:
        brut = sum(r.get("brut", 0) for r in res)
        print(f"AUCUN CONSTAT RETENU  ({brut} propose(s), tous refutes)")
    print("\nAucune correction n'a ete appliquee : une revue propose, "
          "`python -m ht.verifier` valide, un humain decide.")
    print(f"{time.time() - t0:.0f}s")
    print("=" * 72)

    try:
        h = json.load(open(JOURNAL, encoding="utf8")) if os.path.exists(JOURNAL) else []
        h.append({"horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"), "revues": res})
        with open(JOURNAL, "w", encoding="utf8") as f:
            json.dump(h[-30:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
