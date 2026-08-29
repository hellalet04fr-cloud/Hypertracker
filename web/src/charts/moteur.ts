/**
 * SOCLE DE TRACÉ.
 *
 * Aucune librairie de graphiques. Ces figures ont une grammaire propre — mors
 * d'intervalle, hachures sous zéro, échelle de rang inversée — qu'aucune
 * librairie ne rend sans être combattue, et le budget de fluidité ne supporte
 * pas une couche d'abstraction de plus.
 */

/** Au-delà, on peint quatre fois plus de pixels pour une différence invisible. */
export const DPR_MAX = 2.5

export interface Toile {
  ctx: CanvasRenderingContext2D
  /** dimensions CSS, pas physiques : tout le dessin se fait dans ce repère */
  w: number
  h: number
  dpr: number
}

/**
 * Prépare un canvas : dimensions physiques d'un côté, repère CSS de l'autre.
 * Le `setTransform` évite d'avoir à multiplier chaque coordonnée par le ratio,
 * ce qui est exactement le genre d'oubli qui produit une figure floue sur un
 * seul écran.
 */
export function preparer(cv: HTMLCanvasElement, hauteur: number): Toile | null {
  const ctx = cv.getContext('2d')
  if (!ctx) return null
  const dpr = Math.min(globalThis.devicePixelRatio || 1, DPR_MAX)
  const w = cv.clientWidth || cv.parentElement?.clientWidth || 320
  cv.width = Math.max(1, Math.round(w * dpr))
  cv.height = Math.max(1, Math.round(hauteur * dpr))
  cv.style.height = `${hauteur}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, hauteur)
  return { ctx, w, h: hauteur, dpr }
}

const cacheJetons = new Map<string, string>()

/**
 * Lit un jeton CSS. Mis en cache : `getComputedStyle` force un recalcul de
 * style, et l'appeler une fois par barre d'un histogramme suffit à faire chuter
 * le rendu. Le cache se vide si le thème change — ce qui n'arrive pas ici, le
 * registre étant unique et assumé.
 */
export function lireJeton(nom: string): string {
  const c = cacheJetons.get(nom)
  if (c !== undefined) return c
  const v =
    typeof getComputedStyle === 'function'
      ? getComputedStyle(document.documentElement).getPropertyValue(nom).trim()
      : ''
  const r = v || '#888'
  cacheJetons.set(nom, r)
  return r
}

export const oublierJetons = (): void => cacheJetons.clear()

/**
 * INDEX DU POINT LE PLUS PROCHE, PAR BISSECTION.
 *
 * `xs` doit être croissant — c'est le cas de toute série temporelle. Un balayage
 * linéaire coûterait O(n) par déplacement de doigt ; le budget est de 8 ms par
 * déplacement, et une courbe peut porter des milliers de points.
 */
export function plusProche(xs: readonly number[] | Float64Array, cible: number): number {
  const n = xs.length
  if (n === 0) return -1
  let bas = 0
  let haut = n - 1
  while (haut - bas > 1) {
    const mi = (bas + haut) >> 1
    if (xs[mi]! <= cible) bas = mi
    else haut = mi
  }
  return cible - xs[bas]! <= xs[haut]! - cible ? bas : haut
}

export interface Pointeur {
  /** index du point sous le doigt, ou null quand il est relevé */
  surIndex: (i: number | null) => void
  /** projection d'un index vers son abscisse CSS */
  px: (i: number) => number
  n: number
}

/**
 * Suivi au doigt.
 *
 * `touch-action: none` est posé par la feuille de style, et `preventDefault`
 * ici : sans les deux, le navigateur interprète le même geste comme un
 * défilement, et l'infobulle glisse pendant que la page file. Sur une courbe de
 * deux cents points, c'est inexploitable.
 */
export function brancherPointeur(cv: HTMLCanvasElement, p: Pointeur): () => void {
  const xs = new Float64Array(p.n)
  for (let i = 0; i < p.n; i++) xs[i] = p.px(i)

  const bouge = (e: PointerEvent) => {
    if (e.pointerType === 'touch' && e.cancelable) e.preventDefault()
    const r = cv.getBoundingClientRect()
    p.surIndex(plusProche(xs, e.clientX - r.left))
  }
  const fin = () => p.surIndex(null)
  const descend = (e: PointerEvent) => {
    cv.setPointerCapture?.(e.pointerId)
    bouge(e)
  }
  const glisse = (e: PointerEvent) => {
    if (e.buttons || e.pointerType === 'touch') bouge(e)
  }

  cv.addEventListener('pointerdown', descend)
  cv.addEventListener('pointermove', glisse)
  cv.addEventListener('pointerup', fin)
  cv.addEventListener('pointerleave', fin)
  cv.addEventListener('pointercancel', fin)
  return () => {
    cv.removeEventListener('pointerdown', descend)
    cv.removeEventListener('pointermove', glisse)
    cv.removeEventListener('pointerup', fin)
    cv.removeEventListener('pointerleave', fin)
    cv.removeEventListener('pointercancel', fin)
  }
}

/** Message d'un tracé qui n'a rien à tracer — dit, jamais laissé vide. */
export function vide(t: Toile, texte = 'Pas assez de relevés'): void {
  const { ctx, w, h } = t
  ctx.fillStyle = lireJeton('--faible')
  ctx.font = `12px ${lireJeton('--f-texte') || 'sans-serif'}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(texte, w / 2, h / 2)
  ctx.textBaseline = 'alphabetic'
}
