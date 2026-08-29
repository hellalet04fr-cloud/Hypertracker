/**
 * LA BARRE D'ÉTAT DU POSTE DE TRAVAIL, 24 px.
 *
 * Ce qu'on doit pouvoir lire sans quitter des yeux le tableau : combien de
 * lignes sur combien, quel âge a la donnée, et le verdict — qui n'a pas à être
 * cherché dans un onglet voisin.
 */
import { useDonnees } from '@/app/Providers'
import { age, nb } from '@/domain/format'
import s from './BarreEtat.module.css'

interface Props {
  affiches?: number
  total?: number
}

export function BarreEtat({ affiches, total }: Props) {
  const { meta, daily, mesures } = useDonnees()
  const a = daily ? age(Date.parse(daily.horodatage), 48, Date.now()) : null

  return (
    <>
      {affiches != null && total != null && (
        <span className={s.item}>
          {affiches} / {total} affichés
        </span>
      )}
      {a && <span className={`${s.item} ${a.vieux ? s.vieux : ''}`}>relevé {a.texte}</span>}
      <span className={s.item}>ρ {nb(meta.spearman, 4)}</span>
      <span className={s.item}>ECE {nb(meta.ece, 4)}</span>
      <span className={s.item}>{meta.bandes} bandes</span>
      <span className={`${s.item} ${s.verdict}`}>{meta.verdict}</span>
      {/* Mesuré, pas promis : le décodage a-t-il eu lieu hors du thread
          principal, et en combien de temps ? */}
      <span className={`${s.item} ${s.pousse}`}>
        index {Math.round(mesures.indexMs)} ms {mesures.worker ? '(worker)' : '(repli)'}
      </span>
    </>
  )
}
