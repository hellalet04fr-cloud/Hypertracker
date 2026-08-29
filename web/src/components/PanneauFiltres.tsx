/**
 * LES FILTRES.
 *
 * Deux formes, un seul registre : une colonne sur le poste de travail, une
 * rangée qui défile sur mobile.
 *
 * LA RANGÉE PORTE UN MASQUE DE DÉGRADÉ sur son bord droit. Sans lui, une
 * pastille coupée net ressemble à une pastille qui finit là : l'audit a montré
 * que vingt et un contrôles étaient ainsi devenus invisibles.
 */
import type { ReactNode } from 'react'
import { FILTRES, filtresVisibles } from '@/domain/filtres'
import { Mono, Stack, Text } from '@/design/primitives'
import s from './PanneauFiltres.module.css'

interface Props {
  filtre: string
  effectifs: Readonly<Record<string, number>>
  total: number
  onFiltre: (cle: string) => void
  recherche?: ReactNode
  /** forme mobile : une rangée qui défile */
  rangee?: boolean
}

export function PanneauFiltres({ filtre, effectifs, total, onFiltre, recherche, rangee = false }: Props) {
  const visibles = filtresVisibles()

  if (rangee) {
    return (
      <div className={s.rangee} role="group" aria-label="Filtres">
        {visibles.map((f) => (
          <button
            key={f.cle}
            type="button"
            className={`${s.pastille} ${f.cle === filtre ? s.actif : ''}`}
            aria-pressed={f.cle === filtre}
            onClick={() => onFiltre(f.cle)}
          >
            {f.libelle}
            <Mono taille={11} encre="faible" className={s.n}>
              {effectifs[f.cle] ?? 0}
            </Mono>
          </button>
        ))}
      </div>
    )
  }

  const qualites = FILTRES.filter((f) => f.cle.startsWith('q'))

  return (
    <Stack className={s.colonne} espace={0}>
      {recherche}

      <Text variante="libelle" encre="faible" className={s.titre}>
        Population
      </Text>
      {visibles.map((f) => (
        <button
          key={f.cle}
          type="button"
          className={`${s.entree} ${f.cle === filtre ? s.actif : ''}`}
          aria-pressed={f.cle === filtre}
          onClick={() => onFiltre(f.cle)}
        >
          <span className={s.lib}>{f.libelle}</span>
          <Mono taille={11} encre={f.cle === filtre ? 'index' : 'faible'}>
            {effectifs[f.cle] ?? 0}
          </Mono>
        </button>
      ))}

      {/* LA BANDE DE CONVENTION : légende du style de trait des mors, répartition
          ET filtre, en un seul objet. Trois pastilles supplémentaires auraient
          fait doublon avec elle en moins riche. */}
      <Text variante="libelle" encre="faible" className={s.titre}>
        Qualité des données
      </Text>
      <div className={s.convention}>
        {qualites.map((f, i) => (
          <button
            key={f.cle}
            type="button"
            className={`${s.seg} ${f.cle === filtre ? s.actif : ''}`}
            aria-pressed={f.cle === filtre}
            onClick={() => onFiltre(f.cle)}
          >
            <i className={s[`t${i}`]} aria-hidden="true" />
            <span>
              {f.libelle.replace('Qualité ', '')} {effectifs[f.cle] ?? 0}
            </span>
          </button>
        ))}
      </div>

      <Text taille={11} encre="faible" className={s.pied}>
        {total} wallets mesurés. Le style du trait est celui des mors du rail :
        plein, tireté, pointillé.
      </Text>
    </Stack>
  )
}
