"""
LES DEUX PROPRIETES QUI NE SE DEMONTRENT PAS A L'ECRAN.

Un controle d'interface constate un etat ; il ne peut pas prouver qu'un
DECALAGE UNIFORME ne produit aucun mouvement, parce que sur une population
reelle de vrais mouvements existent et qu'un ratio ne prouverait rien. Ces deux
proprietes se demontrent sur des cas construits, ici.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from app import generer_web as G


# ═══════════════════════════════════════════════════ critere 17 — rang relatif
def _registre(tmp_path, releves):
    """Ecrit un registre minimal : {jour: {adresse: rang}}."""
    p = tmp_path / "registre.db"
    c = sqlite3.connect(p)
    c.execute("create table historique (adresse text, ts integer, rang integer)")
    for jour, (base_ts, rangs) in enumerate(releves):
        for a, r in rangs.items():
            c.execute("insert into historique values (?,?,?)", (a, base_ts, r))
    c.commit()
    c.close()
    return str(p)


JOUR = 86_400


def test_un_decalage_uniforme_ne_produit_aucun_mouvement(tmp_path):
    """
    LE DEFAUT D'ORIGINE, reproduit. Dix wallets, aucun changement d'ordre, et
    trois nouveaux arrives EN TETE : tous les rangs absolus reculent de trois.
    L'ancienne version affichait une fleche sur chacun ; le Spearman entre les
    deux releves valait pourtant exactement +1,0000.
    """
    avant = {f"0x{i:02d}": i for i in range(1, 11)}
    apres = {f"0x{i:02d}": i + 3 for i in range(1, 11)}
    apres.update({"0xN1": 1, "0xN2": 2, "0xN3": 3})
    db = _registre(tmp_path, [(1_700_000_000, avant), (1_700_000_000 + JOUR, apres)])

    v = G.rangs_relatifs(db)
    assert v, "aucune variation calculee"
    assert set(v) == set(avant), "les nouveaux venus n'ont pas de variation a montrer"
    assert all(x == 0 for x in v.values()), f"decalage uniforme lu comme un mouvement : {v}"


def test_un_vrai_echange_se_voit(tmp_path):
    """Le controle precedent ne prouverait rien si la fonction rendait toujours zero."""
    avant = {f"0x{i:02d}": i for i in range(1, 6)}
    apres = dict(avant)
    apres["0x01"], apres["0x05"] = 5, 1
    db = _registre(tmp_path, [(1_700_000_000, avant), (1_700_000_000 + JOUR, apres)])

    v = G.rangs_relatifs(db)
    assert v["0x01"] == -4 or v["0x01"] == 4, f"echange invisible : {v}"
    assert v["0x05"] == -v["0x01"]
    assert v["0x03"] == 0, "un wallet immobile ne bouge pas"


def test_plusieurs_releves_dans_la_meme_journee_comptent_pour_un(tmp_path):
    """
    « Cinq releves » designait DEUX dates, dont trois points a 207 et 120
    secondes d'intervalle. Trois ecritures le meme jour ne font pas trois
    releves, et le dernier de la journee fait foi.
    """
    t0 = 1_700_000_000
    p = tmp_path / "registre.db"
    c = sqlite3.connect(p)
    c.execute("create table historique (adresse text, ts integer, rang integer)")
    for a, r in {"0x01": 1, "0x02": 2}.items():
        c.execute("insert into historique values (?,?,?)", (a, t0, r))
    # deux ecritures de plus le MEME jour, ordre inverse
    for a, r in {"0x01": 2, "0x02": 1}.items():
        c.execute("insert into historique values (?,?,?)", (a, t0 + 207, r))
    for a, r in {"0x01": 2, "0x02": 1}.items():
        c.execute("insert into historique values (?,?,?)", (a, t0 + 327, r))
    c.commit()
    c.close()
    # Une seule DATE : rien a comparer, donc aucune variation.
    assert G.rangs_relatifs(str(p)) == {}


def test_sans_deux_dates_la_variation_est_absente(tmp_path):
    db = _registre(tmp_path, [(1_700_000_000, {"0x01": 1})])
    assert G.rangs_relatifs(db) == {}
    assert G.rangs_relatifs(str(tmp_path / "inexistant.db")) == {}


def test_les_dates_se_comptent_en_jours_pas_en_lignes():
    t = 1_700_000_000
    histo = [(t, 1, 1), (t + 207, 1, 1), (t + 327, 1, 1), (t + JOUR, 2, 2)]
    assert G.dates_distinctes(histo) == 2
    assert G.dates_distinctes([]) == 0


# ═══════════════════════════════════ critere 11 — le drawdown apres decimation
DONNEES = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
SORTIE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "web", "public", "data")


def _lots():
    dossier = os.path.join(SORTIE, "wallet")
    if not os.path.isdir(dossier):
        pytest.skip("les donnees web n'ont pas encore ete generees")
    out = {}
    for f in os.listdir(dossier):
        if f.endswith(".json"):
            with open(os.path.join(dossier, f), encoding="utf8") as fh:
                out.update(json.load(fh)["wallets"])
    return out


def _dd_deduit(eq) -> float:
    sommet = pire = 0.0
    for v in eq["v"]:
        sommet = max(sommet, v)
        pire = max(pire, sommet - v)
    return pire


def test_le_drawdown_survit_a_la_decimation():
    """
    Le drawdown n'est plus stocke : il se DEDUIT de la courbe decimee. Tout
    point qui met le sommet a jour est donc force a survivre — sans quoi le pic
    precedant un creux disparait et le repli recalcule sous-estime, en silence.
    """
    lots = _lots()
    classement = {w["a"]: w for w in json.load(
        open(os.path.join(DONNEES, "classement_wallets.json"), encoding="utf8"))["classement"]}
    ecarts = []
    for a, d in lots.items():
        eq, ref = d.get("eq"), classement.get(a, {}).get("dd")
        if not eq or not eq.get("v") or ref is None:
            continue
        deduit = _dd_deduit(eq)
        # 1 % du drawdown de reference, plancher a un cent : un drawdown nul ne
        # se compare pas en relatif.
        ecarts.append((a, abs(deduit - ref), max(0.01, abs(ref) * 0.01)))
    assert ecarts, "aucune courbe a verifier"
    fautifs = [(a, e, t) for a, e, t in ecarts if e > t]
    assert not fautifs, f"drawdown deforme par la decimation : {fautifs[:3]}"


def test_la_courbe_se_termine_sur_le_pnl_reel():
    """Le defaut qui avait touche 39 wallets sur 231 : la courbe finissait
    ailleurs que sur le total affiche juste en dessous."""
    lots = _lots()
    index = {l["a"]: l for l in json.load(
        open(os.path.join(SORTIE, "index.json"), encoding="utf8"))}
    mauvais = []
    for a, d in lots.items():
        eq = d.get("eq")
        if not eq or not eq.get("v") or a not in index:
            continue
        if abs(eq["v"][-1] - index[a]["pnl"]) > 0.02:
            mauvais.append((a, eq["v"][-1], index[a]["pnl"]))
    assert not mauvais, f"courbes mal terminees : {mauvais[:3]}"


def test_les_horodatages_ne_reculent_jamais():
    """Les ecarts sont en minutes ; un ecart negatif ferait reculer le temps sur
    la courbe reconstruite."""
    for a, d in _lots().items():
        eq = d.get("eq")
        if not eq:
            continue
        assert all(x >= 0 for x in eq["d"]), f"{a} : ecart negatif"
        assert len(eq["d"]) == len(eq["v"]) - 1, f"{a} : series desappariees"
