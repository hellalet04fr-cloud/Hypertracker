/**
 * AUJOURD'HUI — ce qui a changé, et à quelle échelle.
 *
 * Chaque compteur de section annonce « affichés / total ». « Dormants 6 » pour
 * 100 dormants réels sous-déclarait un risque par un simple effet de découpage.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useDonnees } from '@/app/Providers'
import { useMise } from '@/app/useLayout'
import { LayoutMobile } from '@/app/LayoutMobile'
import { LayoutDesktop } from '@/app/LayoutDesktop'
import { BandeauVerdict } from '@/components/BandeauVerdict'
import { Compteur, EtatVide, Section } from '@/components/Communs'
import { BarreEtat } from '@/components/BarreEtat'
import { Mono, Stack, Text } from '@/design/primitives'
import { age, critere, date, humaniser, phrase, usd } from '@/domain/format'
import { bande, dormant, scoreTxt, vigilance } from '@/domain/score'
import type { Ligne, Mouvement } from '@/domain/types'
import s from './Aujourdhui.module.css'

interface DefSection {
  titre: string
  lignes: readonly { a: string; extra: string }[]
  total: number
  lien?: { filtre: string; tri?: string }
  vide: string
  note?: string
}

function LigneCourte({ l, extra }: { l: Ligne | undefined; extra: string }) {
  if (!l) return null
  return (
    <Link to={`/classement/${l.a}`} className={s.li}>
      <Mono taille={11} encre="faible" className={s.bande}>
        {bande(l)}
      </Mono>
      <Mono taille={12} encre="gris" className={s.adr}>
        {l.a.slice(0, 6)}…{l.a.slice(-4)}
      </Mono>
      <Mono taille={15} encre="index" graisse={500}>
        {scoreTxt(l)}
      </Mono>
      {/* Les marques suivent le wallet partout : un wallet fraîchement qualifié
          et déjà dormant est l'information la plus intéressante de l'écran, et
          elle était éparpillée sur deux listes distantes de 400 px. */}
      {dormant(l) && (
        <span className={s.mkDort} title="dormant">
          ◦
        </span>
      )}
      {vigilance(l) && (
        <span className={s.mkVig} title="trades non indépendants">
          △
        </span>
      )}
      <Text taille={12} encre="faible" lignes={2} className={s.extra}>
        {extra}
      </Text>
    </Link>
  )
}

export default function Aujourdhui() {
  const { meta, lignes, daily } = useDonnees()
  const mise = useMise()
  const parA = useMemo(() => new Map(lignes.map((l) => [l.a, l])), [lignes])

  const dormants = useMemo(
    () => lignes.filter((l) => l.st === 'RANKED' && dormant(l)).sort((a, b) => (b.dort_j ?? 0) - (a.dort_j ?? 0)),
    [lignes],
  )
  const enVigilance = useMemo(() => lignes.filter(vigilance), [lignes])
  const perdants = useMemo(() => lignes.filter((l) => l.st === 'RANKED' && l.pnl < 0), [lignes])
  const bascule = useMemo(() => lignes.filter((l) => l.pnl > 0 && l.pnl_hors_max <= 0), [lignes])

  const mv = (m: readonly Mouvement[], f: (x: Mouvement) => string) =>
    m.slice(0, 6).map((x) => ({ a: x.a, extra: f(x) }))

  const defs: DefSection[] = daily
    ? [
        {
          titre: 'Nouveaux qualifiés',
          lignes: mv(daily.new_ranked, (x) => humaniser(x.message ?? '')),
          total: daily.new_ranked.length,
          lien: { filtre: 'classes', tri: 'recent' },
          vide: `Aucun wallet n’a franchi les critères ce cycle. Une découverte n’est pas une qualification : il faut ${meta.seuil_trades} trades clos et ${meta.seuil_jours} jours d’historique.`,
        },
        {
          titre: 'Candidats du dernier cycle',
          lignes: mv(daily.watch, (x) => critere((x.manque ?? [])[0] ?? '')),
          total: daily.watch.length,
          vide: 'Aucun candidat proche des critères ce cycle.',
          note: `Aucun de ces wallets n’est refusé : il leur manque du temps. La qualification demande ${meta.seuil_jours} jours d’historique et ${meta.seuil_trades} trades clos.`,
        },
        {
          titre: 'Sorties',
          lignes: mv(daily.archived, (x) => humaniser(x.raison ?? '')),
          total: daily.archived.length,
          vide: 'Aucun retrait. Un wallet n’est retiré que sur un critère réellement réfuté, jamais sur une donnée simplement manquante.',
        },
        {
          titre: 'Dormants',
          lignes: dormants.slice(0, 6).map((l) => ({ a: l.a, extra: `dernier trade il y a ${Math.round(l.dort_j ?? 0)} j` })),
          total: dormants.length,
          lien: { filtre: 'dormants', tri: 'recent' },
          vide: 'Aucun wallet classé n’est dormant depuis plus de deux mois.',
        },
        {
          titre: 'Trades non indépendants',
          lignes: enVigilance.slice(0, 6).map((l) => ({ a: l.a, extra: `Ljung-Box p = ${(l.lb_p ?? 0).toFixed(3)}` })),
          total: enVigilance.length,
          lien: { filtre: 'vigilance', tri: 'dependance' },
          vide: 'Aucune dépendance sérielle détectée.',
          note: 'Sur ces wallets, les trades se renforcent au lieu de se succéder : tout intervalle calculé en supposant l’indépendance est trop optimiste.',
        },
        {
          titre: 'Bascule sans leur meilleur trade',
          lignes: bascule.slice(0, 6).map((l) => ({ a: l.a, extra: `${usd(l.pnl)} → ${usd(l.pnl_hors_max)}` })),
          total: bascule.length,
          lien: { filtre: 'bascule', tri: 'pnl' },
          vide: 'Aucun gagnant ne dépend d’un seul trade à ce point.',
        },
      ]
    : []

  const pleines = defs.filter((d) => d.lignes.length)
  const vides = defs.filter((d) => !d.lignes.length)
  const ageCycle = daily ? age(Date.parse(daily.horodatage), 48, Date.now()) : null
  const heures = daily ? (Date.now() - Date.parse(daily.horodatage)) / 3.6e6 : null

  const corps = (
    <Stack className={s.corps} espace={0}>
      {/* CE QUE LA POPULATION EST, avant ce qui a changé. Un accueil qui n'ouvre
          que sur des mouvements laisse croire que le classement va de soi. */}
      <div className={s.bande4}>
        <div>
          <Text variante="libelle" encre="faible">
            Classés
          </Text>
          <Mono taille={24} encre="clair" graisse={500}>
            {meta.ranked}
          </Mono>
        </div>
        <div>
          <Text variante="libelle" encre="faible">
            En perte
          </Text>
          <Mono taille={24} encre="alerte" graisse={500}>
            {perdants.length}
          </Mono>
        </div>
        <div>
          <Text variante="libelle" encre="faible">
            Bandes
          </Text>
          <Mono taille={24} encre="clair" graisse={500}>
            {meta.bandes}
          </Mono>
        </div>
        <div>
          <Text variante="libelle" encre="faible">
            Verdict
          </Text>
          <Mono taille={12} encre="index" graisse={500}>
            {meta.verdict}
          </Mono>
        </div>
      </div>

      <Text taille={13} encre="gris" className={s.phrase}>
        <strong>{perdants.length} des {meta.ranked} wallets classés perdent de l’argent.</strong>{' '}
        Le classement ordonne des performances estimées ; il n’affirme pas qu’elles sont
        positives, et {meta.bandes} bandes d’équivalence suffisent à décrire {meta.n} wallets —
        à l’intérieur d’une bande, rien ne départage.
      </Text>

      {daily && (
        <Text taille={12} encre="faible" className={s.cycle}>
          Dernier cycle {daily.horodatage.slice(0, 16).replace('T', ' ')} —{' '}
          <span className={ageCycle?.vieux ? s.vieux : undefined}>{ageCycle?.texte}</span> ·{' '}
          {daily.mode}
        </Text>
      )}

      {daily?.prochaine_action && (
        <Text taille={13} encre="gris" className={s.phrase}>
          <strong>Prochaine action</strong> — {phrase(humaniser(daily.prochaine_action))}
        </Text>
      )}

      {!daily && (
        <EtatVide titre="Aucun relevé disponible">
          Cette page est un instantané : elle affichera le prochain cycle dès qu’il aura été
          publié.
        </EtatVide>
      )}

      {pleines.map((d) => (
        <Section
          key={d.titre}
          titre={d.titre}
          apres={<Compteur affiches={d.lignes.length} total={d.total} libelle={d.titre} />}
        >
          {d.lignes.map((x) => (
            <LigneCourte key={x.a} l={parA.get(x.a)} extra={x.extra} />
          ))}
          {d.total > d.lignes.length && d.lien && (
            <Link
              to={`/classement?filtre=${d.lien.filtre}&tri=${d.lien.tri ?? 'score_actifs'}`}
              className={s.tout}
            >
              Voir les {d.total} — {d.total - d.lignes.length} de plus →
            </Link>
          )}
          {d.note && (
            <Text taille={12} encre="faible" className={s.note}>
              {d.note}
            </Text>
          )}
        </Section>
      ))}

      {vides.length > 0 && (
        <Section titre="Rien à signaler" apres={<Compteur affiches={vides.length} total={vides.length} />}>
          {vides.map((d) => (
            <details key={d.titre} className={s.repli}>
              <summary>{d.titre}</summary>
              <Text taille={12} encre="faible">
                {d.vide}
              </Text>
            </details>
          ))}
        </Section>
      )}

      {daily?.blocages.map((b) => (
        <Stack key={b.sujet} className={s.blocage} espace={8}>
          <Text variante="libelle" encre="alerte">
            Blocage — {b.sujet} ({b.portee})
          </Text>
          <Text taille={13} encre="gris">
            {phrase(b.cause)}
          </Text>
          <Text taille={13} encre="gris">
            <strong>Interdit automatiquement</strong> — {phrase(b.action_interdite)}
          </Text>
          <Text taille={13} encre="gris">
            <strong>Demande</strong> — {phrase(b.demande)}
          </Text>
        </Stack>
      ))}
    </Stack>
  )

  if (mise === 'poste') {
    return (
      <LayoutDesktop
        verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
        population={
          <div className={s.aside}>
            <Text variante="libelle" encre="faible">
              Population
            </Text>
            <Text taille={12} encre="faible">
              {meta.n} wallets mesurés sur {meta.explores.toLocaleString('fr-FR')} explorés.
              Dernière génération {date(meta.gen * 1000)}.
            </Text>
          </div>
        }
        releve={<div className={s.scroll}>{corps}</div>}
        inspecteur={
          <div className={s.aside}>
            <Text variante="libelle" encre="faible">
              Lecture
            </Text>
            <Text taille={12} encre="faible">
              Cet écran dit ce qui a changé depuis le dernier cycle. Ce qu’il ne dit pas : que
              les mouvements soient du mérite. Un décalage uniforme de rang n’en est pas.
            </Text>
          </div>
        }
        etat={<BarreEtat />}
      />
    )
  }

  return (
    <LayoutMobile
      titre="Aujourd’hui"
      sousTitre="Ce qui a changé"
      verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
    >
      {corps}
    </LayoutMobile>
  )
}
