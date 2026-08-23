#!/usr/bin/env python3
"""
Application MECANIQUE du protocole OBSERVED scelle (preenregistrement_observed.json).

Ecrit AVANT que les donnees natives du top-5 n'existent. C'est volontaire et c'est la
garantie la plus forte contre l'ajustement apres coup : le code qui rend le verdict ne
peut pas avoir ete influence par le verdict.

Aucune decision n'est prise ici. Les seuils, la selection des wallets et la regle de
verdict viennent tous du fichier scelle ; ce module ne fait que les executer et rendre
compte.

    python -m ht.verdict_observed
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics as st
from datetime import datetime

DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
MIN_TRADES = 30                      # seuil du protocole scelle, non modifiable ici


def _ms(s: str) -> int:
    return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)


def _perp(coin: str) -> bool:
    return ":" not in coin and "/" not in coin


def _sharpe(r):
    if len(r) < 2:
        return None
    sd = st.pstdev(r)
    return (st.mean(r) / sd) if sd > 0 else None


def _rangs(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    for k, i in enumerate(o):
        r[i] = float(k)
    return r


def _spearman(x, y):
    rx, ry = _rangs(x), _rangs(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (num / den) if den > 0 else 0.0


def collecter_observed(top5) -> dict:
    """Trades natifs perp exploitables, par wallet, depuis le ledger."""
    from . import reconstruct as R

    c = sqlite3.connect(os.path.join(DATA, "ledger.db"))
    out = {}
    for a in top5:
        brut = []
        for (p,) in c.execute("SELECT payload FROM closed_trades_natifs WHERE lower(address)=?",
                              (a.lower(),)):
            try:
                brut += json.loads(p).get("trades", [])
            except Exception:
                continue
        # deduplication : les fenetres de 30 jours peuvent se chevaucher d'une seconde
        vus, uniq = set(), []
        for t in brut:
            k = t.get("id") or (t.get("coin"), t.get("closeTime"))
            if k in vus:
                continue
            vus.add(k)
            uniq.append(t)
        bons, _ = R.natifs_exploitables([t for t in uniq if _perp(t.get("coin", ""))])
        out[a] = sorted(bons, key=lambda t: _ms(t["closeTime"]))
    return out


def evaluer() -> dict:
    """Rend le verdict, strictement selon la regle scellee."""
    pre = json.load(open(os.path.join(DATA, "preenregistrement_observed.json")))
    top5 = pre["top5"]
    cl = {w["a"]: w for w in
          json.load(open(os.path.join(DATA, "classement_wallets.json")))["classement"]}
    obs = collecter_observed(top5)

    lignes = []
    for a in top5:
        t = obs.get(a, [])
        # convention scellee : PnL natif NET DES FRAIS, funding retire des deux cotes
        r = [float(x["realizedPnlUsd"]) - float(x.get("fundingUsd") or 0.0) for x in t]
        lignes.append({
            "adresse": a,
            "n_observed": len(r),
            "sharpe_observed": _sharpe(r) if len(r) >= 2 else None,
            "sharpe_derived": cl.get(a, {}).get("sr"),
            "score_derived": cl.get(a, {}).get("score"),
            "suffisant": len(r) >= MIN_TRADES,
        })

    insuffisants = sum(1 for x in lignes if not x["suffisant"])
    apparies = [x for x in lignes if x["sharpe_observed"] is not None
                and x["sharpe_derived"] is not None]
    positifs = sum(1 for x in apparies if x["sharpe_observed"] > 0)
    rho = (_spearman([x["sharpe_derived"] for x in apparies],
                     [x["sharpe_observed"] for x in apparies])
           if len(apparies) >= 3 else None)

    # --- REGLE SCELLEE, appliquee telle quelle
    if insuffisants >= 3:
        verdict = "INCONCLUSIF"
        motif = f"{insuffisants} wallets sur 5 sous {MIN_TRADES} trades natifs"
    elif positifs >= 4 and rho is not None and rho > 0:
        verdict = "VALIDE"
        motif = f"{positifs}/5 Sharpe OBSERVED positifs et correlation de rang {rho:+.3f}"
    elif positifs <= 2 or (rho is not None and rho < 0):
        verdict = "REFUSE"
        motif = (f"{positifs}/5 positifs"
                 + (f", correlation de rang {rho:+.3f}" if rho is not None else ""))
    else:
        verdict = "INCONCLUSIF"
        motif = f"{positifs}/5 positifs — zone indecise assumee par le protocole"

    for x in apparies:
        d, o = x["sharpe_derived"], x["sharpe_observed"]
        x["ecart_absolu"] = round(o - d, 4)
        x["ecart_relatif"] = round((o - d) / abs(d), 3) if abs(d) > 1e-9 else None
        x["changement_de_signe"] = (d > 0) != (o > 0)

    return {"sha256_protocole": pre["sha256"], "verdict": verdict, "motif": motif,
            "n_positifs": positifs, "n_apparies": len(apparies),
            "n_insuffisants": insuffisants, "correlation_rang": rho,
            "detail": lignes,
            "horodatage": datetime.now().astimezone().isoformat(timespec="seconds")}


def main() -> int:
    v = evaluer()
    print(f"protocole scelle {v['sha256_protocole'][:32]}…\n")
    print(f"{'wallet':<14}{'n_obs':>7}{'SR OBSERVED':>13}{'SR DERIVED':>12}{'ecart':>9}{'signe':>9}")
    for x in v["detail"]:
        so, sd, ec = x["sharpe_observed"], x["sharpe_derived"], x.get("ecart_absolu")
        c_so = f"{so:.3f}" if so is not None else "-"
        c_sd = f"{sd:.3f}" if sd is not None else "-"
        c_ec = f"{ec:+.3f}" if ec is not None else "-"
        c_sg = "INVERSE" if x.get("changement_de_signe") else ("OK" if so is not None else "-")
        print(f"{x['adresse'][:12]:<14}{x['n_observed']:>7}{c_so:>13}{c_sd:>12}"
              f"{c_ec:>9}{c_sg:>9}")
    print(f"\n  positifs {v['n_positifs']}/5 | correlation de rang "
          f"{v['correlation_rang'] if v['correlation_rang'] is None else round(v['correlation_rang'], 4)}"
          f" | insuffisants {v['n_insuffisants']}")
    print(f"\n  VERDICT : {v['verdict']} — {v['motif']}")
    with open(os.path.join(DATA, "verdict_observed.json"), "w") as f:
        json.dump(v, f, indent=1)
    print("  persiste -> verdict_observed.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
