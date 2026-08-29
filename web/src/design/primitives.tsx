/**
 * PRIMITIVES.
 *
 * Six objets, et une seule idée : rendre les valeurs hors système
 * INEXPRIMABLES. Un `espace` n'est pas un `number` mais une des sept valeurs du
 * rythme ; une taille de texte n'est pas un `number` mais une des huit valeurs
 * de l'échelle — ce qui rend le 9,5 px trouvé par l'audit impossible à écrire.
 *
 * C'est la seule protection qui tient : une règle en commentaire se contourne
 * sans qu'on s'en aperçoive, un type non.
 */
import { forwardRef } from 'react'
import type { ElementType, HTMLAttributes, ReactNode } from 'react'
import s from './primitives.module.css'

/** Le rythme de 4 px, en entier. Aucune autre valeur n'existe. */
export type Espace = 0 | 4 | 8 | 12 | 16 | 20 | 28 | 44
/** L'échelle typographique. Rien sous 11 px, capitales comprises. */
export type Taille = 11 | 12 | 13 | 15 | 18 | 24 | 32 | 44
export type Encre = 'clair' | 'texte' | 'gris' | 'faible' | 'index' | 'alerte'
export type Niveau = 'fond' | 'panneau' | 'eleve'

const px = (v: Espace): string => `${v}px`

/* ─────────────────────────────────────────────────────────────── Surface */

interface SurfaceProps extends HTMLAttributes<HTMLDivElement> {
  niveau?: Niveau
  /** filet de séparation, sur le bord indiqué */
  filet?: 'haut' | 'bas' | 'droite' | 'gauche'
  fort?: boolean
  children?: ReactNode
}

export const Surface = forwardRef<HTMLDivElement, SurfaceProps>(function Surface(
  { niveau = 'fond', filet, fort = false, className, style, children, ...reste },
  ref,
) {
  const cls = [s.surface, s[niveau], filet ? s[`filet_${filet}`] : null, fort ? s.fort : null, className]
    .filter(Boolean)
    .join(' ')
  return (
    <div ref={ref} className={cls} style={style} {...reste}>
      {children}
    </div>
  )
})

/* ───────────────────────────────────────────────────────────────── Stack */

interface StackProps extends HTMLAttributes<HTMLDivElement> {
  sens?: 'ligne' | 'colonne'
  espace?: Espace
  aligne?: 'debut' | 'centre' | 'fin' | 'base' | 'etire'
  repartit?: 'debut' | 'centre' | 'fin' | 'entre' | 'autour'
  retour?: boolean
  as?: ElementType
  children?: ReactNode
}

export function Stack({
  sens = 'colonne',
  espace = 0,
  aligne = 'etire',
  repartit = 'debut',
  retour = false,
  as: Tag = 'div',
  className,
  style,
  children,
  ...reste
}: StackProps) {
  return (
    <Tag
      className={[s.stack, className].filter(Boolean).join(' ')}
      data-sens={sens}
      data-aligne={aligne}
      data-repartit={repartit}
      data-retour={retour ? '' : undefined}
      style={{ gap: px(espace), ...style }}
      {...reste}
    >
      {children}
    </Tag>
  )
}

/* ────────────────────────────────────────────────────────────────── Text */

interface TextProps extends Omit<HTMLAttributes<HTMLElement>, 'color'> {
  variante?: 'titre' | 'corps' | 'libelle'
  taille?: Taille
  encre?: Encre
  graisse?: 400 | 500 | 600 | 700
  as?: ElementType
  /** coupe à N lignes — au-delà, une liste cesse d'être une liste */
  lignes?: 1 | 2 | 3
  children?: ReactNode
}

export function Text({
  variante = 'corps',
  taille,
  encre = 'texte',
  graisse,
  as: Tag = 'span',
  lignes,
  className,
  style,
  children,
  ...reste
}: TextProps) {
  return (
    <Tag
      className={[s.text, s[`v_${variante}`], lignes ? s.coupe : null, className].filter(Boolean).join(' ')}
      style={{
        ...(taille ? { fontSize: `${taille}px` } : null),
        color: `var(--${encre})`,
        ...(graisse ? { fontWeight: graisse } : null),
        ...(lignes ? ({ ['--lignes' as string]: String(lignes) } as Record<string, string>) : null),
        ...style,
      }}
      {...reste}
    >
      {children}
    </Tag>
  )
}

/* ────────────────────────────────────────────────────────────────── Mono */

interface MonoProps extends Omit<HTMLAttributes<HTMLElement>, 'color'> {
  taille?: Taille
  encre?: Encre
  graisse?: 400 | 500
  as?: ElementType
  children?: ReactNode
}

/**
 * TOUS les chiffres passent par ici. `tabular-nums` n'est pas une option : une
 * valeur qui danse quand elle se met à jour n'est plus une mesure.
 */
export function Mono({
  taille = 13,
  encre = 'texte',
  graisse = 400,
  as: Tag = 'span',
  className,
  style,
  children,
  ...reste
}: MonoProps) {
  return (
    <Tag
      className={[s.mono, className].filter(Boolean).join(' ')}
      style={{ fontSize: `${taille}px`, color: `var(--${encre})`, fontWeight: graisse, ...style }}
      {...reste}
    >
      {children}
    </Tag>
  )
}

/* ───────────────────────────────────────────────────────── Divider, etc. */

export function Divider({ vertical = false }: { vertical?: boolean }) {
  return <hr className={vertical ? s.divVert : s.div} aria-hidden="true" />
}

/** Lisible par une technologie d'assistance, invisible à l'œil. */
export function VisuallyHidden({ children, as: Tag = 'span' }: { children: ReactNode; as?: ElementType }) {
  return <Tag className={s.vh}>{children}</Tag>
}
