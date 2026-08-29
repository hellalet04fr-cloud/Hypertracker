import { describe, expect, it, vi } from 'vitest'
import type { Ligne, PointHisto, SerieEq } from '@/domain/types'
import { DPR_MAX, plusProche, preparer } from './moteur'
import { canvas, description, geometrie, svg } from './rail'
import { drawdown, equity } from './courbe'
import { ZERO_SR, moisApres, nDates, parDate, retrecissement } from './figures'

const L = (p: Partial<Ligne> & { a: string }): Ligne => ({
  rang: 1, groupe: 1, score: 50, ic: [40, 60], sature: false, conf: 50,
  conf_lab: 'moyenne', sr: 0.1, post: 0.05, se: 0.03, pnl: 100, pnl_hors_max: 50,
  frais: 10, n: 40, dd: 20, dort_j: 3, r30: 5, r7: 1, drang_rel: 0, lb_p: 0.5,
  st: 'RANKED', coins: [], ...p,
})

describe('moteur', () => {
  it('plafonne le ratio de pixels — au-delà on peint pour rien', () => {
    // jsdom n'implemente pas getContext('2d') : sans ce faux contexte, le
    // controle mesurerait l'environnement au lieu du code.
    vi.stubGlobal('devicePixelRatio', 4)
    const cv = document.createElement('canvas')
    Object.defineProperty(cv, 'clientWidth', { value: 200 })
    cv.getContext = (() => ({ setTransform: () => {}, clearRect: () => {} })) as never
    const t = preparer(cv, 100)
    expect(t?.dpr).toBe(DPR_MAX)
    expect(cv.width).toBe(500)
    vi.unstubAllGlobals()
  })

  it('rend null plutot que de jeter quand aucun contexte 2D n’est disponible', () => {
    const cv = document.createElement('canvas')
    cv.getContext = (() => null) as never
    expect(preparer(cv, 100)).toBeNull()
  })

  it('trouve le point le plus proche par bissection', () => {
    const xs = [0, 10, 20, 30, 40]
    expect(plusProche(xs, 21)).toBe(2)
    expect(plusProche(xs, 26)).toBe(3)
    expect(plusProche(xs, -5)).toBe(0)
    expect(plusProche(xs, 999)).toBe(4)
    expect(plusProche([], 3)).toBe(-1)
  })

  it('reste exact sur un grand nombre de points', () => {
    const xs = Array.from({ length: 20_000 }, (_, i) => i * 0.5)
    expect(plusProche(xs, 5000.2)).toBe(10_000)
  })
})

describe('rail — la figure centrale', () => {
  it('place l’index sur le score et les mors sur l’intervalle', () => {
    const g = geometrie(L({ a: '0x1', score: 50, ic: [25, 75] }), { w: 300, h: 26, marge: 0 })
    expect(g.xIndex).toBeCloseTo(150, 6)
    expect(g.xBas).toBeCloseTo(75, 6)
    expect(g.xHaut).toBeCloseTo(225, 6)
  })

  it('OUVRE le mors sur une borne saturée — un mors fermé serait une certitude', () => {
    const g = geometrie(L({ a: '0x1', score: 100, ic: [100, 100] }))
    expect(g.ouvertHaut).toBe(true)
    expect(g.ouvertBas).toBe(false)
    // Le SVG doit alors porter un chemin, pas deux segments verticaux.
    expect(svg(L({ a: '0x1', score: 100, ic: [100, 100] }))).toContain('<path')
  })

  it('encode la qualité par le TRAIT, canal non chromatique', () => {
    expect(geometrie(L({ a: '0x1', conf_lab: 'elevee' })).tirets).toEqual([])
    expect(geometrie(L({ a: '0x1', conf_lab: 'moyenne' })).tirets).toEqual([3, 2])
    expect(geometrie(L({ a: '0x1', conf_lab: 'faible' })).tirets).toEqual([1, 3])
  })

  it('décrit les trois canaux en mots pour un lecteur d’écran', () => {
    const d = description(L({ a: '0x1', score: 98.1, ic: [64, 100], conf_lab: 'faible' }))
    expect(d).toContain('98')
    expect(d).toContain('Intervalle')
    expect(d).toContain('faible')
  })

  it('SVG et CANVAS rendent la MÊME figure — 31 505 SVG feraient tomber le navigateur', () => {
    const l = L({ a: '0x1', score: 73.4, ic: [12, 100], conf_lab: 'faible' })
    const o = { w: 120, h: 20 }
    const g = geometrie(l, o)

    const appels: Array<[number, number]> = []
    const faux = {
      save: () => {}, restore: () => {}, translate: () => {}, beginPath: () => {},
      closePath: () => {}, stroke: () => {}, fill: () => {}, setLineDash: () => {},
      moveTo: (x: number, y: number) => appels.push([x, y]),
      lineTo: (x: number, y: number) => appels.push([x, y]),
      lineWidth: 0, strokeStyle: '', fillStyle: '',
    } as unknown as CanvasRenderingContext2D
    canvas(faux, l, 0, 0, { filet: '#1', gris: '#2', index: '#3' }, o)

    // L'index est dessiné en dernier : ses deux points portent son abscisse.
    const xIndex = appels[appels.length - 1]![0]
    expect(Math.abs(xIndex - g.xIndex)).toBeLessThan(0.5)
    // Et le SVG parle de la même abscisse.
    expect(svg(l, o)).toContain(String(g.xIndex))
  })
})

describe('courbe', () => {
  const e: SerieEq = { t0: 1_700_000_000, d: [60, 120], v: [0, 100, 40] }

  it('reconstruit la série depuis des écarts en MINUTES', () => {
    const p = equity(e)
    expect(p).toHaveLength(3)
    expect(p[0]![0]).toBe(1_700_000_000_000)
    expect(p[1]![0]).toBe((1_700_000_000 + 3600) * 1000)
    expect(p[2]![1]).toBe(40)
  })

  it('déduit le drawdown, sommet à zéro', () => {
    const d = drawdown(e)
    expect(d[0]![1]).toBe(0)
    expect(d[1]![1]).toBe(0)
    // sommet 100, valeur 40 -> repli de 60
    expect(d[2]![1]).toBe(-60)
  })

  it('une série absente ne produit rien plutôt qu’un zéro', () => {
    expect(equity(null)).toEqual([])
    expect(drawdown(null)).toEqual([])
  })
})

describe('figures', () => {
  it('déduit les étiquettes de mois d’un point de départ', () => {
    expect(moisApres('2025-09', 0)).toBe('2025-09')
    expect(moisApres('2025-09', 4)).toBe('2026-01')
    expect(moisApres(null, 2)).toBe('')
  })

  it('compte les DATES DISTINCTES, jamais les lignes', () => {
    // Trois points à quelques minutes d'intervalle sont UN relevé.
    const t = Math.floor(Date.UTC(2026, 7, 27, 10) / 1000)
    const h: PointHisto[] = [
      [t, 10, 5],
      [t + 207, 10, 5],
      [t + 327, 10, 5],
      [t + 86_400, 12, 4],
    ]
    expect(nDates(h)).toBe(2)
    expect(parDate(h, 2)).toHaveLength(2)
  })

  it('ignore les points sans valeur sur le champ demandé', () => {
    const t = Math.floor(Date.UTC(2026, 7, 27) / 1000)
    expect(parDate([[t, null, 3], [t + 86_400, 5, null]], 1)).toHaveLength(1)
  })

  it('le zéro du Sharpe est une constante NOMMÉE, pas la borne d’une autre échelle', () => {
    expect(ZERO_SR).toBe(0)
    const s = retrecissement({ sr: 0.39, post: 0.23, se: 0.03, min: -0.6, max: 0.5 })
    expect(s).toContain('<text')
    // L'erreur type est dessinée : le brut est un point ET son flou.
    expect(s).toContain('opacity="0.35"')
  })

  it('trace le rétrécissement sans erreur type quand elle manque', () => {
    const s = retrecissement({ sr: 0.39, post: 0.23, se: null, min: -0.6, max: 0.5 })
    expect(s).not.toContain('opacity="0.35"')
  })
})
