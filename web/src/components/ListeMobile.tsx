/**
 * LA LISTE MOBILE — relevés de 72 px, virtualisés.
 *
 * PAS D'ARIA-LABEL SUR LE CONTENEUR. Il REMPLACE le contenu pour une
 * technologie d'assistance : la version précédente y perdait le nombre de
 * trades, l'activité, la provenance et la description du rail — soigneusement
 * rédigée, jamais lue. Le libellé va sur l'élément focusable ; le contenu reste
 * lisible.
 */
import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Link } from 'react-router-dom'
import type { Ligne } from '@/domain/types'
import { activite, bande, dormant, scoreTxt, vigilance } from '@/domain/score'
import { adresseCourte } from '@/domain/format'
import { description, svg, viewBox } from '@/charts/rail'
import { Mono, Text } from '@/design/primitives'
import { Separateur } from './Communs'
import s from './ListeMobile.module.css'

export const H_RELEVE = 72

interface Props {
  mesurables: readonly Ligne[]
  absents: readonly Ligne[]
  critere: string
  suivis: ReadonlySet<string>
  onSuivre: (a: string) => void
}

type Element =
  | { genre: 'ligne'; l: Ligne }
  | { genre: 'separateur'; n: number }
  | { genre: 'bande'; g: number; n: number }

function aplatir(mesurables: readonly Ligne[], absents: readonly Ligne[], parBande: boolean): Element[] {
  const out: Element[] = []
  let courante = -1
  for (const l of mesurables) {
    if (parBande && l.groupe !== courante) {
      courante = l.groupe
      out.push({ genre: 'bande', g: l.groupe, n: mesurables.filter((x) => x.groupe === l.groupe).length })
    }
    out.push({ genre: 'ligne', l })
  }
  if (absents.length) {
    out.push({ genre: 'separateur', n: absents.length })
    for (const l of absents) out.push({ genre: 'ligne', l })
  }
  return out
}

export function ListeMobile({ mesurables, absents, critere, suivis, onSuivre }: Props) {
  const scroll = useRef<HTMLDivElement>(null)
  // Les bandes ne se marquent que si l'ordre est celui des bandes : sous un
  // autre tri elles s'entrelacent et le séparateur mentirait.
  const elements = aplatir(mesurables, absents, mesurables.every((l, i, t) => i === 0 || t[i - 1]!.groupe <= l.groupe))

  const v = useVirtualizer({
    count: elements.length,
    getScrollElement: () => scroll.current,
    estimateSize: (i) => (elements[i]?.genre === 'ligne' ? H_RELEVE : 96),
    overscan: 6,
  })

  return (
    <div ref={scroll} className={s.scroll}>
      <div style={{ height: v.getTotalSize(), position: 'relative' }}>
        {v.getVirtualItems().map((vi) => {
          const e = elements[vi.index]!
          const style = {
            position: 'absolute' as const,
            top: 0,
            left: 0,
            width: '100%',
            transform: `translateY(${vi.start}px)`,
          }
          if (e.genre === 'separateur') {
            return (
              <div key={vi.key} ref={v.measureElement} data-index={vi.index} style={style}>
                <Separateur n={e.n} critere={critere} />
              </div>
            )
          }
          if (e.genre === 'bande') {
            return (
              <div key={vi.key} ref={v.measureElement} data-index={vi.index} style={style} className={s.bandeSep}>
                <Text variante="libelle" encre="gris">
                  Bande G{String(e.g).padStart(2, '0')}
                </Text>
                <Mono taille={11} encre="faible">
                  {e.n} indiscernables
                </Mono>
              </div>
            )
          }
          const l = e.l
          return (
            <article key={vi.key} style={style} className={s.releve} data-suivi={suivis.has(l.a) ? '' : undefined}>
              <div className={s.haut}>
                <Mono taille={11} encre="faible">
                  {bande(l)}
                </Mono>
                <Mono taille={12} encre="gris">
                  {adresseCourte(l.a)}
                </Mono>
                <span className={s.marques}>
                  {vigilance(l) && (
                    <span className={s.vig} title="trades non indépendants">
                      △
                    </span>
                  )}
                  {dormant(l) && (
                    <span className={s.dort} title={`dormant depuis ${Math.round(l.dort_j ?? 0)} j`}>
                      ◦
                    </span>
                  )}
                </span>
              </div>

              {/* Un chiffre de score n'apparaît JAMAIS sans son rail dans le même
                  bloc visuel. Le SVG suffit ici : la liste mobile n'en affiche
                  qu'une dizaine à la fois. */}
              <div className={s.mesure}>
                <Mono taille={24} encre="index" graisse={500} className={s.score}>
                  {scoreTxt(l)}
                </Mono>
                <svg
                  className={s.rail}
                  viewBox={viewBox({ w: 300, h: 22 })}
                  role="img"
                  aria-label={description(l)}
                  dangerouslySetInnerHTML={{ __html: svg(l, { w: 300, h: 22 }) }}
                />
              </div>

              <Text taille={12} encre="faible" className={s.bas}>
                {l.n} trades · {activite(l)}
              </Text>

              {/* Le libellé vit ICI, sur l'élément focusable — pas sur l'article. */}
              <Link
                to={`/classement/${l.a}`}
                className={s.ouvrir}
                aria-label={`Ouvrir ${adresseCourte(l.a)}. ${description(l)} ${l.n} trades, ${activite(l)}.`}
              />
              <button
                type="button"
                className={s.suivre}
                aria-pressed={suivis.has(l.a)}
                onClick={() => onSuivre(l.a)}
              >
                {suivis.has(l.a) ? 'Suivi' : 'Suivre'}
              </button>
            </article>
          )
        })}
      </div>
    </div>
  )
}
