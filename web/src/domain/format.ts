/**
 * FORMATAGE. Aucun import React, aucun accès au DOM, aucun `Date.now()`
 * implicite : l'instant se passe en argument, sinon rien n'est testable.
 */

/**
 * LE SEUL CHEMIN D'AFFICHAGE D'UNE VALEUR ABSENTE. Aucune substitution, aucun
 * zéro de complaisance. Quand une grandeur est absente pour tout le monde, la
 * raison se dit à côté — « le funding n'est pas séparé du PnL dans la source ».
 */
export const NA = 'N/D'

/** Moins typographique U+2212 : le trait d'union est trop court pour un signe. */
const MOINS = '−'

const fr = (v: number, d: number) => {
  // `(-0.004).toFixed(2)` rend « -0,00 » : un signe negatif sur une valeur
  // arrondie a zero ne dit rien de la mesure, il dit d'ou elle venait — ce que
  // la precision affichee ne porte deja plus.
  const arrondi = Math.abs(v) < 0.5 / 10 ** d ? 0 : v
  return arrondi.toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d })
}

/** Nombre en locale française, ou N/D. */
export function nb(v: number | null | undefined, d = 2): string {
  return v == null || !Number.isFinite(v) ? NA : fr(v, d)
}

/** Pourcentage. */
export function pc(v: number | null | undefined, d = 0): string {
  return v == null || !Number.isFinite(v) ? NA : `${fr(v, d)} %`
}

/**
 * Montant SIGNÉ et abrégé. L'abréviation est le format déclaré : au-dessus de
 * mille on n'écrit qu'une décimale de millier, ce qui borne l'écart légitime à
 * 50 $ — un contrôle de cohérence doit déduire sa tolérance de là, jamais la
 * choisir.
 */
export function usd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NA
  const a = Math.abs(v)
  const s = v < 0 ? MOINS : '+'
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}k`
  return `${s}$${a.toFixed(0)}`
}

/** Montant NON signé et non abrégé — drawdown, frais, volatilité. */
export function usdBrut(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return NA
  const a = Math.abs(v)
  return `$${a.toLocaleString('fr-FR', { maximumFractionDigits: a >= 10 ? 0 : 2 })}`
}

/** Signe d'une quantité monétaire, pour la paire divergente. */
export function signe(v: number | null | undefined): 'pos' | 'neg' | 'nul' {
  if (v == null || !Number.isFinite(v) || v === 0) return 'nul'
  return v > 0 ? 'pos' : 'neg'
}

/** 6 premiers, ellipse, 4 derniers. L'adresse complète va dans `title`. */
export const adresseCourte = (a: string): string =>
  a.length <= 12 ? a : `${a.slice(0, 6)}…${a.slice(-4)}`

/**
 * Groupée par quatre. Quarante-deux caractères d'affilée ne se vérifient pas à
 * l'œil, et c'est pourtant le seul usage d'une adresse.
 */
export const adresseGroupee = (a: string): string =>
  `0x${a.replace(/^0x/i, '').replace(/(.{4})/g, '$1 ').trim()}`

export function date(ms: number | null | undefined): string {
  return ms == null || !Number.isFinite(ms)
    ? NA
    : new Date(ms).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: '2-digit' })
}

export function dateHeure(ms: number | null | undefined): string {
  return ms == null || !Number.isFinite(ms)
    ? NA
    : new Date(ms).toLocaleString('fr-FR', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
}

/** Durée en jours, dite comme on la dit. */
export function jours(j: number | null | undefined): string {
  if (j == null || !Number.isFinite(j)) return NA
  if (j < 1) return "aujourd'hui"
  if (j < 2) return 'hier'
  return `${Math.round(j)} j`
}

export interface Age {
  texte: string
  /** au-delà du seuil : la fraîcheur change de sens, donc de couleur */
  vieux: boolean
}

/**
 * ÂGE RELATIF. Une page statique est consultée longtemps après avoir été
 * produite : une date absolue répond à « quand », jamais à « est-ce encore
 * vrai ». `maintenant` est un argument — le temps ne se lit pas en douce.
 */
export function age(ms: number | null | undefined, seuilH: number, maintenant: number): Age {
  if (ms == null || !Number.isFinite(ms)) return { texte: NA, vieux: false }
  const h = (maintenant - ms) / 3.6e6
  if (h < 0) return { texte: NA, vieux: false }
  const texte =
    h < 1 ? "il y a moins d'une heure" : h < 48 ? `il y a ${Math.round(h)} h` : `il y a ${Math.round(h / 24)} j`
  return { texte, vieux: h > seuilH }
}

/**
 * Les textes du moteur sont écrits en ASCII pur et ne se terminent pas par un
 * point : ce sont des fragments d'audit. À l'écran, dans une phrase française,
 * ça se lit comme une faute.
 */
const ACCENTS: Readonly<Record<string, string>> = {
  qualifie: 'qualifié',
  reactive: 'réactivé',
  archive: 'archivé',
  anciennete: 'ancienneté',
  regularite: 'régularité',
  decouvert: 'découvert',
  refute: 'réfuté',
  reevalue: 'réévalué',
  maintenu: 'maintenu',
}

const CLASSES: Readonly<Record<string, string>> = {
  EXCELLENT_CANDIDATE: 'Candidat excellent',
  PROMISING: 'Prometteur',
  INSUFFICIENT_DATA: 'Données insuffisantes',
  REJECTED: 'Non qualifié',
  RANKED: 'Classé',
  DISCOVERY: 'Observation',
  ARCHIVED: 'Archivé',
}

export const classeFr = (c: string | null | undefined): string =>
  c == null ? NA : (CLASSES[c] ?? c)

export function humaniser(t: string | null | undefined): string {
  return String(t ?? '')
    .replace(
      /\b(EXCELLENT_CANDIDATE|PROMISING|INSUFFICIENT_DATA|REJECTED|RANKED|DISCOVERY|ARCHIVED)\b/g,
      (m) => CLASSES[m] ?? m,
    )
    .replace(
      /\b(qualifie|reactive|archive|anciennete|regularite|decouvert|refute|reevalue|maintenu)\b/g,
      (m) => ACCENTS[m] ?? m,
    )
}

/** Termine une phrase du moteur qui n'a pas de point. */
export function phrase(t: string | null | undefined): string {
  const x = String(t ?? '').trim()
  return x && !/[.!?]$/.test(x) ? `${x}.` : x
}

/**
 * Le motif de non-qualification est rédigé en prose d'audit — « anciennete : 81
 * jours entre trades clos, borne inferieure des jours couverts, non concluant
 * face a 130 ». C'est la bonne trace dans un journal, et cinq lignes illisibles
 * dans une liste. On garde le critère et son chiffre.
 */
export function critere(t: string | null | undefined): string {
  const s = String(t ?? '').trim()
  const m = /^anciennet[ée]\s*:\s*(\d+)\s*jours/i.exec(s)
  if (m) return `ancienneté ${m[1]} j`
  return s.includes(':') ? (s.split(':')[0] ?? s).trim() : s
}

/** p-valeur : notation scientifique sous 0,001, sinon trois décimales. */
export function pval(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return NA
  if (p === 0) return '< 1e-16'
  if (p < 1e-3) return p.toExponential(1).replace('e', ' × 10^').replace('+', '')
  return fr(p, 3)
}
