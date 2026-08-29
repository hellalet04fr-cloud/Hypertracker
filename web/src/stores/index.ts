/**
 * LES QUATRE ÉTATS GLOBAUX, un par domaine.
 *
 * Ce qui se persiste et ce qui ne se persiste pas n'est pas une commodité :
 * c'est une règle. Le tri et le filtre sont AFFICHÉS en permanence, donc les
 * mémoriser est légitime. La requête de recherche ne l'est pas — on revenait
 * trois jours plus tard, le classement était filtré, le compteur d'en-tête
 * annonçait un total réduit, et la seule trace vivait hors écran.
 *
 * Toute écriture dans `localStorage` est enveloppée : navigation privée, quota
 * plein, site data bloqué. Une liste de suivi perdue ne doit JAMAIS empêcher
 * l'application de s'afficher.
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { FILTRE_DEFAUT } from '@/domain/filtres'
import { MAX_CLES, TRI_DEFAUT } from '@/domain/tri'

/** `localStorage` qui ne jette jamais. Un stockage indisponible ralentit, il n'arrête pas. */
const stockageSur = {
  getItem: (k: string): string | null => {
    try {
      return globalThis.localStorage?.getItem(k) ?? null
    } catch {
      return null
    }
  },
  setItem: (k: string, v: string): void => {
    try {
      globalThis.localStorage?.setItem(k, v)
    } catch {
      /* quota plein ou site data bloqué : la session continue en mémoire */
    }
  },
  removeItem: (k: string): void => {
    try {
      globalThis.localStorage?.removeItem(k)
    } catch {
      /* idem */
    }
  },
}

/* ────────────────────────────────────────────────────────────── sélection */

interface EtatSelection {
  /** adresse survolée / au clavier : ce que l'inspecteur suit */
  selection: string | null
  /** adresse épinglée : l'inspecteur cesse de suivre la sélection */
  epingle: string | null
  choisir: (a: string | null) => void
  epingler: (a: string | null) => void
  /** ce que l'inspecteur doit montrer : l'épingle l'emporte */
  cible: () => string | null
}

export const useSelection = create<EtatSelection>((set, get) => ({
  selection: null,
  epingle: null,
  choisir: (a) => set({ selection: a }),
  epingler: (a) => set((e) => ({ epingle: e.epingle === a ? null : a })),
  cible: () => get().epingle ?? get().selection,
}))

/* ──────────────────────────────────────────────────────────────── filtres */

interface EtatFiltres {
  filtre: string
  /** jusqu'à trois clés : au-delà, l'ordre cesse d'être explicable */
  tris: string[]
  /** NON persistée, volontairement */
  requete: string
  poserFiltre: (c: string) => void
  basculerTri: (c: string, ajouter: boolean) => void
  poserRequete: (q: string) => void
  reinitialiser: () => void
}

export const useFiltres = create<EtatFiltres>()(
  persist(
    (set) => ({
      filtre: FILTRE_DEFAUT,
      tris: [TRI_DEFAUT],
      requete: '',
      poserFiltre: (c) => set({ filtre: c }),
      basculerTri: (c, ajouter) =>
        set((e) => {
          if (!ajouter) return { tris: [c] }
          const deja = e.tris.includes(c)
          const suite = deja ? e.tris.filter((x) => x !== c) : [...e.tris, c]
          return { tris: (suite.length ? suite : [c]).slice(0, MAX_CLES) }
        }),
      poserRequete: (q) => set({ requete: q }),
      reinitialiser: () => set({ filtre: FILTRE_DEFAUT, tris: [TRI_DEFAUT], requete: '' }),
    }),
    {
      name: 'ht.filtres',
      storage: createJSONStorage(() => stockageSur),
      // La requête est absente de ce qui se persiste : un filtre invisible qui
      // survit à la session fait mentir le compteur d'en-tête.
      partialize: (e) => ({ filtre: e.filtre, tris: e.tris }),
    },
  ),
)

/* ────────────────────────────────────────────────────────────────── suivi */

interface EtatSuivi {
  suivis: string[]
  basculer: (a: string) => void
  suit: (a: string) => boolean
  deplacer: (a: string, sens: -1 | 1) => void
}

export const useSuivi = create<EtatSuivi>()(
  persist(
    (set, get) => ({
      suivis: [],
      basculer: (a) =>
        set((e) => ({
          suivis: e.suivis.includes(a) ? e.suivis.filter((x) => x !== a) : [...e.suivis, a],
        })),
      suit: (a) => get().suivis.includes(a),
      deplacer: (a, sens) =>
        set((e) => {
          const i = e.suivis.indexOf(a)
          const j = i + sens
          if (i < 0 || j < 0 || j >= e.suivis.length) return e
          const s = [...e.suivis]
          const t = s[i]!
          s[i] = s[j]!
          s[j] = t
          return { suivis: s }
        }),
    }),
    { name: 'ht.suivi', storage: createJSONStorage(() => stockageSur) },
  ),
)

/* ──────────────────────────────────────────────────────────── préférences */

export type Densite = 'compacte' | 'confortable'

interface EtatPreferences {
  /** largeurs des colonnes du poste de travail, en pixels */
  largeurPopulation: number
  largeurInspecteur: number
  /** colonnes masquées du tableau */
  masquees: string[]
  densite: Densite
  poserLargeur: (quoi: 'population' | 'inspecteur', px: number) => void
  basculerColonne: (cle: string) => void
  poserDensite: (d: Densite) => void
}

export const usePreferences = create<EtatPreferences>()(
  persist(
    (set) => ({
      largeurPopulation: 260,
      largeurInspecteur: 420,
      masquees: [],
      densite: 'compacte',
      poserLargeur: (quoi, px) =>
        set(
          quoi === 'population'
            ? { largeurPopulation: Math.max(180, Math.min(480, px)) }
            : { largeurInspecteur: Math.max(300, Math.min(720, px)) },
        ),
      basculerColonne: (cle) =>
        set((e) => ({
          masquees: e.masquees.includes(cle) ? e.masquees.filter((x) => x !== cle) : [...e.masquees, cle],
        })),
      poserDensite: (d) => set({ densite: d }),
    }),
    { name: 'ht.preferences', storage: createJSONStorage(() => stockageSur) },
  ),
)
