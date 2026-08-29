/**
 * SQUELETTES.
 *
 * Un spinner dit « attends » sans dire de quoi ; un squelette montre déjà la
 * forme de ce qui arrive, ce qui rend l'attente lisible et le premier rendu
 * moins brutal. `prefers-reduced-motion` supprime le balayage — une animation
 * qui n'explique rien n'a pas à s'imposer.
 */
import s from './Squelette.module.css'

interface BlocProps {
  /** largeur en pourcentage : un squelette régulier ne ressemble à rien */
  l?: number
  h?: number
}

export function Bloc({ l = 100, h = 12 }: BlocProps) {
  return <span className={s.bloc} style={{ width: `${l}%`, height: `${h}px` }} aria-hidden="true" />
}

export function SqueletteLigne() {
  return (
    <div className={s.ligne}>
      <Bloc l={8} h={11} />
      <Bloc l={22} h={13} />
      <Bloc l={14} h={22} />
      <Bloc l={38} h={20} />
    </div>
  )
}

export function SqueletteEcran() {
  return (
    <div className={s.ecran} role="status" aria-live="polite" aria-busy="true">
      <span className={s.vh}>Chargement du relevé</span>
      <div className={s.entete}>
        <Bloc l={40} h={18} />
        <Bloc l={22} h={11} />
      </div>
      {Array.from({ length: 9 }, (_, i) => (
        <SqueletteLigne key={i} />
      ))}
    </div>
  )
}
