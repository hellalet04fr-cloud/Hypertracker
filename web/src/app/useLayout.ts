/**
 * QUELLE MISE EN PAGE, ET RIEN D'AUTRE.
 *
 * Le point de bascule est une MEDIA QUERY lue par `matchMedia`, jamais un
 * écouteur `resize`. Sur iOS et Android, la barre d'URL qui se rétracte pendant
 * le défilement EST un événement `resize` : la version précédente y perdait le
 * défilement et l'état déplié de la fiche, à chaque scroll. On n'écoute que la
 * largeur, et un changement de hauteur ne déclenche rien.
 */
import { useEffect, useState } from 'react'

export const SEUIL_POSTE = 1024
const REQUETE = `(min-width: ${SEUIL_POSTE}px)`

export type Mise = 'poste' | 'mobile'

const lire = (): Mise => {
  if (typeof globalThis.matchMedia !== 'function') return 'mobile'
  return globalThis.matchMedia(REQUETE).matches ? 'poste' : 'mobile'
}

export function useMise(): Mise {
  const [mise, setMise] = useState<Mise>(lire)

  useEffect(() => {
    if (typeof globalThis.matchMedia !== 'function') return
    const mq = globalThis.matchMedia(REQUETE)
    const surChangement = (e: MediaQueryListEvent) => setMise(e.matches ? 'poste' : 'mobile')
    // `addListener` reste le seul chemin sur quelques WebView : le manquer
    // fige la mise en page dans celle du premier rendu.
    if (mq.addEventListener) mq.addEventListener('change', surChangement)
    else mq.addListener?.(surChangement)
    setMise(mq.matches ? 'poste' : 'mobile')
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', surChangement)
      else mq.removeListener?.(surChangement)
    }
  }, [])

  return mise
}

/**
 * LARGEUR SEULE. Les canvas dépendent de la largeur et d'elle seule : c'est le
 * seul signal qui doit provoquer un redessin. Rendre un nombre plutôt qu'un
 * booléen permet aux tracés de se recalculer sans reconstruire le DOM.
 */
export function useLargeur(): number {
  const [w, setW] = useState(() => (typeof window === 'undefined' ? 1280 : window.innerWidth))

  useEffect(() => {
    let precedente = window.innerWidth
    let minuteur: ReturnType<typeof setTimeout> | undefined
    const surResize = () => {
      // Hauteur seule = barre d'URL. Ce n'est pas un changement de mise en page,
      // et le traiter comme tel renvoyait le lecteur en haut de fiche.
      if (window.innerWidth === precedente) return
      precedente = window.innerWidth
      clearTimeout(minuteur)
      minuteur = setTimeout(() => setW(window.innerWidth), 150)
    }
    window.addEventListener('resize', surResize, { passive: true })
    return () => {
      clearTimeout(minuteur)
      window.removeEventListener('resize', surResize)
    }
  }, [])

  return w
}
