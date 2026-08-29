/**
 * L'INSPECTEUR — quatre onglets, dont celui que l'ancienne application n'avait
 * pas.
 *
 * MESURE dit ce que le modèle estime. PREUVE dit ce qui permettrait de le
 * RÉFUTER, et c'est le cœur du produit : sur 52 259 wallets explorés, aucun ne
 * franchit un test honnête — et la raison pour laquelle aucun ne le franchit
 * doit être lisible, y compris quand elle tient à la résolution du test.
 */
import { useEffect, useState } from 'react'
import type { Detail, Ligne, Meta } from '@/domain/types'
import { useDonnees } from '@/app/Providers'
import { chargerLot, prefixeDe } from '@/data/chargeur'
import { NA, adresseGroupee, classeFr, date, nb, pval, usd, usdBrut } from '@/domain/format'
import { bande, icLong, largeurIC, qualiteFr, scoreTxt, vigilance } from '@/domain/score'
import { description, svg, viewBox } from '@/charts/rail'
import { retrecissement } from '@/charts/figures'
import { Mesure, Section } from './Communs'
import { Bloc } from './Squelette'
import { Mono, Stack, Text } from '@/design/primitives'
import { Series } from './Series'
import { Raisons } from './Raisons'
import s from './Inspecteur.module.css'

export const ONGLETS = ['Mesure', 'Preuve', 'Séries', 'Cycle de vie'] as const
export type Onglet = (typeof ONGLETS)[number]

interface Props {
  adresse: string | null
  /** onglet imposé de l'extérieur (raccourcis 1..4) */
  onglet?: Onglet
  onOnglet?: (o: Onglet) => void
}

export function Inspecteur({ adresse, onglet, onOnglet }: Props) {
  const { meta, lignes } = useDonnees()
  const [interne, setInterne] = useState<Onglet>('Mesure')
  const actif = onglet ?? interne
  const choisir = onOnglet ?? setInterne

  const l = adresse ? lignes.find((x) => x.a === adresse) : undefined
  const { detail, etat } = useDetail(adresse, meta.gen)

  if (!l) {
    return (
      <div className={s.repos}>
        <Text taille={12} encre="faible">
          Survolez une ligne, ou appuyez sur <kbd>↓</kbd>. <kbd>Espace</kbd> épingle un wallet pour
          que l’inspecteur cesse de suivre la sélection.
        </Text>
      </div>
    )
  }

  return (
    <div className={s.cadre}>
      <div className={s.tete}>
        <Mono taille={11} encre="faible">
          {bande(l)} · rang {String(l.rang).padStart(3, '0')} / {meta.n}
        </Mono>
        <Mono taille={12} encre="gris" className={s.adr}>
          {adresseGroupee(l.a)}
        </Mono>
      </div>

      <div className={s.onglets} role="tablist">
        {ONGLETS.map((o, i) => (
          <button
            key={o}
            role="tab"
            type="button"
            aria-selected={o === actif}
            className={`${s.onglet} ${o === actif ? s.actif : ''}`}
            onClick={() => choisir(o)}
          >
            {o}
            <Mono taille={11} encre="faible" className={s.touche}>
              {i + 1}
            </Mono>
          </button>
        ))}
      </div>

      <div className={s.contenu} role="tabpanel">
        {actif === 'Mesure' && <OngletMesure l={l} meta={meta} detail={detail} />}
        {actif === 'Preuve' && <OngletPreuve l={l} meta={meta} detail={detail} etat={etat} />}
        {actif === 'Séries' && <Series detail={detail} etat={etat} />}
        {actif === 'Cycle de vie' && <OngletCycle detail={detail} etat={etat} />}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────── chargement du détail */

type EtatDetail = 'chargement' | 'pret' | 'erreur'

export function useDetail(adresse: string | null, gen: number): { detail: Detail | null; etat: EtatDetail } {
  const [detail, setDetail] = useState<Detail | null>(null)
  const [etat, setEtat] = useState<EtatDetail>('chargement')

  useEffect(() => {
    if (!adresse) {
      setDetail(null)
      setEtat('pret')
      return
    }
    let vivant = true
    setEtat('chargement')
    void chargerLot(prefixeDe(adresse), gen).then((lot) => {
      if (!vivant) return
      const d = lot?.wallets[adresse] ?? null
      setDetail(d)
      setEtat(d ? 'pret' : 'erreur')
    })
    return () => {
      vivant = false
    }
  }, [adresse, gen])

  return { detail, etat }
}

/* ────────────────────────────────────────────────────────── Mesure */

function OngletMesure({ l, meta, detail }: { l: Ligne; meta: Meta; detail: Detail | null }) {
  const larg = largeurIC(l)
  const pairs = meta.n
  return (
    <Stack espace={0}>
      {/* Un chiffre de score n'apparaît JAMAIS sans son rail dans le même bloc. */}
      <div className={s.hero}>
        <Text variante="libelle" encre="faible">
          Performance
        </Text>
        <Mono taille={44} encre="index" graisse={500} className={s.grand}>
          {scoreTxt(l)}
        </Mono>
        <svg
          className={s.rail}
          viewBox={viewBox({ w: 300, h: 26 })}
          role="img"
          aria-label={description(l)}
          dangerouslySetInnerHTML={{ __html: svg(l, { w: 300, h: 26 }) }}
        />
      </div>

      <Mesure k="Incertitude" v={icLong(l)} />
      <Mesure k="Largeur de l’IC" v={String(larg)} />
      <Mesure k="Bande d’équivalence" v={bande(l)} />
      <Mesure k="Probabilité calibrée" v={l.conf == null ? NA : `${l.conf} %`} />
      <Mesure k="Qualité des données" v={qualiteFr(l.conf_lab)} />

      {larg === 0 && (
        <Text taille={12} encre="faible" className={s.note}>
          <strong>L’intervalle est de largeur nulle parce que l’échelle est bornée</strong>, pas
          parce que la mesure est certaine : ses deux bornes ont été écrasées sur {l.ic[0]}. C’est
          le seul endroit où ce produit pourrait laisser croire à une certitude parfaite — il n’en
          a aucune.
        </Text>
      )}
      {l.conf == null && (
        <Text taille={12} encre="faible" className={s.note}>
          La probabilité calibrée n’existe pas pour ce wallet : le modèle isotonique n’a pas été
          conservé, il ne peut donc pas s’appliquer à un wallet apparu depuis. Elle reste N/D
          plutôt qu’approchée — {meta.sans_p_cal} wallets sur {pairs} sont dans ce cas.
        </Text>
      )}

      <Section titre="Résultat" />
      <Mesure k="PnL net" v={usd(l.pnl)} />
      <Mesure k="PnL hors meilleur trade" v={usd(l.pnl_hors_max)} />
      <Mesure k="Frais payés" v={usdBrut(l.frais)} />
      <Mesure k="Drawdown maximal" v={usdBrut(l.dd)} />
      <Mesure k="Trades clos" v={String(l.n)} />
      <Mesure k="Activité 30 j / 7 j" v={`${l.r30} / ${l.r7}`} />
      <Mesure k="Variation de rang relatif" v={l.drang_rel == null ? NA : String(l.drang_rel)} />

      {l.pnl > 0 && l.pnl_hors_max <= 0 && (
        <Text taille={12} encre="alerte" className={s.note}>
          <strong>Ce wallet devient perdant sans son plus gros trade.</strong> Son résultat ne
          décrit pas une méthode reproductible mais un événement.
        </Text>
      )}

      {detail && <Raisons detail={detail} lib={meta.lib} />}
    </Stack>
  )
}

/* ────────────────────────────────────────────────────────── Preuve */

function OngletPreuve({
  l,
  meta,
  detail,
  etat,
}: {
  l: Ligne
  meta: Meta
  detail: Detail | null
  etat: EtatDetail
}) {
  if (etat === 'chargement') {
    return (
      <Stack espace={8} className={s.charge}>
        <Bloc l={70} h={14} />
        <Bloc l={90} h={12} />
        <Bloc l={55} h={12} />
      </Stack>
    )
  }
  if (!detail) {
    return (
      <Text taille={12} encre="faible" className={s.note}>
        Le détail de ce wallet n’a pas pu être chargé. Les grandeurs de la liste restent
        exactes ; celles qui exigent la série complète sont indisponibles.
      </Text>
    )
  }

  const p = detail.preuve
  const srMin = Math.min(l.sr, l.post) - 0.15
  const srMax = Math.max(l.sr, l.post) + 0.15

  return (
    <Stack espace={0}>
      <Text taille={12} encre="gris" className={s.intro}>
        Ce qui suit ne cherche pas à confirmer le score : ce sont les épreuves qu’il doit
        survivre.
      </Text>

      <Mesure k="Sharpe et erreur type" v={`${nb(l.sr, 2)} ± ${nb(l.se, 2)}`} />
      <div className={s.figure}>
        <svg
          viewBox="0 0 300 40"
          role="img"
          aria-label={`Sharpe brut ${nb(l.sr, 2)} ramené à ${nb(l.post, 2)}`}
          dangerouslySetInnerHTML={{
            __html: retrecissement({ sr: l.sr, post: l.post, se: l.se, min: srMin, max: srMax }),
          }}
        />
        <Text taille={12} encre="faible">
          Un échantillon mince est ramené vers la moyenne de la population : c’est ce déplacement,
          et non le chiffre brut, qui fonde le score.
        </Text>
      </div>

      <Section titre="Contre le hasard" />
      <Mesure k="p-valeur, permutation par signe" v={pval(p.p_perm)} />
      <Mesure
        k="IC bootstrap par blocs"
        v={p.boot_ic ? `${nb(p.boot_ic[0], 3)} … ${nb(p.boot_ic[1], 3)}` : NA}
      />
      <Mesure k="Longueur de bloc retenue" v={p.boot_bloc == null ? NA : String(p.boot_bloc)} />
      <Mesure k="Seuil de test multiple" v={pval(meta.seuil_bonferroni)} />
      <Text taille={12} encre={p.ic_negatif ? 'alerte' : 'faible'} className={s.note}>
        {p.ic_negatif
          ? `L’intervalle de bootstrap est entièrement AU-DESSOUS de zéro : la perte de ce wallet n’est pas du bruit. ${meta.ic_boot_negatif} wallets sur ${meta.n} sont dans ce cas.`
          : p.ic_positif
            ? `L’intervalle est entièrement au-dessus de zéro — comme ${meta.ic_boot_positif} sur ${meta.n}, soit l’ordre de grandeur attendu par pur hasard à 95 % sans correction. Ce n’est pas une preuve, c’est l’absence d’une réfutation immédiate.`
            : 'L’intervalle contient zéro : la performance de ce wallet est compatible avec le hasard.'}
      </Text>
      {!meta.test_resolu && (
        <Text taille={12} encre="faible" className={s.note}>
          <strong>Le test ne résout pas son propre seuil.</strong> À {meta.tirages}{' '}
          rééchantillonnages, la plus petite p-valeur exprimable vaut {pval(meta.resolution_p)} —
          soit {Math.round(meta.resolution_p / meta.seuil_bonferroni)} fois le seuil de{' '}
          {pval(meta.seuil_bonferroni)}. Aucun wallet ne PEUT le franchir, quelle que soit sa
          performance : lire ce zéro comme une preuve d’absence serait l’erreur exactement
          symétrique de celle que ce produit corrige.
        </Text>
      )}

      <Section titre="Dépendance sérielle" />
      <Mesure k="Autocorrélation, retard 1" v={nb(p.ac1, 3)} />
      <Mesure k="Ljung-Box(5)" v={pval(p.lb_p)} />
      {vigilance(l) && (
        <Text taille={12} encre="alerte" className={s.note}>
          <strong>Trades non indépendants</strong> — probable renforcement de position. Toute
          p-valeur calculée en supposant l’indépendance est trop optimiste ; c’est précisément
          l’anomalie qui disqualifiait le deuxième du classement précédent.
        </Text>
      )}

      <Section titre="Ce qui reste sans le plus gros trade" />
      <Mesure k="Part du meilleur trade" v={p.part_max == null ? NA : `${nb(p.part_max * 100, 0)} %`} />
      <Mesure k="PnL hors meilleur trade" v={usd(l.pnl_hors_max)} />
      <Mesure k="Bascule gagnant → perdant" v={p.bascule ? 'oui' : 'non'} />

      <Section titre="Frais et persistance" />
      <Mesure k="Ce que les frais retirent" v={p.frais_sr == null ? NA : `${nb(p.frais_sr, 3)} de Sharpe`} />
      <Mesure k="Sharpe, première moitié" v={nb(p.sr_h1, 2)} />
      <Mesure k="Sharpe, seconde moitié" v={nb(p.sr_h2, 2)} />
      {p.sr_h1 == null && (
        <Text taille={12} encre="faible" className={s.note}>
          L’historique est trop court pour être coupé en deux : la persistance n’est pas
          mesurable, elle n’est pas nulle.
        </Text>
      )}
    </Stack>
  )
}

/* ─────────────────────────────────────────────────── Cycle de vie */

function OngletCycle({ detail, etat }: { detail: Detail | null; etat: EtatDetail }) {
  if (etat === 'chargement') return <Bloc l={80} h={14} />
  if (!detail) return <Text taille={12} encre="faible">Détail indisponible.</Text>
  return (
    <Stack espace={0}>
      <Mesure k="Qualification" v={classeFr(detail.classe)} />
      <Mesure k="Découvert via" v={detail.src ?? NA} />
      <Mesure k="Première vue" v={detail.vu ? date(detail.vu * 1000) : NA} />
      <Mesure k="Qualifié le" v={detail.promu ? date(detail.promu * 1000) : NA} />
      <Mesure k="Dernière collecte" v={detail.coll ? date(detail.coll * 1000) : NA} />
      <Mesure k="Retours au classement" v={String(detail.ret)} />
      {/* DATES DISTINCTES, jamais lignes : « 5 relevés » désignait deux dates,
          dont trois points à 207 et 120 secondes d'intervalle. */}
      <Mesure k="Relevés d’historique" v={`${detail.n_dates} date${detail.n_dates > 1 ? 's' : ''}`} />
      {detail.n_dates < 2 && (
        <Text taille={12} encre="faible" className={s.note}>
          Une seule date : aucune évolution n’est traçable, et aucune variation de rang n’est
          calculable. L’historique s’enrichit d’un point par cycle.
        </Text>
      )}
    </Stack>
  )
}
