/**
 * CONTRASTE WCAG 2.1, en fonctions pures.
 *
 * Sert à deux choses : documenter les jetons, et faire ÉCHOUER un test qui
 * parcourt le DOM rendu. La version précédente de ce produit portait la moitié
 * de son texte à 2,84:1 — sous le minimum AA, et même sous le seuil grand
 * texte — parce qu'aucun contrôle ne pouvait le voir.
 */

/** Seuil AA pour du texte courant. */
export const AA = 4.5
/** Seuil AA pour du grand texte : ≥ 24 px, ou ≥ 18,66 px en gras. */
export const AA_GRAND = 3

const canal = (c: number): number => {
  const v = c / 255
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}

export type RGB = readonly [number, number, number]

/** `#rgb`, `#rrggbb`, `rgb(r,g,b)` ou `rgba(r,g,b,a)`. Null si illisible. */
export function lireCouleur(s: string): { rgb: RGB; alpha: number } | null {
  const t = s.trim()
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(t)
  if (hex) {
    const h = hex[1]!
    const p = h.length === 3 ? [...h].map((c) => c + c) : [h.slice(0, 2), h.slice(2, 4), h.slice(4, 6)]
    return { rgb: [parseInt(p[0]!, 16), parseInt(p[1]!, 16), parseInt(p[2]!, 16)], alpha: 1 }
  }
  const f = t.match(/[\d.]+/g)
  if (!f || f.length < 3) return null
  return {
    rgb: [Number(f[0]), Number(f[1]), Number(f[2])],
    alpha: f.length > 3 ? Number(f[3]) : 1,
  }
}

export const luminance = (c: RGB): number =>
  0.2126 * canal(c[0]) + 0.7152 * canal(c[1]) + 0.0722 * canal(c[2])

export function ratio(a: RGB, b: RGB): number {
  const la = luminance(a)
  const lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

/** Compose un premier plan translucide sur son fond avant de mesurer. */
export const composer = (fg: RGB, bg: RGB, alpha: number): RGB =>
  [0, 1, 2].map((i) => fg[i]! * alpha + bg[i]! * (1 - alpha)) as unknown as RGB

/** Le seuil applicable à un texte, selon sa taille et sa graisse. */
export const seuilPour = (px: number, graisse: number): number =>
  px >= 24 || (px >= 18.66 && graisse >= 600) ? AA_GRAND : AA
