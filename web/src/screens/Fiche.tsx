/**
 * LA FICHE.
 *
 * Sur mobile, un écran plein ; sur le poste de travail, la même chose dans la
 * colonne d'inspecteur, sans quitter le tableau.
 *
 * « RETOUR » A UNE DESTINATION, pas seulement une direction. Sur une ouverture
 * directe — exactement le lien que le bouton « Copier » invite à partager — il
 * n'y a pas d'entrée précédente, et `history.back()` faisait sortir de
 * l'application, écran vide.
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useDonnees } from '@/app/Providers'
import { useMise } from '@/app/useLayout'
import { useRetour } from '@/app/routes'
import { LayoutDesktop } from '@/app/LayoutDesktop'
import { LayoutMobile } from '@/app/LayoutMobile'
import { BandeauVerdict } from '@/components/BandeauVerdict'
import { BarreEtat } from '@/components/BarreEtat'
import { EtatVide } from '@/components/Communs'
import { Inspecteur, ONGLETS } from '@/components/Inspecteur'
import type { Onglet } from '@/components/Inspecteur'
import { useRaccourcis } from '@/design/keymap'
import { Text } from '@/design/primitives'
import { adresseCourte, adresseGroupee } from '@/domain/format'
import { useSuivi } from '@/stores'
import s from './Fiche.module.css'

export default function Fiche() {
  const { adresse = '' } = useParams()
  const { meta, lignes, daily } = useDonnees()
  const mise = useMise()
  const retour = useRetour()
  const [onglet, setOnglet] = useState<Onglet>('Mesure')
  const suit = useSuivi((e) => e.suivis.includes(adresse))
  const basculer = useSuivi((e) => e.basculer)
  const [copie, setCopie] = useState<'repos' | 'ok' | 'refus'>('repos')

  const l = lignes.find((x) => x.a === adresse.toLowerCase())

  useRaccourcis({
    onglet1: () => setOnglet(ONGLETS[0]),
    onglet2: () => setOnglet(ONGLETS[1]),
    onglet3: () => setOnglet(ONGLETS[2]),
    onglet4: () => setOnglet(ONGLETS[3]),
    suivre: () => l && basculer(l.a),
    fermer: retour,
  })

  useEffect(() => {
    if (copie === 'repos') return
    const t = setTimeout(() => setCopie('repos'), 1500)
    return () => clearTimeout(t)
  }, [copie])

  const copier = async (texte: string) => {
    try {
      await navigator.clipboard.writeText(texte)
      setCopie('ok')
    } catch {
      setCopie('refus')
    }
  }

  const heures = daily ? (Date.now() - Date.parse(daily.horodatage)) / 3.6e6 : null

  if (!l) {
    const vide = (
      <EtatVide titre="Wallet introuvable" action={<button type="button" className={s.retour} onClick={retour}>← Retour au classement</button>}>
        L’adresse <code>{adresseCourte(adresse)}</code> ne figure pas parmi les {meta.n} wallets
        mesurés. Elle peut être en observation sans avoir encore assez de trades clos.
      </EtatVide>
    )
    return mise === 'poste' ? (
      <LayoutDesktop
        verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
        population={null}
        releve={vide}
        inspecteur={null}
        etat={<BarreEtat />}
      />
    ) : (
      <LayoutMobile titre="Fiche" verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}>
        {vide}
      </LayoutMobile>
    )
  }

  const actions = (
    <div className={s.actions}>
      <button type="button" className={s.btn} onClick={() => void copier(l.a)}>
        {copie === 'ok' ? 'Copiée' : copie === 'refus' ? 'Refusée' : 'Copier'}
      </button>
      <button type="button" className={s.btn} onClick={() => void copier(adresseGroupee(l.a))}>
        Groupée
      </button>
      <button
        type="button"
        className={`${s.btn} ${suit ? s.on : ''}`}
        aria-pressed={suit}
        onClick={() => basculer(l.a)}
      >
        {suit ? 'Suivi' : 'Suivre'}
      </button>
    </div>
  )

  if (mise === 'poste') {
    return (
      <LayoutDesktop
        verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
        population={
          <div className={s.aside}>
            <button type="button" className={s.retour} onClick={retour}>
              ← Retour au classement
            </button>
            {actions}
          </div>
        }
        releve={
          <div className={s.pleine}>
            <Inspecteur adresse={l.a} onglet={onglet} onOnglet={setOnglet} />
          </div>
        }
        inspecteur={
          <div className={s.aside}>
            <Text taille={12} encre="faible">
              Cette fiche ne cherche pas à justifier le score : l’onglet <strong>Preuve</strong>{' '}
              rassemble ce qui permettrait de le réfuter. Un wallet qu’aucune épreuve ne réfute
              n’est pas pour autant démontré.
            </Text>
          </div>
        }
        etat={<BarreEtat />}
      />
    )
  }

  return (
    <LayoutMobile
      titre={adresseCourte(l.a)}
      sousTitre={`bande G${String(l.groupe).padStart(2, '0')}`}
      verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
      action={
        <button type="button" className={s.retour} onClick={retour} aria-label="Retour au classement">
          ←
        </button>
      }
    >
      <div className={s.mobile}>
        {actions}
        <Inspecteur adresse={l.a} onglet={onglet} onOnglet={setOnglet} />
      </div>
    </LayoutMobile>
  )
}
