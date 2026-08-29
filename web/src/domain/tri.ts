/**
 * LE REGISTRE DES TRIS.
 *
 * Chaque clé déclare son libellé, son comparateur, et surtout LE CHAMP
 * RÉELLEMENT MESURÉ. Ce dernier n'est pas une curiosité : les valeurs
 * manquantes ne se trient pas. Les enfouir en fin de tri avec un `?? -1` les
 * fait passer pour de mauvaises performances, alors que c'est une absence de
 * mesure — exactement ce que la règle N/D interdit partout ailleurs.
 */
import type { Ligne } from './types'
import { dormant } from './score'

/** Champ porteur de la mesure, ou null quand le tri porte sur une grandeur toujours présente. */
export type ChampMesure = keyof Ligne | null

export interface Tri {
  cle: string
  libelle: string
  /** comparateur sur les lignes MESURABLES uniquement */
  cmp: (a: Ligne, b: Ligne) => number
  champ: ChampMesure
  /** l'ordre naturel de ce tri : décroissant pour une performance, croissant pour un risque */
  sens: 'desc' | 'asc'
}

const num = (v: number | null | undefined): number => (v == null ? Number.NaN : v)

export const TRIS: readonly Tri[] = [
  // Le score ignore la fraîcheur par construction : le tri par défaut ne doit
  // pas présenter comme « le meilleur » un wallet mort depuis un an.
  {
    cle: 'score_actifs',
    libelle: 'Score · actifs',
    cmp: (a, b) => Number(dormant(a)) - Number(dormant(b)) || b.score - a.score,
    champ: null,
    sens: 'desc',
  },
  { cle: 'groupe', libelle: 'Bande', cmp: (a, b) => a.groupe - b.groupe || b.score - a.score, champ: null, sens: 'asc' },
  { cle: 'score', libelle: 'Score', cmp: (a, b) => b.score - a.score, champ: null, sens: 'desc' },
  { cle: 'pnl', libelle: 'PnL net', cmp: (a, b) => b.pnl - a.pnl, champ: null, sens: 'desc' },
  {
    cle: 'pnl_hors_max',
    libelle: 'PnL hors max',
    cmp: (a, b) => b.pnl_hors_max - a.pnl_hors_max,
    champ: null,
    sens: 'desc',
  },
  { cle: 'frais', libelle: 'Frais', cmp: (a, b) => b.frais - a.frais, champ: null, sens: 'desc' },
  { cle: 'sharpe', libelle: 'Sharpe', cmp: (a, b) => b.sr - a.sr, champ: null, sens: 'desc' },
  { cle: 'trades', libelle: 'Trades', cmp: (a, b) => b.n - a.n, champ: null, sens: 'desc' },
  { cle: 'drawdown', libelle: 'Drawdown', cmp: (a, b) => a.dd - b.dd, champ: null, sens: 'asc' },
  { cle: 'proba', libelle: 'Probabilité', cmp: (a, b) => num(b.conf) - num(a.conf), champ: 'conf', sens: 'desc' },
  { cle: 'activite', libelle: 'Activité 30 j', cmp: (a, b) => b.r30 - a.r30, champ: null, sens: 'desc' },
  {
    cle: 'recent',
    libelle: 'Dernier trade',
    cmp: (a, b) => num(a.dort_j) - num(b.dort_j),
    champ: 'dort_j',
    sens: 'asc',
  },
  {
    cle: 'variation',
    libelle: 'Variation',
    cmp: (a, b) => num(b.drang_rel) - num(a.drang_rel),
    champ: 'drang_rel',
    sens: 'desc',
  },
  {
    cle: 'dependance',
    libelle: 'Dépendance sérielle',
    cmp: (a, b) => num(a.lb_p) - num(b.lb_p),
    champ: 'lb_p',
    sens: 'asc',
  },
]

const PAR_CLE = new Map(TRIS.map((t) => [t.cle, t]))

/** Repli NOMMÉ, jamais positionnel : un repli par index a déjà changé de sens
 *  en silence le jour où une entrée a été insérée en deuxième place. */
export const TRI_DEFAUT = 'score_actifs'
export const triDe = (cle: string): Tri => PAR_CLE.get(cle) ?? PAR_CLE.get(TRI_DEFAUT)!

export interface Partition {
  /** lignes triées, sur lesquelles le critère a une valeur */
  mesurables: Ligne[]
  /** lignes SORTIES de l'ordre, annoncées sous un séparateur nommé */
  absents: Ligne[]
  /** libellé du critère, pour nommer le séparateur */
  libelle: string
}

const absent = (l: Ligne, champ: keyof Ligne): boolean => {
  const v = l[champ]
  return v == null || (typeof v === 'number' && !Number.isFinite(v))
}

/**
 * Trie et SÉPARE. Les non-mesurables ne sont pas derniers : ils sont hors de
 * portée du critère, et la liste doit le dire.
 */
export function partitionner(lignes: readonly Ligne[], cle: string): Partition {
  const t = triDe(cle)
  if (t.champ === null) return { mesurables: [...lignes].sort(t.cmp), absents: [], libelle: t.libelle }
  const champ = t.champ
  const mesurables: Ligne[] = []
  const absents: Ligne[] = []
  for (const l of lignes) (absent(l, champ) ? absents : mesurables).push(l)
  mesurables.sort(t.cmp)
  // Les absents gardent un ordre stable et lisible — par score — pour ne pas
  // donner l'impression d'un classement dans le classement.
  absents.sort((a, b) => b.score - a.score)
  return { mesurables, absents, libelle: t.libelle }
}

/**
 * MULTI-TRI, jusqu'à trois clés. La première clé décide ; les suivantes ne
 * départagent que les égalités exactes. Au-delà de trois, l'ordre cesse d'être
 * explicable à celui qui le lit, et un ordre inexplicable ne vaut rien.
 */
export const MAX_CLES = 3

export function comparateurMulti(cles: readonly string[]): (a: Ligne, b: Ligne) => number {
  const tris = cles.slice(0, MAX_CLES).map(triDe)
  return (a, b) => {
    for (const t of tris) {
      const d = t.cmp(a, b)
      if (d !== 0 && Number.isFinite(d)) return d
    }
    // Départage final par l'adresse : sans lui l'ordre n'est pas déterministe,
    // et deux rendus de la même liste peuvent différer.
    return a.a < b.a ? -1 : a.a > b.a ? 1 : 0
  }
}

/** Partition sur la PREMIÈRE clé, ordre sur toutes. */
export function partitionnerMulti(lignes: readonly Ligne[], cles: readonly string[]): Partition {
  const premiere = cles[0] ?? TRI_DEFAUT
  const t = triDe(premiere)
  const cmp = comparateurMulti(cles.length ? cles : [TRI_DEFAUT])
  if (t.champ === null) return { mesurables: [...lignes].sort(cmp), absents: [], libelle: t.libelle }
  const champ = t.champ
  const mesurables: Ligne[] = []
  const absents: Ligne[] = []
  for (const l of lignes) (absent(l, champ) ? absents : mesurables).push(l)
  mesurables.sort(cmp)
  absents.sort((a, b) => b.score - a.score)
  return { mesurables, absents, libelle: t.libelle }
}
