/**
 * LES FIGURES SECONDAIRES : barres, frise, nuage, rétrécissement.
 *
 * Chacune a une raison d'exister que sa forme porte, et qu'une librairie de
 * graphiques aurait effacée en la ramenant à un « bar chart ».
 */
import type { PointHisto } from '@/domain/types'
import { lireJeton, vide } from './moteur'
import type { Toile } from './moteur'

/* ───────────────────────────────────────────────────────────── barres */

export interface OptionsBarres {
  /** barre désignée : la médiane d'une distribution, le mois courant */
  pleine?: number | null
  survol?: number | null
  etiquettes?: readonly string[]
}

export function barres(t: Toile, valeurs: readonly number[], o: OptionsBarres = {}): ((i: number) => number) | null {
  const { ctx, w, h } = t
  const n = valeurs.length
  if (!n) {
    vide(t)
    return null
  }
  const mx = Math.max(1, ...valeurs)
  const pad = 2
  const base = h - 16
  const bw = (w - 2 * pad) / n
  const px = (i: number) => pad + i * bw + bw / 2
  const designee = o.survol ?? o.pleine ?? null

  for (let i = 0; i < n; i++) {
    const bh = (valeurs[i]! / mx) * (base - 4)
    const marquee = i === designee
    ctx.fillStyle = marquee ? lireJeton('--index') : lireJeton('--gris')
    ctx.globalAlpha = marquee ? 1 : 0.42
    ctx.fillRect(pad + i * bw, base - bh, Math.max(1, bw - 1.5), Math.max(1, bh))
  }
  ctx.globalAlpha = 1

  ctx.strokeStyle = lireJeton('--filet')
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(pad, base + 0.5)
  ctx.lineTo(w - pad, base + 0.5)
  ctx.stroke()

  const e = o.etiquettes
  if (e?.length) {
    ctx.fillStyle = lireJeton('--faible')
    ctx.font = '11px monospace'
    ctx.textAlign = 'left'
    ctx.fillText(e[0] ?? '', pad, h - 2)
    ctx.textAlign = 'right'
    ctx.fillText(e[n - 1] ?? '', w - pad, h - 2)
  }
  return px
}

/** « 2025-09 » plus i mois. Répéter l'étiquette à chaque point coûtait 31 Ko. */
export function moisApres(m0: string | null, i: number): string {
  if (!m0) return ''
  const a = Number(m0.slice(0, 4))
  const m = Number(m0.slice(5, 7)) - 1 + i
  return `${a + Math.floor(m / 12)}-${String(((m % 12) + 12) % 12 + 1).padStart(2, '0')}`
}

/* ────────────────────────────────────────────────────────────── frise */

export interface OptionsFrise {
  /** ÉCHELLE INVERSÉE : le 1 en haut, parce que « monter au classement » doit
   *  monter à l'écran. Sans cela la frise du rang dit exactement le contraire
   *  de ce qu'elle montre. */
  inverse?: boolean
  prefixe?: string
  survol?: number | null
}

export type PointFrise = readonly [number, number]

export function frise(t: Toile, pts: readonly PointFrise[], o: OptionsFrise = {}): ((i: number) => number) | null {
  const { ctx, w, h } = t
  if (pts.length < 2) {
    // Une seule date n'est pas une évolution. L'historique se compte en DATES
    // DISTINCTES, jamais en lignes : « 5 relevés » désignait deux dates.
    vide(t, pts.length === 1 ? 'Une seule date — pas encore d’évolution' : 'Aucun relevé daté')
    return null
  }
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  const x0 = Math.min(...xs)
  const x1 = Math.max(...xs)
  let y0 = Math.min(...ys)
  let y1 = Math.max(...ys)
  if (y1 === y0) {
    y1 += 1
    y0 -= 1
  }
  const pad = 6
  const px = (i: number) => pad + ((pts[i]![0] - x0) / (x1 - x0 || 1)) * (w - 2 * pad)
  const py = (v: number) =>
    o.inverse
      ? pad + ((v - y0) / (y1 - y0)) * (h - 2 * pad - 14)
      : pad + (1 - (v - y0) / (y1 - y0)) * (h - 2 * pad - 14)

  ctx.strokeStyle = lireJeton('--gris')
  ctx.lineWidth = 1
  ctx.beginPath()
  pts.forEach((p, i) => (i ? ctx.lineTo(px(i), py(p[1])) : ctx.moveTo(px(i), py(p[1]))))
  ctx.stroke()

  ctx.fillStyle = lireJeton('--index')
  pts.forEach((p, i) => {
    ctx.beginPath()
    ctx.arc(px(i), py(p[1]), i === o.survol ? 3.5 : 2, 0, Math.PI * 2)
    ctx.fill()
  })

  ctx.fillStyle = lireJeton('--faible')
  ctx.font = '11px monospace'
  ctx.textAlign = 'left'
  ctx.fillText(`${o.prefixe ?? ''}${ys[0]}`, pad, h - 2)
  ctx.textAlign = 'right'
  ctx.fillText(`${o.prefixe ?? ''}${ys[ys.length - 1]}`, w - pad, h - 2)
  return px
}

/**
 * DATES DISTINCTES, jamais lignes. Trois points à 207 et 120 secondes
 * d'intervalle sont un seul relevé, pas trois.
 */
export function parDate(histo: readonly PointHisto[], champ: 1 | 2): PointFrise[] {
  const parJour = new Map<string, PointHisto>()
  for (const p of histo) {
    if (p[champ] == null) continue
    const jour = new Date(p[0] * 1000).toISOString().slice(0, 10)
    // Le dernier relevé du jour fait foi : c'est l'état dans lequel la journée
    // s'est terminée.
    parJour.set(jour, p)
  }
  return [...parJour.values()]
    .sort((a, b) => a[0] - b[0])
    .map((p) => [p[0] * 1000, p[champ] as number] as PointFrise)
}

export const nDates = (histo: readonly PointHisto[]): number =>
  new Set(histo.map((p) => new Date(p[0] * 1000).toISOString().slice(0, 10))).size

/* ────────────────────────────────────────────────────────────── nuage */

/**
 * Score contre probabilité. Si les deux grandeurs étaient la même chose, ce
 * nuage serait une diagonale. Il ne l'est pas — et c'est tout l'intérêt de le
 * montrer plutôt que de l'affirmer.
 */
export function nuage(
  t: Toile,
  population: readonly (readonly [number, number])[],
  cible: readonly [number, number] | null,
): void {
  const { ctx, w, h } = t
  const pad = 26
  const px = (v: number) => pad + (v / 100) * (w - pad - 6)
  const py = (v: number) => h - pad - (v / 100) * (h - pad - 10)

  ctx.strokeStyle = lireJeton('--filet')
  ctx.lineWidth = 1
  for (let g = 0; g <= 100; g += 50) {
    ctx.beginPath()
    ctx.moveTo(px(g), py(0))
    ctx.lineTo(px(g), py(100))
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(px(0), py(g))
    ctx.lineTo(px(100), py(g))
    ctx.stroke()
  }

  ctx.fillStyle = lireJeton('--gris')
  ctx.globalAlpha = 0.5
  for (const [x, y] of population) {
    ctx.beginPath()
    ctx.arc(px(x), py(y), 1.6, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1

  if (cible) {
    ctx.strokeStyle = lireJeton('--index')
    ctx.beginPath()
    ctx.arc(px(cible[0]), py(cible[1]), 4.5, 0, Math.PI * 2)
    ctx.stroke()
  }

  ctx.fillStyle = lireJeton('--faible')
  ctx.font = '11px monospace'
  ctx.textAlign = 'center'
  ctx.fillText('SCORE', w / 2, h - 4)
  ctx.save()
  ctx.translate(9, h / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillText('PROBABILITÉ', 0, 0)
  ctx.restore()
}

/* ────────────────────────────────────────────────── rétrécissement (SVG) */

/**
 * Le zéro de cet axe est une constante NOMMÉE propre au Sharpe. Emprunter la
 * borne basse de l'échelle de score marchait — par coïncidence, les deux valant
 * zéro — et se serait mis à mentir le jour où l'échelle aurait changé.
 */
export const ZERO_SR = 0

export interface Retrecissement {
  sr: number
  post: number
  se: number | null
  min: number
  max: number
}

/** Le déplacement du Sharpe brut vers le Sharpe retenu, sur une échelle commune. */
export function retrecissement(r: Retrecissement, w = 300, h = 40): string {
  const pad = 8
  const etendue = r.max - r.min || 1
  const X = (v: number) => pad + ((v - r.min) / etendue) * (w - 2 * pad)
  const y = 22
  const a = X(r.sr)
  const b = X(r.post)
  const z = X(ZERO_SR)
  const p: string[] = []

  p.push(`<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="var(--filet)" stroke-width="1"/>`)
  p.push(`<line x1="${z}" y1="${y - 5}" x2="${z}" y2="${y + 5}" stroke="var(--filet-fort)" stroke-width="1"/>`)
  p.push(
    `<text x="${z}" y="${h - 2}" fill="var(--faible)" font-size="11" font-family="var(--f-mono)" text-anchor="middle">${ZERO_SR}</text>`,
  )

  // L'erreur type, quand elle existe : le brut n'est pas un point, c'est un
  // point ET son flou. Le montrer désamorce la lecture « 0,3894 » au dixième de
  // millième.
  if (r.se != null && Number.isFinite(r.se)) {
    p.push(
      `<line x1="${X(r.sr - r.se)}" y1="${y}" x2="${X(r.sr + r.se)}" y2="${y}" stroke="var(--gris)" stroke-width="3" opacity="0.35"/>`,
    )
  }
  p.push(`<line x1="${a}" y1="${y}" x2="${b}" y2="${y}" stroke="var(--gris)" stroke-width="1"/>`)
  p.push(`<circle cx="${a}" cy="${y}" r="3" fill="none" stroke="var(--gris)" stroke-width="1"/>`)
  p.push(`<line x1="${b}" y1="${y - 8}" x2="${b}" y2="${y + 8}" stroke="var(--index)" stroke-width="1"/>`)
  const d = r.post - r.sr
  p.push(
    `<text x="${(a + b) / 2}" y="${y - 10}" fill="var(--texte)" font-size="11" font-family="var(--f-mono)" text-anchor="middle">${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(3)}</text>`,
  )
  return p.join('')
}
