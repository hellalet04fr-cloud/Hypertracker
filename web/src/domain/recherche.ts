/**
 * LA RECHERCHE.
 *
 * Deux défauts mesurés, tous deux dus à une comparaison brute sur
 * l'hexadécimal :
 *
 *   — l'application propose un bouton « Groupée » qui copie « 0x F2C9 C2EB … ».
 *     Recollé dans son propre champ de recherche : zéro résultat.
 *   — « 1 » remontait 211 wallets : tous ceux dont l'adresse contient un « 1 ».
 *
 * On normalise donc DES DEUX CÔTÉS, et une requête purement numérique cherche
 * un rang, pas une sous-chaîne.
 */
import type { Ligne } from './types'

/** Ce qu'une adresse EST, indépendamment de la façon dont on l'a écrite. */
export const norm = (s: string): string => s.toLowerCase().replace(/[^0-9a-z]/g, '')

export type Genre = 'vide' | 'rang' | 'bande' | 'texte'

export interface Requete {
  genre: Genre
  brut: string
  /** forme normalisée, pour le genre `texte` */
  norme: string
  /** valeur entière, pour les genres `rang` et `bande` */
  valeur: number
}

export function analyser(brut: string): Requete {
  const t = brut.trim()
  if (!t) return { genre: 'vide', brut: t, norme: '', valeur: 0 }
  if (/^\d{1,5}$/.test(t)) return { genre: 'rang', brut: t, norme: t, valeur: Number(t) }
  const g = /^g\s*(\d{1,2})$/i.exec(t)
  if (g) return { genre: 'bande', brut: t, norme: t, valeur: Number(g[1]) }
  return { genre: 'texte', brut: t, norme: norm(t), valeur: 0 }
}

export function chercher(lignes: readonly Ligne[], brut: string): Ligne[] {
  const q = analyser(brut)
  switch (q.genre) {
    case 'vide':
      return [...lignes]
    case 'rang':
      return lignes.filter((l) => l.rang === q.valeur)
    case 'bande':
      return lignes.filter((l) => l.groupe === q.valeur)
    case 'texte':
      return lignes.filter(
        (l) => norm(l.a).includes(q.norme) || l.coins.some((c) => norm(c).includes(q.norme)),
      )
  }
}

export interface Segment {
  t: string
  marque: boolean
}

/**
 * Met en évidence la sous-chaîne trouvée DANS LE TEXTE AFFICHÉ, alors que la
 * comparaison a eu lieu sur la forme normalisée. Il faut donc reprojeter les
 * indices : on avance dans le texte d'origine en ne comptant que les caractères
 * qui survivent à la normalisation.
 */
export function surligner(texte: string, brut: string): Segment[] {
  const q = analyser(brut)
  if (q.genre !== 'texte' || !q.norme) return [{ t: texte, marque: false }]

  // Indices du texte d'origine, pour chaque caractère de sa forme normalisée.
  const carte: number[] = []
  let normalise = ''
  for (let i = 0; i < texte.length; i++) {
    const c = texte[i]!.toLowerCase()
    if (/[0-9a-z]/.test(c)) {
      normalise += c
      carte.push(i)
    }
  }
  const k = normalise.indexOf(q.norme)
  if (k < 0) return [{ t: texte, marque: false }]

  const debut = carte[k]!
  const finIncl = carte[k + q.norme.length - 1]!
  const out: Segment[] = []
  if (debut > 0) out.push({ t: texte.slice(0, debut), marque: false })
  out.push({ t: texte.slice(debut, finIncl + 1), marque: true })
  if (finIncl + 1 < texte.length) out.push({ t: texte.slice(finIncl + 1), marque: false })
  return out
}
