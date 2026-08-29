"""
Generateur du contrat web (web/src/domain/types.ts). Il DERIVE de l'affichable,
il ne decide rien : aucun score, aucun seuil, aucun protocole n'est touche ici.

Ce que ce fichier ajoute au generateur precedent tient en une phrase : la PREUVE.
L'ancienne page montrait un rang de 1 a 291 et rien pour le refuter. Deux audits
ont mesure que ce rang etait une fiction — largeur mediane de l'intervalle de
credibilite 56 points sur 100, 72 % des wallets classes perdent de l'argent,
Sharpe/trade median pire que le hasard. Le classement reste publie parce qu'il
est le materiau, mais chaque wallet porte desormais de quoi le contredire :
p-valeur de permutation, intervalle de bootstrap par blocs, autocorrelation,
Ljung-Box, Sharpe par moitie d'historique, cout des frais en unites de Sharpe,
part du meilleur trade, bascule sans lui, et le verdict de test multiple.

DECOUPAGE. La page precedente chargeait 1 003 ko d'un bloc pour afficher une
liste. Ici : meta.json et index.json pour la liste, un lot par prefixe d'adresse
pour le detail, daily.json pour le rapport de cycle.

LECTURE SEULE sur ht_data. Le seul fichier ecrit hors de web/public/data est
app_data.json, et il l'est par prepare_donnees.py lui-meme, qui en est
proprietaire : ce module l'importe pour reutiliser ses calculs (bandes
d'equivalence, decimation de l'equity, serie mensuelle contigue, internement des
phrases, analyser()) plutot que d'en produire une seconde version qui divergerait.

    python -m app.generer_web        depuis la racine du depot
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time

import numpy as np

import ht.montecarlo as mc
from app import prepare_donnees as PD
from ht.schema import InsufficientData

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIE = os.path.join(RACINE, "web", "public", "data")

# Nombre de tirages du bootstrap ET de permutations. 2000 est le compromis mesure
# entre la stabilite des bornes et le cout : 291 wallets, 61 812 trades, environ
# deux minutes et demie de calcul total.
N_TIRAGES = 2000
# Retards du Ljung-Box. En dessous de MIN_N_LJUNG observations la statistique Q
# n'approxime plus un chi2 : elle reste None, jamais remplacee.
H_LJUNG = 5
MIN_N_LJUNG = 10


# --------------------------------------------------------------------------- outils
def _graine(adresse: str) -> int:
    """
    Graine DETERMINISTE derivee de l'adresse. Deux executions du generateur
    doivent rendre la meme p-valeur et le meme intervalle : une preuve qui bouge
    d'un cycle a l'autre sans que la donnee ait bouge n'est pas une preuve.
    """
    return int(hashlib.sha256(adresse.encode()).hexdigest()[:8], 16)


def _mesure(f, *args, **kw):
    """
    Rend None quand la grandeur n'est pas calculable — serie trop courte,
    variance nulle, queues extremes. JAMAIS de valeur de repli : un zero de
    complaisance se lit comme une mesure, et se propage dans les tris.
    """
    try:
        return f(*args, **kw)
    except InsufficientData:
        return None


def _sig(x, k: int = 4):
    """
    Arrondi a `k` chiffres SIGNIFICATIFS, pour les grandeurs qui peuvent etre
    minuscules sans etre nulles. round(p, 6) ecrase une p-valeur de 1e-30 en 0.0,
    qui se lit "impossible" au lieu de "tres petite".
    """
    return None if x is None else float(f"{x:.{k}g}")


def _rd(x, k: int = 4):
    return None if x is None else round(float(x), k)


# --------------------------------------------------------------------------- preuve
def preuve(adresse: str, r: np.ndarray, brut: np.ndarray,
           seuil_bonferroni: float) -> tuple[dict, float | None]:
    """
    De quoi REFUTER un wallet, calcule sur sa serie de rendements nets, plus le
    PnL prive de son meilleur trade — qui sert aussi a la ligne de liste.

    Les deux grandeurs couteuses — bootstrap et permutation — ne sont evaluees
    qu'une fois chacune : elles portent a elles seules l'essentiel du temps de
    generation.
    """
    n = len(r)
    g = _graine(adresse)

    perm = _mesure(mc.test_permutation_signe, r, mc.sharpe_par_trade,
                   seed=g, n_permutations=N_TIRAGES)
    boot = _mesure(mc.bootstrap_par_blocs, r, mc.sharpe_par_trade,
                   seed=g, n_tirages=N_TIRAGES)

    p_perm = None if perm is None else perm.p_value
    boot_ic = None if boot is None else [_rd(boot.ic_bas), _rd(boot.ic_haut)]

    # Ljung-Box : DIAGNOSTIC seul. Il ne filtre rien, ne pondere rien — il dit
    # que la serie est dependante, donc que tout ce qui suppose l'independance
    # est a lire avec prudence. Le bootstrap par blocs est deja la reponse.
    lb = None if n < MIN_N_LJUNG else _mesure(mc.ljung_box, r, H_LJUNG)

    # DEUX MOITIES CHRONOLOGIQUES, jamais melangees : un edge qui n'existe que
    # dans la premiere moitie est un edge mort, et c'est exactement ce qu'un
    # Sharpe global masque.
    mi = n // 2
    sr_h1 = _mesure(mc.sharpe_par_trade, r[:mi])
    sr_h2 = _mesure(mc.sharpe_par_trade, r[mi:])

    # COUT DES FRAIS en unites de Sharpe : ce que la meme serie vaudrait si elle
    # ne les payait pas, moins ce qu'elle vaut. Positif = les frais retirent.
    sr_brut = _mesure(mc.sharpe_par_trade, brut)
    sr_net = _mesure(mc.sharpe_par_trade, r)
    frais_sr = None if (sr_brut is None or sr_net is None) else sr_brut - sr_net

    # PART DU MEILLEUR TRADE, rapportee a la somme des VALEURS ABSOLUES. Le
    # rapport max/somme n'est pas borne — un wallet dont les gains annulent
    # presque les pertes affiche une part de plusieurs centaines de pour cent,
    # et le chiffre cesse de vouloir dire quoi que ce soit.
    total_abs = float(np.sum(np.abs(r))) if n else 0.0
    part_max = None if total_abs == 0.0 else float(np.max(r)) / total_abs

    hors_max = None if n == 0 else float(np.sum(r) - np.max(r))
    # BASCULE : gagnant avec son meilleur trade, perdant sans lui. Chez les
    # gagnants du classement, 66 % du PnL vient d'un seul trade.
    bascule = bool(hors_max is not None and float(np.sum(r)) > 0.0 and hors_max <= 0.0)

    # DEUX VERDICTS DISTINCTS, et il ne faut pas les confondre.
    #
    #   ic_exclut_zero  l'intervalle de bootstrap par blocs ne contient pas zero.
    #                   Mesurable a cette resolution, mais SANS correction pour
    #                   tests multiples : sur 291 wallets on en attend ~7 par
    #                   pur hasard a 95 %.
    #   survit_bonferroni  la p-valeur franchit 0,05 / (wallets explores). A
    #                   N_TIRAGES tirages ce seuil peut etre INATTEIGNABLE ; le
    #                   drapeau vaut alors faux PAR RESOLUTION, pas par mesure.
    # DEUX SENS, JAMAIS ADDITIONNES. Exclure zero PAR LE HAUT dit « peut-etre
    # mieux que rien » ; par le BAS, « perd, et ce n'est pas du bruit ». Les
    # compter ensemble produit un nombre qui flatte.
    ic_positif = bool(boot_ic is not None and boot_ic[0] > 0.0)
    ic_negatif = bool(boot_ic is not None and boot_ic[1] < 0.0)
    ic_exclut_zero = ic_positif or ic_negatif
    survit = bool(p_perm is not None and boot_ic is not None
                  and p_perm < seuil_bonferroni and boot_ic[0] > 0.0)

    return {
        "p_perm": _sig(p_perm),
        "boot_ic": boot_ic,
        "boot_bloc": None if boot is None else boot.longueur_bloc,
        "ac1": _rd(_mesure(mc.autocorrelation, r, 1)),
        "lb_p": None if lb is None else _sig(lb[1]),
        "sr_h1": _rd(sr_h1),
        "sr_h2": _rd(sr_h2),
        "frais_sr": _rd(frais_sr),
        "part_max": _rd(part_max),
        "bascule": bascule,
        "ic_exclut_zero": ic_exclut_zero,
        "ic_positif": ic_positif,
        "ic_negatif": ic_negatif,
        "survit_bonferroni": survit,
    }, hors_max


# --------------------------------------------------------------------------- rangs
def rangs_relatifs(chemin_db: str) -> dict[str, int]:
    """
    Variation de rang RELATIF entre les deux dernieres DATES DISTINCTES.

    Le releve precedent comparait des rangs ABSOLUS : 185 wallets portaient une
    fleche alors que le Spearman entre les deux releves valait exactement
    +1,0000 — personne n'avait bouge, dix-huit wallets etaient simplement
    arrives au-dessus. On classe donc chaque date PARMI LES SEULS WALLETS
    PRESENTS AUX DEUX DATES : un decalage uniforme devient nul par construction.

    Deux DATES, pas deux lignes : le registre ecrit plusieurs fois par cycle, et
    "cinq releves" designait deux jours dont trois points a 207 secondes
    d'intervalle. Au sein d'une journee, le dernier releve fait foi.

    Un wallet absent de l'une des deux dates n'a pas de variation a montrer :
    None, donc N/D. On ne lui invente pas un rang de depart.
    """
    if not os.path.exists(chemin_db):
        return {}
    c = sqlite3.connect(chemin_db)
    try:
        par_jour: dict[str, dict[str, int]] = {}
        for adresse, ts, rang in c.execute(
                "select adresse, ts, rang from historique"
                " where rang is not null order by ts"):
            jour = time.strftime("%Y-%m-%d", time.gmtime(ts))
            par_jour.setdefault(jour, {})[adresse] = rang
    finally:
        c.close()
    jours = sorted(par_jour)
    if len(jours) < 2:
        return {}
    avant, apres = par_jour[jours[-2]], par_jour[jours[-1]]
    communs = sorted(set(avant) & set(apres))
    if not communs:
        return {}

    def relatif(releve: dict[str, int]) -> dict[str, int]:
        return {a: i for i, a in enumerate(sorted(communs, key=lambda x: releve[x]), 1)}

    ra, rb = relatif(avant), relatif(apres)
    # Positif = places gagnees, comme un rang qui diminue.
    return {a: ra[a] - rb[a] for a in communs}


def dates_distinctes(histo) -> int:
    """Nombre de jours calendaires portes par l'historique d'un wallet. Compter
    les lignes annoncait "5 releves" pour deux journees."""
    return len({time.strftime("%Y-%m-%d", time.gmtime(p[0])) for p in histo})


# --------------------------------------------------------------------------- ecriture
def ecrire(chemin: str, contenu) -> int:
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf8", newline="\n") as f:
        json.dump(contenu, f, separators=(",", ":"), ensure_ascii=False)
    return os.path.getsize(chemin)


CHAMPS_DAILY_SCALAIRE = ("cycle_id", "horodatage", "mode", "prochaine_action")
CHAMPS_DAILY_LISTE = ("new_today", "new_ranked", "reactivated", "watch", "remarquables",
                      "top_movers", "declining", "archived", "blocages")
CHAMPS_DAILY_DICT = ("data_health", "system_health")


def daily(source: dict | None) -> dict | None:
    """
    Le rapport de cycle, restreint aux champs du contrat. `top20` en sort : c'est
    le classement, deja publie dans index.json, et transporter deux fois la meme
    verite invite a la voir diverger.

    Une section absente est une section VIDE, pas une valeur inventee : le
    rapport enumere des mouvements, et n'en enumerer aucun est exact.
    """
    if source is None:
        return None
    out: dict = {k: source.get(k) for k in CHAMPS_DAILY_SCALAIRE}
    out.update({k: source.get(k) or [] for k in CHAMPS_DAILY_LISTE})
    out.update({k: source.get(k) or {} for k in CHAMPS_DAILY_DICT})
    return out


# --------------------------------------------------------------------------- principal
def main() -> int:
    t_debut = time.time()
    chemin_db = os.path.join(PD.D, "registre.db")

    # DENOMINATEUR DU TEST MULTIPLE. Ce n'est pas le nombre de wallets classes :
    # c'est le nombre de wallets REELLEMENT examines. Le sous-declarer est la
    # facon la plus simple de se mentir sur un classement.
    explores = 0
    if os.path.exists(chemin_db):
        c = sqlite3.connect(chemin_db)
        try:
            explores = int(c.execute("select count(*) from wallets").fetchone()[0])
        finally:
            c.close()
    if explores < 1:
        print("ABANDON : le registre ne donne aucun wallet explore, donc aucun "
              "denominateur de test multiple. Rien n'est ecrit.", file=sys.stderr)
        return 1
    seuil_bonferroni = 0.05 / explores

    drang = rangs_relatifs(chemin_db)

    lignes: list[dict] = []
    lots: dict[str, dict] = {}
    n_w = len(PD.wallets)
    tty = sys.stdout.isatty()
    for i, w in enumerate(PD.wallets, 1):
        a = w["a"]
        tr = sorted(PD.SER.get(a, []), key=lambda t: t["close"])
        r = np.array([t["pnl"] - t["fee"] for t in tr], dtype=float)
        brut = np.array([t["pnl"] for t in tr], dtype=float)
        pr, hors_max = preuve(a, r, brut, seuil_bonferroni)

        lignes.append({
            "a": a, "rang": w["rang"], "groupe": w["groupe"], "score": w["score"],
            "ic": w["ic"],
            # SATURE : au moins une borne touche le bord de l'echelle. L'intervalle
            # est alors tronque par la borne, pas mesure — 100 ne veut pas dire
            # "certitude", il veut dire "on ne sait pas jusqu'ou".
            "sature": w["ic"][0] <= 0 or w["ic"][1] >= 100,
            "conf": w["conf"], "conf_lab": w["conf_lab"],
            "sr": w["sr"], "post": w["post"], "se": w["se"],
            "pnl": w["pnl"], "pnl_hors_max": _rd(hors_max, 2), "frais": w["frais"],
            "n": w["n"], "dd": w["dd"],
            # Absents du tout quand le wallet n'a aucun trade clos : None, donc N/D.
            "dort_j": w.get("dort_j"), "r30": w.get("r30"), "r7": w.get("r7"),
            "drang_rel": drang.get(a), "lb_p": pr["lb_p"],
            "st": w["st"], "coins": w["coins"],
        })

        prefixe = a[2:4] if a.startswith("0x") else a[:2]
        lots.setdefault(prefixe, {})[a] = {
            "a": a, "eq": w["eq"],
            # `hist` vaut [] quand il n'y a rien a distribuer : null, pas un
            # histogramme vide qui se dessinerait comme une distribution plate.
            "hist": w["hist"] or None,
            "histo": w["histo"], "n_dates": dates_distinctes(w["histo"]),
            "forts": w["forts"], "faibles": w["faibles"], "risques": w["risques"],
            "obs": w.get("obs"), "preuve": pr,
            "m0": w["m0"], "m": w["m"],
            "classe": w["classe"], "src": w["src"], "vu": w["vu"],
            "promu": w["promu"], "coll": w["coll"], "ret": w["ret"],
            "t0": w["t0"], "t1": w["t1"], "win": w["win"], "pf": w["pf"],
            "best": w["best"], "pire": w["pire"], "duree_h": w["duree_h"],
            "vol": w["vol"], "tpj": w["tpj"], "conc": w["conc"], "jours": w["jours"],
            "stab": w["stab"], "qualite": w["qualite"],
        }

        if tty:
            print(f"\r  preuve {i}/{n_w}  {a[:10]}...", end="", flush=True)
        elif i % 25 == 0 or i == n_w:
            print(f"  preuve {i}/{n_w}  ({time.time() - t_debut:.0f} s)", flush=True)
    if tty:
        print()

    details = [d for lot in lots.values() for d in lot.values()]
    survivants = sum(1 for d in details if d["preuve"]["survit_bonferroni"])
    ic_positif = sum(1 for d in details if d["preuve"]["ic_positif"])
    ic_negatif = sum(1 for d in details if d["preuve"]["ic_negatif"])
    # PLANCHER DE RESOLUTION du test de permutation : a N tirages, la plus petite
    # p-valeur exprimable vaut 1/(N+1). S'il depasse le seuil de Bonferroni,
    # aucun wallet ne PEUT le franchir, quelle que soit sa performance.
    resolution_p = 1.0 / (N_TIRAGES + 1.0)

    rep = json.load(open(os.path.join(PD.D, "reputation_data.json"),
                         encoding="utf8"))["meta"]

    m = PD.meta
    meta = {
        "n": m["n"], "trades": m["trades"], "maj": m["maj"], "gen": m["gen"],
        "spearman": m["spearman"], "p": m["p"], "ece": m["ece"],
        "tau": m["tau"], "m": m["m"],
        "verdict": m["verdict"], "verdict_motif": m["verdict_motif"],
        "avec_natif": m["avec_natif"], "sans_p_cal": m["sans_p_cal"],
        "ranked": m["ranked"], "discovery_total": m["discovery_total"],
        "archives_total": m["archives_total"],
        "bandes": m["bandes"], "satures_haut": m["satures_haut"],
        "ic_largeur_mediane": m["ic_largeur_mediane"],
        "seuil_jours": m["seuil_jours"], "seuil_trades": m["seuil_trades"],
        "seuil_conc": m["seuil_conc"],
        "explores": explores, "seuil_bonferroni": seuil_bonferroni,
        "survivants": survivants,
        # Ce que l'ecran doit pouvoir dire pour ne pas faire passer une limite de
        # dispositif pour un resultat. Voir le commentaire de `preuve()`.
        "ic_boot_positif": ic_positif,
        "ic_boot_negatif": ic_negatif,
        "resolution_p": resolution_p,
        "tirages": N_TIRAGES,
        "test_resolu": bool(resolution_p <= seuil_bonferroni),
        "lib": PD._lib,
        # Les 315 fiches de reputation ne sont PAS embarquees : seul le compte
        # l'est. 163 ko de leaderboard pour dire que 2 wallets sur 315 sont
        # mesurables — c'est le compte qui porte l'information, pas les fiches.
        "reputation": {"n": rep["n"], "sans_trade_clos": rep["sans_trade_clos"],
                       "mesurables": rep["mesurables"], "source": rep["source"]},
    }

    # IDEMPOTENCE : les lots d'un cycle precedent dont plus aucun wallet ne porte
    # le prefixe sont supprimes. Sans cela, un wallet archive continuerait d'etre
    # servi par un fichier que plus rien ne regenere.
    dossier_lots = os.path.join(SORTIE, "wallet")
    os.makedirs(dossier_lots, exist_ok=True)
    attendus = {f"{p}.json" for p in lots}
    for nom in sorted(os.listdir(dossier_lots)):
        if nom.endswith(".json") and nom not in attendus:
            os.remove(os.path.join(dossier_lots, nom))
            print(f"  lot obsolete supprime : wallet/{nom}")

    poids = {
        "meta.json": ecrire(os.path.join(SORTIE, "meta.json"), meta),
        "index.json": ecrire(os.path.join(SORTIE, "index.json"), lignes),
    }
    rapport = daily(PD.REG["daily"])
    if rapport is None:
        print("  ATTENTION daily_report.json absent ou illisible : daily.json n'est "
              "pas ecrit, l'onglet restera vide plutot qu'invente.")
    else:
        poids["daily.json"] = ecrire(os.path.join(SORTIE, "daily.json"), rapport)
    total_lots = 0
    for prefixe, contenu in sorted(lots.items()):
        total_lots += ecrire(os.path.join(dossier_lots, f"{prefixe}.json"),
                             {"gen": meta["gen"], "wallets": contenu})

    print(f"\necrit -> {SORTIE}")
    for nom, octets in poids.items():
        print(f"  {nom:<14}{octets / 1024:8.1f} Ko")
    print(f"  {'wallet/*.json':<14}{total_lots / 1024:8.1f} Ko   "
          f"({len(lots)} lots, {n_w} wallets, "
          f"{total_lots / max(1, len(lots)) / 1024:.1f} Ko par lot en moyenne)")
    print(f"  {'TOTAL':<14}{(sum(poids.values()) + total_lots) / 1024:8.1f} Ko")

    print(f"\n  explores {explores}   seuil de Bonferroni {seuil_bonferroni:.3g}"
          f"   survivants {survivants}")
    # RESOLUTION DU TEST DE PERMUTATION. Avec N_TIRAGES permutations, la plus
    # petite p-valeur atteignable vaut 1/(N+1). Si ce plancher depasse le seuil
    # de Bonferroni, aucun wallet ne peut le franchir par la permutation :
    # `survit_bonferroni` est alors negatif PAR RESOLUTION, pas par mesure. C'est
    # une limite du dispositif et elle doit etre dite — la lire comme une preuve
    # d'absence serait l'erreur exactement symetrique de celle que ce produit
    # corrige.
    plancher = 1.0 / (N_TIRAGES + 1.0)
    if plancher > seuil_bonferroni:
        print(f"  ATTENTION plancher de p-valeur {plancher:.3g} > seuil "
              f"{seuil_bonferroni:.3g} : a {N_TIRAGES} tirages le test de "
              f"permutation ne RESOUT pas ce seuil. Aucune conclusion d'absence.")
    print(f"  bascule sans le meilleur trade : "
          f"{sum(1 for d in details if d['preuve']['bascule'])}/{n_w}")
    print(f"  Ljung-Box(5) p < 0,05 (trades non independants) : "
          f"{sum(1 for l in lignes if l['lb_p'] is not None and l['lb_p'] < 0.05)}/{n_w}")
    print(f"  rang relatif calculable : "
          f"{sum(1 for l in lignes if l['drang_rel'] is not None)}/{n_w}")
    print(f"  {time.time() - t_debut:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
