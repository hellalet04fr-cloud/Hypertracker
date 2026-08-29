/**
 * L'APPLICATION MOBILE.
 *
 * Pile d'écrans, navigation basse à trois entrées. Ce n'est pas la version
 * étroite du poste de travail : les colonnes n'y sont pas empilées, elles ont
 * disparu au profit d'un seul flux de relevés.
 *
 * L'EN-TÊTE EST OPAQUE. Un `backdrop-filter` seul ne suffit pas : le flou n'est
 * garanti par aucun moteur — Firefox le désactive par configuration, certaines
 * WebView Android et les modes économie d'énergie l'ignorent — et il ne reste
 * alors que huit pour cent d'opacité manquante sur du texte à fort contraste.
 * Un score de 29 px se lisait à travers le titre.
 */
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Mono, Text } from '@/design/primitives'
import s from './LayoutMobile.module.css'

export interface Onglet {
  to: string
  libelle: string
  fin?: boolean
}

const ONGLETS: readonly Onglet[] = [
  { to: '/', libelle: "Aujourd'hui", fin: true },
  { to: '/classement', libelle: 'Classement' },
  { to: '/donnees', libelle: 'Données' },
]

interface Props {
  titre: string
  sousTitre?: string
  /** compteur d'en-tête : TOUJOURS « affichés / total », jamais la tranche */
  compteur?: ReactNode
  verdict?: ReactNode
  action?: ReactNode
  children: ReactNode
}

export function LayoutMobile({ titre, sousTitre, compteur, verdict, action, children }: Props) {
  return (
    <div className={s.app}>
      <header className={s.entete}>
        <div className={s.titres}>
          <Text variante="titre" taille={15} encre="clair" as="h1" className={s.h1}>
            {titre}
          </Text>
          {sousTitre && (
            <Mono taille={11} encre="faible">
              {sousTitre}
            </Mono>
          )}
        </div>
        {compteur}
        {action}
      </header>

      {verdict}

      <main className={s.corps}>{children}</main>

      <nav className={s.nav} aria-label="Navigation principale">
        {ONGLETS.map((o) => (
          <NavLink
            key={o.to}
            to={o.to}
            end={o.fin ?? false}
            className={({ isActive }) => `${s.onglet} ${isActive ? s.actif : ''}`}
          >
            {o.libelle}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
