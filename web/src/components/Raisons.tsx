/**
 * LES RAISONS, EN CLAIR.
 *
 * Trois listes dérivées par le générateur des mêmes métriques que le score :
 * ce qui porte le chiffre, ce qui le tempère, ce qui doit alerter. Elles étaient
 * transportées et jamais affichées — 38 Ko payés par tout le monde pour
 * personne.
 *
 * Un profit factor supérieur à 10 n'apparaît JAMAIS en point fort : à ce niveau
 * il décrit un échantillon dégénéré — quelques gagnants énormes, presque aucun
 * perdant — pas une performance. Le générateur le bascule en vigilance, et
 * l'écran ne le rattrape pas.
 */
import type { Detail } from '@/domain/types'
import { Text } from '@/design/primitives'
import { Section } from './Communs'
import s from './Raisons.module.css'

const GENRES = [
  { cle: 'forts', titre: 'Points forts', signe: '+', classe: 'f' },
  { cle: 'faibles', titre: 'Réserves', signe: '–', classe: 'r' },
  { cle: 'risques', titre: 'Vigilance', signe: '×', classe: 'v' },
] as const

interface Props {
  detail: Detail
  /** table des phrases répétées : 286 wallets sur 291 portaient la même */
  lib: readonly string[]
}

const texte = (x: string | number, lib: readonly string[]): string =>
  typeof x === 'number' ? (lib[x] ?? '') : x

export function Raisons({ detail, lib }: Props) {
  return (
    <>
      {GENRES.map((g) => {
        const l = detail[g.cle]
        if (!l.length) return null
        return (
          <div key={g.cle}>
            <Section titre={g.titre} />
            {l.map((x, i) => (
              <div key={i} className={`${s.ligne} ${s[g.classe]}`}>
                <span className={s.signe} aria-hidden="true">
                  {g.signe}
                </span>
                <Text taille={13} encre={g.classe === 'v' ? 'alerte' : 'texte'}>
                  {texte(x, lib)}
                </Text>
              </div>
            ))}
          </div>
        )
      })}
    </>
  )
}
