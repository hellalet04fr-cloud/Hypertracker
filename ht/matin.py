#!/usr/bin/env python3
"""
HYPERTRACKER — cycle du matin.

Huit phases, dans l'ordre : DATA, DISCOVERY, EVALUATION, RANKING, LIFECYCLE,
ALERTS, REPORT, UI. Chacune journalise ce qu'elle a fait, ce qu'elle a decide et
pourquoi ; un futur lecteur doit pouvoir reprendre le travail depuis les seuls
fichiers persistants.

COUT HYPERTRACKER : ZERO. Toutes les sources du cycle sont gratuites — les
instantanes de carnet et les classements sont deja sur disque, la reconstruction
passe par l'API publique Hyperliquid. Le quota HyperTracker n'est pas depense
par le cycle quotidien ; il est verifie et reporte, jamais consomme sans decision
explicite. C'est ce qui permet au cycle de tourner tous les jours sans arbitrage.

    python -m ht.matin --dry-run     montre tout, n'ecrit rien, n'appelle rien
    python -m ht.matin               execute
    python -m ht.matin --limite 200  borne le nombre de wallets reevalues
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime

from . import alertes as A
from . import classement as CL
from . import decouverte as D
from . import quota as Q
from . import registre as R
from .lifecycle import (ARCHIVED, DISCOVERY, DONNEES_INSUFFISANTES, PROMETTEUR,
                        RANKED, etat_cible, qualifies_for_ranking)

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
SERIES = os.path.join(DATA, "series_wallets.json")
CLASSEMENT = os.path.join(DATA, "classement_wallets.json")
RAPPORT = os.path.join(DATA, "daily_report.json")

# Plafond de reevaluation par cycle. La reconstruction d'un wallet coute environ
# 4 requetes Hyperliquid ; a plusieurs milliers de wallets, tout reevaluer chaque
# matin serait long sans rien apporter — un wallet dont aucune donnee n'a bouge
# rend le meme score. D'ou le drapeau `sale` : on ne recalcule que le sale.
LIMITE_REEVALUATION = 400

# Budget de requetes Hyperliquid par cycle, pour la collecte de nouvelles series.
# Hyperliquid est gratuit mais limite en debit : la collecte est CADENCEE, sans
# aucune reprise agressive. Le budget porte sur le COUT, jamais sur le nombre de
# candidats a trouver — une regle d'arret indexee sur la performance biaiserait
# la selection, ce que le protocole de criblage s'interdit explicitement.
BUDGET_REQUETES = 150


def _horodatage() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def cycle_id() -> str:
    return "cycle-" + datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


class Cycle:
    """Etat d'un passage. En dry-run, rien n'est ecrit ni appele."""

    def __init__(self, dry_run: bool = False, limite: int = LIMITE_REEVALUATION,
                 budget_requetes: int = BUDGET_REQUETES):
        self.dry = dry_run
        self.limite = limite
        self.budget_requetes = budget_requetes
        self.id = cycle_id()
        self.c = R.connexion()
        self.debut = time.time()
        self.phases: dict[str, dict] = {}
        self.evenements: list[dict] = []
        self.erreurs: list[str] = []

    # -- journal ------------------------------------------------------------
    def note(self, phase: str, tache: str, **kw):
        if not self.dry:
            R.journaliser(self.c, self.id, phase, tache, **kw)

    def phase(self, nom: str, **bilan):
        self.phases[nom] = bilan
        return bilan

    # -- PHASE 1 : DATA -----------------------------------------------------
    def p1_data(self) -> dict:
        """Etat des sources et du budget. On mesure avant de depenser."""
        q = Q.bilan()
        frais = os.path.exists(SERIES) and os.path.getmtime(SERIES) > time.time() - 86400 * 2
        b = {"quota_epuise": Q.epuise(), "quota": q,
             "series_presentes": os.path.exists(SERIES),
             "series_fraiches": bool(frais),
             "classement_present": os.path.exists(CLASSEMENT),
             "requetes_hypertracker_prevues": 0}
        if b["quota_epuise"]:
            self.evenements.append({
                "categorie": A.QUOTA_WARNING,
                "message": "quota HyperTracker epuise : le cycle n'en depend pas, "
                           "aucune collecte payante n'est tentee"})
        self.note("DATA", "etat_sources", resultat=json.dumps(b), decision="poursuivre",
                  raison="le cycle ne depense aucun quota HyperTracker")
        return self.phase("DATA", **b)

    # -- PHASE 2 : DISCOVERY ------------------------------------------------
    def p2_discovery(self, limite_carnet: int | None = None) -> dict:
        b = D.decouvrir(self.c, limite_carnet=limite_carnet, dry_run=self.dry,
                        cycle_id=self.id)
        self.decouverts = b.get("adresses", [])
        for src, e in b.get("erreurs", {}).items():
            self.erreurs.append(f"decouverte/{src}: {e}")
            self.evenements.append({"categorie": A.DATA_FAILURE,
                                    "message": f"source de decouverte « {src} » indisponible : {e}"})
        self.note("DISCOVERY", "balayage_sources", resultat=json.dumps(b),
                  decision=f"{b['nouveaux']} nouveaux",
                  raison="sources locales, aucune requete")
        return self.phase("DISCOVERY", **b)

    # -- PHASE 2b : COLLECTE ------------------------------------------------
    def p2b_collecte(self, budget: int) -> dict:
        """Acquiert la serie de quelques wallets DISCOVERY encore inconnus.

        SANS CETTE PHASE, LA DECOUVERTE NE SERT A RIEN. On peut decouvrir
        31 000 adresses dans les carnets ; tant qu'aucune serie n'est collectee,
        aucune ne peut etre evaluee, donc aucune ne peut devenir RANKED. C'est
        ici que le systeme devient reellement autonome.

        Le cout est borne par un BUDGET DE REQUETES, jamais par un nombre de
        candidats a trouver : une regle d'arret qui porterait sur la performance
        biaiserait la selection. On depense au plus `budget` requetes Hyperliquid
        et on s'arrete, quel que soit le resultat.

        Le triage coute UNE requete et ecarte l'essentiel : un wallet dont le
        carnet ne montre pas assez de fills n'est pas reconstruit. Seuls les
        survivants paient la pagination complete.
        """
        b = {"budget": budget, "requetes": 0, "examines": 0, "series_ajoutees": 0,
             "ecartes_triage": 0, "erreurs": 0, "refuses_budget": 0}
        if budget <= 0:
            return self.phase("COLLECTE", **b, raison="budget nul")

        series = json.load(open(SERIES)) if os.path.exists(SERIES) else {}
        connues = set(series)
        cibles = [a for a in R.a_reevaluer(self.c, None) if a not in connues][:budget]
        b["candidats"] = len(cibles)
        if self.dry:
            COUT_MAX = 6
            tenables = max(0, budget // COUT_MAX)
            b["refuses_budget"] = max(0, len(cibles) - tenables)
            return self.phase("COLLECTE", **b, action="simule",
                              requetes_estimees=min(budget, len(cibles) * COUT_MAX),
                              tenables=tenables)

        from . import hl_public as HL
        from . import reconstruct as RC
        from . import screening as SC
        perp = lambda co: ":" not in co and "/" not in co

        # Cout maximal d'un wallet : 1 requete de triage + 5 pages de pagination.
        # On n'engage un wallet que si le PIRE cas tient encore dans le budget —
        # verifier apres coup laissait le depassement se produire (mesure : 65
        # requetes pour un budget de 60). Preferer zero requete inutile a une.
        COUT_MAX = 6
        for a in cibles:
            if b["requetes"] + COUT_MAX > budget:
                # REFUS PROPRE, ET TRACE. Un budget qui s'epuise en silence est
                # indistinguable d'une file d'attente vide : le rapport du matin
                # dirait « rien a collecter » alors qu'il reste tout a faire.
                b["refuses_budget"] = len(cibles) - b["examines"]
                self.note("COLLECTE", "refus_budget",
                          cout_estime=COUT_MAX, cout_reel=0, decision="refuse",
                          raison=f"budget {budget} epuise a {b['requetes']}, "
                                 f"{b['refuses_budget']} wallet(s) reportes")
                break
            try:
                sonde, fills = SC.trier(a)
                b["requetes"] += 1
                b["examines"] += 1
                if not sonde.passe_triage:
                    b["ecartes_triage"] += 1
                    R.marquer_sale(self.c, [a], False)
                    continue
                if not sonde.sous_plafond:
                    fills = HL.user_fills_by_time(a, start_ms=0, pages_max=5)
                    b["requetes"] += 5
                rec = RC.reconstruire_wallet(a, [f for f in fills if perp(f["coin"])])
                RC.appliquer_convention_nette(rec.trades)
                series[a] = [{"pnl": t.realizedPnlUsd, "fee": t.feeUsd,
                              "open": t.openTime, "close": t.closeTime, "coin": t.coin}
                             for t in rec.trades
                             if not t.tronque and not t.position_ouverte]
                b["series_ajoutees"] += 1
                R.majw(self.c, a, derniere_collecte=R.maintenant(),
                       dernier_cycle=self.id)
            except Exception as e:
                b["erreurs"] += 1
                self.note("COLLECTE", "echec", adresse=a, erreur=f"{type(e).__name__}: {e}")
                R.marquer_sale(self.c, [a], False)
        if b["series_ajoutees"]:
            json.dump(series, open(SERIES, "w"), separators=(",", ":"))
        self.c.commit()
        self.note("COLLECTE", "acquisition", resultat=json.dumps(b),
                  cout_reel=b["requetes"], cout_estime=budget,
                  raison="Hyperliquid public, aucun quota HyperTracker")
        return self.phase("COLLECTE", **b)

    # -- PHASE 3 : EVALUATION ----------------------------------------------
    def p3_evaluation(self) -> dict:
        """Metriques des wallets dont on possede deja la serie.

        INCREMENTAL. On n'evalue que ce qui est marque sale, et on ne fabrique
        rien : un wallet decouvert dont on n'a aucune serie reste DISCOVERY sans
        metrique. Aller chercher sa serie coute des requetes Hyperliquid ; cette
        collecte est une phase separee, bornee, et non declenchee ici.
        """
        series = json.load(open(SERIES)) if os.path.exists(SERIES) else {}
        base = CL.base_depuis_series(series)
        sales = R.a_reevaluer(self.c, self.limite)
        evalues, sans_serie = 0, 0
        self.metriques: dict[str, dict] = {}
        for a in sales:
            m = base.get(a)
            if m is None:
                sans_serie += 1
                continue
            self.metriques[a] = dict(m)
            evalues += 1
        # les wallets deja classes restent evaluables meme s'ils ne sont pas sales
        for a, m in base.items():
            self.metriques.setdefault(a, dict(m))
        b = {"marques_sales": len(sales), "evalues": evalues,
             "sans_serie_locale": sans_serie, "avec_metriques": len(self.metriques)}
        self.note("EVALUATION", "metriques_locales", resultat=json.dumps(b),
                  cout_reel=0, raison="series deja sur disque, aucune requete")
        return self.phase("EVALUATION", **b)

    # -- PHASE 4 : RANKING --------------------------------------------------
    def p4_ranking(self) -> dict:
        series = json.load(open(SERIES)) if os.path.exists(SERIES) else {}
        ancien = json.load(open(CLASSEMENT)) if os.path.exists(CLASSEMENT) else None
        self.ancien = {w["a"]: w for w in (ancien or {}).get("classement", [])}
        for i, w in enumerate((ancien or {}).get("classement", []), 1):
            self.ancien[w["a"]]["rang"] = i
        doc = CL.reporter_p_cal(CL.calculer(series), ancien)
        self.doc = doc
        self.rangs = {w["a"]: i for i, w in enumerate(doc["classement"], 1)}
        self.nouveau = {w["a"]: w for w in doc["classement"]}
        if not self.dry:
            json.dump(doc, open(CLASSEMENT, "w"), indent=1)
        b = {"classes": doc["n"], "m": round(doc["m"], 6), "tau": round(doc["tau"], 6),
             "sans_probabilite_calibree": doc.get("sans_p_cal", 0)}
        self.note("RANKING", "classement", resultat=json.dumps(b),
                  decision="ecrit" if not self.dry else "simule",
                  raison="a priori reestime sur la population complete")
        return self.phase("RANKING", **b)

    # -- PHASE 5 : LIFECYCLE ------------------------------------------------
    def p5_lifecycle(self) -> dict:
        promus, archives, reactives, maintenus, points = [], [], [], 0, 0
        for a, w in self.nouveau.items():
            row = R.wallet(self.c, a)
            statut = row["statut"] if row else DISCOVERY
            watch = bool(row["watch"]) if row else False
            m = dict(w)
            m["rang"] = self.rangs.get(a)
            v = qualifies_for_ranking(m)
            cible, raison = etat_cible(m, statut, watch=watch)
            if not self.dry:
                if row is None:
                    R.enregistrer_decouverte(self.c, a, "classement")
                R.majw(self.c, a, n_trades=m.get("n"), score=m.get("score"),
                       rang=m.get("rang"), confiance=m.get("confiance"),
                       qualite=m.get("qualite"), classe=v.classe, sale=0,
                       evalue_le=R.maintenant())
            if cible != statut:
                fiche = {"a": a, "avant": statut, "apres": cible, "raison": raison,
                         "score": m.get("score"), "rang": m.get("rang"),
                         "classe": v.classe}
                (promus if cible == RANKED else archives).append(fiche)
                if not self.dry:
                    R.transition(self.c, a, cible, raison, metriques=m,
                                 cycle_id=self.id)
                self.note("LIFECYCLE", "transition", adresse=a, statut_avant=statut,
                          statut_apres=cible, decision=cible, raison=raison)
                if cible == ARCHIVED:
                    self.evenements.append({
                        "categorie": A.WALLET_ARCHIVED, "adresse": a,
                        "message": f"retire du classement — {raison}",
                        "details": {"raison": raison, "dernier_score": m.get("score")}})
                elif statut == ARCHIVED:
                    # REACTIVATION. Distincte d'une premiere qualification : ce
                    # wallet avait deja ete retire, et il vient de redemontrer
                    # qu'il satisfait les criteres.
                    reactives.append(fiche)
                    self.evenements.append({
                        "categorie": A.REACTIVATED, "adresse": a,
                        "message": f"revient au classement au rang {m.get('rang')}",
                        "details": {"rang": m.get("rang"), "score": m.get("score")}})
                else:
                    self.evenements.append({
                        "categorie": A.NEW_RANKED, "adresse": a,
                        "message": f"qualifie — {v.classe}, rang {m.get('rang')}",
                        "details": {"rang": m.get("rang"), "score": m.get("score"),
                                    "classe": v.classe, "n": m.get("n")}})
            else:
                maintenus += 1
                if not self.dry and statut == RANKED:
                    # Point d'historique CONDITIONNEL : voir registre.enregistrer_point.
                    # Ecrire a chaque cycle produisait 195 lignes sans information.
                    if R.enregistrer_point(self.c, a, RANKED, "maintenu", m,
                                           cycle_id=self.id):
                        points += 1

        # wallets connus qui ne sont PLUS dans le classement calcule : leur serie
        # ne suffit plus. Ils sont archives avec le motif adequat, jamais effaces.
        for row in R.par_statut(self.c, RANKED):
            a = row["adresse"]
            if a in self.nouveau or row["watch"]:
                continue
            raison = "insufficient current data"
            archives.append({"a": a, "avant": RANKED, "apres": ARCHIVED,
                             "raison": raison, "score": row["score"],
                             "rang": row["rang"], "classe": None})
            if not self.dry:
                R.transition(self.c, a, ARCHIVED, raison, cycle_id=self.id)
            self.evenements.append({"categorie": A.WALLET_ARCHIVED, "adresse": a,
                                    "message": f"retire du classement — {raison}"})
        if not self.dry:
            self.c.commit()
        b = {"promus": len(promus), "archives": len(archives),
             "reactives": len(reactives), "maintenus": maintenus,
             "points_historique": points,
             "detail_promus": promus[:50], "detail_archives": archives[:50],
             "detail_reactives": reactives[:50]}
        return self.phase("LIFECYCLE", **b)

    # -- PHASE 6 : ALERTS ---------------------------------------------------
    def p6_alerts(self) -> dict:
        for a, w in self.nouveau.items():
            w["rang"] = self.rangs.get(a)
            row = R.wallet(self.c, a)
            w["classe"] = row["classe"] if row and row["classe"] else \
                qualifies_for_ranking(w).classe
        self.evenements += A.comparer(self.ancien, self.nouveau,
                                      nouveaux_rangs=self.rangs,
                                      n_avant=len(self.ancien),
                                      n_apres=len(self.nouveau))
        self.evenements.append({
            "categorie": A.DAILY_COMPLETE,
            "message": f"cycle {self.id} termine",
            "cle": f"{A.DAILY_COMPLETE}|{self.id}"})
        retenues = 0 if self.dry else A.emettre(self.c, self.id, self.evenements)
        par_cat: dict[str, int] = {}
        for e in self.evenements:
            par_cat[e["categorie"]] = par_cat.get(e["categorie"], 0) + 1
        b = {"evenements": len(self.evenements), "retenues_apres_dedup": retenues,
             "par_categorie": par_cat}
        return self.phase("ALERTS", **b)

    # -- PHASE 7 : REPORT ---------------------------------------------------
    def p7_report(self) -> dict:
        n = R.compter(self.c)
        top = [{"rang": i, "a": w["a"], "score": round(w["score"], 1),
                "confiance": w["confiance"], "n": w["n"],
                "conc": round(w["conc"], 3) if w["conc"] is not None else None,
                "dd": round(w["dd"], 2), "pnl": round(w["pnl"], 2)}
               for i, w in enumerate(self.doc["classement"][:20], 1)]

        def mouvements(cat):
            return [{"a": e["adresse"], "message": e["message"],
                     "details": e.get("details")}
                    for e in self.evenements if e["categorie"] == cat][:20]

        # WATCH : les prometteurs, insuffisamment documentes. Ils ne sont ni
        # classes ni rejetes — ce sont ceux qu'il faut regarder revenir.
        surveiller = []
        for a2, w2 in self.nouveau.items():
            row2 = R.wallet(self.c, a2)
            if row2 and row2["statut"] == RANKED:
                continue
            v2 = qualifies_for_ranking(w2)
            if v2.classe in (PROMETTEUR, DONNEES_INSUFFISANTES):
                surveiller.append({"a": a2, "classe": v2.classe,
                                   "score": round(w2["score"], 1),
                                   "n": w2["n"], "manque": (v2.manques or v2.indetermines)[:1]})
        surveiller.sort(key=lambda x: -x["score"])

        rapport = {
            "cycle_id": self.id,
            "horodatage": _horodatage(),
            "mode": "dry-run" if self.dry else "reel",
            # NEW TODAY = wallets DECOUVERTS ce cycle. Distinct de NEW RANKED.
            "new_today": [{"a": x, "message": "découvert ce cycle"}
                          for x in getattr(self, "decouverts", [])[:20]],
            "new_ranked": mouvements(A.NEW_RANKED),
            "reactivated": mouvements(A.REACTIVATED),
            "watch": surveiller[:20],
            "remarquables": mouvements(A.NEW_WALLET),
            "top_movers": mouvements(A.RANK_UP),
            "declining": mouvements(A.RANK_DOWN),
            "archived": [{"a": x["a"], "raison": x["raison"],
                          "dernier_score": x.get("score"), "dernier_rang": x.get("rang")}
                         for x in self.phases.get("LIFECYCLE", {}).get("detail_archives", [])],
            "top20": top,
            "data_health": {
                "wallets_analyses": self.phases.get("EVALUATION", {}).get("avec_metriques", 0),
                "discovery": n.get(DISCOVERY, 0),
                "ranked": n.get(RANKED, 0),
                "archived": n.get(ARCHIVED, 0),
                "watchlist": n.get("watch", 0),
                "a_reevaluer": n.get("sales", 0),
                "series_fraiches": self.phases.get("DATA", {}).get("series_fraiches"),
                "sans_probabilite_calibree":
                    self.phases.get("RANKING", {}).get("sans_probabilite_calibree", 0),
                "erreurs_collecte": self.erreurs,
                "quota": self.phases.get("DATA", {}).get("quota"),
                "requetes_hypertracker_utilisees": 0,
                "requetes_hyperliquid_consommees":
                    self.phases.get("COLLECTE", {}).get("requetes", 0),
                "budget_requetes": self.budget_requetes,
                "budget_restant": max(0, self.budget_requetes
                                      - self.phases.get("COLLECTE", {}).get("requetes", 0)),
                "refuses_budget": self.phases.get("COLLECTE", {}).get("refuses_budget", 0),
                "series_locales": self.phases.get("COLLECTE", {}).get("series_ajoutees", 0),
                "decouverts_ce_cycle": self.phases.get("DISCOVERY", {}).get("nouveaux", 0),
            },
            "system_health": {
                "phases_executees": list(self.phases),
                "erreurs": self.erreurs,
                "duree_s": round(time.time() - self.debut, 1),
                "derniere_synchronisation": _horodatage(),
            },
            "blocages": self._blocages(),
            "prochaine_action": self._prochaine_action(),
        }
        if not self.dry:
            # ENCODAGE EXPLICITE. `ensure_ascii=False` conserve les accents dans le
            # fichier, mais `open()` sans encodage retombe sur la page de code du
            # systeme — cp1252 sous Windows. Le rapport devenait alors illisible
            # pour tout lecteur UTF-8, et la preparation de l'application echouait
            # sur le premier caractere accentue.
            with open(RAPPORT, "w", encoding="utf8") as f:
                json.dump(rapport, f, ensure_ascii=False, indent=1)
        self.rapport = rapport
        return self.phase("REPORT", chemin=RAPPORT if not self.dry else None,
                          new_today=len(rapport["new_today"]),
                          new_ranked=len(rapport["new_ranked"]),
                          reactivated=len(rapport["reactivated"]),
                          watch=len(rapport["watch"]),
                          archived=len(rapport["archived"]))

    def _prochaine_action(self) -> str:
        """Une seule, deduite de l'etat reel. Pas une liste de voeux."""
        co = self.phases.get("COLLECTE", {})
        if co.get("refuses_budget"):
            return (f"{co['refuses_budget']} wallet(s) attendent une collecte : "
                    f"relancer avec --budget plus eleve, ou attendre le cycle suivant")
        if self.erreurs:
            return f"traiter {len(self.erreurs)} erreur(s) de cycle"
        if self.phases.get("RANKING", {}).get("sans_probabilite_calibree"):
            return ("autoriser ou refuser explicitement le rejeu du recalibrage "
                    "isotonique (voir blocages)")
        n = R.compter(self.c)
        if n.get("sales", 0):
            return f"{n['sales']} wallet(s) restent a evaluer : laisser les cycles avancer"
        return "aucune action requise"

    def _blocages(self) -> list[dict]:
        """Ce que le systeme ne PEUT PAS faire seul, et pourquoi. Un blocage tu
        devient une derive silencieuse au bout de quelques cycles."""
        b = []
        sans = self.phases.get("RANKING", {}).get("sans_probabilite_calibree", 0)
        if sans:
            b.append({
                "sujet": "probabilite calibree",
                "portee": f"{sans} wallet(s)",
                "cause": "le modele isotonique ajuste n'a jamais ete persiste : seuls "
                         "ses indicateurs le sont (ECE 0.0647). Impossible de calibrer "
                         "un wallet absent du lot d'origine.",
                "action_interdite": "reajuster l'isotonique sur la population du jour "
                                    "serait une decision scientifique (la calibration "
                                    "est pre-enregistree et scellee)",
                "demande": "autorisation humaine explicite pour rejouer le recalibrage",
            })
        return b

    # -- PHASE 8 : UI -------------------------------------------------------
    def p8_ui(self) -> dict:
        """Regenere les donnees consommees par l'application, puis l'application.

        L'audit d'authenticite est execute juste apres : si un compteur n'est pas
        a zero, le cycle le signale au lieu de publier une interface dont on ne
        sait pas d'ou viennent les chiffres.
        """
        if self.dry:
            return self.phase("UI", action="simule",
                              commandes=["app.prepare_donnees", "app.generer_app",
                                         "app.audit_donnees"])
        import subprocess
        import sys
        etapes, ok = [], True
        for mod in ("app.prepare_donnees", "app.generer_app", "app.audit_donnees"):
            r = subprocess.run([sys.executable, "-m", mod], capture_output=True,
                               text=True, encoding="utf8", errors="replace",
                               cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            etapes.append({"module": mod, "code": r.returncode,
                           "sortie": (r.stdout or "").strip()[-400:]})
            if r.returncode != 0:
                ok = False
                self.erreurs.append(f"{mod} : code {r.returncode}")
                self.evenements.append({
                    "categorie": A.DATA_FAILURE,
                    "message": f"{mod} a echoue (code {r.returncode}) — interface non publiee"})
                break
        self.note("UI", "regeneration", resultat=json.dumps(etapes)[:900],
                  decision="publie" if ok else "bloque")
        return self.phase("UI", ok=ok, etapes=etapes)

    # -- orchestration ------------------------------------------------------
    def executer(self, limite_carnet: int | None = None) -> dict:
        if not self.dry:
            R.ouvrir_cycle(self.c, self.id, "reel")
        self.p1_data()
        self.p2_discovery(limite_carnet)
        self.p2b_collecte(self.budget_requetes)
        self.p3_evaluation()
        self.p4_ranking()
        self.p5_lifecycle()
        self.p6_alerts()
        self.p7_report()
        self.p8_ui()
        if not self.dry:
            R.fermer_cycle(self.c, self.id, "OK" if not self.erreurs else "PARTIEL",
                           json.dumps(self.phases, default=str)[:4000])
            self.c.commit()
        return self.phases


def afficher(cy: Cycle) -> None:
    p = cy.phases
    t = "DRY-RUN — aucune ecriture, aucune requete" if cy.dry else "EXECUTION REELLE"
    print(f"\n{'=' * 68}\nHYPERTRACKER — CYCLE DU MATIN   {cy.id}\n{t}\n{'=' * 68}")
    d = p.get("DISCOVERY", {})
    print(f"  DISCOVERY   {d.get('nouveaux', 0):>6} nouveaux | "
          f"{d.get('deja_connus', 0)} deja connus | {d.get('par_source', {})}")
    co = p.get("COLLECTE", {})
    req = co.get("requetes_estimees") if cy.dry else co.get("requetes", 0)
    print(f"  COLLECTE    {co.get('series_ajoutees', 0):>6} series | "
          f"{req or 0} requetes Hyperliquid (budget {co.get('budget', 0)}) | "
          f"{co.get('candidats', 0)} candidats | {co.get('ecartes_triage', 0)} ecartes")
    e = p.get("EVALUATION", {})
    print(f"  EVALUATION  {e.get('evalues', 0):>6} evalues | "
          f"{e.get('sans_serie_locale', 0)} sans serie locale")
    r = p.get("RANKING", {})
    print(f"  RANKING     {r.get('classes', 0):>6} classes | m={r.get('m')} tau={r.get('tau')}")
    l = p.get("LIFECYCLE", {})
    print(f"  LIFECYCLE   {l.get('promus', 0):>6} promus | {l.get('archives', 0)} archives"
          f" | {l.get('reactives', 0)} reactives | {l.get('maintenus', 0)} maintenus"
          f" | {l.get('points_historique', 0)} points d'historique")
    a = p.get("ALERTS", {})
    print(f"  ALERTS      {a.get('evenements', 0):>6} evenements | "
          f"{a.get('retenues_apres_dedup', 0)} retenues | {a.get('par_categorie', {})}")
    r2 = p.get("REPORT", {})
    print(f"  REPORT      decouverts={r2.get('new_today', 0)} "
          f"qualifies={r2.get('new_ranked', 0)} reactives={r2.get('reactivated', 0)} "
          f"archives={r2.get('archived', 0)} a_surveiller={r2.get('watch', 0)}")
    u = p.get("UI", {})
    print(f"  UI          {u.get('action') or ('publie' if u.get('ok') else 'BLOQUE')}")
    n = R.compter(cy.c)
    print(f"\n  wallets : DISCOVERY {n.get(DISCOVERY, 0)} | RANKED {n.get(RANKED, 0)} | "
          f"ARCHIVED {n.get(ARCHIVED, 0)} | watchlist {n.get('watch', 0)}")
    print(f"\n  prochaine action : {getattr(cy, 'rapport', {}).get('prochaine_action', '—')}")
    if cy.erreurs:
        print("\n  ERREURS :")
        for x in cy.erreurs:
            print("    -", x)
    for b in getattr(cy, "rapport", {}).get("blocages", []):
        print(f"\n  BLOCAGE — {b['sujet']} ({b['portee']})")
        print(f"    cause   : {b['cause']}")
        print(f"    demande : {b['demande']}")
    print(f"\n  duree {time.time() - cy.debut:.1f}s | requetes HyperTracker : 0\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cycle quotidien HyperTracker")
    ap.add_argument("--dry-run", action="store_true",
                    help="montre tout, n'ecrit rien, n'appelle rien")
    ap.add_argument("--limite", type=int, default=LIMITE_REEVALUATION,
                    help="plafond de wallets reevalues")
    ap.add_argument("--limite-carnet", type=int, default=None,
                    help="plafond d'adresses lues dans les carnets (mise au point)")
    ap.add_argument("--budget", type=int, default=BUDGET_REQUETES,
                    help="budget de requetes Hyperliquid pour la collecte de series")
    a = ap.parse_args(argv)
    cy = Cycle(dry_run=a.dry_run, limite=a.limite, budget_requetes=a.budget)
    try:
        cy.executer(limite_carnet=a.limite_carnet)
    finally:
        afficher(cy)
        cy.c.close()
    return 1 if cy.erreurs else 0


if __name__ == "__main__":
    raise SystemExit(main())
