/**
 * LE REGISTRE UNIQUE DES RACCOURCIS.
 *
 * Un seul écouteur, un seul endroit où lire ce que fait une touche. Des
 * `addEventListener` dispersés produisent deux choses : des raccourcis qui se
 * marchent dessus, et une aide clavier qui ment parce que personne ne pense à
 * la mettre à jour. Ici, l'aide EST le registre.
 */
import { useEffect, useRef } from 'react'

export type Action =
  | 'precedent'
  | 'suivant'
  | 'ouvrir'
  | 'epingler'
  | 'recherche'
  | 'filtres'
  | 'onglet1'
  | 'onglet2'
  | 'onglet3'
  | 'onglet4'
  | 'suivre'
  | 'aide'
  | 'fermer'

export interface Raccourci {
  action: Action
  /** valeurs de KeyboardEvent.key acceptées */
  touches: readonly string[]
  /** ce qui s'affiche dans l'aide */
  affichage: string
  libelle: string
  categorie: 'Navigation' | 'Sélection' | 'Recherche' | 'Inspecteur' | 'Général'
  /**
   * Faux quand la touche doit rester au champ de saisie. « j » dans une
   * recherche est un « j », pas un déplacement de ligne — c'est le genre de
   * détail qui rend une application inutilisable sans qu'on sache pourquoi.
   */
  horsSaisie: boolean
}

export const RACCOURCIS: readonly Raccourci[] = [
  { action: 'precedent', touches: ['ArrowUp', 'k'], affichage: '↑ · k', libelle: 'Ligne précédente', categorie: 'Navigation', horsSaisie: true },
  { action: 'suivant', touches: ['ArrowDown', 'j'], affichage: '↓ · j', libelle: 'Ligne suivante', categorie: 'Navigation', horsSaisie: true },
  { action: 'ouvrir', touches: ['Enter'], affichage: '⏎', libelle: 'Ouvrir la fiche', categorie: 'Navigation', horsSaisie: true },
  { action: 'epingler', touches: [' '], affichage: 'Espace', libelle: 'Épingler dans l’inspecteur', categorie: 'Sélection', horsSaisie: true },
  { action: 'suivre', touches: ['s'], affichage: 's', libelle: 'Suivre / ne plus suivre', categorie: 'Sélection', horsSaisie: true },
  { action: 'recherche', touches: ['/'], affichage: '/', libelle: 'Aller à la recherche', categorie: 'Recherche', horsSaisie: true },
  { action: 'filtres', touches: ['f'], affichage: 'f', libelle: 'Panneau de filtres', categorie: 'Recherche', horsSaisie: true },
  { action: 'onglet1', touches: ['1'], affichage: '1', libelle: 'Onglet Mesure', categorie: 'Inspecteur', horsSaisie: true },
  { action: 'onglet2', touches: ['2'], affichage: '2', libelle: 'Onglet Preuve', categorie: 'Inspecteur', horsSaisie: true },
  { action: 'onglet3', touches: ['3'], affichage: '3', libelle: 'Onglet Séries', categorie: 'Inspecteur', horsSaisie: true },
  { action: 'onglet4', touches: ['4'], affichage: '4', libelle: 'Onglet Cycle de vie', categorie: 'Inspecteur', horsSaisie: true },
  { action: 'aide', touches: ['?'], affichage: '?', libelle: 'Aide clavier', categorie: 'Général', horsSaisie: true },
  // La seule qui traverse un champ de saisie : sortir doit toujours marcher.
  { action: 'fermer', touches: ['Escape'], affichage: 'Échap', libelle: 'Fermer la couche la plus haute', categorie: 'Général', horsSaisie: false },
]

const PAR_TOUCHE = new Map<string, Raccourci>()
for (const r of RACCOURCIS) for (const t of r.touches) PAR_TOUCHE.set(t, r)

export const CATEGORIES = ['Navigation', 'Sélection', 'Recherche', 'Inspecteur', 'Général'] as const

/** Le focus est-il dans un endroit où une lettre est une lettre ? */
export function dansSaisie(cible: EventTarget | null): boolean {
  if (!(cible instanceof HTMLElement)) return false
  const t = cible.tagName
  // `isContentEditable` est type `boolean` par lib.dom mais vaut `undefined` la
  // ou l'hote ne l'implemente pas : sans la coercition, cette fonction rendait
  // `undefined` la ou son type promettait `false`. Un type peut mentir ; une
  // valeur non.
  return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || cible.isContentEditable === true
}

export type Gestionnaires = Partial<Record<Action, (e: KeyboardEvent) => void>>

/**
 * UN SEUL écouteur, posé sur `document`, qui traduit une touche en action et
 * délègue. Les gestionnaires passent par une ref : le hook ne se réabonne pas à
 * chaque rendu, ce qui compte quand la page rend soixante lignes par seconde.
 */
export function useRaccourcis(gestionnaires: Gestionnaires, actif = true): void {
  const ref = useRef(gestionnaires)
  ref.current = gestionnaires

  useEffect(() => {
    if (!actif) return
    const surTouche = (e: KeyboardEvent) => {
      // Une combinaison avec un modificateur appartient au navigateur ou au
      // système : la voler produit des surprises, pas des raccourcis.
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const r = PAR_TOUCHE.get(e.key)
      if (!r) return
      if (r.horsSaisie && dansSaisie(e.target)) return
      const g = ref.current[r.action]
      if (!g) return
      e.preventDefault()
      g(e)
    }
    document.addEventListener('keydown', surTouche)
    return () => document.removeEventListener('keydown', surTouche)
  }, [actif])
}
