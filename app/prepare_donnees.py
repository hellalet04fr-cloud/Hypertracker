"""Prepare les donnees de l'application. Precalcule tout : aucun calcul au rendu.
Ne touche a aucun score, seuil ni protocole — il ne fait que deriver de l'affichable."""
import json, os, math, time, statistics as st
from ht import screening as SCR          # seuils du protocole, en lecture seule

D = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
CL = json.load(open(os.path.join(D, "classement_wallets.json")))
SER = json.load(open(os.path.join(D, "series_wallets.json")))
VER = json.load(open(os.path.join(D, "verdict_observed.json")))
CAL = json.load(open(os.path.join(D, "resultat_calibration.json")))
CMP = json.load(open(os.path.join(D, "comparaison_modeles.json")))
OBS = {x["adresse"].lower(): x for x in VER["detail"]}

# Reference de fraicheur : la derniere activite observee dans TOUT le jeu de donnees.
# On ne compare pas a l'horloge : les series sont figees a leur date de collecte, et
# mesurer l'inactivite contre « maintenant » vieillirait artificiellement tout le monde.
REF = max(max(t["close"] for t in v) for v in SER.values() if v)

# RESOLUTION PLEINE. Mesure : a 56 points sur tout l'historique, 167 wallets sur 231
# n'avaient plus qu'UN point sur 7 jours et 118 n'en avaient que deux sur 30 jours.
# Le filtre de periode etait donc decoratif. A 240 points, la moyenne de 153 trades
# par wallet passe en resolution exacte pour la grande majorite.
N_EQ = 240
N_SPARK = 18       # micro-courbe des cartes de classement
N_HIST = 13        # tranches de l'histogramme

# Reprise a l'identique de ht.ranking.MIN_PERIODS_FOR_PERSISTENCE. En dessous de ce
# nombre de mois distincts, la regularite mensuelle n'est pas calculable : elle reste
# None et s'affiche N/D, jamais 0 ni une valeur substituee.
MIN_MOIS_REGULARITE = 3


def indices(taille, n, obligatoires=()):
    """
    Indices d'un sous-echantillonnage regulier, en CONSERVANT TOUJOURS le dernier
    point ainsi que les indices explicitement exiges.

    Sans la garantie sur le dernier point, les indices 0, pas, 2*pas... s'arretent
    avant la fin et la courbe ne se termine pas sur le PnL reel du wallet. Mesure :
    39 wallets sur 231 affichaient une courbe finissant ailleurs que sur leur total,
    pendant que la legende, elle, donnait le bon chiffre.

    `obligatoires` sert le meme principe pour les extremums : un point de creux
    maximal supprime par l'echantillonnage donne une courbe de drawdown dont le
    minimum contredit le champ `dd` affiche a cote. Mesure avant correction : jusqu'a
    19.57 USD d'ecart. Un point remarquable ne se sous-echantillonne pas.
    """
    if taille <= n:
        return list(range(taille))
    pas = (taille - 1) / (n - 1)
    idx = {min(taille - 1, round(i * pas)) for i in range(n)}
    idx |= {i for i in obligatoires if 0 <= i < taille}
    return sorted(idx)


def echant(v, n):
    """Sous-echantillonnage regulier simple, dernier point toujours conserve."""
    return [v[i] for i in indices(len(v), n)]


def prepare(a, w):
    tr = sorted(SER.get(a, []), key=lambda t: t["close"])
    r = [t["pnl"] - t["fee"] for t in tr]
    out = {
        "a": a, "score": round(w["score"], 1),
        "ic": [round(w["ic"][0]), round(w["ic"][1])],
        # La probabilite calibree peut ne PAS EXISTER : le modele isotonique
        # ajuste n'a jamais ete persiste, donc un wallet apparu depuis la
        # calibration n'en a pas. None se propage jusqu'a l'affichage N/D — il ne
        # devient pas 0, qui se lirait « probabilite nulle ».
        "conf": None if w.get("p_cal") is None else round(w["p_cal"] * 100),
        "conf_lab": w["confiance"], "qualite": w["qualite"],
        "sr": round(w["sr"], 4), "post": round(w["post"], 4),
        "se": None if w.get("se") is None else round(w["se"], 4),
        "n": w["n"], "jours": round(w["jours"]),
        "pnl": round(w["pnl"], 2), "dd": round(w["dd"], 2),
        "conc": round(w["conc"], 3),
    }
    if not r:
        out.update({"win": None, "pf": None, "best": None, "pire": None,
                    "duree_h": None, "tpj": None, "vol": None, "eq": None, "hist": [],
                    "coins": [], "t0": None, "t1": None, "frais": None,
                    "stab": None, "pire_serie": None, "m": []})
        return out

    gains = [x for x in r if x > 0]
    pertes = [x for x in r if x < 0]
    out["win"] = round(len(gains) / len(r) * 100, 1)
    sp = sum(abs(x) for x in pertes)
    out["pf"] = round(sum(gains) / sp, 2) if sp > 0 else None
    out["best"] = round(max(r), 2)
    out["pire"] = round(min(r), 2)
    dur = [(t["close"] - t["open"]) / 3600000 for t in tr]
    out["duree_h"] = round(st.median(dur), 1)
    out["tpj"] = round(len(r) / max(1, w["jours"]), 2)
    out["vol"] = round(st.pstdev(r), 2) if len(r) > 1 else None
    out["t0"] = tr[0]["close"]
    out["t1"] = tr[-1]["close"]
    # ACTIVITE RECENTE. Le score mesure une performance passee et ignore la fraicheur :
    # un wallet excellent puis arrete garde son rang. Mesure sur le classement livre,
    # 9 des 20 premiers n'avaient fait AUCUN trade en 30 jours. L'activite devient donc
    # une dimension a part entiere, a cote du score — elle ne le modifie pas.
    out["r30"] = sum(1 for t in tr if t["close"] >= REF - 30 * 86400000)
    out["r7"] = sum(1 for t in tr if t["close"] >= REF - 7 * 86400000)
    out["dort_j"] = round((REF - tr[-1]["close"]) / 86400000, 1)

    out["frais"] = round(sum(t["fee"] for t in tr), 2)

    # courbe d'equity ET courbe de drawdown, construites dans la MEME boucle sur la
    # serie complete, puis sous-echantillonnees a la meme longueur : echant() etant
    # deterministe pour une longueur donnee, les deux courbes retiennent exactement
    # les memes indices et restent alignees dans le temps.
    #
    # Le sommet demarre a 0.0, pas au premier point. C'est la convention du moteur
    # (ht/ranking.py, « drawdown sur la courbe de PnL net cumule ») : un repli sous le
    # point de depart compte comme drawdown. Verifie sur les 231 wallets — en partant
    # du premier point au lieu de 0, 57 wallets donnaient une courbe dont le maximum
    # contredisait le champ `dd` affiche juste a cote, jusqu'a 5 499 USD d'ecart. Avec
    # cette convention, l'ecart maximal tombe a 0.005 (arrondi seul).
    # UNE SEULE COURBE EST STOCKEE. Le drawdown se DEDUIT de l'equity — c'est
    # d'ailleurs ainsi qu'il est calcule : dd(i) = max(eq[0..i], 0) - eq(i). Le
    # stocker separement doublait la charge pour zero information nouvelle :
    # mesure, `eq` et `ddc` pesaient 1 503 Ko sur les 1 857 Ko du document.
    #
    # Pour que la deduction soit EXACTE apres sous-echantillonnage, tout point qui
    # met le sommet a jour doit survivre : sans eux, le pic precedant le creux peut
    # disparaitre et le drawdown recalcule sous-estime — mesure sur 31 wallets sur
    # 267, jusqu'a 161 USD. Ils sont donc forces, comme le creux l'etait deja. Cout
    # reel : 5 points de plus en mediane sur un echantillon de 240.
    c, sommet, eq, ddc, pics = 0.0, 0.0, [], [], []
    for t, x in zip(tr, r):
        c += x
        if c > sommet:
            sommet = c
            pics.append(len(eq))
        eq.append([t["close"], round(c, 2)])
        ddc.append(round(sommet - c, 2))
    creux = max(range(len(ddc)), key=lambda i: ddc[i])
    idx = indices(len(eq), N_EQ, obligatoires=tuple(pics) + (creux,))

    # HORODATAGES EN DELTAS DE SECONDES. Chaque point portait un epoch en
    # millisecondes — treize chiffres repetes 240 fois. Les ecarts successifs en
    # tiennent quatre a six, et la seconde est mille fois plus fine que l'axe des
    # dates affiche.
    ts = [eq[i][0] // 1000 for i in idx]
    out["eq"] = {"t0": ts[0], "d": [ts[k] - ts[k - 1] for k in range(1, len(ts))],
                 "v": [eq[i][1] for i in idx]}

    # REGULARITE MENSUELLE. Le moteur calcule deja cette grandeur en interne
    # (ht/ranking.py, « persistance : mois gagnants »), mais ne la publie pas dans le
    # classement. On reprend sa definition a l'identique — agregation du PnL net par
    # (annee, mois), un mois compte comme gagnant si son PnL net est > 0 — ainsi que sa
    # garde : en dessous de MIN_PERIODS_FOR_PERSISTENCE = 3 mois distincts, la grandeur
    # n'est pas calculable et reste None, donc affichee N/D. Aucune valeur substituee.
    par_mois = {}
    for t, x in zip(tr, r):
        d = time.gmtime(t["close"] / 1000)
        par_mois[(d.tm_year, d.tm_mon)] = par_mois.get((d.tm_year, d.tm_mon), 0.0) + x
    mois = sorted(par_mois)
    if len(mois) >= MIN_MOIS_REGULARITE:
        out["stab"] = round(sum(1 for m in mois if par_mois[m] > 0) / len(mois) * 100, 1)
        serie = pire = 0
        for m in mois:
            serie = serie + 1 if par_mois[m] <= 0 else 0
            pire = max(pire, serie)
        out["pire_serie"] = pire
    else:
        out["stab"] = None
        out["pire_serie"] = None
    # UNE SEULE SERIE MENSUELLE : etiquette, PnL, nombre de trades. Les deux
    # tableaux precedents portaient les MEMES etiquettes de mois, dupliquees.
    # L'activite mensuelle vient des memes horodatages que le PnL, donc elle est
    # exactement aussi reelle — et c'est la seule facon honnete de montrer « ce
    # wallet trade-t-il encore », que le score ignore par construction.
    cnt = {}
    for t in tr:
        d2 = time.gmtime(t["close"] / 1000)
        cnt[(d2.tm_year, d2.tm_mon)] = cnt.get((d2.tm_year, d2.tm_mon), 0) + 1
    out["m"] = [[f"{y:04d}-{m:02d}", round(par_mois[(y, m)], 2), cnt.get((y, m), 0)]
                for y, m in mois]

    # distribution des resultats, bornee aux quantiles pour rester lisible
    s = sorted(r)
    lo, hi = s[int(0.02 * (len(s) - 1))], s[int(0.98 * (len(s) - 1))]
    if hi <= lo:
        lo, hi = min(r), max(r) or 1.0
    pas = (hi - lo) / N_HIST if hi > lo else 1.0
    h = [0] * N_HIST
    for x in r:
        i = min(N_HIST - 1, max(0, int((x - lo) / pas)))
        h[i] += 1
    out["hist"] = {"lo": round(lo, 2), "pas": round(pas, 4), "b": h}

    cnt = {}
    for t in tr:
        cnt[t["coin"]] = cnt.get(t["coin"], 0) + 1
    out["coins"] = [k for k, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:4]]

    # Confrontation DERIVED / OBSERVED, telle qu'elle sort du protocole scelle. On
    # recopie ses champs sans en deriver de nouveaux : la comparaison appartient au
    # protocole, l'interface ne fait que la montrer. Presente sur 5 wallets sur 231.
    o = OBS.get(a.lower())
    if o:
        out["obs"] = {"n": o["n_observed"], "sr": o["sharpe_observed"],
                      "sr_der": o.get("sharpe_derived"),
                      "suffisant": o["suffisant"], "ecart": o.get("ecart_absolu"),
                      "ecart_rel": o.get("ecart_relatif"),
                      "signe": o.get("changement_de_signe")}
    return out


# Au-dela de ce niveau, un profit factor cesse de decrire une performance et
# decrit un echantillon : quelques gagnants enormes contre presque aucun
# perdant. Ce n'est pas une force, c'est une fragilite.
PF_DEGENERE = 10.0


def analyser(w):
    """Points forts / faibles / vigilance, derives des metriques EXISTANTES."""
    forts, faibles, risques = [], [], []
    if w["n"] >= 150: forts.append(f"Historique solide — {w['n']} trades")
    elif w["n"] < 60: faibles.append(f"Peu de trades — {w['n']} seulement")
    if w["jours"] >= 300: forts.append(f"Ancienneté — {w['jours']} jours d'activité")
    elif w["jours"] < 130: faibles.append(f"Historique court — {w['jours']} jours")
    if w["conc"] <= 0.15: forts.append(f"PnL bien réparti — concentration {w['conc']:.2f}")
    elif w["conc"] > 0.40:
        faibles.append(f"PnL concentré — concentration {w['conc']:.2f}")
        risques.append("Le résultat dépend de quelques trades : peu reproductible")
    if w["sr"] >= 0.30: forts.append(f"Sharpe par trade élevé — {w['sr']:.2f}")
    elif w["sr"] <= 0.05: faibles.append(f"Sharpe faible — {w['sr']:.2f}")
    if w["win"] is not None and w["win"] >= 60: forts.append(f"Taux de réussite {w['win']:.0f} %")
    if w["pf"] is not None and w["pf"] > PF_DEGENERE:
        risques.append(f"Distribution dégénérée — profit factor {w['pf']:.1f} sur "
                       f"{w['n']} trades, très peu de trades perdants")
    elif w["pf"] is not None and w["pf"] >= 1.5:
        forts.append(f"Profit factor {w['pf']:.2f}")
    ret = 1 - w["post"] / w["sr"] if w["sr"] else 0
    if ret > 0.5:
        faibles.append("Estimation fortement rétrécie : échantillon trop mince "
                       f"({w['sr']:.2f} → {w['post']:.2f})")
    if w["pnl"] is not None and w["dd"] and w["pnl"] > 0 and w["dd"] > abs(w["pnl"]):
        risques.append(f"Drawdown ({w['dd']:.0f}) supérieur au PnL total ({w['pnl']:.0f})")
    if w.get("stab") is not None:
        if w["stab"] >= 70: forts.append(f"Régularité mensuelle — {w['stab']:.0f} % de mois gagnants")
        elif w["stab"] < 40: faibles.append(f"Résultats irréguliers — {w['stab']:.0f} % de mois gagnants")
        if w.get("pire_serie", 0) >= 4:
            risques.append(f"{w['pire_serie']} mois perdants consécutifs dans l'historique")
    if w.get("r30", 0) >= 20: forts.append(f"Tres actif — {w['r30']} trades sur 30 jours")
    elif w.get("r30", 0) >= 5: forts.append(f"Actif — {w['r30']} trades sur 30 jours")
    if w.get("dort_j") is not None:
        if w["dort_j"] > 90:
            faibles.append(f"Inactif depuis {w['dort_j']:.0f} jours")
            risques.append("Wallet dormant : la performance passee ne dit rien de "
                           "ce qu'il ferait aujourd'hui")
        elif w["dort_j"] > 30:
            faibles.append(f"Peu actif — dernier trade il y a {w['dort_j']:.0f} jours")
    o = w.get("obs")
    if o is None:
        risques.append("Aucune donnée native HyperTracker : classement DERIVED uniquement")
    elif not o["suffisant"]:
        risques.append(f"Échantillon natif insuffisant — {o['n']} trades, 30 requis")
    if w["qualite"] < 2:
        risques.append("Qualité de données faible : au plus un critère sur trois satisfait")
    return {"forts": forts[:5], "faibles": faibles[:4], "risques": risques[:4]}


def registre():
    """Etat de cycle de vie, historique et rapport du jour, s'ils existent.

    L'interface doit pouvoir repondre a « pourquoi ce wallet est-il #3 aujourd'hui,
    pourquoi etait-il #17 hier, pourquoi a-t-il ete retire ». Ces reponses ne sont
    pas dans les series : elles sont dans le registre, qui les conserve en append
    seul. Si le registre n'existe pas encore, l'application fonctionne sans —
    elle n'affiche simplement aucun historique, plutot qu'un historique invente.
    """
    vide = {"statuts": {}, "hist": {}, "archives": [], "daily": None}
    p = os.path.join(D, "registre.db")
    if not os.path.exists(p):
        return vide
    import sqlite3
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    out = dict(vide)
    try:
        for r in c.execute("select adresse, statut, classe, watch, source, decouvert_le,"
                           " archive_raison, archive_le, score, rang, provenance,"
                           " raison_decouverte, derniere_collecte, n_retours, promu_le"
                           " from wallets"):
            out["statuts"][r["adresse"]] = {
                "st": r["statut"], "classe": r["classe"], "watch": bool(r["watch"]),
                "src": r["source"], "vu": r["decouvert_le"],
                "ar": r["archive_raison"], "ad": r["archive_le"],
                "prov": r["provenance"], "rd": r["raison_decouverte"],
                "coll": r["derniere_collecte"], "ret": r["n_retours"],
                "promu": r["promu_le"],
            }
            if r["statut"] == "ARCHIVED":
                out["archives"].append({
                    "a": r["adresse"], "raison": r["archive_raison"],
                    "le": r["archive_le"], "score": r["score"], "rang": r["rang"]})
        # historique : on ne garde que les points qui portent un rang ou un score,
        # et au plus N_HIST_W par wallet — assez pour tracer, pas assez pour peser.
        for r in c.execute("select adresse, ts, score, rang, statut, raison from historique"
                           " where score is not null or rang is not null order by ts"):
            out["hist"].setdefault(r["adresse"], []).append(
                [r["ts"], round(r["score"], 1) if r["score"] is not None else None,
                 r["rang"], r["statut"], (r["raison"] or "")[:120]])
        for a, v in out["hist"].items():
            out["hist"][a] = v[-N_HIST_W:]
    finally:
        c.close()
    q = os.path.join(D, "daily_report.json")
    if os.path.exists(q):
        # Lecture DEFENSIVE : un rapport ecrit par une version anterieure peut
        # encore etre en page de code systeme. On preferera toujours afficher une
        # application sans le rapport du jour plutot que de ne rien publier.
        try:
            out["daily"] = json.load(open(q, encoding="utf8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            out["daily"] = None
            print(f"  ATTENTION daily_report.json illisible ({type(e).__name__}) : "
                  f"l'onglet Quotidien restera vide")
    return out


N_HIST_W = 60      # points d'historique conserves par wallet

REG = registre()

wallets = []
for i, w in enumerate(CL["classement"], 1):
    d = prepare(w["a"], w)
    d["rang"] = i
    d.update(analyser(d))
    # `etat` et non `st` : ce dernier est l'alias du module statistics, et le
    # masquer au niveau module cassait la mediane des durees plus haut.
    etat = REG["statuts"].get(w["a"], {})
    # Aucune valeur par defaut flatteuse : sans registre, le statut est inconnu et
    # s'affiche comme tel, il ne devient pas « RANKED » par commodite.
    d["st"] = etat.get("st")
    d["classe"] = etat.get("classe")
    d["watch"] = etat.get("watch", False)
    d["src"] = etat.get("src")
    d["vu"] = etat.get("vu")
    d["rd"] = etat.get("rd")
    d["coll"] = etat.get("coll")
    d["ret"] = etat.get("ret") or 0
    d["promu"] = etat.get("promu")
    # PROVENANCE reelle : OBSERVED seulement si une donnee native existe pour ce
    # wallet. Jamais deduite du registre, jamais convertie.
    d["prov"] = "OBSERVED" if d.get("obs") else "DERIVED"
    # `histo` et non `hist` : ce dernier porte deja l'histogramme des PnL, et
    # l'ecraser aurait vide silencieusement le graphique de distribution.
    d["histo"] = REG["hist"].get(w["a"], [])
    # VARIATION DE RANG entre les deux derniers releves portant un rang. Non
    # calculable avec moins de deux releves : le champ reste None et s'affiche
    # N/D. Mesure : 195 wallets sur 267 en ont assez, 72 n'en ont pas.
    rangs = [x[2] for x in d["histo"] if x[2] is not None]
    d["drang"] = (rangs[-2] - rangs[-1]) if len(rangs) >= 2 else None
    wallets.append(d)

# --- BANDES D'EQUIVALENCE : voir la note ci-dessus. Calculees APRES le
#     classement complet, sur l'ordre reel des scores.
_bande, _ancre = 1, None
for _w in sorted(wallets, key=lambda x: x["rang"]):
    if _ancre is None or not (_w["ic"][0] <= _ancre["ic"][1]
                              and _w["ic"][1] >= _ancre["ic"][0]):
        if _ancre is not None:
            _bande += 1
        _ancre = _w
    _w["groupe"] = _bande

_par_score = {}
for _w in wallets:
    _par_score[_w["score"]] = _par_score.get(_w["score"], 0) + 1
for _w in wallets:
    _w["exaequo"] = _par_score[_w["score"]]

meta = {
    "n": len(wallets), "trades": sum(w["n"] for w in wallets),
    # Combien de bandes le classement porte reellement, et combien de wallets
    # touchent une borne de l'echelle — l'ecran doit pouvoir le dire.
    "bandes": _bande,
    "satures_haut": sum(1 for w in wallets if w["ic"][1] >= 100),
    "ic_largeur_mediane": sorted(w["ic"][1] - w["ic"][0] for w in wallets)[len(wallets) // 2],
    # DATE DERIVEE, plus un litteral. Elle etait ecrite en dur et se perimait
    # a chaque cycle : l'ecran Donnees annoncait « mise a jour 2026-08-24 »
    # trois lignes au-dessus de « derniere collecte 27 aout ». Le seul
    # indicateur nomme « fraicheur des donnees » se contredisait lui-meme.
    "maj": time.strftime("%Y-%m-%d"),
    "spearman": round(CMP["primaire"]["B"][0], 4),
    "p": CMP["primaire"]["B"][1],
    "ece": round(CAL["ece_apres"], 4),
    "tau": round(CL["tau"], 4), "m": round(CL["m"], 4),
    "verdict": VER["verdict"], "verdict_motif": VER["motif"],
    "top5": [x["adresse"] for x in VER["detail"]],
    # etat de la confrontation au natif, repris tel quel du protocole scelle
    "obs_apparies": VER["n_apparies"], "obs_positifs": VER["n_positifs"],
    "obs_insuffisants": VER["n_insuffisants"], "obs_correlation": VER["correlation_rang"],
    # repartition des niveaux de confiance, pour les indicateurs d'accueil
    "conf_elevee": sum(1 for w in wallets if w["conf_lab"] == "elevee"),
    "conf_moyenne": sum(1 for w in wallets if w["conf_lab"] == "moyenne"),
    "conf_faible": sum(1 for w in wallets if w["conf_lab"] == "faible"),
    "score_max": max(w["score"] for w in wallets),
    "avec_natif": sum(1 for w in wallets if w.get("obs")),
    # etat du cycle de vie, tel que le registre le connait
    "ranked": sum(1 for w in wallets if w.get("st") == "RANKED"),
    "discovery_total": len(REG["statuts"]) - sum(1 for v in REG["statuts"].values()
                                                 if v["st"] != "DISCOVERY"),
    "archives_total": len(REG["archives"]),
    "sans_p_cal": sum(1 for w in wallets if w.get("conf") is None),
    "registre": bool(REG["statuts"]),
    # SEUILS LUS DANS LE MOTEUR, jamais recopies dans le gabarit. L'interface
    # explique pourquoi un candidat n'est pas qualifie ; si elle enonce « 130
    # jours » de son propre chef et que ht.screening en demande 150 demain,
    # elle ment sans que rien ne le signale. Les faire transiter par la donnee
    # rend cette derive impossible.
    "seuil_jours": SCR.MIN_JOURS,
    "seuil_trades": SCR.MIN_TRADES,
    "seuil_conc": SCR.MAX_CONCENTRATION,
}
out = os.path.join(D, "app_data.json")
json.dump({"meta": meta, "wallets": wallets,
           "archives": REG["archives"], "daily": REG["daily"]},
          open(out, "w"), separators=(",", ":"))
print(f"ecrit -> {out}  ({os.path.getsize(out)/1024:.0f} Ko)")
print(f"  {len(wallets)} wallets | equity moyenne "
      f"{st.mean(len(w['eq']['v']) if w['eq'] else 0 for w in wallets):.0f} points")
print(f"  avec natifs OBSERVED : {sum(1 for w in wallets if w.get('obs'))}")
print(f"  win rate disponible  : {sum(1 for w in wallets if w['win'] is not None)}/{len(wallets)}")
