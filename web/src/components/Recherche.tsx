/**
 * LA RECHERCHE.
 *
 * Debounce à 120 ms, et la frappe reste toujours instantanée : la valeur
 * affichée est locale, la valeur propagée est différée. Sans cela, chaque
 * caractère attend un tri de 291 lignes avant d'apparaître.
 *
 * Elle accepte le format que l'application PRODUIT elle-même — « 0x F2C9 C2EB »
 * que copie le bouton « Groupée » — et lit une requête purement numérique comme
 * un RANG : « 1 » remontait sinon deux cent onze wallets.
 */
import { useEffect, useId, useRef, useState } from 'react'
import type { Ligne } from '@/domain/types'
import { analyser } from '@/domain/recherche'
import { Mono, Text } from '@/design/primitives'
import s from './Recherche.module.css'

const DELAI = 120

interface Props {
  valeur: string
  onChange: (q: string) => void
  lignes: readonly Ligne[]
}

export function Recherche({ valeur, onChange, lignes }: Props) {
  const [local, setLocal] = useState(valeur)
  const id = useId()
  const dernier = useRef(valeur)

  // L'URL peut changer sans passer par la frappe : lien partagé, retour arrière.
  useEffect(() => {
    if (valeur !== dernier.current) {
      dernier.current = valeur
      setLocal(valeur)
    }
  }, [valeur])

  useEffect(() => {
    if (local === dernier.current) return
    const t = setTimeout(() => {
      dernier.current = local
      onChange(local)
    }, DELAI)
    // Annule la recherche précédente : une frappe rapide ne doit pas empiler
    // autant de tris qu'elle a de caractères.
    return () => clearTimeout(t)
  }, [local, onChange])

  const q = analyser(local)
  const rangMax = lignes.length ? Math.max(...lignes.map((l) => l.rang)) : 0
  const invalide = q.genre === 'rang' && q.valeur > rangMax

  return (
    <div className={s.boite}>
      <label htmlFor={id} className={s.vh}>
        Rechercher une adresse, un actif, un rang ou une bande
      </label>
      <input
        id={id === 'recherche' ? id : 'recherche'}
        className={s.champ}
        type="search"
        inputMode="search"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        placeholder="Adresse, actif, rang ou bande"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        aria-describedby={local ? `${id}-genre` : undefined}
        aria-invalid={invalide}
      />
      {local && (
        <button type="button" className={s.effacer} onClick={() => setLocal('')} aria-label="Effacer la recherche">
          ×
        </button>
      )}
      {local && (
        <Text id={`${id}-genre`} taille={11} encre={invalide ? 'alerte' : 'faible'} className={s.genre}>
          {invalide ? (
            <>
              Rang {q.valeur} inexistant — le classement s’arrête à{' '}
              <Mono taille={11} encre="alerte">
                {rangMax}
              </Mono>
            </>
          ) : q.genre === 'rang' ? (
            'recherche par rang'
          ) : q.genre === 'bande' ? (
            'recherche par bande d’équivalence'
          ) : (
            'adresse ou actif'
          )}
        </Text>
      )}
    </div>
  )
}
