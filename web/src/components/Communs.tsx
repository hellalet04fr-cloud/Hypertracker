/**
 * LES PETITS OBJETS PARTAGÉS, chacun né d'un défaut mesuré.
 */
import type { ReactNode } from 'react'
import { Mono, Stack, Text } from '@/design/primitives'
import s from './Communs.module.css'

/**
 * TOUJOURS « affichés / total ». Jamais la longueur de la tranche : « Dormants
 * 6 » pour 100 dormants réels sous-déclarait un risque par un effet de
 * découpage, ce qui est la faute la plus grave qu'un compteur puisse commettre.
 */
export function Compteur({ affiches, total, libelle }: { affiches: number; total: number; libelle?: string }) {
  const tronque = total > affiches
  return (
    <Mono taille={11} encre={tronque ? 'gris' : 'faible'} aria-label={libelle}>
      {tronque ? `${affiches} / ${total}` : String(total)}
    </Mono>
  )
}

/**
 * Les valeurs absentes SORTENT de l'ordre et sont annoncées. Enfouies en fin de
 * tri, elles passent pour de mauvaises performances alors que c'est une absence
 * de mesure.
 */
export function Separateur({ n, critere }: { n: number; critere: string }) {
  return (
    <Stack className={s.separateur} espace={4}>
      <Text variante="libelle" encre="gris">
        {n} wallet{n > 1 ? 's' : ''} non mesurable{n > 1 ? 's' : ''} sur « {critere} »
      </Text>
      <Text taille={12} encre="faible">
        Ils ne sont pas derniers : ils sont hors de portée de ce critère. Les classer avec les
        autres les ferait passer pour de mauvais résultats.
      </Text>
    </Stack>
  )
}

/**
 * AUCUNE commande interne, aucun nom de module, aucune heure de tâche planifiée.
 * La page est partagée par lien : ce message s'adresse à l'opérateur mais il est
 * lu par tout le monde.
 */
export function EtatVide({ titre, children, action }: { titre: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <Stack className={s.vide} espace={12} aligne="centre">
      <Text variante="libelle" encre="gris">
        {titre}
      </Text>
      {children && (
        <Text taille={13} encre="faible" className={s.videTexte}>
          {children}
        </Text>
      )}
      {action}
    </Stack>
  )
}

/** Un titre de section, avec son filet et son compteur. */
export function Section({ titre, apres, children }: { titre: string; apres?: ReactNode; children?: ReactNode }) {
  return (
    <>
      <div className={s.sect}>
        <Text variante="libelle" encre="faible">
          {titre}
        </Text>
        <span className={s.trait} />
        {apres}
      </div>
      {children}
    </>
  )
}

/** Une mesure : son libellé, sa valeur, son unité. */
export function Mesure({ k, v, u }: { k: string; v: ReactNode; u?: string }) {
  return (
    <div className={s.mesure}>
      <Text variante="libelle" encre="faible" className={s.mesureK}>
        {k}
      </Text>
      <span className={s.mesureV}>
        {v}
        {u && (
          <Mono taille={11} encre="faible">
            {' '}
            {u}
          </Mono>
        )}
      </span>
    </div>
  )
}

/** Marque de vigilance : trades non indépendants. Visible AVANT la fiche. */
export function MarqueVigilance({ titre }: { titre?: string }) {
  return (
    <span className={s.vigilance} title={titre ?? 'Trades non indépendants (Ljung-Box p < 0,05)'}>
      <span aria-hidden="true">△</span>
      <span className={s.vh}>vigilance : trades non indépendants</span>
    </span>
  )
}
