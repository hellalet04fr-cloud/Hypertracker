/**
 * LE TABLEAU DU POSTE DE TRAVAIL — 28 px par ligne, 14 colonnes, virtualisé.
 *
 * La densité vient de la HIÉRARCHIE, pas de la compression : une ligne de 28 px
 * porte quatorze colonnes lisibles si l'échelle typographique et l'alignement
 * des chiffres sont justes, et six illisibles si on se contente de réduire la
 * police.
 *
 * LES RAILS SONT PEINTS DANS UN SEUL CANVAS, en surimpression de leur colonne,
 * redessiné à chaque défilement. Un SVG par ligne ferait 31 505 sous-arbres —
 * le navigateur tombe bien avant. Un canvas par ligne en ferait trente-quatre,
 * ce qui tient, mais recrée trente-quatre contextes à chaque changement de
 * filtre ; un seul contexte les dessine tous en une passe.
 */
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { Ligne } from '@/domain/types'
import { NA, adresseCourte, jours, nb, signe, usd, usdBrut } from '@/domain/format'
import { bande, icCourt, qualiteFr, scoreTxt, vigilance } from '@/domain/score'
import { description } from '@/charts/rail'
import { canvas as railCanvas } from '@/charts/rail'
import { lireJeton } from '@/charts/moteur'
import { Separateur } from './Communs'
import s from './TableauReleve.module.css'

export const H_LIGNE = 28
/** Rangee de CONTROLES : 32 px, la cible minimale a la souris. */
export const H_ENTETE = 32
const W_RAIL = 120
const H_RAIL = 20

export interface Colonne {
  cle: string
  titre: string
  /** clé de tri, quand la colonne en porte une */
  tri?: string
  largeur: number
  aligne?: 'g' | 'd'
}

export const COLONNES: readonly Colonne[] = [
  { cle: 'groupe', titre: 'Groupe', tri: 'groupe', largeur: 62 },
  { cle: 'adresse', titre: 'Adresse', largeur: 128 },
  { cle: 'score', titre: 'Score', tri: 'score', largeur: 58, aligne: 'd' },
  { cle: 'rail', titre: 'Rail', largeur: W_RAIL },
  { cle: 'ic', titre: 'IC', largeur: 76, aligne: 'd' },
  { cle: 'proba', titre: 'Prob.', tri: 'proba', largeur: 58, aligne: 'd' },
  { cle: 'qualite', titre: 'Qualité', largeur: 70 },
  { cle: 'sharpe', titre: 'Sharpe', tri: 'sharpe', largeur: 62, aligne: 'd' },
  { cle: 'se', titre: '±ET', largeur: 54, aligne: 'd' },
  { cle: 'pnl', titre: 'PnL net', tri: 'pnl', largeur: 78, aligne: 'd' },
  { cle: 'pnl_hors_max', titre: 'PnL hors max', tri: 'pnl_hors_max', largeur: 92, aligne: 'd' },
  { cle: 'frais', titre: 'Frais', tri: 'frais', largeur: 66, aligne: 'd' },
  { cle: 'trades', titre: 'Trades', tri: 'trades', largeur: 56, aligne: 'd' },
  { cle: 'dernier', titre: 'Dernier trade', tri: 'recent', largeur: 92, aligne: 'd' },
]

type Element = { genre: 'ligne'; l: Ligne } | { genre: 'separateur'; n: number }

interface Props {
  mesurables: readonly Ligne[]
  absents: readonly Ligne[]
  critere: string
  tris: readonly string[]
  selection: string | null
  epingle: string | null
  onSelection: (a: string) => void
  onOuvrir: (a: string) => void
  onTri: (cle: string, ajouter: boolean) => void
  masquees: ReadonlySet<string>
}

export function TableauReleve({
  mesurables,
  absents,
  critere,
  tris,
  selection,
  epingle,
  onSelection,
  onOuvrir,
  onTri,
  masquees,
}: Props) {
  const scroll = useRef<HTMLDivElement>(null)
  const cvRef = useRef<HTMLCanvasElement>(null)

  const elements: Element[] = [
    ...mesurables.map((l) => ({ genre: 'ligne' as const, l })),
    ...(absents.length ? [{ genre: 'separateur' as const, n: absents.length }] : []),
    ...absents.map((l) => ({ genre: 'ligne' as const, l })),
  ]

  const v = useVirtualizer({
    count: elements.length,
    getScrollElement: () => scroll.current,
    estimateSize: (i) => (elements[i]?.genre === 'ligne' ? H_LIGNE : 84),
    overscan: 8,
  })

  const visibles = v.getVirtualItems()
  const colonnes = COLONNES.filter((c) => !masquees.has(c.cle))
  const decalageRail = colonnes.slice(0, colonnes.findIndex((c) => c.cle === 'rail')).reduce((a, c) => a + c.largeur, 0)
  const railVisible = colonnes.some((c) => c.cle === 'rail')

  /** Une passe, tous les rails visibles. */
  const peindre = useCallback(() => {
    const cv = cvRef.current
    const el = scroll.current
    if (!cv || !el || !railVisible) return
    const dpr = Math.min(globalThis.devicePixelRatio || 1, 2.5)
    const h = el.clientHeight
    if (cv.width !== Math.round(W_RAIL * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(W_RAIL * dpr)
      cv.height = Math.round(h * dpr)
      cv.style.height = `${h}px`
    }
    const ctx = cv.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W_RAIL, h)
    const pal = {
      filet: lireJeton('--filet'),
      gris: lireJeton('--gris'),
      index: lireJeton('--index'),
    }
    for (const vi of visibles) {
      const e = elements[vi.index]
      if (e?.genre !== 'ligne') continue
      // `vi.start` est relatif au debut des lignes ; l'entete collee occupe
      // H_ENTETE au-dessus d'elles dans la piste defilante.
      const y = vi.start + H_ENTETE - el.scrollTop + (H_LIGNE - H_RAIL) / 2
      if (y < -H_RAIL || y > h) continue
      railCanvas(ctx, e.l, 0, y, pal, { w: W_RAIL, h: H_RAIL, marge: 5, pas: 4 })
    }
  }, [visibles, elements, railVisible])

  useLayoutEffect(peindre)

  useEffect(() => {
    const el = scroll.current
    if (!el) return
    let attente = 0
    const surScroll = () => {
      // Une seule repeinture par trame : le budget est de 16 ms, et repeindre
      // à chaque événement de défilement en consomme plusieurs.
      if (attente) return
      attente = requestAnimationFrame(() => {
        attente = 0
        peindre()
      })
    }
    el.addEventListener('scroll', surScroll, { passive: true })
    return () => {
      cancelAnimationFrame(attente)
      el.removeEventListener('scroll', surScroll)
    }
  }, [peindre])

  const rangTri = (cle?: string) => (cle ? tris.indexOf(cle) : -1)

  const largeurTotale = colonnes.reduce((a, c) => a + c.largeur, 0)

  return (
    // UN SEUL conteneur de defilement, sur les deux axes. L'en-tete est dedans,
    // colle en haut : il suit donc le defilement horizontal des lignes, ce
    // qu'un en-tete pose a l'exterieur ne peut pas faire.
    <div ref={scroll} className={s.cadre} role="grid" aria-rowcount={mesurables.length + absents.length}>
      <div className={s.piste} style={{ width: largeurTotale }}>
        <div className={s.entete} role="row">
        {colonnes.map((c) => {
          const r = rangTri(c.tri)
          return c.tri ? (
            <button
              key={c.cle}
              type="button"
              className={`${s.th} ${c.aligne === 'd' ? s.d : ''} ${r >= 0 ? s.trie : ''}`}
              style={{ width: c.largeur }}
              onClick={(e) => onTri(c.tri!, e.shiftKey)}
              aria-sort={r === 0 ? 'descending' : 'none'}
              title={`Trier par ${c.titre} — ⇧ clic pour ajouter au tri`}
            >
              {c.titre}
              {r >= 0 && <span className={s.rangTri}>{r + 1}</span>}
            </button>
          ) : (
            <span key={c.cle} className={`${s.th} ${c.aligne === 'd' ? s.d : ''}`} style={{ width: c.largeur }}>
              {c.titre}
            </span>
          )
        })}
        </div>

        {/* Enveloppe de HAUTEUR NULLE : elle ne prend aucune place dans le flux,
            reste collee en haut de la zone visible, et se decale avec les
            colonnes puisqu'elle vit dans le contenu defilant. */}
        {railVisible && (
          <div className={s.calqueBoite} style={{ marginLeft: decalageRail }}>
            <canvas ref={cvRef} className={s.calqueRail} style={{ width: W_RAIL }} aria-hidden="true" />
          </div>
        )}

        <div style={{ height: v.getTotalSize(), position: 'relative' }}>
          {visibles.map((vi) => {
            const e = elements[vi.index]!
            const style = {
              position: 'absolute' as const,
              top: 0,
              left: 0,
              transform: `translateY(${vi.start}px)`,
            }
            if (e.genre === 'separateur') {
              return (
                <div key={vi.key} ref={v.measureElement} data-index={vi.index} style={{ ...style, width: '100%' }}>
                  <Separateur n={e.n} critere={critere} />
                </div>
              )
            }
            const l = e.l
            const actif = l.a === selection
            return (
              <div
                key={vi.key}
                role="row"
                tabIndex={-1}
                aria-selected={actif}
                className={`${s.tr} ${actif ? s.actif : ''} ${l.a === epingle ? s.epingle : ''}`}
                style={style}
                onMouseEnter={() => onSelection(l.a)}
                onFocus={() => onSelection(l.a)}
                onDoubleClick={() => onOuvrir(l.a)}
              >
                {colonnes.map((c) => (
                  <Cellule key={c.cle} c={c} l={l} onOuvrir={onOuvrir} />
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

const CLS_SIGNE = { pos: s.pos, neg: s.neg, nul: s.nul } as const

function Cellule({ c, l, onOuvrir }: { c: Colonne; l: Ligne; onOuvrir: (a: string) => void }) {
  const cls = `${s.td} ${c.aligne === 'd' ? s.d : ''}`
  const w = { width: c.largeur }

  switch (c.cle) {
    case 'groupe':
      return (
        <span className={cls} style={w}>
          {bande(l)}
          {vigilance(l) && (
            <span className={s.vig} title="trades non indépendants">
              △
            </span>
          )}
        </span>
      )
    case 'adresse':
      // Le libellé accessible vit sur le bouton, jamais sur la ligne.
      return (
        <button
          type="button"
          className={`${cls} ${s.lien}`}
          style={w}
          title={l.a}
          onClick={() => onOuvrir(l.a)}
          aria-label={`Ouvrir ${adresseCourte(l.a)}. ${description(l)}`}
        >
          {adresseCourte(l.a)}
        </button>
      )
    case 'score':
      // LA SEULE COLONNE EN --index. Le réserver à l'estimation ponctuelle est
      // ce qui la rend impossible à manquer.
      return (
        <span className={`${cls} ${s.score}`} style={w}>
          {scoreTxt(l)}
        </span>
      )
    case 'rail':
      // Peinte par le calque : la cellule ne réserve que la place.
      return <span className={cls} style={w} aria-hidden="true" />
    case 'ic':
      return (
        <span className={cls} style={w}>
          {icCourt(l)}
        </span>
      )
    case 'proba':
      return (
        <span className={`${cls} ${l.conf == null ? s.absent : ''}`} style={w}>
          {l.conf == null ? NA : `${l.conf} %`}
        </span>
      )
    case 'qualite':
      return (
        <span className={cls} style={w}>
          {qualiteFr(l.conf_lab)}
        </span>
      )
    case 'sharpe':
      return (
        <span className={cls} style={w}>
          {nb(l.sr, 2)}
        </span>
      )
    case 'se':
      return (
        <span className={`${cls} ${s.faible}`} style={w}>
          ±{nb(l.se, 2)}
        </span>
      )
    // LA PAIRE DIVERGENTE NE S'APPLIQUE QU'AUX QUANTITÉS MONÉTAIRES SIGNÉES.
    // Jamais au score, jamais au rang : ce sont des positions, pas des montants.
    case 'pnl':
      return (
        <span className={`${cls} ${CLS_SIGNE[signe(l.pnl)]}`} style={w}>
          {usd(l.pnl)}
        </span>
      )
    case 'pnl_hors_max':
      return (
        <span className={`${cls} ${CLS_SIGNE[signe(l.pnl_hors_max)]}`} style={w}>
          {usd(l.pnl_hors_max)}
        </span>
      )
    case 'frais':
      return (
        <span className={`${cls} ${s.neg}`} style={w}>
          {usdBrut(l.frais)}
        </span>
      )
    case 'trades':
      return (
        <span className={cls} style={w}>
          {l.n}
        </span>
      )
    case 'dernier':
      return (
        <span className={`${cls} ${(l.dort_j ?? 0) > 60 ? s.neg : ''}`} style={w}>
          {jours(l.dort_j)}
        </span>
      )
    default:
      return <span className={cls} style={w} />
  }
}
