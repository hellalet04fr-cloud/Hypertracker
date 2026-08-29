/**
 * ROUTAGE RÉEL, URL PARTAGEABLES.
 *
 * Filtre, tri, recherche et sélection vivent dans l'URL : un lien reproduit
 * exactement ce que l'expéditeur voyait. Le bouton retour du système fonctionne
 * alors sans une ligne de code — et sur une ouverture directe, « Retour » ne
 * fait JAMAIS `history.back()` sans filet : il retombe sur `/classement` quand
 * il n'y a pas d'entrée précédente. C'est exactement le lien que le bouton
 * « Copier » invite à partager.
 *
 * Les écrans sont chargés en `lazy` : le budget JS initial est de 180 ko gzip,
 * et `charts/` n'a rien à faire dans le premier bundle.
 */
import { Suspense, lazy } from 'react'
import { Navigate, Outlet, createBrowserRouter, useNavigate } from 'react-router-dom'
import { Donnees, Frontiere } from './Providers'
import { SqueletteEcran } from '@/components/Squelette'

const Aujourdhui = lazy(() => import('@/screens/Aujourdhui'))
const Classement = lazy(() => import('@/screens/Classement'))
const Fiche = lazy(() => import('@/screens/Fiche'))
const EcranDonnees = lazy(() => import('@/screens/EcranDonnees'))

/**
 * Un retour qui a une DESTINATION, pas seulement une direction. `history.back()`
 * sur une ouverture directe faisait sortir de l'application, écran vide.
 */
export function useRetour(repli = '/classement'): () => void {
  const naviguer = useNavigate()
  return () => {
    // `idx` n'existe que si le routeur a lui-même empilé une entrée.
    const etat = history.state as { idx?: number } | null
    if (etat?.idx != null && etat.idx > 0) naviguer(-1)
    else naviguer(repli, { replace: true })
  }
}

function Racine() {
  return (
    <Frontiere>
      <Donnees squelette={<SqueletteEcran />}>
        <Suspense fallback={<SqueletteEcran />}>
          <Outlet />
        </Suspense>
      </Donnees>
    </Frontiere>
  )
}

export const routeur = createBrowserRouter([
  {
    path: '/',
    element: <Racine />,
    children: [
      { index: true, element: <Aujourdhui /> },
      { path: 'classement', element: <Classement /> },
      { path: 'classement/:adresse', element: <Fiche /> },
      { path: 'donnees', element: <EcranDonnees /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
