# HyperTracker — état complet du projet

Document de contexte destiné à être lu par un humain **et** ingéré par une IA, afin de
produire des prompts efficaces sur ce projet.

Mis à jour le **2026-08-26**.
Dépôt : `C:\Users\maram\Hypertracker` → github.com/hellalet04fr-cloud/Hypertracker (`main`)
Données runtime (hors Git) : `C:\Users\maram\ht_data`

**État chiffré au moment de la rédaction :**

| | |
|---|---|
| Commits | 13 |
| Modules `ht/` | 45 · `app/` 5 · tests 22 fichiers |
| Lignes de code | ~16 600 (hors tests) |
| Tests | **549** — 394 rapides (~45 s) + 155 lourds (`-m lent`) |
| Wallets classés | 248 |
| Trades analysés | 42 684 |
| Séries collectées | 256 |
| Registre | 31 668 wallets — 31 473 DISCOVERY, 195 RANKED, 0 ARCHIVED |
| Spearman OOS | 0.2651 (p = 0.0012) |
| ECE après calibration | 0.0647 |
| Verdict OBSERVED | **INCONCLUSIF** — 4 wallets sur 5 sous 30 trades natifs |

---

## 1. Ce qu'est le projet, et ce qui a été définitivement écarté

**Objectif unique, verrouillé dans le code** (`ht/garde.py`, constante `OBJECTIF`) :

> identifier, classer et suivre les wallets Hyperliquid les plus performants,
> avec un score statistique robuste et une confiance calibrée.

**Branches abandonnées — définitivement.** Listées en dur dans `BRANCHES_ABANDONNEES` ;
une garde automatique refuse toute tâche qui s'en approche :

- Liquidity Sweep / « sweep »
- recherche d'edge de trading
- optimisation d'exécution maker/taker
- optimisation TP/SL
- backtesting de stratégie
- bots de trading

Ces branches ont réellement été explorées puis fermées **sur mesure**, pas par principe.
Un prompt qui y revient sera bloqué par la garde — c'est le comportement voulu, pas un bug.

---

## 2. Chronologie — ce qui a été fait, et ce que chaque étape a appris

Cette section est la plus utile pour comprendre *pourquoi* le projet est dans son état
actuel. Chaque phase a produit un résultat, mais surtout une leçon qui contraint la suite.

### Phase 1 — Reconstruction des trades (fondation)

Reconstruire l'historique de trading d'un wallet à partir des *fills* publics Hyperliquid.
Machine à états flat-to-flat : un trade commence quand la position quitte zéro et se
termine quand elle y revient.

**Bugs réels corrigés :**
- La machine accumulait une position **non signée** → 137 cycles au lieu de 216, 37 % de
  non-réconciliation. Corrigé par une carte `_SENS` depuis `dir` + resynchronisation sur
  `startPosition` (qui fait autorité) → **1,7 %**.
- `user_funding` n'était **pas paginé** (plafond 500) → 4,4 % du funding capturé.
  `PAGES_MAX_FUNDING = 60` → **94 %**.

**Leçon :** la convention PnL est *brut − frais + funding*, et `startPosition` de chaque
fill est la source de vérité qui resynchronise l'état.

### Phase 2 — Le gate de réconciliation DERIVED / OBSERVED

Comparer notre reconstruction aux données natives HyperTracker.

**Bugs réels corrigés :**
- Le gate comparait **net contre brut** sous le même nom de champ → comparaison fausse et
  invisible. Corrigé par `CHAMP_HOMOLOGUE` explicite.
- 2 lignes natives avec `avgExit = 0` portaient 3 714 USD → MAE du gate à 10,847.
  `natifs_exploitables()` → **0,854**.

**Leçon :** deux champs qui portent le même nom ne mesurent pas forcément la même chose.

### Phase 3 — Le Deflated Sharpe qui a réfuté nos propres candidats

Le Deflated Sharpe (Bailey & López de Prado) corrige le Sharpe du nombre d'essais tentés.
Il manquait le facteur σ de dispersion inter-essais.

Une fois corrigé, mesure de la vraie dispersion (**σ = 0.1768**) → le critère est devenu
**plus strict**, et a fait tomber les 9 candidats que nous venions de produire.

**Ils n'ont pas été repêchés.** C'est l'événement le plus structurant du projet : le
protocole a réfuté son propre résultat et on l'a accepté.

### Phase 4 — Recadrage : le projet n'est pas une recherche d'edge

Plusieurs branches d'optimisation de trading ont été explorées puis fermées. L'objectif a
été re-verrouillé sur l'identification de wallets, et les branches abandonnées inscrites
dans la garde.

**Leçon :** la garde n'est pas de la bureaucratie — c'est ce qui empêche le projet de
redériver à chaque nouveau prompt.

### Phase 5 — Le modèle de score

Bayes hiérarchique empirique. Comparaison de trois modèles (A fréquentiste corrigé,
B bayésien empirique, C baseline régularisée) sur des critères **fixés à l'avance** dans
`specification_score_wallets.json` (scellé). **B gagne.**

**Bug réel corrigé :** la métrique de concentration `max(r)/sum(r)` était **indéfinie pour
163 wallets sur 231** (PnL total ≤ 0) et atteignait 34,38 là où une part vit dans [0,1].
Remplacée par la **part absolue bornée** `max|r| / Σ|r|` → ρ(score, concentration) passe
de **0,54 à 0,11**.

### Phase 6 — Calibration

Recalibrage isotonique sur un jeu dédié (74 en ajustement, 84 en test), pré-enregistré et
scellé. **ECE 0,1402 → 0,0647**, verdict LEVÉ.

**Conséquence non anticipée, qui bloque aujourd'hui :** seuls les *indicateurs* ont été
persistés, pas le modèle ajusté. Voir §9.

### Phase 7 — Couche d'agents autonomes

`quota.py`, `budgets.py`, `planificateur.py`, `orchestrateur.py`, `delegation.py`.

**Bugs réels corrigés :**
- La stagnation était définie sur le **succès d'exécution** → la boucle a tourné 20 fois
  sur le même audit. Redéfinie sur le **changement d'état**.
- Puis la stagnation n'avait **pas de sortie** → ajout d'`ignorer_stagnation` pour les
  invocations délibérées.
- Une fixture de test fuyait sur le `cycles.json` **de production** → monkeypatch.
- Récursion pytest : la tâche d'audit lançait son propre fichier de test.

### Phase 8 — L'application mobile, version 1

Première app : 5 onglets, palette sombre. Puis corrections successives issues d'usage réel
sur iPhone.

**Bugs réels corrigés :**
- `echant()` ne conservait **jamais le dernier point** → 39 courbes sur 231 se terminaient
  ailleurs que sur le PnL réel, pendant que la légende juste en dessous donnait le bon
  chiffre. Deux affichages contradictoires de la même grandeur.
- Texte coupé sur iPhone : `min-width: 0` manquant sur des enfants flex.
- Filtres de période décoratifs : à 56 points, 167 wallets sur 231 n'avaient plus qu'**un
  seul point** sur 7 jours. Résolution portée à 240 points, et les périodes à moins de
  3 points **désactivées** plutôt que de tracer une ligne mensongère.

**Deux faux positifs d'audit investigués plutôt qu'écartés :** « 94.2 » qui apparaissait à
l'intérieur de « 694.26 », et 179 « divergences » qui n'étaient qu'un arrondi d'affichage.

### Phase 9 — L'activité devient une dimension

Constat de l'utilisateur : *« la plupart des wallets que tu as classés étaient morts »*.
Mesure : **9 des 20 premiers n'avaient fait aucun trade en 30 jours**.

Ajout de `r30`, `r7`, `dort_j`. L'activité est une dimension **à côté** du score — elle ne
le modifie pas.

### Phase 10 — L'onglet Réputation

Demande : des traders performants *avec bonne réputation sur HyperTracker*.

**Mesure qui a changé la réponse :** recouvrement entre nos 231 wallets (issus des carnets)
et les 463 adresses de leaderboard = **0 sur 231**. Et sur 315 wallets de leaderboard,
**256 n'ont aucun trade clos** : ils tiennent des positions longtemps sans jamais revenir à
plat. Notre modèle compte des allers-retours clos ; il ne peut structurellement pas les
mesurer.

**Décision :** ne pas fusionner. L'onglet affiche les chiffres de HyperTracker,
explicitement attribués à HyperTracker, avec l'explication du pourquoi.

**Bug réel corrigé :** les leaderboards `all-pnl` agrègent le spot — un détenteur de tokens
y affichait **70 milliards**. Restreint à `perp-pnl`, métriques prises sur la **seule** ligne
du meilleur rang.

### Phase 11 — Le crash DuckDB qui cachait tout

`pytest` mourait sur une *Windows fatal exception: access violation*. Ce n'était ni une
lenteur ni un blocage : le processus entier tombait. **La suite de 503 tests n'avait donc
jamais pu être exécutée jusqu'au bout.**

**Cause :** une base DuckDB **en mémoire** ne déverse rien sur disque tant qu'on ne lui a
pas donné de `temp_directory`. Les jointures leave-one-out sur 16,5 M d'ordres dépassaient
la limite de 6,2 GiB et échouaient au lieu de basculer hors-cœur.

**Après correction :** la requête isolée rend 13 096 090 lignes en 124 s ; le test qui
tuait la suite passe en 374 s.

### Phase 12 — Refonte de l'interface : direction VERNIER

L'interface était un tableau augmenté. Reconstruction complète autour d'une contrainte de
**vérité**, pas d'ornement :

> un chiffre n'est jamais montré sans l'échelle sur laquelle il a été lu,
> ni sans l'incertitude avec laquelle il a été lu.

**Le dispositif INDEX + MORS**, appliqué partout :
- le **score** est une *position* : index ambre sur un rail gradué 0–100 ;
- l'**incertitude** est un *écartement* : les mâchoires d'un pied à coulisse posées aux
  bornes de l'intervalle de crédibilité à 95 % ;
- la **qualité des données** est une *fermeté de trait* : mâchoires pleines, tiretées ou
  pointillées.

Conséquence permanente et sans avertissement écrit : un wallet à 100 dont l'échantillon est
mince se lit comme un index collé à l'extrémité du rail, tenu par des mâchoires larges et
tiretées. *Performance élevée n'est pas confiance élevée* — porté par la forme.

**Découverte majeure :** l'interface précédente appelait « confiance » **deux grandeurs
différentes**, produisant l'absurdité « confiance 30 % — confiance élevée ». Ce sont :

| Champ | Ce que c'est réellement |
|---|---|
| `conf_lab` / `qualite` | **Qualité des données** — nombre de critères satisfaits sur 3 |
| `conf` (`p_cal`) | **Probabilité calibrée** que le vrai Sharpe soit positif |
| `ic` | **Intervalle de crédibilité à 95 %** sur le score |

Elles sont désormais nommées séparément partout.

**Bugs réels trouvés en exécutant (pas en relisant) :**
- Les pistes de grille prenaient la largeur **minimale de leur contenu** → barre de
  navigation à 324 px sur un écran de 320. Corrigé par `minmax(0, 1fr)`.
- Le débord par marges négatives se résolvait à **−20 px au lieu de −16** et poussait la
  page hors de la fenêtre.
- Les légendes explicatives étaient tronquées par ellipse — *une explication amputée de sa
  fin n'explique plus rien*.
- La courbe de drawdown recalculée naïvement contredisait le champ `dd` affiché à côté sur
  **57 wallets, jusqu'à 5 499 USD d'écart** : le moteur fait partir le sommet de 0, pas du
  premier point.
- Le sous-échantillonnage supprimait le **point de creux maximal**, redonnant 19,57 USD
  d'écart. *Un point remarquable ne se sous-échantillonne pas.*

**Note méthodologique :** l'extension navigateur n'étant pas connectée, l'app a été pilotée
par le **protocole DevTools**. `--window-size` était ignoré par le mode headless installé :
le viewport restait figé à 477 px et les premières captures **mentaient**. Sans ce
diagnostic, trois défauts réels seraient passés.

### Phase 13 — Automatisation complète (dernière en date)

HyperTracker cesse d'être un classement figé. Voir §5 pour l'architecture.

**Découverte structurante :** **le classement n'était pas dans le dépôt.** Aucun fichier ne
produisait `classement_wallets.json` — le calcul vivait dans un répertoire de travail
temporaire. Aucune automatisation n'était possible : *on ne peut pas rejouer ce qu'on n'a
pas*. Rapatrié à l'identique dans `ht/scoring.py` + `ht/classement.py`, avec vérification
exigeante : mêmes wallets, même ordre, **zéro champ divergent** sur les 231 de production.

**Correction importante évitée de justesse :** j'ai failli archiver **33 wallets à tort**.
Le champ `jours` mesure l'écart entre le premier et le dernier trade *clos* ; le seuil
`MIN_JOURS` porte sur les *jours couverts*, toujours supérieurs. C'est une **borne
inférieure** : elle prouve quand elle passe, elle ne réfute pas quand elle échoue.

**Bugs réels trouvés en exécutant :**
- **43 alertes RANK_DOWN pour zéro dégradation.** Neuf wallets étaient entrés au classement ;
  tous ceux du dessous avaient perdu des places sans décliner. Les alertes de rang exigent
  désormais un déplacement de **position relative**.
- **65 requêtes dépensées pour un budget de 60** : la vérification arrivait après coup. On
  n'engage plus un wallet que si son *pire cas* tient dans le budget restant.

---

## 3. Les invariants — ils ne se négocient pas

| # | Invariant | Conséquence concrète |
|---|---|---|
| 1 | **Clé API** uniquement dans `HYPERTRACKER_API_TOKEN` | Jamais affichée, loggée, commitée, mise dans `.env.example`, ni exposée au frontend. Absente → arrêt sur `HYPERTRACKER_API_TOKEN is missing.` |
| 2 | **Aucune donnée fictive** | Une valeur manquante s'affiche `N/D`. Jamais comblée, jamais estimée. |
| 3 | **DERIVED ≠ OBSERVED** | Jamais mélangés, jamais l'un converti en l'autre. Seul OBSERVED peut certifier. |
| 4 | **Aucun seuil abaissé** pour faire passer un candidat | 12 seuils scellés par SHA256 (§7). |
| 5 | **Jamais « smart money » sur le seul PnL** | Le PnL sans mesure de risque ni de chance n'est pas un signal. |
| 6 | **Pas de contournement de quota**, pas de retry agressif | Les limites de service sont respectées, même quand elles bloquent. |

**Ces invariants ont déjà réfuté nos propres résultats** (Deflated Sharpe, phase 3). Ce ne
sont pas des slogans.

---

## 4. Le modèle scientifique

**Bayes hiérarchique empirique.** La variable latente est le vrai Sharpe par trade du
wallet ; l'observé est rétréci vers un a priori estimé par **déconvolution** sur une
population non biaisée (wallets tirés des carnets par hachage) :

```
tau² = max(0, dispersion_robuste² − moyenne(SE²))
a priori d'origine : m = −0.0724, tau = 0.0744
post = (tau²·sr + se²·m) / (tau² + se²)
psd  = sqrt(tau²·se² / (tau² + se²))
score = 100 · Φ(post / tau)
ic    = 100 · Φ((post ∓ 1.96·psd) / tau)
```

- Erreur-type du Sharpe corrigée asymétrie/kurtosis (**Mertens**).
- **Deflated Sharpe** avec facteur σ = 0.1768 réellement mesuré.
- **Concentration** : part absolue bornée `max|r| / Σ|r|`.
- **Drawdown** : sommet initialisé à **0**, pas au premier point.
- **Calibration** : isotonique, ECE à binning par quantiles, Brier.
- **Validation** : splits OOS *purged/embargoed* (`ht/oos.py`, MIN_PAR_BLOC = 50), block
  bootstrap, tests de permutation par inversion de signe.

**L'a priori est réestimé sur la population** à chaque cycle — c'est la définition de la
méthode. Ce qui serait fautif, et que le projet s'interdit, c'est de le réestimer sur une
**sous-population de gagnants** : cela rétrécirait tout le monde vers une moyenne de
gagnants et gonflerait l'ensemble.

---

## 5. Architecture

### 5.1 Couche scientifique — `ht/` (45 modules)

| Module | Rôle |
|---|---|
| `garde.py` | **Le seul module autorisé à dire NON.** 4 familles : DERIVE, SCELLES (SHA256), SEUILS (12 constantes), PROVENANCE. |
| `scoring.py` | Primitives du score, reprises à l'identique. **Aucune science nouvelle.** |
| `classement.py` | Le classement complet, rejouable. |
| `quota.py` | Le **429 fait autorité**, pas le compteur local (qui a divergé : 100 → 98 → 76). Reset mesuré à **03:00 UTC**. |
| `budgets.py` | `Cout(...)` ; `autorise()` refuse sur la disponibilité **et** sur le ROI. |
| `screening.py` | Criblage à deux étages : triage 1 requête (écarte 67 %), reconstruction pour les survivants. Porte les **critères de candidature pré-enregistrés**. |
| `behavior.py` | Profil comportemental DuckDB sur 16,5 M d'ordres. Jointures *leave-one-out* : un wallet n'est jamais sa propre référence. |
| `planificateur.py` | Les tâches **descendent des verrous enregistrés**. Verrou inconnu → diagnostic, puis délégation. |
| `orchestrateur.py` | Stagnation définie sur le **changement d'état**. |
| `delegation.py` | `claude -p` headless, gardes sur le prompt **avant** envoi et sur la sortie **avant** acceptation. |

### 5.2 Couche automatisation (la plus récente)

**Trois états persistants** (`ht/registre.py`, SQLite en **append seul**) :

| État | Sens |
|---|---|
| `DISCOVERY` | découvert, pas encore assez documenté |
| `RANKED` | satisfait les critères de candidature — **apparaît dans l'app** |
| `ARCHIVED` | ne les satisfait plus. **Aucune donnée n'est jamais supprimée** |

Retour `ARCHIVED → RANKED` automatique dès requalification.

**La règle centrale** — `ht/lifecycle.qualifies_for_ranking()` — est déterministe et
n'utilise **que** les seuils pré-enregistrés. **Le score ne participe pas à la
qualification** : il classe des wallets déjà qualifiés. L'y faire entrer reviendrait à
sélectionner sur la performance, donc à fabriquer un classement de survivants.

Quatre verdicts : `EXCELLENT_CANDIDATE`, `PROMISING`, `INSUFFICIENT_DATA`, `REJECTED`.

**L'asymétrie fondamentale :** on promeut sur une preuve, **on retire sur une preuve**. Un
critère que les données locales ne permettent pas de trancher (`indetermines`) ne peut
jamais motiver un archivage.

**Le cycle** (`ht/matin.py`) — 9 phases, `--dry-run` intégral, **0 requête HyperTracker** :

```
DATA → DISCOVERY → COLLECTE → EVALUATION → RANKING → LIFECYCLE → ALERTS → REPORT → UI
```

- **DISCOVERY** : carnets d'ordres + leaderboards, dédupliqué, avec provenance et date.
- **COLLECTE** : bornée par un **budget de requêtes**, jamais par un nombre de candidats à
  trouver — une règle d'arrêt indexée sur la performance biaiserait la sélection.
- **ALERTS** : 10 catégories, dédupliquées par catégorie + adresse + jour.
- **REPORT** : `daily_report.json` — new today, movers, declining, archived, top 20, data
  health, system health, **blocages**.

Planifié par `ht/planifier.py` à **08:00 Europe/Paris** (heure locale, donc l'heure d'été
est suivie automatiquement ; le module **refuse d'installer** si l'horloge machine ne
coïncide pas avec Paris).

### 5.3 Couche données

**Hyperliquid (gratuit)** — `userFills`, `userFillsByTime`, `userFunding`,
`candleSnapshot`, `fundingHistory`, `meta`. Reconstruction flat-to-flat.

**HyperTracker (quota)** — `/api/external/closed-trades`, `/closed-trades/summary`,
`/fills`. Fenêtre plafonnée à **30 jours** (confirmé par 7 × HTTP 400). Quota **global**,
pas par endpoint. WebSocket indisponible sur l'offre Free.

### 5.4 Couche application — `app/` (5 scripts)

App mobile, direction VERNIER, 4 onglets : **Quotidien / Classement / Recherche /
Watchlist**. Routage par fragment — le bouton retour du système fonctionne, une fiche est
une **vraie page adressable**, et l'état de filtrage comme la position de défilement sont
restitués au retour.

| Script | Rôle |
|---|---|
| `prepare_donnees.py` | Précalcule tout. Connecté au registre (statut, historique, rapport). |
| `generer_app.py` | Génère le HTML autonome (1,98 Mo). |
| `audit_donnees.py` | **Recalcule tout indépendamment.** 12 compteurs, tous à zéro, sinon « ANOMALIE — ne pas publier ». |
| `collecter_reputation.py` | A priori **scellé** appliqué tel quel, jamais réestimé sur des gagnants. |
| `prepare_reputation.py` | Restreint aux leaderboards `perp-pnl`. |

---

## 6. Faits établis empiriquement — ne pas re-débattre

Chacun a coûté du temps de mesure. Les redemander est du gaspillage.

1. **Segmentation flat-to-flat validée** : 0 chevauchement sur 324 paires natives.
2. **Populations disjointes** : 231 wallets de carnets et 463 adresses de leaderboard →
   **0 recouvrement sur 231**.
3. **Les whales de leaderboard sont structurellement non mesurables** par un modèle de
   trades clos : 256/315 ont **zéro** trade clos. Verrou externe, pas un bug.
4. **PnL de compte ≠ performance par trade clos.** Les wallets de leaderboard scorables ont
   un Sharpe négatif malgré des rangs élevés. Ne pas fusionner les deux grandeurs.
5. **Le cap 30 jours est réel.** Aucun contournement légitime du quota n'existe.
6. **Les leaderboards `all-pnl` agrègent le spot** — inutilisables pour mesurer du trading.
7. **`jours` (écart entre trades clos) ≠ `jours_couverts`.** Le premier est une borne
   inférieure du second.
8. **Une base DuckDB en mémoire ne déborde pas sur disque** sans `temp_directory`.

---

## 7. Les 12 seuils scellés

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

**Critères de candidature pré-enregistrés** (`ht/screening.py`) :
`MIN_TRADES = 30`, `MIN_JOURS = 130.0`, `MAX_CONCENTRATION = 0.40`, `MAX_TRONCATURE = 0.20`.

**Critères de qualité de données** (`ht/classement.py`) : `n ≥ 150`, `conc ≤ 0.40`,
`jours ≥ 130`. Le compte des trois donne `qualite` (0–3) et le libellé faible / moyenne /
élevée.

**Fichiers scellés :** `specification_score_wallets.json`,
`preenregistrement_calibration.json`, `preenregistrement_observed.json` — les trois
vérifiés intacts.

---

## 8. Catalogue des bugs réels (le plus instructif)

| Défaut | Effet mesuré | Correction |
|---|---|---|
| Position non signée | 137 cycles au lieu de 216 ; 37 % non réconciliés | carte `_SENS` + resync → **1,7 %** |
| `user_funding` non paginé | 4,4 % du funding capturé | `PAGES_MAX_FUNDING = 60` → **94 %** |
| Gate net contre brut | comparaison fausse et invisible | `CHAMP_HOMOLOGUE` explicite |
| 2 lignes `avgExit = 0` | MAE 10,847 | `natifs_exploitables()` → **0,854** |
| Deflated Sharpe sans σ | seuil trop laxiste, puis **plus strict** | facteur rétabli, 9 candidats abandonnés |
| Concentration `max/somme` | indéfinie 163/231, max 34,38, ρ = 0,54 | part absolue bornée → **ρ = 0,11** |
| Stagnation sur succès | 20 tours sur le même audit | redéfinie sur changement d'état |
| `echant()` sans dernier point | 39 courbes finissant sur le mauvais PnL | dernier point toujours conservé |
| Fusion de leaderboards | rang d'un tableau + métriques d'un autre | une seule ligne, le meilleur rang |
| DuckDB sans `temp_directory` | **crash processus, suite de tests jamais terminée** | débordement disque → test passe en 374 s |
| Grilles `1fr` | nav à 324 px sur écran de 320 | `minmax(0, 1fr)` |
| Marges négatives en flex | −20 px au lieu de −16 | rangées sorties du conteneur |
| Drawdown depuis le 1ᵉʳ point | 57 wallets, jusqu'à 5 499 USD d'écart | sommet à 0 → écart **0,005** |
| Creux sous-échantillonné | 19,57 USD d'écart | point de creux forcé |
| Alertes de rang absolues | **43 fausses alertes** | position relative exigée |
| Budget vérifié après coup | 65 requêtes pour 60 | pire cas vérifié **avant** |

**Trois faux positifs d'audit investigués plutôt qu'écartés** : « 94.2 » dans « 694.26 »,
179 « divergences » d'arrondi d'affichage, et un angle mort réel — l'audit n'excluait qu'un
bloc de données ; l'ajout d'un second faisait remonter des faux positifs. **L'audit a été
corrigé, pas assoupli.**

---

## 9. Blocages ouverts, et leur nature

| Blocage | Nature | Détail |
|---|---|---|
| **Probabilité calibrée non rejouable** | **Interne, actif** | Le modèle isotonique ajusté n'a **jamais été persisté** — seuls ses indicateurs le sont (ECE 0,0647). **17 wallets** n'ont donc pas de `p_cal` et affichent N/D. Le réajuster serait une décision scientifique sur un objet scellé : **interdit sans autorisation explicite**. Le rapport quotidien les compte à chaque cycle. |
| Whales de leaderboard non mesurables | **Externe, structurel** | Demanderait un modèle *mark-to-market* sur positions ouvertes — c'est-à-dire un autre objet de mesure. |
| Quota HyperTracker | **Externe** | Aucun contournement légitime. Reset 03:00 UTC. Le cycle quotidien n'en dépense **aucun**. |
| Verdict OBSERVED | **Externe** | **INCONCLUSIF** : 4 wallets sur 5 sous 30 trades natifs. Ne jamais convertir en validation. |

---

## 10. Comment donner les meilleurs prompts

### Ce qui fonctionne

- **Un objectif mesurable unique** par prompt. Pas dix chantiers.
- **Me laisser l'autonomie technique** : décider et exécuter sans confirmation pour ce qui
  est raisonnable.
- **M'autoriser explicitement à conclure « impossible » ou « non pertinent ».** Les
  meilleures contributions du projet ont été des refus argumentés.
- **Demander la mesure avant la construction.** « Mesure d'abord si X vaut le coup » évite
  de bâtir du décoratif.
- **Demander une vérification par exécution, pas par relecture.** Presque tous les défauts
  réels de ce projet sont sortis en faisant tourner le code, jamais en le relisant.

### Ce qui échoue

- « Fais que le wallet X passe le gate » → refus (revient à abaisser un seuil).
- « Estime la donnée manquante » → `N/D` sera affiché.
- « Sprint 24 h, 15 objectifs » → dispersion. Découper.
- Revenir sur une branche abandonnée → la garde bloque.

### Gabarit de prompt

```
OBJECTIF          : [une phrase, mesurable]
CONTRAINTE        : [invariant concerné, ex. « sans toucher aux seuils scellés »]
CRITÈRE DE SUCCÈS : [comment on saura que c'est fait]
CRITÈRE D'ARRÊT   : [quand abandonner plutôt que forcer]
```

### Format de rapport attendu

Progression en %, verrous rencontrés, prochaine action unique.

---

## 11. Commandes utiles

```bash
python -m ht.matin --dry-run       # montre tout, n'écrit rien, n'appelle rien
python -m ht.matin                 # cycle réel
python -m ht.matin --budget 200    # ajuste le budget de collecte
python -m ht.planifier --etat      # état de la tâche 08:00
python -m ht.classement            # recalcule le classement seul
python app/prepare_donnees.py      # prépare les données de l'app
python app/generer_app.py          # génère l'app
python app/audit_donnees.py        # audit d'authenticité (12 compteurs à zéro)
pytest                             # 394 tests rapides, ~45 s
pytest -m lent                     # 155 tests sur le lac de données
```
