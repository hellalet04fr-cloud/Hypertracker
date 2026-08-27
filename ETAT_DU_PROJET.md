# HyperTracker — état complet du projet

Document de contexte destiné à être lu par un humain **et** ingéré par une IA, afin de
produire des prompts efficaces sur ce projet. Mis à jour le 2026-08-25.

Dépôt : `C:\Users\maram\Hypertracker` → github.com/hellalet04fr-cloud/Hypertracker (`main`)
Données runtime (hors Git) : `C:\Users\maram\ht_data`

---

## 1. L'objectif, et ce qui a été définitivement écarté

**Objectif unique, verrouillé dans le code** (`ht/garde.py`, constante `OBJECTIF`) :

> identifier, classer et suivre les wallets Hyperliquid les plus performants,
> avec un score statistique robuste et une confiance calibrée.

**Branches abandonnées — définitivement.** Elles sont listées en dur dans
`BRANCHES_ABANDONNEES` et une garde automatique refuse toute tâche qui s'en approche :

- Liquidity Sweep / « sweep »
- recherche d'edge de trading
- optimisation d'exécution maker/taker
- optimisation TP/SL
- backtesting de stratégie
- bots de trading

Ces branches ont réellement été explorées puis fermées sur mesure, pas par principe.
Un prompt qui y revient sera bloqué par la garde — c'est le comportement voulu.

---

## 2. Les invariants — ils ne se négocient pas

Ils forment la colonne vertébrale. Un bon prompt ne demande jamais de les enfreindre.

| # | Invariant | Conséquence concrète |
|---|---|---|
| 1 | **Clé API** uniquement dans la variable d'environnement `HYPERTRACKER_API_TOKEN` | Jamais affichée, jamais loggée, jamais commitée, jamais dans `.env.example`, jamais exposée au frontend. Absente → arrêt sur le message exact `HYPERTRACKER_API_TOKEN is missing.` |
| 2 | **Aucune donnée fictive** | Une valeur manquante s'affiche `N/A`. Jamais comblée, jamais estimée, jamais illustrée. |
| 3 | **DERIVED ≠ OBSERVED** | Jamais mélangés, jamais l'un converti en l'autre. Seul OBSERVED peut certifier. |
| 4 | **Aucun seuil abaissé** pour faire passer un candidat | 12 seuils scellés par SHA256 (voir §5). |
| 5 | **Jamais « smart money » sur le seul PnL** | Le PnL sans mesure de risque ni de chance n'est pas un signal. |
| 6 | **Pas de contournement de quota**, pas de retry agressif | Les limites de service sont respectées, même quand elles bloquent. |

**Ces invariants ont déjà réfuté nos propres résultats.** Exemple : le Deflated Sharpe,
une fois corrigé du facteur σ manquant, a fait tomber nos 9 candidats. Ils n'ont pas été
repêchés.

---

## 3. Architecture

### 3.1 Couche scientifique — `ht/` (37 modules)

**Le modèle de score.** Bayes hiérarchique empirique. La variable latente est le vrai
Sharpe par trade du wallet ; l'observé est rétréci vers un a priori estimé par
déconvolution sur une population **non biaisée** :

```
tau² = max(0, dispersion_robuste² − moyenne(SE²))
a priori scellé : m = −0.0724, tau = 0.0744
```

- Erreur-type du Sharpe corrigée skew/kurtosis (**Mertens**).
- **Deflated Sharpe** (Bailey & López de Prado), avec le facteur σ de dispersion
  inter-essais réellement mesuré (σ = 0.1768).
- **Concentration** : part absolue bornée du meilleur trade. L'ancienne métrique
  `max(r)/sum(r)` était indéfinie pour 163/231 wallets et corrélée au score (ρ = 0.54) ;
  la nouvelle est à ρ = 0.11.
- **Calibration** : recalibrage isotonique, ECE à binning par quantiles, score de Brier.
- **Validation** : splits OOS temporels *purged/embargoed* (`ht/oos.py`), block bootstrap,
  tests de permutation par inversion de signe.

**Modules structurants :**

| Module | Rôle |
|---|---|
| `garde.py` | **Le seul module autorisé à dire NON.** 4 familles : DERIVE (branches abandonnées), SCELLES (SHA256), SEUILS (12 constantes), PROVENANCE (DERIVED ne certifie jamais). |
| `quota.py` | Le **429 fait autorité**, pas le compteur local (qui a divergé : 100 → 98 → 76). Reset mesuré à **03:00 UTC**. |
| `budgets.py` | `Cout(hypertracker, hyperliquid, cpu_s, tokens_k)` ; `autorise()` refuse sur la disponibilité **et** sur le ROI. |
| `planificateur.py` | Les tâches **descendent des verrous enregistrés**. Verrou inconnu → diagnostic, puis tâche déléguée — jamais d'improvisation. |
| `orchestrateur.py` | Cycle : garde → stagnation → plan → budget → exécution → tests → audit → journal. La stagnation est définie sur le **changement d'état**, pas sur le succès d'exécution (une définition naïve avait fait tourner 20 fois le même audit). |
| `delegation.py` | `claude -p` headless, gardes sur le prompt **avant** envoi et sur la sortie **avant** acceptation, `--max-turns`, `--permission-mode plan`. |
| `behavior.py` | Profil comportemental via DuckDB sur les snapshots de carnet (16,5 M d'ordres). Jointures *leave-one-out* : un wallet n'est jamais sa propre référence. |

### 3.2 Couche données

**Hyperliquid (gratuit)** — `userFills`, `userFillsByTime`, `userFunding`,
`candleSnapshot`, `fundingHistory`, `meta`.

- Reconstruction d'état **flat-to-flat**. `startPosition` de chaque fill fait autorité
  et resynchronise la machine à états.
- Convention PnL : **brut − frais + funding**.

**HyperTracker (quota)** — `/api/external/closed-trades`, `/closed-trades/summary`,
`/fills`.

- Fenêtre plafonnée à **30 jours** — confirmé empiriquement (7 × HTTP 400 sur fenêtre large).
- Quota **global**, pas par endpoint. WebSocket indisponible sur l'offre Free.
- Le niveau *fill* de `/fills` est DERIVED, donc ne certifie pas.

### 3.3 Couche automatisation — le cycle du matin

Depuis le 2026-08-25, HyperTracker n'est plus un classement fige : c'est un cycle
qui tourne seul.

**Trois etats persistants** (`ht/registre.py`, SQLite en append seul) :

| Etat | Sens |
|---|---|
| `DISCOVERY` | decouvert, pas encore assez documente |
| `RANKED` | satisfait les criteres de candidature — **apparait dans l'app** |
| `ARCHIVED` | ne les satisfait plus. **Aucune donnee n'est jamais supprimee** |

Le retour `ARCHIVED -> RANKED` est automatique des requalification.

**La regle centrale** — `ht/lifecycle.qualifies_for_ranking()` — est deterministe et
n'utilise **que** les seuils pre-enregistres de `ht/screening.py`. Le score ne participe
pas a la qualification : il classe des wallets deja qualifies. Quatre verdicts :
`EXCELLENT_CANDIDATE`, `PROMISING`, `INSUFFICIENT_DATA`, `REJECTED`.

**Asymetrie assumee** : on promeut sur une preuve, on retire sur une preuve. Un critere
que les donnees locales ne permettent pas de trancher ne peut **jamais** motiver un
archivage.

**Le cycle** (`ht/matin.py`) — 9 phases, `--dry-run` complet, **0 requete HyperTracker** :
DATA, DISCOVERY, COLLECTE, EVALUATION, RANKING, LIFECYCLE, ALERTS, REPORT, UI.
Planifie par `ht/planifier.py` a **08:00 Europe/Paris** (heure locale, donc l'heure d'ete
est suivie automatiquement ; le module refuse d'installer si l'horloge machine ne coincide
pas avec Paris).

**Le classement est enfin dans le depot.** `ht/scoring.py` et `ht/classement.py` reprennent
a l'identique les primitives qui vivaient hors depot — verifie : **zero champ divergent**
sur les 231 wallets de production. Sans cela, aucune automatisation n'etait possible.

### 3.4 Couche application — `app/` (5 scripts)

App mobile réelle, 5 onglets : **Classement / Recherche / Watchlist / Comparer / Réputation**.
Palette terminal sombre, Manrope + IBM Plex Mono, safe-area iPhone, `viewport-fit=cover`.

| Script | Rôle |
|---|---|
| `prepare_donnees.py` | Précalcule tout. Sous-échantillonnage `echant()` qui **conserve toujours le dernier point**. Ajoute `r30`, `r7`, `dort_j` (activité). |
| `generer_app.py` | Génère le HTML autonome. Pagination 40, tri combiné `duo()` (60 % score / 40 % activité). |
| `audit_donnees.py` | **Recalcule tout indépendamment** depuis les fichiers bruts. 9 compteurs, tous doivent valoir zéro, sinon « ANOMALIE — ne pas publier ». |
| `collecter_reputation.py` | Score les wallets de leaderboard avec l'a priori **scellé** (jamais réestimé sur des gagnants). |
| `prepare_reputation.py` | Restreint aux leaderboards `perp-pnl`. Métriques prises sur la **seule** ligne du meilleur rang. |

---

## 4. Faits établis empiriquement — ne pas re-débattre

Chacun a coûté du temps de mesure. Les redemander est du gaspillage.

1. **Segmentation flat-to-flat validée** : 0 chevauchement sur 324 paires natives.
2. **Populations disjointes** : les 231 wallets issus des carnets (tirage par hash, non
   biaisé) et les 463 adresses de leaderboard ont **0 recouvrement sur 231**.
3. **Les whales de leaderboard sont structurellement non mesurables** par un modèle de
   trades clos : elles ne reviennent jamais à plat. 256/315 ont **zéro** trade clos.
   Ce n'est pas un bug à corriger, c'est un verrou externe.
4. **PnL de compte ≠ performance par trade clos.** Les 2 wallets scorables des
   leaderboards ont un Sharpe négatif malgré des rangs HyperTracker élevés. Les deux
   grandeurs ne sont pas comparables — ne pas les fusionner.
5. **Le cap 30 jours est réel.** Aucun contournement légitime du quota n'existe
   (documenté comme BLOQUÉ PAR RESSOURCE EXTERNE).
6. **Les leaderboards `all-pnl` agrègent le spot** : un simple détenteur de tokens y
   affiche 70 milliards. Inutilisables pour mesurer une performance de trading.

---

## 5. Les 12 seuils scellés

Vérifiés par SHA256 à chaque cycle. Les abaisser est interdit.

```
ht.gate.MIN_PAIRES_APPARIEES            = 100
ht.gate.MAX_TAUX_NON_RECONCILIABLE      = 0.2
ht.gate.MIN_CONCORDANCE_PNL             = 0.9
ht.gate.MAX_MAE_PNL_RELATIVE            = 0.02
ht.gate.MAX_ECART_TEMPS_MS              = 60000
ht.gate.MAX_ECE_CERTIFIEE               = 0.1
ht.final_gate.MAX_PART_MEILLEUR_TRADE   = 0.4
ht.final_gate.MAX_DEGRADATION_RELATIVE  = 0.5
ht.final_gate.MAX_PART_FRAIS            = 0.5
ht.oos.MIN_PAR_BLOC                     = 50
ht.calibration.MIN_OBS_CALIBRATION      = 50
ht.ranking.MIN_TRADES_FOR_RANKING       = 30
```

Fichiers scellés : `specification_score_wallets.json`,
`preenregistrement_calibration.json`, `preenregistrement_observed.json` — les trois
sont vérifiés intacts.

---

## 6. Bugs réels trouvés et corrigés (échantillon instructif)

Ces corrections montrent le type de défaut qui compte sur ce projet.

| Défaut | Effet mesuré | Correction |
|---|---|---|
| Machine à états accumulait une position non signée | 137 cycles au lieu de 216 ; 37 % non réconciliés | Carte `_SENS` depuis `dir` + resync `startPosition` → **1,7 %** |
| `user_funding` non paginé (plafond 500) | 4,4 % du funding capturé | `PAGES_MAX_FUNDING = 60` → **94 %** |
| Gate comparait net contre brut sous le même nom de champ | Comparaison fausse et invisible | `CHAMP_HOMOLOGUE` explicite |
| 2 lignes natives à `avgExit = 0` portant 3 714 USD | MAE du gate à 10,847 | `natifs_exploitables()` → **0,854** |
| Deflated Sharpe sans le facteur σ | Seuil trop laxiste ; puis, corrigé, **plus strict** — a réfuté nos propres candidats | Facteur rétabli, candidats abandonnés |
| `echant()` ne gardait jamais le dernier point | 39 courbes sur 231 finissaient sur le mauvais PnL, la légende affichant le bon | Dernier point toujours conservé |
| Fusion de leaderboards | Rang d'un tableau mêlé aux métriques d'un autre | Métriques prises sur une seule ligne |
| **DuckDB : base en mémoire sans `temp_directory`** | *Windows access violation* → **la suite de 503 tests n'avait jamais pu aller au bout** | Répertoire de débordement + `preserve_insertion_order=false`. Test passe en 374 s. |

**Deux faux positifs d'audit ont été investigués plutôt qu'écartés** : « 94.2 » qui
apparaissait à l'intérieur de « 694.26 », et 179 « divergences » qui n'étaient qu'un
arrondi d'affichage à une décimale. Le troisième cas a révélé un vrai angle mort :
l'audit n'excluait qu'un seul bloc de données, l'ajout d'un second faisait remonter des
faux positifs. **L'audit a été corrigé, pas assoupli.**

---

## 7. État actuel

- Onglet **Réputation** livré : chiffres HyperTracker explicitement attribués à
  HyperTracker, avec encadré expliquant pourquoi aucun score maison n'y figure.
  Coût : 463 requêtes Hyperliquid, **0 requête HyperTracker**.
- Dimension **activité** intégrée au classement (les wallets morts étaient un vrai
  problème signalé).
- Audit d'authenticité : **9 compteurs à zéro** — « AUCUNE DONNÉE FICTIVE ».
- Les 4 gardes répondent correctement, dont le refus attendu de DERIVED pour certifier.
- 189 tests cœur passent en 16 s. La suite complète (503 tests) est désormais
  exécutable, mais reste lente : certains tests sur données réelles prennent plusieurs
  minutes chacun.
- Tout est poussé sur `main`.

---

## 8. Comment me donner les meilleurs prompts

### Ce qui fonctionne

- **Un objectif mesurable unique** par prompt. « Fais passer l'ECE sous 0.10 », « trouve
  pourquoi la suite de tests ne finit pas ». Pas une liste de dix chantiers.
- **Me laisser l'autonomie technique.** Décider et exécuter sans demander confirmation
  pour ce qui est raisonnable.
- **M'autoriser explicitement à conclure « impossible » ou « non pertinent ».** Les
  meilleures contributions de ce projet ont été des refus argumentés, pas des livrables.
- **Demander la mesure avant la construction.** « Mesure d'abord si X vaut le coup »
  évite de bâtir des choses décoratives.

### Ce qui échoue

- « Fais que le wallet X passe le gate » → refus (revient à abaisser un seuil).
- « Estime la donnée manquante » → `N/A` sera affiché à la place.
- « Sprint 24 h, 15 objectifs » → dispersion. Découper.
- Revenir sur une branche abandonnée → la garde bloque.

### Gabarit de prompt

```
OBJECTIF          : [une phrase, mesurable]
CONTRAINTE        : [invariant concerné, ex. « sans toucher aux seuils scellés »]
CRITÈRE DE SUCCÈS : [comment on saura que c'est fait]
CRITÈRE D'ARRÊT   : [quand abandonner plutôt que forcer]
```

### Format de rapport attendu en retour

Progression en %, verrous rencontrés, prochaine action unique.

---

## 9. Verrous ouverts

| Verrou | Nature | Contournement |
|---|---|---|
| **Probabilite calibree non rejouable** | **Interne** | Le modele isotonique ajuste n'a jamais ete persiste — seuls ses indicateurs le sont (ECE 0.0647). Un wallet apparu depuis n'a donc pas de `p_cal` et affiche N/D. Le reajuster serait une decision scientifique sur un objet scelle : interdit sans autorisation explicite. Le rapport quotidien compte ces wallets. |
| Whales de leaderboard non mesurables | **Externe et structurel** | Demanderait un modèle *mark-to-market* sur positions ouvertes — c'est-à-dire un autre objet de mesure, pas une amélioration de celui-ci. |
| Quota HyperTracker | **Externe** | Aucun contournement légitime. Reset à 03:00 UTC. |
| Suite de tests lente | Interne, non bloquant | Les tests sur données réelles manipulent 16,5 M de lignes. Séparer les marqueurs `reel` du cycle rapide serait la piste. |
