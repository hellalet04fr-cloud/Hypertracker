/**
 * LE CLASSEMENT.
 *
 * Filtre, tri et recherche vivent dans l'URL : un lien reproduit exactement ce
 * que l'expéditeur voyait. La requête, elle, ne se PERSISTE pas entre sessions —
 * on revenait trois jours plus tard, la liste était filtrée, le compteur
 * annonçait un total réduit, et la seule trace vivait hors écran.
 */
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDonnees } from '@/app/Providers'
import { useMise } from '@/app/useLayout'
import { LayoutDesktop } from '@/app/LayoutDesktop'
import { LayoutMobile } from '@/app/LayoutMobile'
import { BandeauVerdict } from '@/components/BandeauVerdict'
import { BarreEtat } from '@/components/BarreEtat'
import { Compteur, EtatVide } from '@/components/Communs'
import { ListeMobile } from '@/components/ListeMobile'
import { TableauReleve } from '@/components/TableauReleve'
import { PanneauFiltres } from '@/components/PanneauFiltres'
import { Recherche } from '@/components/Recherche'
import { Inspecteur } from '@/components/Inspecteur'
import { useRaccourcis } from '@/design/keymap'
import { Stack, Text } from '@/design/primitives'
import { FILTRE_DEFAUT, appliquer, effectifs, filtreDe } from '@/domain/filtres'
import { chercher } from '@/domain/recherche'
import { TRI_DEFAUT, partitionnerMulti, triDe } from '@/domain/tri'
import { useFiltres, usePreferences, useSelection, useSuivi } from '@/stores'
import s from './Classement.module.css'

export default function Classement() {
  const { meta, lignes, daily } = useDonnees()
  const mise = useMise()
  const naviguer = useNavigate()
  const [params, setParams] = useSearchParams()

  const filtreStore = useFiltres()
  const suivis = useSuivi((e) => e.suivis)
  const basculerSuivi = useSuivi((e) => e.basculer)
  const masquees = usePreferences((e) => e.masquees)
  const { selection, epingle, choisir, epingler } = useSelection()

  // L'URL FAIT AUTORITÉ. Le store ne sert qu'à retenir une préférence entre
  // deux visites ; ce qui est écrit dans le lien l'emporte toujours.
  const filtre = params.get('filtre') ?? filtreStore.filtre ?? FILTRE_DEFAUT
  const tris = useMemo(() => (params.get('tri') ?? filtreStore.tris.join(',')).split(',').filter(Boolean), [params, filtreStore.tris])
  const requete = params.get('q') ?? ''
  const requeteDifferee = useDeferredValue(requete)

  const [panneau, setPanneau] = useState(false)

  const majUrl = useCallback(
    (cle: string, valeur: string | null) => {
      const p = new URLSearchParams(params)
      if (valeur) p.set(cle, valeur)
      else p.delete(cle)
      setParams(p, { replace: true })
    },
    [params, setParams],
  )

  // Le store retient ce qui est légitime de retenir : le filtre et le tri, tous
  // deux visibles en permanence. Jamais la requête.
  useEffect(() => {
    filtreStore.poserFiltre(filtre)
  }, [filtre]) // eslint-disable-line react-hooks/exhaustive-deps

  const ensembleSuivis = useMemo(() => new Set(suivis), [suivis])

  const selectionnees = useMemo(() => {
    const f = appliquer(lignes, filtre, ensembleSuivis)
    return requeteDifferee ? chercher(f, requeteDifferee) : f
  }, [lignes, filtre, ensembleSuivis, requeteDifferee])

  const { mesurables, absents, libelle } = useMemo(
    () => partitionnerMulti(selectionnees, tris),
    [selectionnees, tris],
  )

  const compte = useMemo(() => effectifs(lignes, ensembleSuivis), [lignes, ensembleSuivis])
  const total = mesurables.length + absents.length

  const ordre = useMemo(() => [...mesurables, ...absents], [mesurables, absents])
  const iSelection = ordre.findIndex((l) => l.a === selection)

  const deplacer = useCallback(
    (d: -1 | 1) => {
      if (!ordre.length) return
      const i = Math.max(0, Math.min(ordre.length - 1, (iSelection < 0 ? 0 : iSelection) + d))
      choisir(ordre[i]!.a)
    },
    [ordre, iSelection, choisir],
  )

  useRaccourcis(
    {
      precedent: () => deplacer(-1),
      suivant: () => deplacer(1),
      ouvrir: () => selection && naviguer(`/classement/${selection}`),
      epingler: () => selection && epingler(selection),
      suivre: () => selection && basculerSuivi(selection),
      filtres: () => setPanneau((v) => !v),
      recherche: () => document.getElementById('recherche')?.focus(),
      fermer: () => {
        // Fermer une couche, c'est AUSSI rendre le focus. Laisse dans le champ
        // de recherche, il rendait « Entree » inoperant — Entree etant
        // volontairement neutralise dans une saisie.
        const a = document.activeElement
        if (a instanceof HTMLElement && /INPUT|TEXTAREA/.test(a.tagName)) {
          a.blur()
          return
        }
        if (panneau) setPanneau(false)
        else epingler(null)
      },
    },
    mise === 'poste',
  )

  const heures = daily ? (Date.now() - Date.parse(daily.horodatage)) / 3.6e6 : null
  const vide =
    total === 0 ? (
      <EtatVide titre={requete ? 'Aucun résultat' : 'Aucun wallet'}>
        {requete
          ? `Aucune adresse, aucun actif, aucun rang ne correspond à « ${requete} ».`
          : `Aucun wallet ne satisfait le filtre « ${filtreDe(filtre).libelle} ».`}
      </EtatVide>
    ) : null

  if (mise === 'poste') {
    return (
      <LayoutDesktop
        verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
        population={
          <PanneauFiltres
            filtre={filtre}
            effectifs={compte}
            total={lignes.length}
            onFiltre={(c) => majUrl('filtre', c === FILTRE_DEFAUT ? null : c)}
            recherche={
              <Recherche valeur={requete} onChange={(q) => majUrl('q', q || null)} lignes={lignes} />
            }
          />
        }
        releve={
          vide ?? (
            <TableauReleve
              mesurables={mesurables}
              absents={absents}
              critere={libelle}
              tris={tris}
              selection={selection}
              epingle={epingle}
              onSelection={choisir}
              onOuvrir={(a) => naviguer(`/classement/${a}`)}
              onTri={(cle, ajouter) => {
                filtreStore.basculerTri(cle, ajouter)
                const suite = ajouter
                  ? [...new Set([...tris, cle])].slice(0, 3)
                  : [cle]
                majUrl('tri', suite.join(','))
              }}
              masquees={new Set(masquees)}
            />
          )
        }
        inspecteur={<Inspecteur adresse={epingle ?? selection} />}
        etat={<BarreEtat affiches={total} total={lignes.length} />}
      />
    )
  }

  return (
    <LayoutMobile
      titre="Classement"
      sousTitre={triDe(tris[0] ?? TRI_DEFAUT).libelle}
      compteur={<Compteur affiches={total} total={lignes.length} libelle="wallets affichés" />}
      verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
    >
      <Stack className={s.mobile} espace={0}>
        <Recherche valeur={requete} onChange={(q) => majUrl('q', q || null)} lignes={lignes} />
        <PanneauFiltres
          filtre={filtre}
          effectifs={compte}
          total={lignes.length}
          onFiltre={(c) => majUrl('filtre', c === FILTRE_DEFAUT ? null : c)}
          rangee
        />
        {filtreDe(filtre).note && (
          <Text taille={12} encre="faible" className={s.note}>
            {filtreDe(filtre).note}
          </Text>
        )}
        {vide ?? (
          <ListeMobile
            mesurables={mesurables}
            absents={absents}
            critere={libelle}
            suivis={ensembleSuivis}
            onSuivre={basculerSuivi}
          />
        )}
      </Stack>
    </LayoutMobile>
  )
}
