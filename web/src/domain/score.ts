/**
 * CE QUE LE SCORE A LE DROIT DE DIRE.
 *
 * La largeur médiane de l'intervalle de crédibilité vaut 56 points sur 100.
 * Un rang unique de 1 à 291 est donc une fiction, et un dixième de point une
 * précision qui n'existe pas. Ce fichier est l'endroit où l'on refuse les deux.
 */
import type { Ligne, Qualite } from './types'

/** Bornes du modèle : le score est une probabilité a posteriori en pourcentage. */
export const ECHELLE = [0, 100] as const

/** Au-delà de cette largeur d'intervalle, le dixième de point ne veut plus rien dire. */
export const IC_LARGE = 20

/** Au-delà de ce silence, un wallet est dormant : le score ignore la fraîcheur. */
export const DORT_J = 60

export const largeurIC = (l: Pick<Ligne, 'ic'>): number => l.ic[1] - l.ic[0]

/**
 * Un chiffre n'est jamais plus précis que son intervalle. Écrire « 98,1 » sur
 * [64–100] annonce un dixième là où la mesure ne porte pas dix points.
 */
export function scoreTxt(l: Pick<Ligne, 'ic' | 'score'>): string {
  return largeurIC(l) > IC_LARGE ? String(Math.round(l.score)) : l.score.toFixed(1)
}

/** Bande d'équivalence : à l'intérieur, rien ne départage. */
export const bande = (l: Pick<Ligne, 'groupe'>): string => `G${String(l.groupe).padStart(2, '0')}`

export const satureHaut = (l: Pick<Ligne, 'ic'>): boolean => l.ic[1] >= ECHELLE[1]
export const satureBas = (l: Pick<Ligne, 'ic'>): boolean => l.ic[0] <= ECHELLE[0]

/**
 * Forme courte de l'intervalle, pour un en-tête.
 *
 * UN INTERVALLE DE LARGEUR NULLE N'EST JAMAIS AFFICHÉ COMME UN INTERVALLE.
 * « IC 100–100 » était le seul endroit du produit prétendant à une certitude
 * parfaite, et c'était un artefact : l'échelle est bornée, les deux bornes ont
 * été écrasées dessus.
 */
export function icCourt(l: Pick<Ligne, 'ic'>): string {
  if (l.ic[0] === l.ic[1]) return `${l.ic[0]} · borne`
  return `${satureBas(l) ? '≤' : ''}${l.ic[0]}–${satureHaut(l) ? '≥' : ''}${l.ic[1]}`
}

/** Forme longue, pour une fiche : elle dit pourquoi la borne est ce qu'elle est. */
export function icLong(l: Pick<Ligne, 'ic'>): string {
  if (l.ic[0] === l.ic[1]) return `${l.ic[0]} — borne de l’échelle, pas une mesure`
  const notes: string[] = []
  if (satureBas(l)) notes.push('bas saturé')
  if (satureHaut(l)) notes.push('haut saturé')
  return `${l.ic[0]}–${l.ic[1]}${notes.length ? ` · ${notes.join(', ')}` : ''}`
}

export const dormant = (l: Pick<Ligne, 'dort_j'>): boolean => (l.dort_j ?? 0) > DORT_J

/**
 * Trades non indépendants. C'est l'anomalie qui disqualifiait le n° 2 du
 * classement — autocorrélation lag-1 +0,389 — et elle doit être visible AVANT
 * d'ouvrir la fiche.
 */
export const vigilance = (l: Pick<Ligne, 'lb_p'>): boolean => l.lb_p != null && l.lb_p < 0.05

/** Activité, dite en clair. Le score ignore la fraîcheur par construction. */
export function activite(l: Pick<Ligne, 'dort_j'>): string {
  if (l.dort_j == null) return 'activité N/D'
  if (l.dort_j <= 2) return 'actif'
  if (l.dort_j <= DORT_J) return `récent · ${Math.round(l.dort_j)} j`
  return `inactif · ${Math.round(l.dort_j)} j`
}

const LIB_QUALITE: Readonly<Record<Qualite, string>> = {
  elevee: 'élevée',
  moyenne: 'moyenne',
  faible: 'faible',
}
export const qualiteFr = (q: Qualite): string => LIB_QUALITE[q]

/**
 * Style de trait des mors — le TROISIÈME canal du rail, non chromatique.
 * Tableau de tirets SVG/canvas ; vide = trait plein.
 */
export const TRAIT: Readonly<Record<Qualite, readonly number[]>> = {
  elevee: [],
  moyenne: [3, 2],
  faible: [1, 3],
}

/**
 * PnL sans le meilleur trade : bascule-t-il ?
 * Chez les gagnants, 66 % du PnL vient d'un seul trade en médiane, et 20 des 66
 * gagnants deviennent perdants sans lui.
 */
export const bascule = (l: Pick<Ligne, 'pnl' | 'pnl_hors_max'>): boolean =>
  l.pnl > 0 && l.pnl_hors_max <= 0
