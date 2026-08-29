/**
 * Les cas limites, et rien d'autre. Un test qui vérifie qu'une fonction rend ce
 * qu'elle rend ne prouve rien ; ceux-ci reproduisent chacun un défaut mesuré.
 */
import { describe, expect, it } from 'vitest'
import type { Ligne } from './types'
import { NA, adresseGroupee, age, critere, humaniser, pval, usd, usdBrut } from './format'
import { bande, icCourt, icLong, largeurIC, scoreTxt, vigilance } from './score'
import { partitionner, partitionnerMulti, triDe, TRI_DEFAUT } from './tri'
import { appliquer, filtreDe, FILTRE_DEFAUT, filtresVisibles } from './filtres'
import { analyser, chercher, norm, surligner } from './recherche'
import { calculer, divergences } from './bandes'

const L = (p: Partial<Ligne> & { a: string }): Ligne => ({
  rang: 1,
  groupe: 1,
  score: 50,
  ic: [40, 60],
  sature: false,
  conf: 50,
  conf_lab: 'moyenne',
  sr: 0.1,
  post: 0.05,
  se: 0.03,
  pnl: 100,
  pnl_hors_max: 50,
  frais: 10,
  n: 40,
  dd: 20,
  dort_j: 3,
  r30: 5,
  r7: 1,
  drang_rel: 0,
  lb_p: 0.5,
  st: 'RANKED',
  coins: ['BTC'],
  ...p,
})

describe('format', () => {
  it('abrège au-dessus de mille, avec un moins typographique', () => {
    expect(usd(6154.97)).toBe('+$6.2k')
    expect(usd(-2115.42)).toBe('−$2.1k')
    expect(usd(1_240_000)).toBe('+$1.24M')
    expect(usd(74)).toBe('+$74')
  })

  it('N/D est le seul chemin d’une valeur absente', () => {
    expect(usd(null)).toBe(NA)
    expect(usd(Number.NaN)).toBe(NA)
    expect(usdBrut(undefined)).toBe(NA)
    // Surtout pas un zéro de complaisance.
    expect(usd(null)).not.toBe('+$0')
  })

  it('groupe l’adresse par quatre — 42 caractères ne se vérifient pas à l’œil', () => {
    expect(adresseGroupee('0xf2c9c2ebaebfc38f76d825b09a91aeec477f4fcf')).toBe(
      '0xf2c9 c2eb aebf c38f 76d8 25b0 9a91 aeec 477f 4fcf',
    )
  })

  it('l’âge bascule en vieux au-delà du seuil, et le temps se passe en argument', () => {
    const t = 1_700_000_000_000
    expect(age(t - 3.6e6, 48, t).vieux).toBe(false)
    expect(age(t - 90 * 24 * 3.6e6, 48, t).vieux).toBe(true)
    expect(age(t - 1.8e6, 48, t).texte).toBe("il y a moins d'une heure")
  })

  it('accentue les mots ASCII du moteur sans toucher au moteur', () => {
    expect(humaniser('qualifie — EXCELLENT_CANDIDATE, rang 4')).toBe(
      'qualifié — Candidat excellent, rang 4',
    )
  })

  it('réduit la prose d’audit au critère et à son chiffre', () => {
    expect(critere('anciennete : 81 jours entre trades clos, borne inferieure')).toBe(
      'ancienneté 81 j',
    )
    expect(critere('25 trades clos < 30')).toBe('25 trades clos < 30')
  })

  it('écrit une p-valeur minuscule en notation scientifique', () => {
    expect(pval(0.5)).toBe('0,500')
    expect(pval(9.57e-7)).toContain('10^')
    expect(pval(null)).toBe(NA)
  })
})

describe('score', () => {
  it('supprime la décimale dès que l’intervalle dépasse 20 points', () => {
    // Un chiffre n'est jamais plus précis que son intervalle.
    expect(scoreTxt(L({ a: 'x', score: 98.1, ic: [64, 100] }))).toBe('98')
    expect(scoreTxt(L({ a: 'x', score: 98.8, ic: [80, 100] }))).toBe('98.8')
    expect(largeurIC(L({ a: 'x', ic: [64, 100] }))).toBe(36)
  })

  it('n’affiche JAMAIS un intervalle de largeur nulle comme un intervalle', () => {
    const sature = L({ a: 'x', score: 100, ic: [100, 100] })
    expect(icCourt(sature)).not.toContain('100–100')
    expect(icCourt(sature)).toContain('borne')
    expect(icLong(sature)).toContain('pas une mesure')
  })

  it('annonce la saturation d’une seule borne', () => {
    expect(icCourt(L({ a: 'x', ic: [31, 100] }))).toBe('31–≥100')
    expect(icLong(L({ a: 'x', ic: [0, 60] }))).toContain('bas saturé')
  })

  it('nomme la bande sur deux chiffres', () => {
    expect(bande(L({ a: 'x', groupe: 3 }))).toBe('G03')
  })

  it('marque la dépendance sérielle sous 0,05', () => {
    expect(vigilance(L({ a: 'x', lb_p: 0.0159 }))).toBe(true)
    expect(vigilance(L({ a: 'x', lb_p: 0.5 }))).toBe(false)
    // Absence de mesure n'est pas absence de dépendance.
    expect(vigilance(L({ a: 'x', lb_p: null }))).toBe(false)
  })
})

describe('tri', () => {
  const lignes = [
    L({ a: '0xa', conf: 90, score: 10 }),
    L({ a: '0xb', conf: null, score: 80 }),
    L({ a: '0xc', conf: 10, score: 50 }),
    L({ a: '0xd', conf: null, score: 20 }),
  ]

  it('SORT les non-mesurables de l’ordre au lieu de les enfouir en queue', () => {
    const p = partitionner(lignes, 'proba')
    expect(p.mesurables.map((l) => l.a)).toEqual(['0xa', '0xc'])
    expect(p.absents.map((l) => l.a)).toEqual(['0xb', '0xd'])
    expect(p.libelle).toBe('Probabilité')
  })

  it('ne sépare rien quand le critère est toujours présent', () => {
    expect(partitionner(lignes, 'score').absents).toHaveLength(0)
  })

  it('repli NOMMÉ sur une clé inconnue', () => {
    expect(triDe('nawak').cle).toBe(TRI_DEFAUT)
  })

  it('repousse les dormants sans les cacher', () => {
    const p = partitionner(
      [L({ a: '0xa', score: 99, dort_j: 300 }), L({ a: '0xb', score: 10, dort_j: 1 })],
      'score_actifs',
    )
    expect(p.mesurables.map((l) => l.a)).toEqual(['0xb', '0xa'])
  })

  it('multi-tri : la seconde clé ne départage que les égalités exactes', () => {
    const eg = [L({ a: '0xa', groupe: 1, score: 10 }), L({ a: '0xb', groupe: 1, score: 90 })]
    expect(partitionnerMulti(eg, ['groupe', 'score']).mesurables.map((l) => l.a)).toEqual([
      '0xb',
      '0xa',
    ])
  })

  it('l’ordre est déterministe même à égalité totale', () => {
    const eg = [L({ a: '0xb', score: 5 }), L({ a: '0xa', score: 5 })]
    expect(partitionnerMulti(eg, ['score']).mesurables.map((l) => l.a)).toEqual(['0xa', '0xb'])
  })
})

describe('filtres', () => {
  const lignes = [
    L({ a: '0xa', st: 'RANKED', dort_j: 300, lb_p: 0.01 }),
    L({ a: '0xb', st: 'DISCOVERY', dort_j: 1 }),
    L({ a: '0xc', st: 'RANKED', pnl: 500, pnl_hors_max: -20 }),
  ]
  const vide = new Set<string>()

  it('repli NOMMÉ — un repli positionnel a déjà changé de sens en silence', () => {
    expect(filtreDe('inconnu').cle).toBe(FILTRE_DEFAUT)
  })

  it('les filtres de qualité existent sans avoir de pastille', () => {
    expect(filtreDe('q1').cle).toBe('q1')
    expect(filtresVisibles().map((f) => f.cle)).not.toContain('q1')
  })

  it('isole la bascule sans le meilleur trade', () => {
    expect(appliquer(lignes, 'bascule', vide).map((l) => l.a)).toEqual(['0xc'])
  })

  it('isole la vigilance', () => {
    expect(appliquer(lignes, 'vigilance', vide).map((l) => l.a)).toEqual(['0xa'])
  })
})

describe('recherche', () => {
  const a = '0xf2c9c2ebaebfc38f76d825b09a91aeec477f4fcf'
  const lignes = [L({ a, rang: 4, groupe: 2 }), L({ a: '0x00b3fe42', rang: 7, groupe: 1 })]

  it('retrouve l’adresse groupée que l’application copie elle-même', () => {
    const groupee = '0xF2C9 C2EB AEBF C38F 76D8 25B0 9A91 AEEC 477F 4FCF'
    expect(chercher(lignes, groupee).map((l) => l.a)).toEqual([a])
  })

  it('une requête numérique est un RANG, pas un fragment hexadécimal', () => {
    // « 1 » remontait 211 wallets : tous ceux dont l'adresse contient un 1.
    expect(analyser('7').genre).toBe('rang')
    expect(chercher(lignes, '7').map((l) => l.rang)).toEqual([7])
  })

  it('une bande se cherche aussi', () => {
    expect(chercher(lignes, 'G02').map((l) => l.groupe)).toEqual([2])
  })

  it('cherche par ticker', () => {
    expect(chercher([L({ a: '0x1', coins: ['ETH'] })], 'eth')).toHaveLength(1)
  })

  it('normalise des deux côtés', () => {
    expect(norm('0x F2C9 C2EB')).toBe('0xf2c9c2eb')
  })

  it('surligne dans le texte AFFICHÉ, pas dans la forme normalisée', () => {
    const s = surligner('0xf2c9…4fcf', 'f2 c9')
    expect(s.filter((x) => x.marque).map((x) => x.t)).toEqual(['f2c9'])
    expect(s.map((x) => x.t).join('')).toBe('0xf2c9…4fcf')
  })
})

describe('bandes', () => {
  it('regroupe tant que l’intervalle recouvre celui de l’ancre', () => {
    const l = [
      L({ a: '0xa', rang: 1, ic: [90, 100] }),
      L({ a: '0xb', rang: 2, ic: [85, 99] }),
      L({ a: '0xc', rang: 3, ic: [10, 40] }),
    ]
    const c = calculer(l)
    expect(c.get('0xa')).toBe(1)
    expect(c.get('0xb')).toBe(1)
    expect(c.get('0xc')).toBe(2)
  })

  it('signale une divergence avec la bande transportée', () => {
    const l = [L({ a: '0xa', rang: 1, ic: [90, 100], groupe: 1 }), L({ a: '0xb', rang: 2, ic: [0, 5], groupe: 1 })]
    expect(divergences(l)).toEqual(['0xb'])
  })
})
