"""Prepare les donnees de l'application. Precalcule tout : aucun calcul au rendu.
Ne touche a aucun score, seuil ni protocole — il ne fait que deriver de l'affichable."""
import json, os, math, statistics as st

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


def echant(v, n):
    """
    Sous-echantillonne en CONSERVANT TOUJOURS le dernier point.

    Sans cette garantie, les indices 0, pas, 2*pas... s'arretent avant la fin et la
    courbe ne se termine pas sur le PnL reel du wallet. Mesure : 39 wallets sur 231
    affichaient une courbe finissant ailleurs que sur leur total, pendant que la
    legende, elle, donnait le bon chiffre. Deux affichages contradictoires pour la
    meme grandeur.
    """
    if len(v) <= n:
        return v
    pas = (len(v) - 1) / (n - 1)
    idx = sorted({min(len(v) - 1, round(i * pas)) for i in range(n)})
    return [v[i] for i in idx]


def prepare(a, w):
    tr = sorted(SER.get(a, []), key=lambda t: t["close"])
    r = [t["pnl"] - t["fee"] for t in tr]
    out = {
        "a": a, "score": round(w["score"], 1),
        "ic": [round(w["ic"][0]), round(w["ic"][1])],
        "conf": round(w["p_cal"] * 100),
        "conf_lab": w["confiance"], "qualite": w["qualite"],
        "sr": round(w["sr"], 4), "post": round(w["post"], 4),
        "n": w["n"], "jours": round(w["jours"]),
        "pnl": round(w["pnl"], 2), "dd": round(w["dd"], 2),
        "conc": round(w["conc"], 3),
    }
    if not r:
        out.update({"win": None, "pf": None, "best": None, "pire": None,
                    "duree_h": None, "tpj": None, "vol": None, "eq": [], "hist": [],
                    "coins": [], "t0": None, "t1": None})
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

    # courbe d'equity : PnL cumule, sous-echantillonnee
    c, eq = 0.0, []
    for t, x in zip(tr, r):
        c += x
        eq.append([t["close"], round(c, 2)])
    out["eq"] = echant(eq, N_EQ)
    # sparkline : forme normalisee 0-1, pour scanner la trajectoire sans ouvrir la fiche
    sp = echant([y for _, y in eq], N_SPARK)
    lo, hi = min(sp), max(sp)
    out["sp"] = [round((v - lo) / (hi - lo), 3) for v in sp] if hi > lo else [0.5] * len(sp)

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

    o = OBS.get(a.lower())
    if o:
        out["obs"] = {"n": o["n_observed"], "sr": o["sharpe_observed"],
                      "suffisant": o["suffisant"], "ecart": o.get("ecart_absolu")}
    return out


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
    if w["pf"] is not None and w["pf"] >= 1.5: forts.append(f"Profit factor {w['pf']:.2f}")
    ret = 1 - w["post"] / w["sr"] if w["sr"] else 0
    if ret > 0.5:
        faibles.append("Estimation fortement rétrécie : échantillon trop mince "
                       f"({w['sr']:.2f} → {w['post']:.2f})")
    if w["pnl"] is not None and w["dd"] and w["pnl"] > 0 and w["dd"] > abs(w["pnl"]):
        risques.append(f"Drawdown ({w['dd']:.0f}) supérieur au PnL total ({w['pnl']:.0f})")
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


wallets = []
for i, w in enumerate(CL["classement"], 1):
    d = prepare(w["a"], w)
    d["rang"] = i
    d.update(analyser(d))
    wallets.append(d)

meta = {
    "n": len(wallets), "trades": sum(w["n"] for w in wallets),
    "maj": "2026-08-24",
    "spearman": round(CMP["primaire"]["B"][0], 4),
    "p": CMP["primaire"]["B"][1],
    "ece": round(CAL["ece_apres"], 4),
    "tau": round(CL["tau"], 4), "m": round(CL["m"], 4),
    "verdict": VER["verdict"], "verdict_motif": VER["motif"],
    "top5": [x["adresse"] for x in VER["detail"]],
}
out = os.path.join(D, "app_data.json")
json.dump({"meta": meta, "wallets": wallets}, open(out, "w"), separators=(",", ":"))
print(f"ecrit -> {out}  ({os.path.getsize(out)/1024:.0f} Ko)")
print(f"  {len(wallets)} wallets | equity moyenne {st.mean(len(w['eq']) for w in wallets):.0f} points")
print(f"  avec natifs OBSERVED : {sum(1 for w in wallets if w.get('obs'))}")
print(f"  win rate disponible  : {sum(1 for w in wallets if w['win'] is not None)}/{len(wallets)}")
