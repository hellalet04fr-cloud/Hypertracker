/**
 * LE CONTEXTE DE DONNÉES, ET CE QUI SE PASSE QUAND ELLES MANQUENT.
 *
 * `meta.json` d'abord — neuf kilo-octets dont dépendent le shell, le verdict et
 * tous les compteurs. `index.json` ensuite, décodé dans un worker. Un squelette
 * pendant ce temps, jamais un spinner : un spinner dit « attends » sans dire de
 * quoi, un squelette montre déjà la forme de ce qui arrive.
 */
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Component, ErrorInfo } from 'react'
import { Component as ReactComponent } from 'react'
import type { Daily, Ligne, Meta } from '@/domain/types'
import { chargerDaily, chargerIndex, chargerMeta, nettoyer } from '@/data/chargeur'
import type { Colonnes } from '@/data/colonnes'
import type { Mesures } from '@/data/chargeur'
import { toutesLignes } from '@/data/colonnes'

export interface Donnees {
  meta: Meta
  colonnes: Colonnes
  lignes: Ligne[]
  daily: Daily | null
  mesures: Mesures
}

type Etat =
  | { phase: 'chargement'; meta: Meta | null }
  | { phase: 'pret'; donnees: Donnees }
  | { phase: 'erreur'; message: string }

const Ctx = createContext<Donnees | null>(null)

export function useDonnees(): Donnees {
  const d = useContext(Ctx)
  if (!d) throw new Error('useDonnees hors du fournisseur')
  return d
}

/** Vrai tant que les données ne sont pas là — pour les squelettes. */
const CtxChargement = createContext(true)
export const useChargement = (): boolean => useContext(CtxChargement)

export function Donnees({ children, squelette }: { children: ReactNode; squelette: ReactNode }) {
  const [etat, setEtat] = useState<Etat>({ phase: 'chargement', meta: null })

  useEffect(() => {
    let vivant = true
    void (async () => {
      try {
        const meta = await chargerMeta()
        if (!vivant) return
        setEtat({ phase: 'chargement', meta })
        // Les lots d'hier n'ont plus rien à dire ; la purge ne bloque rien.
        void nettoyer(meta.gen)
        const [{ colonnes, mesures }, daily] = await Promise.all([
          chargerIndex(),
          chargerDaily().catch(() => null),
        ])
        if (!vivant) return
        setEtat({
          phase: 'pret',
          donnees: { meta, colonnes, lignes: toutesLignes(colonnes), daily, mesures },
        })
      } catch (e) {
        if (!vivant) return
        setEtat({ phase: 'erreur', message: e instanceof Error ? e.message : String(e) })
      }
    })()
    return () => {
      vivant = false
    }
  }, [])

  if (etat.phase === 'erreur') {
    return (
      <div role="alert" style={{ padding: '28px 20px', maxWidth: 520 }}>
        <p style={{ font: '600 18px/1.3 var(--f-titre)', color: 'var(--alerte)', margin: 0 }}>
          Données indisponibles
        </p>
        <p style={{ color: 'var(--gris)', fontSize: 13 }}>
          Le relevé n’a pas pu être chargé. Cette page est un instantané : elle affichera le
          prochain cycle dès qu’il aura été publié.
        </p>
        <p style={{ color: 'var(--faible)', fontSize: 11, fontFamily: 'var(--f-mono)' }}>
          {etat.message}
        </p>
      </div>
    )
  }

  if (etat.phase === 'chargement') {
    return <CtxChargement.Provider value>{squelette}</CtxChargement.Provider>
  }

  return (
    <CtxChargement.Provider value={false}>
      <Ctx.Provider value={etat.donnees}>{children}</Ctx.Provider>
    </CtxChargement.Provider>
  )
}

/* ───────────────────────────────────────────────────── frontière d'erreur */

interface FrontiereProps {
  children: ReactNode
}
interface FrontiereEtat {
  erreur: Error | null
}

/**
 * Une exception dans un tracé ne doit pas emporter l'application entière. Elle
 * est dite, à l'endroit où elle s'est produite.
 */
export class Frontiere extends (ReactComponent as typeof Component)<FrontiereProps, FrontiereEtat> {
  override state: FrontiereEtat = { erreur: null }

  static getDerivedStateFromError(erreur: Error): FrontiereEtat {
    return { erreur }
  }

  override componentDidCatch(erreur: Error, info: ErrorInfo): void {
    // Console seulement : aucune commande interne, aucun nom de module ne doit
    // atteindre l'écran — la page est partagée par lien.
    console.error('[hypertracker]', erreur, info.componentStack)
  }

  override render(): ReactNode {
    if (this.state.erreur) {
      return (
        <div role="alert" style={{ padding: 20, color: 'var(--alerte)', fontSize: 13 }}>
          Cette partie de l’écran n’a pas pu s’afficher.
        </div>
      )
    }
    return this.props.children
  }
}
