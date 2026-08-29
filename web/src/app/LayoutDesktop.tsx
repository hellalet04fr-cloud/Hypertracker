/**
 * LE POSTE DE TRAVAIL.
 *
 * Trois colonnes redimensionnables, plein écran, aucune largeur maximale. Ce
 * n'est pas la version large de l'application mobile : c'est une autre
 * composition, faite pour qu'on lise 34 lignes à la fois et qu'on inspecte sans
 * naviguer.
 *
 * Les poignées se pilotent AU POINTEUR ET AU CLAVIER. Une colonne
 * redimensionnable seulement à la souris est une colonne fixe pour qui n'en a
 * pas.
 */
import { useCallback, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { usePreferences } from '@/stores'
import s from './LayoutDesktop.module.css'

interface PoigneeProps {
  quoi: 'population' | 'inspecteur'
  libelle: string
  valeur: number
  poser: (px: number) => void
}

const PAS_CLAVIER = 16

function Poignee({ quoi, libelle, valeur, poser }: PoigneeProps) {
  const ref = useRef<HTMLDivElement>(null)
  const glisse = useRef<{ x0: number; v0: number } | null>(null)

  const bouge = useCallback(
    (e: PointerEvent) => {
      const g = glisse.current
      if (!g) return
      const d = e.clientX - g.x0
      poser(quoi === 'population' ? g.v0 + d : g.v0 - d)
    },
    [poser, quoi],
  )

  const fin = useCallback(() => {
    glisse.current = null
    document.removeEventListener('pointermove', bouge)
    document.removeEventListener('pointerup', fin)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [bouge])

  useEffect(() => () => fin(), [fin])

  return (
    <div
      ref={ref}
      className={s.poignee}
      role="separator"
      aria-orientation="vertical"
      aria-label={libelle}
      aria-valuenow={Math.round(valeur)}
      tabIndex={0}
      onPointerDown={(e) => {
        e.preventDefault()
        glisse.current = { x0: e.clientX, v0: valeur }
        document.addEventListener('pointermove', bouge)
        document.addEventListener('pointerup', fin)
        // Sans ces deux lignes, un glissé rapide sélectionne le texte des deux
        // colonnes et le curseur redevient une flèche au premier pixel sorti.
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
      }}
      onKeyDown={(e) => {
        const sens = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0
        if (!sens) return
        e.preventDefault()
        e.stopPropagation()
        poser(valeur + sens * PAS_CLAVIER * (quoi === 'population' ? 1 : -1))
      }}
    />
  )
}

interface Props {
  verdict: ReactNode
  population: ReactNode
  releve: ReactNode
  inspecteur: ReactNode
  etat: ReactNode
}

export function LayoutDesktop({ verdict, population, releve, inspecteur, etat }: Props) {
  const largeurPopulation = usePreferences((e) => e.largeurPopulation)
  const largeurInspecteur = usePreferences((e) => e.largeurInspecteur)
  const poserLargeur = usePreferences((e) => e.poserLargeur)

  return (
    <div className={s.poste}>
      {verdict}
      <div
        className={s.colonnes}
        style={{
          gridTemplateColumns: `${largeurPopulation}px 1px minmax(0, 1fr) 1px ${largeurInspecteur}px`,
        }}
      >
        <section className={s.population} aria-label="Population">
          {population}
        </section>
        <Poignee
          quoi="population"
          libelle="Largeur de la colonne Population"
          valeur={largeurPopulation}
          poser={(px) => poserLargeur('population', px)}
        />
        <section className={s.releve} aria-label="Relevé">
          {releve}
        </section>
        <Poignee
          quoi="inspecteur"
          libelle="Largeur de la colonne Inspecteur"
          valeur={largeurInspecteur}
          poser={(px) => poserLargeur('inspecteur', px)}
        />
        <section className={s.inspecteur} aria-label="Inspecteur">
          {inspecteur}
        </section>
      </div>
      <footer className={s.etat}>{etat}</footer>
    </div>
  )
}
