/**
 * LE VERDICT, AU-DESSUS DE LA LISTE.
 *
 * La réserve vivait en note de bas de page pendant que la fausse précision
 * occupait le titre. Le score n'a été confronté à une donnée native que sur
 * 5 wallets sur 291, dont 4 sous le seuil de 30 trades natifs : la validation
 * repose de fait sur UN wallet.
 *
 * Non refermable tant que le verdict n'est pas VALIDÉ : ce n'est pas une
 * notification, c'est une condition de lecture.
 *
 * ET SURTOUT — quand le dispositif ne RÉSOUT pas son propre seuil, il le dit.
 * « 0 survivant » se lirait comme un verdict ; à 2 000 tirages la plus petite
 * p-valeur exprimable vaut 5,0 × 10⁻⁴, soit cinq cents fois le seuil de
 * Bonferroni. Le test est infranchissable par construction, et lire ce zéro
 * comme une preuve d'absence serait l'erreur exactement symétrique de celle que
 * ce produit corrige.
 */
import type { Meta } from '@/domain/types'
import { pval } from '@/domain/format'
import { Mono, Stack, Text } from '@/design/primitives'
import s from './BandeauVerdict.module.css'

export type EtatVerdict = 'inconclusif' | 'valide' | 'perime'

export function etatDe(meta: Meta, ageHeures: number | null): EtatVerdict {
  if (ageHeures != null && ageHeures > 48) return 'perime'
  return /^VALID/i.test(meta.verdict) ? 'valide' : 'inconclusif'
}

interface Props {
  meta: Meta
  /** âge du dernier cycle, en heures — null quand il est inconnu */
  ageHeures?: number | null
  compact?: boolean
}

export function BandeauVerdict({ meta, ageHeures = null, compact = false }: Props) {
  const etat = etatDe(meta, ageHeures)
  if (etat === 'valide') return null

  const titre =
    etat === 'perime' ? 'Données périmées — ordre à ne plus lire' : `${meta.verdict} — ordre non validé`

  return (
    <Stack
      as="aside"
      role="note"
      aria-label="Verdict du protocole"
      className={`${s.bandeau} ${compact ? s.compact : ''}`}
      espace={4}
      data-etat={etat}
    >
      <Text variante="titre" taille={compact ? 15 : 18} encre="alerte" graisse={600}>
        {titre}
      </Text>

      {!compact && (
        <Text taille={13} encre="gris">
          {meta.avec_natif} wallets sur {meta.n} ont été confrontés à une seconde source.{' '}
          {meta.verdict_motif} La médiane des intervalles vaut {meta.ic_largeur_mediane} points
          sur 100.
        </Text>
      )}

      {/* La limite du dispositif, dite là où on lit son résultat. */}
      {!meta.test_resolu && (
        <Text taille={compact ? 12 : 13} encre="faible" className={s.limite}>
          Aucun wallet ne franchit le seuil de test multiple —{' '}
          <Mono taille={11} encre="faible">
            {pval(meta.seuil_bonferroni)}
          </Mono>{' '}
          — mais à {meta.tirages} rééchantillonnages la plus petite p-valeur exprimable vaut{' '}
          <Mono taille={11} encre="faible">
            {pval(meta.resolution_p)}
          </Mono>
          . Le test ne résout pas son propre seuil : ce zéro est une limite d’instrument, pas un
          verdict sur les wallets.
        </Text>
      )}

      <Mono taille={11} encre="faible" className={s.chiffres}>
        {meta.bandes} bandes d’équivalence · {meta.ic_boot_positif}/{meta.n} au-dessus de zéro,{' '}
        {meta.ic_boot_negatif} au-dessous — avant correction
      </Mono>
    </Stack>
  )
}
