/**
 * LE CONTRAT DE DONNÉES.
 *
 * Rien dans `domain/` n'importe React : c'est ce qui rend ces calculs testables
 * sans DOM et réutilisables dans un worker. La règle vaut aussi pour ce
 * fichier — il ne décrit que des formes, jamais du rendu.
 *
 * La page précédente embarquait 1 003 ko de JSON d'un bloc, dont 160 ko pour
 * afficher trois nombres. Ici le document est découpé selon ce qu'un écran a
 * réellement besoin de lire : `meta` et `index` pour la liste, un lot par
 * préfixe d'adresse pour le détail.
 */

/** Étiquette de qualité des données — trois critères satisfaits sur trois. */
export type Qualite = 'elevee' | 'moyenne' | 'faible'

/** État de cycle de vie, tel que le registre le connaît. */
export type Etat = 'RANKED' | 'DISCOVERY' | 'ARCHIVED'

/**
 * UNE LIGNE DE LISTE. Exactement les champs qu'une liste affiche ou trie —
 * rien de plus. Le détail vit dans un lot, chargé à l'ouverture d'une fiche.
 */
export interface Ligne {
  /** adresse, minuscules, préfixe 0x compris */
  a: string
  /** rang exact : conservé pour l'URL et le tri, PAS pour l'affichage */
  rang: number
  /** bande d'équivalence — c'est elle qui s'affiche à la place du rang */
  groupe: number
  /** 0–100 */
  score: number
  /** intervalle de crédibilité à 95 % */
  ic: [number, number]
  /** au moins une borne touche 0 ou 100 : l'intervalle est tronqué, pas mesuré */
  sature: boolean
  /** probabilité calibrée, ou null quand le modèle isotonique ne s'applique pas */
  conf: number | null
  conf_lab: Qualite
  /** Sharpe par trade, brut */
  sr: number
  /** Sharpe après rétrécissement bayésien — c'est lui qui fonde le score */
  post: number
  /** erreur type du Sharpe (Mertens, corrigée asymétrie/kurtosis) */
  se: number
  /** PnL net de frais */
  pnl: number
  /** PnL sans le meilleur trade — chez les gagnants, 66 % du PnL en vient */
  pnl_hors_max: number
  frais: number
  /** trades clos */
  n: number
  /** drawdown maximal, positif */
  dd: number
  /** jours depuis le dernier trade clos */
  dort_j: number | null
  r30: number
  r7: number
  /**
   * Variation de rang RELATIF. L'ancienne version comparait des rangs absolus :
   * 185 wallets portaient une flèche alors que le Spearman entre relevés valait
   * +1,0000 — un décalage uniforme de +18 dû à l'arrivée de nouveaux wallets,
   * pas un mouvement. Null quand moins de deux DATES distinctes.
   */
  drang_rel: number | null
  /** p-valeur de Ljung-Box(5). < 0,05 = trades non indépendants. */
  lb_p: number | null
  st: Etat
  coins: string[]
}

/** Un point d'equity reconstruit : [instant en ms, PnL cumulé net]. */
export type Point = readonly [number, number]

/**
 * Série d'equity encodée : `t0` en secondes, écarts en MINUTES, valeurs en
 * dollars. L'axe porte des mois et l'infobulle un jour — la seconde était
 * mille fois plus fine que ce que l'écran montre.
 */
export interface SerieEq {
  t0: number
  d: number[]
  v: number[]
}

/** Histogramme des résultats par trade. */
export interface Histo {
  lo: number
  pas: number
  b: number[]
}

/**
 * Un point d'historique : [instant en secondes, score, rang].
 * L'historique se compte en DATES DISTINCTES, jamais en lignes — « 5 relevés »
 * désignait deux dates, dont trois points à 207 et 120 secondes d'intervalle.
 */
export type PointHisto = readonly [number, number | null, number | null]

/** Confrontation à la donnée native de la source. */
export interface Observe {
  n: number
  sr: number
  sr_der: number
  suffisant: boolean
  ecart: number
  ecart_rel: number | null
  signe: boolean
}

/**
 * CE QUI PERMET DE RÉFUTER un wallet. C'est l'onglet que l'ancienne
 * application n'avait pas, et c'est le cœur du produit : sur 52 259 wallets
 * explorés, un seul survit à un test honnête.
 */
export interface Preuve {
  /** p-valeur du test de permutation par retournement de signe */
  p_perm: number | null
  /** bornes du Sharpe par bootstrap stationnaire par blocs */
  boot_ic: [number, number] | null
  /** longueur de bloc retenue par le bootstrap */
  boot_bloc: number | null
  /** autocorrélation empirique au retard 1 */
  ac1: number | null
  /** p-valeur de Ljung-Box(5) */
  lb_p: number | null
  /** Sharpe sur la première moitié de l'historique propre au wallet */
  sr_h1: number | null
  /** Sharpe sur la seconde moitié */
  sr_h2: number | null
  /** ce que les frais retirent, en unités de Sharpe */
  frais_sr: number | null
  /** part du PnL portée par le seul meilleur trade */
  part_max: number | null
  /** le wallet bascule-t-il gagnant → perdant sans son meilleur trade ? */
  bascule: boolean
  /**
   * L'intervalle de bootstrap par blocs exclut-il zéro ? Mesurable à la
   * résolution du dispositif, mais SANS correction pour tests multiples : sur
   * 291 wallets on en attend une quinzaine par pur hasard à 95 %.
   */
  ic_exclut_zero: boolean
  /** l'intervalle est entièrement AU-DESSUS de zéro : peut-être mieux que rien */
  ic_positif: boolean
  /** entièrement AU-DESSOUS : ce wallet perd, et ce n'est pas du bruit */
  ic_negatif: boolean
  /**
   * Franchit-il le seuil de test multiple ? Quand `Meta.test_resolu` est faux,
   * ce drapeau vaut faux PAR RÉSOLUTION du test, pas par mesure — le lire comme
   * une preuve d'absence serait l'erreur exactement symétrique de celle que ce
   * produit corrige.
   */
  survit_bonferroni: boolean
}

/** Le détail d'un wallet, chargé par lot à l'ouverture de sa fiche. */
export interface Detail {
  a: string
  eq: SerieEq | null
  hist: Histo | null
  histo: PointHisto[]
  /** nombre de DATES distinctes dans l'historique */
  n_dates: number
  forts: (string | number)[]
  faibles: (string | number)[]
  risques: (string | number)[]
  obs: Observe | null
  preuve: Preuve
  m0: string | null
  /** trades clos par mois, série CONTIGUË : un mois sans trade vaut zéro */
  m: number[]
  classe: string | null
  src: string | null
  vu: number | null
  promu: number | null
  coll: number | null
  ret: number
  t0: number | null
  t1: number | null
  win: number | null
  pf: number | null
  best: number | null
  pire: number | null
  duree_h: number | null
  vol: number | null
  tpj: number | null
  conc: number
  jours: number
  stab: number | null
  qualite: number
}

/** Un lot de détails, indexé par adresse. */
export interface Lot {
  gen: number
  wallets: Record<string, Detail>
}

/** Le verdict du protocole de confrontation à la source native. */
export interface Meta {
  n: number
  trades: number
  maj: string
  /** horodatage exact de génération, en secondes */
  gen: number
  spearman: number
  p: number
  ece: number
  tau: number
  m: number
  verdict: string
  verdict_motif: string
  avec_natif: number
  sans_p_cal: number
  ranked: number
  discovery_total: number
  archives_total: number
  /** nombre de bandes d'équivalence portées par le classement */
  bandes: number
  satures_haut: number
  ic_largeur_mediane: number
  seuil_jours: number
  seuil_trades: number
  seuil_conc: number
  /** wallets explorés — dénominateur du seuil de test multiple */
  explores: number
  /** 0,05 / explores */
  seuil_bonferroni: number
  /** combien survivent au bootstrap par blocs ET à Bonferroni */
  survivants: number
  /**
   * Combien ont un IC de bootstrap entièrement AU-DESSUS de zéro, avant
   * correction pour tests multiples. À ne jamais additionner avec le compte
   * négatif : les deux disent des choses opposées.
   */
  ic_boot_positif: number
  /** combien ont un IC entièrement AU-DESSOUS de zéro : perte établie */
  ic_boot_negatif: number
  /** plus petite p-valeur exprimable : 1 / (tirages + 1) */
  resolution_p: number
  /** nombre de rééchantillonnages par wallet */
  tirages: number
  /**
   * Le dispositif RÉSOUT-il le seuil de Bonferroni ? Faux quand
   * `resolution_p > seuil_bonferroni` : aucun wallet ne peut alors le franchir,
   * quelle que soit sa performance. L'écran doit le dire, sans quoi `survivants
   * = 0` se lit comme un verdict alors que c'est une limite d'instrument.
   */
  test_resolu: boolean
  /** table des phrases répétées, indexée par les listes forts/faibles/risques */
  lib: string[]
  reputation: { n: number; sans_trade_clos: number; mesurables: number; source: string }
}

/** Une entrée du rapport de cycle. */
export interface Mouvement {
  a: string
  message?: string
  raison?: string
  classe?: string
  score?: number
  n?: number
  manque?: string[]
}

export interface Blocage {
  sujet: string
  portee: string
  cause: string
  action_interdite: string
  demande: string
}

export interface Daily {
  cycle_id: string
  horodatage: string
  mode: string
  prochaine_action: string | null
  new_today: Mouvement[]
  new_ranked: Mouvement[]
  reactivated: Mouvement[]
  watch: Mouvement[]
  remarquables: Mouvement[]
  top_movers: Mouvement[]
  declining: Mouvement[]
  archived: Mouvement[]
  blocages: Blocage[]
  data_health: Record<string, unknown>
  system_health: Record<string, unknown>
}
