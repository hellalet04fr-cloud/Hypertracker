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

Conséquence pratique pour cette session : **les sous-agents sont coupés**, tout se
fait en direct.

| Étape | État |
|---|---|
| 1 · Socle | **à moitié** — Vite, TS strict, jetons, contrat de données faits ; primitives, routage, layouts absents |
| 2 · Données | **fait, en avance** — `app/generer_web.py`, 163 lots, nouveaux champs statistiques |
| 3 · Liste | non commencé |
| 4 · Fiche et inspecteur | non commencé |
| 5 · Aujourd'hui et Données | non commencé |
| 6 · A11y, mouvement, golden files | non commencé |

### DÉCISIONS PRISES

- **Colonnes typées plutôt qu'un tableau d'objets** (contrat posé dans
  `src/domain/types.ts`) : 31 505 objets JS coûtent ~40 Mo et font tomber le
  premier rendu ; les colonnes en coûtent ~3 Mo.
- **`--faible` planchonné à 6,09:1** et les jetons de trace déclarés
  *non textuels* : mesure faite, `--s2` tombe à 4,42:1 sur `--eleve`, donc les
  couleurs de série peignent des formes, jamais des mots.
- **Ljung-Box est un diagnostic pur** (`ht/montecarlo.py`) : il n'alimente aucun
  score, aucun seuil, aucun classement. Chi2 implémenté par gamma incomplète
  régulière — ni scipy ni statsmodels ne sont garantis présents.
- **Le plancher de résolution du test de permutation est exporté vers l'écran.**
  À 2 000 tirages la plus petite p-valeur exprimable vaut 5,0 × 10⁻⁴, soit
  **520 fois** le seuil de Bonferroni (9,57 × 10⁻⁷) : `survivants = 0` est une
  limite d'instrument, pas un verdict sur les wallets. `meta.test_resolu`,
  `meta.resolution_p` et `meta.ic_boot_positif` existent pour que l'interface
  puisse le dire au lieu de le taire.

### DIVERGENCE SIGNALÉE, NON CORRIGÉE

Le document de reprise annonce « 1 wallet sur 31 505 survit ». Mesure refaite sur
la population actuelle (291 wallets mesurés, 52 259 explorés) : **0 survivant**,
et le test ne résout pas son propre seuil (voir ci-dessus). Ce qui reste
mesurable à cette résolution : **15 wallets sur 291** ont un intervalle de
bootstrap par blocs excluant zéro — avant toute correction pour tests multiples,
où l'on en attendrait une quinzaine par pur hasard. À ne pas présenter comme un
résultat.
