/**
 * L'ONGLET SÉRIES — les tracés, montés sur canvas.
 *
 * Les canvas ne se redessinent QUE sur changement de largeur. La barre d'URL qui
 * se rétracte pendant le défilement est un événement `resize` : la version
 * précédente y reconstruisait la fiche entière, perdant le défilement et l'état
 * déplié à chaque scroll.
 */
import { useEffect, useRef, useState } from 'react'
import type { Detail } from '@/domain/types'
import { useLargeur } from '@/app/useLayout'
import { preparer, brancherPointeur } from '@/charts/moteur'
import { dessiner, drawdown, equity } from '@/charts/courbe'
import { barres, frise, moisApres, parDate } from '@/charts/figures'
import { date, usd } from '@/domain/format'
import { Mono, Stack, Text } from '@/design/primitives'
import { Section } from './Communs'
import { Bloc } from './Squelette'
import s from './Series.module.css'

interface Props {
  detail: Detail | null
  etat: 'chargement' | 'pret' | 'erreur'
}

export function Series({ detail, etat }: Props) {
  if (etat === 'chargement') {
    return (
      <Stack espace={12} className={s.charge}>
        <Bloc l={100} h={140} />
        <Bloc l={100} h={100} />
      </Stack>
    )
  }
  if (!detail) {
    return (
      <Text taille={12} encre="faible" className={s.note}>
        Les séries de ce wallet n’ont pas pu être chargées.
      </Text>
    )
  }

  const pts = equity(detail.eq)
  const dd = drawdown(detail.eq)

  return (
    <Stack espace={0}>
      <Section titre="PnL cumulé" apres={<Mono taille={11} encre="faible">{usd(pts.at(-1)?.[1] ?? null)}</Mono>} />
      <Trace
        hauteur={160}
        dessin={(t, survol) => {
          dessiner(t, pts, { survol })
          return pts.length
        }}
        legende={(i) =>
          pts[i] ? `${usd(pts[i]![1])} · ${date(pts[i]![0])}` : ''
        }
        vide={pts.length < 2}
        videTexte="Moins de deux trades clos : aucune courbe à tracer."
      />
      <Text taille={12} encre="faible" className={s.note}>
        {date(detail.t0)} → {date(detail.t1)} · {pts.length} points conservés sur la série
        décimée, sommets et creux forcés.
      </Text>

      <Section titre="Drawdown" />
      <Trace
        hauteur={120}
        dessin={(t, survol) => {
          dessiner(t, dd, { survol, couleur: 'var(--gris)' })
          return dd.length
        }}
        legende={(i) => (dd[i] ? `${usd(dd[i]![1])} · ${date(dd[i]![0])}` : '')}
        vide={dd.length < 2}
        videTexte="Pas de repli mesurable."
      />
      <Text taille={12} encre="faible" className={s.note}>
        Déduit de l’equity — c’est sa définition. Le stocker séparément doublait la charge pour
        zéro information nouvelle.
      </Text>

      <Section titre="Activité mensuelle" />
      <Trace
        hauteur={110}
        dessin={(t, survol) => {
          barres(t, detail.m, {
            survol,
            etiquettes: detail.m.map((_, i) => moisApres(detail.m0, i)),
          })
          return detail.m.length
        }}
        legende={(i) => `${detail.m[i] ?? 0} trades · ${moisApres(detail.m0, i)}`}
        vide={detail.m.length === 0}
        videTexte="Aucun mois d’activité."
      />
      <Text taille={12} encre="faible" className={s.note}>
        Série CONTIGUË : un mois sans trade clos vaut zéro. Sans cela, un wallet inactif de mars
        à juillet aurait vu février et août dessinés côte à côte.
      </Text>

      {detail.hist && (
        <>
          <Section titre="Distribution des trades" />
          <Trace
            hauteur={110}
            dessin={(t, survol) => {
              const b = detail.hist!.b
              const tot = b.reduce((a, x) => a + x, 0)
              let cum = 0
              let med = 0
              for (let i = 0; i < b.length; i++) {
                cum += b[i]!
                if (cum >= tot / 2) {
                  med = i
                  break
                }
              }
              barres(t, b, { pleine: med, survol })
              return b.length
            }}
            legende={(i) =>
              `${detail.hist!.b[i] ?? 0} trades · ${usd(detail.hist!.lo + (i + 0.5) * detail.hist!.pas)}`
            }
            vide={false}
          />
        </>
      )}

      <Section titre="Rang dans le temps" />
      <Trace
        hauteur={100}
        dessin={(t, survol) => {
          const p = parDate(detail.histo, 2)
          frise(t, p, { inverse: true, prefixe: '#', survol })
          return p.length
        }}
        legende={(i) => {
          const p = parDate(detail.histo, 2)
          return p[i] ? `#${p[i]![1]} · ${date(p[i]![0])}` : ''
        }}
        vide={parDate(detail.histo, 2).length < 2}
        videTexte={`${detail.n_dates} date${detail.n_dates > 1 ? 's' : ''} distincte${detail.n_dates > 1 ? 's' : ''} — pas encore d’évolution.`}
      />
      <Text taille={12} encre="faible" className={s.note}>
        Échelle inversée : le 1 en haut, parce que « monter au classement » doit monter à
        l’écran.
      </Text>
    </Stack>
  )
}

/* ─────────────────────────────────────────────── un tracé et son infobulle */

interface TraceProps {
  hauteur: number
  /** dessine et retourne le nombre de points, pour brancher le pointeur */
  dessin: (t: ReturnType<typeof preparer> extends null ? never : NonNullable<ReturnType<typeof preparer>>, survol: number | null) => number
  legende: (i: number) => string
  vide: boolean
  videTexte?: string
}

function Trace({ hauteur, dessin, legende, vide, videTexte }: TraceProps) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [survol, setSurvol] = useState<number | null>(null)
  const largeur = useLargeur()

  useEffect(() => {
    const cv = ref.current
    if (!cv || vide) return
    const t = preparer(cv, hauteur)
    if (!t) return
    const n = dessin(t, survol)
    if (!n) return
    // La projection est refaite à chaque dessin : la largeur peut avoir changé.
    return brancherPointeur(cv, {
      n,
      px: (i) => ((i + 0.5) / n) * t.w,
      surIndex: setSurvol,
    })
    // `largeur` est dans les dépendances À DESSEIN : c'est le seul signal qui
    // doit provoquer un redessin. La hauteur du viewport n'en est pas un.
  }, [dessin, hauteur, survol, vide, largeur])

  if (vide) {
    return (
      <div className={s.puits}>
        <Text taille={12} encre="faible">
          {videTexte ?? 'Pas assez de relevés.'}
        </Text>
      </div>
    )
  }

  return (
    <div className={s.puits}>
      <canvas ref={ref} className={s.canvas} />
      {survol != null && (
        <Mono taille={12} encre="clair" className={s.bulle}>
          {legende(survol)}
        </Mono>
      )}
    </div>
  )
}
