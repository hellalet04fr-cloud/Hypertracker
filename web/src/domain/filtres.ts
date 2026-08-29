/**
 * LE REGISTRE DES FILTRES.
 *
 * Deux listes distinctes se cachent ici, et les confondre a déjà cassé le
 * produit : le REGISTRE des filtres — que d'autres contrôles appellent par leur
 * clé — et ce qui se montre en pastille. Retirer une pastille redondante
 * retirait aussi le filtre, et le contrôle qui l'appelait retombait en silence
 * sur le filtre par défaut, en sélectionnant la mauvaise population.
 */
import type { Ligne } from './types'
import { dormant, vigilance } from './score'

export interface Filtre {
  cle: string
  libelle: string
  predicat: (l: Ligne, suivis: ReadonlySet<string>) => boolean
  /** faux quand un autre contrôle porte ce filtre : pas de pastille, mais le filtre existe */
  visible: boolean
  /** aide affichée quand le résultat est vide ou trompeur */
  note?: string
}

export const FILTRES: readonly Filtre[] = [
  { cle: 'classes', libelle: 'Classés', predicat: (l) => l.st === 'RANKED', visible: true },
  { cle: 'tous', libelle: 'Tous', predicat: () => true, visible: true },
  { cle: 'dormants', libelle: 'Dormants', predicat: (l) => dormant(l), visible: true },
  {
    cle: 'vigilance',
    libelle: 'Vigilance',
    predicat: (l) => vigilance(l),
    visible: true,
    note: 'Trades non indépendants (Ljung-Box p < 0,05) : les intervalles calculés en supposant l’indépendance sont trop optimistes.',
  },
  { cle: 'actifs30', libelle: 'Actifs 30 j', predicat: (l) => l.r30 > 0, visible: true },
  { cle: 'gagnants', libelle: 'PnL net > 0', predicat: (l) => l.pnl > 0, visible: true },
  {
    cle: 'bascule',
    libelle: 'Bascule sans son meilleur trade',
    predicat: (l) => l.pnl > 0 && l.pnl_hors_max <= 0,
    visible: true,
    note: 'Gagnants qui deviennent perdants une fois retiré leur plus gros trade.',
  },
  { cle: 'suivis', libelle: 'Suivis', predicat: (l, s) => s.has(l.a), visible: true },
  {
    // Ce filtre ne peut montrer que les wallets EMBARQUÉS. L'onglet Données en
    // annonce 52 030 en observation : deux populations, un seul mot.
    cle: 'observation',
    libelle: 'Observation (échantillon)',
    predicat: (l) => l.st === 'DISCOVERY',
    visible: true,
    note: 'Seuls les wallets déjà mesurés figurent ici. La population en observation est bien plus large — voir l’onglet Données.',
  },
  // Appelés par la bande de convention, pas par une pastille : deux contrôles
  // pour un même filtre étaient un doublon, mais retirer le filtre avec la
  // pastille cassait la bande.
  { cle: 'q3', libelle: 'Qualité élevée', predicat: (l) => l.conf_lab === 'elevee', visible: false },
  { cle: 'q2', libelle: 'Qualité moyenne', predicat: (l) => l.conf_lab === 'moyenne', visible: false },
  { cle: 'q1', libelle: 'Qualité faible', predicat: (l) => l.conf_lab === 'faible', visible: false },
]

const PAR_CLE = new Map(FILTRES.map((f) => [f.cle, f]))

export const FILTRE_DEFAUT = 'classes'

/** Repli NOMMÉ. Voir l'en-tête de ce fichier : le repli positionnel a déjà menti. */
export const filtreDe = (cle: string): Filtre => PAR_CLE.get(cle) ?? PAR_CLE.get(FILTRE_DEFAUT)!

export const filtresVisibles = (): readonly Filtre[] => FILTRES.filter((f) => f.visible)

export function appliquer(
  lignes: readonly Ligne[],
  cle: string,
  suivis: ReadonlySet<string>,
): Ligne[] {
  const f = filtreDe(cle)
  return lignes.filter((l) => f.predicat(l, suivis))
}

/** Effectif de chaque filtre, pour que les pastilles annoncent un nombre vrai. */
export function effectifs(
  lignes: readonly Ligne[],
  suivis: ReadonlySet<string>,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of FILTRES) {
    let n = 0
    for (const l of lignes) if (f.predicat(l, suivis)) n++
    out[f.cle] = n
  }
  return out
}
