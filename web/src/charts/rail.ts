/**
 * LE RAIL D'INCERTITUDE — LA FIGURE CENTRALE.
 *
 * Règle non négociable : un chiffre de score n'apparaît JAMAIS sans son rail
 * dans le même bloc visuel.
 *
 *   position de l'index  = le score
 *   écartement des mors  = l'intervalle de crédibilité à 95 %
 *   style du trait       = la qualité des données
 *
 * Trois canaux REDONDANTS ET NON CHROMATIQUES, pour que l'information survive au
 * daltonisme comme au soleil sur un écran.
 *
 * MORS OUVERT = BORNE D'ÉCHELLE ATTEINTE. Dessiner un mors fermé sur une
 * troncature donnerait à une borne l'apparence d'une mesure — c'est exactement
 * ce que « IC 100–100 » faisait dans la version précédente, seul endroit du
 * produit prétendant à une certitude parfaite.
 *
 * Ce fichier ne calcule QUE de la géométrie. Deux rendus la consomment : un SVG
 * pour les figures isolées, un canvas pour les 31 505 lignes d'un tableau — car
 * 31 505 SVG font tomber le navigateur. Les deux doivent produire la MÊME
 * figure, et un test le vérifie au demi-pixel.
 */
import type { Ligne } from '@/domain/types'
import { ECHELLE, TRAIT, satureBas, satureHaut, scoreTxt, icLong, qualiteFr } from '@/domain/score'

export interface Geometrie {
  w: number
  h: number
  /** ordonnée du rail gradué */
  y: number
  /** abscisses : index, mors bas, mors haut */
  xIndex: number
  xBas: number
  xHaut: number
  /** abscisses des graduations */
  graduations: number[]
  ouvertBas: boolean
  ouvertHaut: boolean
  tirets: readonly number[]
}

export interface Options {
  w?: number
  h?: number
  /** marge horizontale : sans elle, un index à 0 ou 100 sort du cadre */
  marge?: number
  /** nombre d'intervalles entre graduations */
  pas?: number
}

export function geometrie(l: Ligne, o: Options = {}): Geometrie {
  const w = o.w ?? 300
  const h = o.h ?? 26
  const marge = o.marge ?? 7
  const pas = o.pas ?? 4
  const utile = w - 2 * marge
  const X = (v: number) =>
    marge + (Math.max(ECHELLE[0], Math.min(ECHELLE[1], v)) / ECHELLE[1]) * utile
  const graduations: number[] = []
  for (let k = 0; k <= pas; k++) graduations.push(marge + (k / pas) * utile)
  return {
    w,
    h,
    y: h - 10,
    xIndex: X(l.score),
    xBas: X(l.ic[0]),
    xHaut: X(l.ic[1]),
    graduations,
    ouvertBas: satureBas(l),
    ouvertHaut: satureHaut(l),
    tirets: TRAIT[l.conf_lab],
  }
}

/** La description lue par une technologie d'assistance. Les trois canaux, en mots. */
export const description = (l: Ligne): string =>
  `Score ${scoreTxt(l)} sur ${ECHELLE[1]}. Intervalle de crédibilité ${icLong(l)}. ` +
  `Qualité des données ${qualiteFr(l.conf_lab)}.`

/* ────────────────────────────────────────────────────────────────── SVG */

const machoireSvg = (x: number, y: number, ouvert: boolean, sens: 1 | -1): string =>
  ouvert
    ? `<path d="M${x - sens * 4} ${y - 10} L${x} ${y - 6} L${x - sens * 4} ${y - 2}" fill="none" stroke="var(--gris)" stroke-width="1"/>`
    : `<line x1="${x}" y1="${y - 9}" x2="${x}" y2="${y - 3}" stroke="var(--gris)" stroke-width="1"/>`

/** Rendu SVG, pour une figure isolée. Retourne le contenu, pas la balise racine. */
export function svg(l: Ligne, o: Options = {}): string {
  const g = geometrie(l, o)
  const p: string[] = []
  for (const x of g.graduations) {
    p.push(`<line x1="${x}" y1="${g.y}" x2="${x}" y2="${g.y + 4}" stroke="var(--filet)" stroke-width="1"/>`)
  }
  p.push(
    `<line x1="${g.graduations[0]}" y1="${g.y}" x2="${g.graduations[g.graduations.length - 1]}" y2="${g.y}" stroke="var(--filet)" stroke-width="1"/>`,
  )
  const da = g.tirets.length ? ` stroke-dasharray="${g.tirets.join(' ')}"` : ''
  p.push(
    `<line x1="${g.xBas}" y1="${g.y - 6}" x2="${g.xHaut}" y2="${g.y - 6}" stroke="var(--gris)" stroke-width="1"${da}/>`,
  )
  p.push(machoireSvg(g.xBas, g.y, g.ouvertBas, -1))
  p.push(machoireSvg(g.xHaut, g.y, g.ouvertHaut, 1))
  p.push(
    `<line x1="${g.xIndex}" y1="${g.y - 12}" x2="${g.xIndex}" y2="${g.y + 5}" stroke="var(--index)" stroke-width="1"/>`,
  )
  p.push(
    `<path d="M${g.xIndex - 2.8} ${g.y - 12} L${g.xIndex + 2.8} ${g.y - 12} L${g.xIndex} ${g.y - 8.4} Z" fill="var(--index)"/>`,
  )
  return p.join('')
}

export const viewBox = (o: Options = {}): string => `0 0 ${o.w ?? 300} ${o.h ?? 26}`

/* ─────────────────────────────────────────────────────────────── Canvas */

export interface Palette {
  filet: string
  gris: string
  index: string
}

/**
 * Rendu canvas, DANS LA MÊME PASSE que la ligne du tableau. Le contexte est
 * déjà translaté : on dessine en coordonnées locales à partir de (x0, y0).
 */
export function canvas(
  ctx: CanvasRenderingContext2D,
  l: Ligne,
  x0: number,
  y0: number,
  pal: Palette,
  o: Options = {},
): void {
  const g = geometrie(l, o)
  ctx.save()
  ctx.translate(x0, y0)
  ctx.lineWidth = 1

  ctx.strokeStyle = pal.filet
  ctx.beginPath()
  for (const x of g.graduations) {
    ctx.moveTo(x, g.y)
    ctx.lineTo(x, g.y + 4)
  }
  ctx.moveTo(g.graduations[0]!, g.y)
  ctx.lineTo(g.graduations[g.graduations.length - 1]!, g.y)
  ctx.stroke()

  ctx.strokeStyle = pal.gris
  ctx.setLineDash(g.tirets as number[])
  ctx.beginPath()
  ctx.moveTo(g.xBas, g.y - 6)
  ctx.lineTo(g.xHaut, g.y - 6)
  ctx.stroke()
  ctx.setLineDash([])

  const machoire = (x: number, ouvert: boolean, sens: 1 | -1) => {
    ctx.beginPath()
    if (ouvert) {
      ctx.moveTo(x - sens * 4, g.y - 10)
      ctx.lineTo(x, g.y - 6)
      ctx.lineTo(x - sens * 4, g.y - 2)
    } else {
      ctx.moveTo(x, g.y - 9)
      ctx.lineTo(x, g.y - 3)
    }
    ctx.stroke()
  }
  machoire(g.xBas, g.ouvertBas, -1)
  machoire(g.xHaut, g.ouvertHaut, 1)

  ctx.strokeStyle = pal.index
  ctx.beginPath()
  ctx.moveTo(g.xIndex, g.y - 12)
  ctx.lineTo(g.xIndex, g.y + 5)
  ctx.stroke()
  ctx.fillStyle = pal.index
  ctx.beginPath()
  ctx.moveTo(g.xIndex - 2.8, g.y - 12)
  ctx.lineTo(g.xIndex + 2.8, g.y - 12)
  ctx.lineTo(g.xIndex, g.y - 8.4)
  ctx.closePath()
  ctx.fill()

  ctx.restore()
}
