/**
 * COURBE TEMPORELLE — equity, drawdown.
 *
 * LE SIGNE SE LIT À LA FORME, jamais à une couleur gain/perte sur la ligne : la
 * zone sous zéro est hachurée. Un instrument ne colorie pas ses mesures, et une
 * information portée par la seule couleur disparaît pour un lecteur sur douze.
 */
import type { Point, SerieEq } from '@/domain/types'
import { lireJeton, vide } from './moteur'
import type { Toile } from './moteur'

/**
 * Reconstruit la série : `t0` en secondes, écarts en MINUTES. L'axe porte des
 * mois et l'infobulle un jour — la seconde était mille fois plus fine que ce que
 * l'écran montre, et coûtait deux caractères par point.
 */
export function equity(e: SerieEq | null): Point[] {
  if (!e?.v?.length) return []
  const out: Point[] = [[e.t0 * 1000, e.v[0]!]]
  let t = e.t0
  for (let i = 0; i < e.d.length; i++) {
    t += e.d[i]! * 60
    out.push([t * 1000, e.v[i + 1] ?? 0])
  }
  return out
}

/**
 * Le drawdown se DÉDUIT de l'equity — c'est sa définition :
 * dd(i) = max(eq[0..i], 0) − eq(i). Le stocker doublait la charge pour zéro
 * information nouvelle. La déduction reste exacte parce que tout point mettant
 * le sommet à jour survit à la décimation.
 */
export function drawdown(e: SerieEq | null): Point[] {
  let pic = 0
  return equity(e).map(([t, v]) => {
    pic = Math.max(pic, v)
    const repli = pic - v
    // `-(0)` vaut `-0`, qui se formate « −$0 » : le signe negatif d'un repli NUL
    // est un artefact de la negation, pas une mesure.
    return [t, repli === 0 ? 0 : -repli] as Point
  })
}

export interface OptionsCourbe {
  couleur?: string
  /** index du point sous le doigt */
  survol?: number | null
  /** étiquettes d'axe aux deux bouts */
  axes?: boolean
}

export interface Projection {
  px: (i: number) => number
  py: (v: number) => number
}

export function dessiner(t: Toile, pts: readonly Point[], o: OptionsCourbe = {}): Projection | null {
  const { ctx, w, h } = t
  if (pts.length < 2) {
    vide(t)
    return null
  }
  const basAxe = o.axes === false ? 2 : 14
  const pad = 2
  let x0 = Infinity
  let x1 = -Infinity
  let y0 = 0
  let y1 = 0
  for (const [x, y] of pts) {
    if (x < x0) x0 = x
    if (x > x1) x1 = x
    if (y < y0) y0 = y
    if (y > y1) y1 = y
  }
  if (y1 === y0) {
    y1 += 1
    y0 -= 1
  }
  const px = (i: number) => pad + ((pts[i]![0] - x0) / (x1 - x0 || 1)) * (w - 2 * pad)
  const py = (v: number) => pad + (1 - (v - y0) / (y1 - y0)) * (h - 2 * pad - basAxe)

  // Ligne de zéro : le repère, pas une donnée.
  ctx.setLineDash([1, 3])
  ctx.strokeStyle = lireJeton('--filet-fort')
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(pad, py(0))
  ctx.lineTo(w - pad, py(0))
  ctx.stroke()
  ctx.setLineDash([])

  // HACHURES SOUS ZÉRO. La forme dit le signe ; la couleur ne le dit jamais
  // seule.
  if (pts.some((p) => p[1] < 0)) {
    ctx.save()
    ctx.beginPath()
    ctx.moveTo(px(0), py(0))
    pts.forEach((p, i) => ctx.lineTo(px(i), py(Math.min(0, p[1]))))
    ctx.lineTo(px(pts.length - 1), py(0))
    ctx.closePath()
    ctx.clip()
    ctx.strokeStyle = lireJeton('--gris')
    ctx.globalAlpha = 0.18
    for (let i = -h; i < w + h; i += 5) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i + h, h)
      ctx.stroke()
    }
    ctx.restore()
  }

  ctx.strokeStyle = o.couleur ?? lireJeton('--texte')
  ctx.lineWidth = 1.25
  ctx.lineJoin = 'round'
  ctx.beginPath()
  pts.forEach((p, i) => (i ? ctx.lineTo(px(i), py(p[1])) : ctx.moveTo(px(i), py(p[1]))))
  ctx.stroke()

  const s = o.survol
  if (s != null && s >= 0 && s < pts.length) {
    ctx.strokeStyle = lireJeton('--index')
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(px(s), pad)
    ctx.lineTo(px(s), h - pad - basAxe)
    ctx.stroke()
    ctx.fillStyle = lireJeton('--index')
    ctx.beginPath()
    ctx.arc(px(s), py(pts[s]![1]), 2.6, 0, Math.PI * 2)
    ctx.fill()
  }

  if (o.axes !== false) {
    const mois = (ms: number) =>
      new Date(ms).toLocaleDateString('fr-FR', { month: 'short', year: '2-digit' })
    ctx.fillStyle = lireJeton('--faible')
    ctx.font = '11px monospace'
    ctx.textAlign = 'left'
    ctx.fillText(mois(x0), pad, h - 2)
    ctx.textAlign = 'right'
    ctx.fillText(mois(x1), w - pad, h - 2)
  }
  return { px, py }
}
