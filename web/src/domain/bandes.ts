/**
 * BANDES D'ÉQUIVALENCE — vérification côté client de ce que le générateur
 * produit.
 *
 * Deux wallets appartiennent à la même bande tant que l'intervalle du courant
 * recouvre encore celui du PREMIER de la bande. La bande ne prétend rien de plus
 * que ce qu'elle dit : à l'intérieur, rien ne permet de départager.
 *
 * Recalculer ici ce que le générateur a déjà calculé n'est pas une redondance
 * décorative : c'est le seul moyen de voir si les deux divergent, et une
 * divergence signifie qu'une des deux moitiés du produit ment.
 */
import type { Ligne } from './types'

const recouvre = (a: Ligne, b: Ligne): boolean => a.ic[0] <= b.ic[1] && a.ic[1] >= b.ic[0]

/** Recalcule les bandes à partir des seuls intervalles, dans l'ordre des rangs. */
export function calculer(lignes: readonly Ligne[]): Map<string, number> {
  const ordre = [...lignes].sort((x, y) => x.rang - y.rang)
  const out = new Map<string, number>()
  let bande = 1
  let ancre: Ligne | null = null
  for (const l of ordre) {
    if (ancre === null || !recouvre(l, ancre)) {
      if (ancre !== null) bande++
      ancre = l
    }
    out.set(l.a, bande)
  }
  return out
}

/** Les adresses dont la bande recalculée diffère de celle transportée. */
export function divergences(lignes: readonly Ligne[]): string[] {
  const calc = calculer(lignes)
  return lignes.filter((l) => calc.get(l.a) !== l.groupe).map((l) => l.a)
}

/** Effectif de chaque bande dans une sélection donnée. */
export function effectifs(lignes: readonly Ligne[]): Map<number, number> {
  const out = new Map<number, number>()
  for (const l of lignes) out.set(l.groupe, (out.get(l.groupe) ?? 0) + 1)
  return out
}
