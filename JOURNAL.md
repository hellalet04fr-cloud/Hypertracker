# JOURNAL

Journal de reprise. Écrit **après chaque étape terminée**, jamais à la fin.
Une interruption propre coûte dix minutes ; une interruption sale en coûte deux heures.

---

## 2026-08-29 · session 2 — reprise après coupure

**CHANTIER : B — refonte React + Vite** (`PROMPT-REFONTE-HYPERTRACKER.md`).

### État constaté à la reprise

La session précédente a été coupée par la limite mensuelle d'utilisation, au milieu
d'un lancement parallèle de sept modules. **Un seul a abouti** : le pipeline de
données Python. Les six autres — `domain/ design/ charts/ data/ app/ components/` —
ont échoué avant d'écrire quoi que ce soit, laissant les dossiers vides.

Conséquence pratique : **les sous-agents sont coupés**, tout se fait en direct.

### AVANCEMENT

| Étape | État | Commit |
|---|---|---|
| 1 · Socle | **fait** | `e270ab1` `2542a3e` `7bf8e7b` `a2813a1` |
| 2 · Données | **fait** | `0f8fec3` |
| 3 · Liste | **fait** — virtualisée, tri multi-clés, rails en canvas | ci-dessous |
| 4 · Fiche et inspecteur | **fait** — 4 onglets dont Preuve | ci-dessous |
| 5 · Aujourd'hui et Données | **fait** | ci-dessous |
| 6 · A11y, mouvement, golden files | **en cours** | — |

### MESURES RÉELLES (poste de travail, données réelles)

| Budget §7 | Cible | Mesuré |
|---|---|---|
| JS initial gzip | < 180 ko | **~82 ko** (react 45,6 + vendor 26,5 + routeur 6,0 + index 4,3) |
| Décodage de l'index | — | **19–28 ms, dans le worker** |
| Poids des données | — | 593 Ko découpés (meta 9,4 · index 102 · daily 11 · 163 lots) |

### PROCHAINE ACTION PRÉCISE

Étape 6 : écrire `e2e/` (Playwright) avec les 18 critères d'acceptation, l'audit
de contraste et de cibles tactiles sur le DOM rendu, puis les golden files aux
quatre largeurs.

### DÉCISIONS PRISES

- **Colonnes typées plutôt qu'un tableau d'objets** : 31 505 objets JS coûtent
  ~40 Mo et font tomber le premier rendu ; les colonnes en coûtent ~3 Mo.
- **Un seul canvas pour tous les rails visibles**, en surimpression de sa colonne.
  Un SVG par ligne ferait 31 505 sous-arbres ; un canvas par ligne recréerait
  34 contextes à chaque changement de filtre. Une seule géométrie alimente le
  rendu SVG (figure isolée) et le rendu canvas (tableau) — un test compare les
  deux au demi-pixel.
- **`--faible` planchonné à 6,09:1**, jetons de trace déclarés *non textuels* :
  mesure faite, `--s2` tombe à 4,42:1 sur `--eleve`.
- **Ljung-Box est un diagnostic pur** : il n'alimente aucun score, aucun seuil,
  aucun classement.
- **Le plancher de résolution du test est exporté vers l'écran.** À 2 000 tirages
  la plus petite p-valeur exprimable vaut 5,0 × 10⁻⁴, soit **520 fois** le seuil
  de Bonferroni : `survivants = 0` est une limite d'instrument, pas un verdict.
- **Les deux sens de l'intervalle de bootstrap ne s'additionnent jamais.**
  Compter ensemble « exclut zéro par le haut » et « par le bas » donnait 78/291,
  qui se lit comme 78 candidats. La vérité est **15 au-dessus** (l'ordre de
  grandeur du hasard à 95 % sans correction) et **63 au-dessous** (des pertes
  établies).

### DIVERGENCES SIGNALÉES, NON CORRIGÉES

- Le document de reprise annonce « 1 wallet sur 31 505 survit ». Mesure refaite
  sur la population actuelle : **0**, et le test ne résout pas son propre seuil.
- Le document annonce 4 bandes de tailles (4, 108, 96, 3) sur 211 wallets ; sur
  les 291 actuels les tailles sont différentes mais le nombre de bandes tient.
- L'audit demande « le PnL net entre dans les critères » de qualification. **Non
  appliqué** : c'est une modification de la règle scientifique scellée, qui exige
  une autorisation humaine explicite. Le PnL net est en revanche affiché en
  colonne de premier plan, avec `PnL hors max` et `Frais` à côté.
