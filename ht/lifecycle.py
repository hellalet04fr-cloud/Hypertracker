#!/usr/bin/env python3
"""
Cycle de vie d'un wallet : qualification, promotion, archivage.

AUCUN SEUIL N'EST INVENTE ICI. Les quatre criteres de candidature sont ceux,
pre-enregistres, de `ht.screening` — les memes qui ont selectionne la population
actuelle. Les trois criteres de qualite de donnees sont ceux de `ht.classement`.
Ce module ne fait que les appliquer de facon deterministe et les nommer.

    ht.screening.MIN_TRADES         = 30     plancher de trades clos
    ht.screening.MIN_JOURS          = 130.0  etendue d'historique
    ht.screening.MAX_CONCENTRATION  = 0.40   part du plus gros trade
    ht.screening.MAX_TRONCATURE     = 0.20   part de trades non reconstruits

Il n'existe volontairement aucune regle du type « score > 80 = performant ». Le
score ne participe PAS a la qualification : il classe des wallets deja qualifies.
Faire entrer le score dans le critere d'entree reviendrait a selectionner sur la
performance, donc a fabriquer un classement de survivants.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .classement import MAX_CONC as QUALITE_MAX_CONC
from .classement import MIN_JOURS as QUALITE_MIN_JOURS
from .classement import MIN_TRADES_FIABLE
from .registre import ARCHIVED, DISCOVERY, RANKED
from .screening import MAX_CONCENTRATION, MAX_TRONCATURE, MIN_JOURS, MIN_TRADES

# Verdicts de qualification
EXCELLENT = "EXCELLENT_CANDIDATE"
PROMETTEUR = "PROMISING"
DONNEES_INSUFFISANTES = "INSUFFICIENT_DATA"
REJETE = "REJECTED"

# Motifs d'archivage, en clair et stables : ils sont lus par l'interface.
RAISON_DONNEES = "insufficient current data"
RAISON_DEGRADATION = "performance deterioration"
RAISON_RETOUR = "requalified"


@dataclass
class Verdict:
    classe: str
    qualifie: bool
    raisons: list[str] = field(default_factory=list)
    manques: list[str] = field(default_factory=list)
    # Criteres que les donnees locales ne permettent NI de satisfaire NI de
    # refuter. Ils ne valent jamais « satisfait » par defaut, et ne peuvent
    # jamais motiver un archivage : on retire un wallet sur une preuve, pas sur
    # une absence de preuve.
    indetermines: list[str] = field(default_factory=list)

    @property
    def resume(self) -> str:
        s = f"{self.classe} : " + ("; ".join(self.raisons) or "aucun motif")
        if self.indetermines:
            s += " | non verifiable : " + "; ".join(self.indetermines)
        return s

    @property
    def refute(self) -> bool:
        """Un critere est-il DEFINITIVEMENT viole ? Seul cela justifie un retrait."""
        return bool(self.manques)


def _metrique(m: dict, cle: str, defaut=None):
    v = m.get(cle, defaut)
    return defaut if v is None else v


def qualifies_for_ranking(m: dict) -> Verdict:
    """LA fonction centrale. Deterministe : memes metriques, meme verdict.

    `m` porte les grandeurs deja calculees par le moteur : n, jours, conc,
    troncature, qualite. Une grandeur absente n'est jamais remplacee par une
    valeur favorable — elle compte comme non satisfaite et le dit.

    Quatre issues, dans un ordre qui a un sens :

      REJECTED             un critere STRUCTUREL est viole. La concentration et
                           le taux de troncature ne s'ameliorent pas en
                           attendant : un wallet dont le resultat tient a un seul
                           trade ne deviendra pas robuste avec le temps.
      INSUFFICIENT_DATA    il manque du volume ou de l'anciennete. Cela, le temps
                           le repare. Le wallet reste en observation.
      PROMISING            qualifie, mais la qualite de donnees n'est pas au
                           maximum. Il entre au classement et y sera signale
                           comme repose sur une preuve plus mince.
      EXCELLENT_CANDIDATE  qualifie et trois criteres de qualite sur trois.
    """
    raisons, manques, flou = [], [], []

    n = _metrique(m, "n", 0)
    conc = m.get("conc")

    # --- ANCIENNETE : deux grandeurs a ne pas confondre.
    # `jours_couverts` est celle sur laquelle ht.screening.MIN_JOURS a ete defini.
    # `jours` — l'ecart entre le premier et le dernier trade CLOS — est celle que
    # le classement conserve, et elle est structurellement PLUS PETITE : un wallet
    # peut avoir 200 jours de couverture et 106 jours entre deux fermetures.
    #
    # C'est donc une BORNE INFERIEURE. Un ecart >= 130 prouve le critere ; un
    # ecart < 130 ne le refute pas. Confondre les deux archiverait des wallets
    # sur une grandeur qui ne dit pas ce qu'on lui ferait dire — mesure sur la
    # population livree : 33 wallets sur 231.
    couv = m.get("jours_couverts")
    jours = _metrique(m, "jours", 0.0)
    anciennete_ok = False
    if couv is not None:
        if couv >= MIN_JOURS:
            anciennete_ok = True
        else:
            manques.append(f"{couv:.0f} jours couverts < {MIN_JOURS:.0f}")
    elif jours >= MIN_JOURS:
        anciennete_ok = True
    else:
        flou.append(f"anciennete : {jours:.0f} jours entre trades clos, borne "
                    f"inferieure des jours couverts, non concluant face a "
                    f"{MIN_JOURS:.0f}")

    # --- VOLUME. `n` est exact : aucune ambiguite possible.
    if n < MIN_TRADES:
        manques.insert(0, f"{n} trades clos < {MIN_TRADES}")
    if manques:
        return Verdict(DONNEES_INSUFFISANTES, False, manques, manques, flou)
    if n < MIN_TRADES:
        return Verdict(DONNEES_INSUFFISANTES, False, flou, [], flou)

    # --- TRONCATURE. Non recalculable depuis les series locales : elles ne
    # conservent que les trades clos non tronques, et pas le taux. Elle a
    # cependant ete verifiee A L'ENTREE par ht.screening, qui refuse au-dela de
    # MAX_TRONCATURE. Present dans les series => critere satisfait a la collecte.
    # On le declare tout de meme, plutot que de laisser un defaut favorable le
    # faire passer en silence.
    tronc = m.get("troncature")
    if tronc is None:
        flou.append(f"taux de troncature non recalculable localement "
                    f"(verifie < {MAX_TRONCATURE:.2f} a la collecte)")
    elif tronc > MAX_TRONCATURE:
        return Verdict(REJETE, False, [f"troncature {tronc:.2f} > {MAX_TRONCATURE:.2f}"],
                       [f"troncature {tronc:.2f} > {MAX_TRONCATURE:.2f}"], flou)

    # --- CONCENTRATION : exacte et refutable. Une violation ne se repare pas en
    # attendant — un resultat qui tient a un seul trade ne devient pas robuste.
    if conc is None:
        flou.append("concentration non calculable")
    elif conc > MAX_CONCENTRATION:
        d = [f"concentration {conc:.2f} > {MAX_CONCENTRATION:.2f}"]
        return Verdict(REJETE, False, d, d, flou)

    if not anciennete_ok:
        # rien n'est refute, mais rien n'est prouve non plus
        return Verdict(DONNEES_INSUFFISANTES, False, flou, [], flou)

    # --- qualifie. Reste a dire avec quelle epaisseur de preuve.
    qualite = _metrique(m, "qualite", None)
    if qualite is None:
        qualite = sum([n >= MIN_TRADES_FIABLE,
                       conc is not None and conc <= QUALITE_MAX_CONC,
                       jours >= QUALITE_MIN_JOURS])
    raisons.append(f"{n} trades clos sur {jours:.0f} jours")
    if conc is not None:
        raisons.append(f"concentration {conc:.2f}")
    if qualite >= 3:
        raisons.append("trois criteres de qualite sur trois")
        return Verdict(EXCELLENT, True, raisons, [], flou)
    reserves = [f"qualite de donnees {qualite}/3"]
    if n < MIN_TRADES_FIABLE:
        reserves.append(f"{n} trades < {MIN_TRADES_FIABLE} pour un decoupage hors "
                        f"echantillon en trois blocs")
    # Ces reserves ne sont PAS des manques : le wallet est qualifie, sa preuve est
    # seulement plus mince. Les ranger dans `manques` le rendrait archivable.
    return Verdict(PROMETTEUR, True, raisons + reserves, [], flou)


def doit_archiver(m: dict, *, watch: bool = False) -> tuple[bool, str]:
    """Un wallet RANKED merite-t-il encore sa place ?

    Le critere de conservation est exactement le critere d'entree : ce qui fait
    entrer fait rester. Un seuil de sortie plus laxiste creerait deux populations
    — les entrants et les tolerés — et le classement cesserait d'etre lisible.

    Un wallet SUIVI MANUELLEMENT n'est jamais archive automatiquement. L'utilisateur
    a exprime un interet ; le systeme n'a pas a le lui retirer pendant la nuit.
    """
    if watch:
        return False, "suivi manuellement : jamais archive automatiquement"
    v = qualifies_for_ranking(m)
    if v.qualifie:
        return False, v.resume
    # ON RETIRE SUR UNE PREUVE, PAS SUR UNE ABSENCE DE PREUVE. Un critere que les
    # donnees locales ne permettent pas de trancher laisse le wallet en place ; il
    # est signale dans le rapport pour qu'un humain decide, jamais archive en
    # silence pendant la nuit.
    if not v.refute:
        return False, ("maintenu : aucun critere refute, "
                       + "; ".join(v.indetermines or ["motif inconnu"]))
    raison = RAISON_DEGRADATION if v.classe == REJETE else RAISON_DONNEES
    return True, f"{raison} — " + "; ".join(v.manques)


def etat_cible(m: dict, statut_actuel: str, *, watch: bool = False) -> tuple[str, str]:
    """Etat vise pour ce wallet, et la raison. Ne touche a rien : decide seulement.

    Les transitions permises sont les quatre du cahier des charges, y compris le
    retour ARCHIVED -> RANKED, qui est automatique des que le wallet redevient
    qualifie.
    """
    v = qualifies_for_ranking(m)
    if statut_actuel == RANKED:
        part, raison = doit_archiver(m, watch=watch)
        return (ARCHIVED, raison) if part else (RANKED, v.resume)
    if v.qualifie:
        raison = RAISON_RETOUR if statut_actuel == ARCHIVED else v.resume
        return RANKED, raison
    # Un wallet ARCHIVE qui ne requalifie pas RESTE archive. Le renvoyer en
    # DISCOVERY effacerait son motif de retrait et sa date, c'est-a-dire
    # precisement ce qu'on veut pouvoir relire dans six mois.
    if statut_actuel == ARCHIVED:
        return ARCHIVED, v.resume
    return DISCOVERY, v.resume
