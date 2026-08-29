/**
 * DONNÉES — fraîcheur, couverture, provenance, blocages.
 *
 * Le produit doit rendre visible QUAND IL NE SAIT PAS. Cet écran ne décrit pas
 * les wallets : il décrit ce que l'on sait d'eux, et à quel prix.
 */
import { useDonnees } from '@/app/Providers'
import { useMise } from '@/app/useLayout'
import { LayoutDesktop } from '@/app/LayoutDesktop'
import { LayoutMobile } from '@/app/LayoutMobile'
import { BandeauVerdict } from '@/components/BandeauVerdict'
import { BarreEtat } from '@/components/BarreEtat'
import { Mesure, Section } from '@/components/Communs'
import { Mono, Stack, Text } from '@/design/primitives'
import { NA, age, date, dateHeure, nb, phrase, pval } from '@/domain/format'
import s from './EcranDonnees.module.css'

export default function EcranDonnees() {
  const { meta, daily, lignes, mesures } = useDonnees()
  const mise = useMise()
  const maintenant = Date.now()
  const aCycle = daily ? age(Date.parse(daily.horodatage), 48, maintenant) : null
  const aPage = age(meta.gen * 1000, 24 * 7, maintenant)
  const heures = daily ? (maintenant - Date.parse(daily.horodatage)) / 3.6e6 : null
  const sante = (daily?.data_health ?? {}) as Record<string, number | boolean | undefined>

  const corps = (
    <Stack className={s.corps} espace={0}>
      <Section titre="Fraîcheur" />
      <div className={s.grille}>
        <Mesure
          k="Dernière collecte"
          v={
            <>
              {daily ? dateHeure(Date.parse(daily.horodatage)) : NA}
              {aCycle && (
                <Mono taille={11} encre={aCycle.vieux ? 'alerte' : 'faible'} className={s.age}>
                  {aCycle.texte}
                </Mono>
              )}
            </>
          }
        />
        <Mesure
          k="Page générée le"
          v={
            <>
              {date(meta.gen * 1000)}
              <Mono taille={11} encre={aPage.vieux ? 'alerte' : 'faible'} className={s.age}>
                {aPage.texte}
              </Mono>
            </>
          }
        />
        <Mesure k="Mode du cycle" v={daily?.mode ?? NA} />
        <Mesure k="Décodage de l’index" v={`${Math.round(mesures.indexMs)} ms`} u={mesures.worker ? 'worker' : 'repli'} />
      </div>

      <Section titre="Couverture" />
      <div className={s.grille}>
        <Mesure k="Wallets mesurés" v={String(meta.n)} />
        <Mesure k="Wallets classés" v={String(meta.ranked)} />
        <Mesure k="Explorés au total" v={meta.explores.toLocaleString('fr-FR')} />
        <Mesure k="En observation" v={meta.discovery_total.toLocaleString('fr-FR')} />
        <Mesure k="Trades analysés" v={(meta.trades / 1000).toFixed(1)} u="k" />
        <Mesure k="Reste à évaluer" v={String(sante['a_reevaluer'] ?? NA)} />
      </div>
      <Text taille={12} encre="faible" className={s.note}>
        Le classement ne porte que sur les <strong>{meta.n} wallets déjà mesurés</strong>. Les{' '}
        {meta.discovery_total.toLocaleString('fr-FR')} autres sont en observation : ils n’ont pas
        encore assez de trades clos pour qu’une estimation ait un sens. Deux populations, deux
        mots — les confondre donnerait au classement une couverture qu’il n’a pas.
      </Text>

      <Section titre="Ce que le test peut, et ne peut pas" />
      <div className={s.grille}>
        <Mesure k="Seuil de test multiple" v={pval(meta.seuil_bonferroni)} />
        <Mesure k="Rééchantillonnages" v={String(meta.tirages)} />
        <Mesure k="Plus petite p-valeur exprimable" v={pval(meta.resolution_p)} />
        <Mesure k="Wallets franchissant le seuil" v={String(meta.survivants)} />
        <Mesure k="IC entièrement au-dessus de zéro" v={`${meta.ic_boot_positif} / ${meta.n}`} />
        <Mesure k="IC entièrement au-dessous" v={`${meta.ic_boot_negatif} / ${meta.n}`} />
        <Mesure k="Bandes d’équivalence" v={String(meta.bandes)} />
      </div>
      {!meta.test_resolu && (
        <Text taille={13} encre="gris" className={s.note}>
          <strong>Le dispositif ne résout pas son propre seuil.</strong> À {meta.tirages}{' '}
          rééchantillonnages, la plus petite p-valeur exprimable vaut {pval(meta.resolution_p)},
          soit {Math.round(meta.resolution_p / meta.seuil_bonferroni)} fois le seuil de{' '}
          {pval(meta.seuil_bonferroni)}. Aucun wallet ne <em>peut</em> le franchir, quelle que
          soit sa performance : « {meta.survivants} survivant » est une limite d’instrument, pas
          un verdict. Le franchir exigerait plus d’un million de tirages par wallet.
        </Text>
      )}
      <Text taille={12} encre="faible" className={s.note}>
        {meta.ic_boot_positif} wallets sur {meta.n} ont un intervalle de bootstrap{' '}
        <strong>entièrement au-dessus de zéro</strong> — c’est l’ordre de grandeur de ce qu’on
        attendrait par pur hasard à 95 % sans correction, donc ce n’est pas un résultat, c’est
        l’absence d’une réfutation immédiate. En regard, {meta.ic_boot_negatif} wallets ont un
        intervalle entièrement <strong>au-dessous</strong> : leur perte, elle, n’est pas du
        bruit. Additionner les deux comptes produirait un nombre qui flatte.
      </Text>

      <Section titre="Provenance" />
      <div className={s.grille}>
        <Mesure k="Observé" v={String(meta.avec_natif)} u={`/ ${meta.n}`} />
        <Mesure k="Dérivé" v={String(meta.n - meta.avec_natif)} u={`/ ${meta.n}`} />
        <Mesure k="Sans probabilité calibrée" v={String(meta.sans_p_cal)} u={`/ ${meta.n}`} />
        <Mesure k="Verdict du protocole" v={meta.verdict} />
        <Mesure k="ρ de Spearman" v={nb(meta.spearman, 4)} />
        <Mesure k="ECE" v={nb(meta.ece, 4)} />
      </div>
      <Text taille={12} encre="faible" className={s.note}>
        <strong>Deux « HyperTracker » sur cet écran.</strong> La source externe est l’API{' '}
        <Mono taille={11} encre="faible">
          ht-api.coinmarketman.com
        </Mono>
        , qui publie les classements et les trades natifs ; cette application, qui les lit, porte
        le même nom. Partout ci-dessous, « HyperTracker » sans autre précision désigne la{' '}
        <strong>source</strong>.
      </Text>
      <Text taille={12} encre="faible" className={s.note}>
        Seuls <strong>{meta.avec_natif} wallets sur {meta.n}</strong> ont une donnée native
        permettant de confronter notre reconstruction à une seconde source. Le verdict reste{' '}
        <strong>{meta.verdict}</strong> : {phrase(meta.verdict_motif)} Ce n’est pas une
        validation, et l’interface ne le présente jamais comme telle.
      </Text>

      <Section titre="Réputation — classements de la source" />
      <div className={s.grille}>
        <Mesure k="Wallets du leaderboard" v={String(meta.reputation.n)} />
        <Mesure k="Sans aucun trade clos" v={String(meta.reputation.sans_trade_clos)} />
        <Mesure k="Mesurables par notre modèle" v={String(meta.reputation.mesurables)} />
      </div>
      <Text taille={12} encre="faible" className={s.note}>
        {meta.reputation.sans_trade_clos} de ces {meta.reputation.n} wallets n’ont{' '}
        <strong>aucun trade clos</strong> : ils tiennent des positions longtemps sans revenir à
        plat. Notre modèle compte des allers-retours clos, il ne peut pas les mesurer. PnL de
        compte et performance par trade clos ne sont pas la même grandeur, et l’application ne
        les additionne jamais.
      </Text>

      <Section titre="Ressources" />
      <div className={s.grille}>
        <Mesure k="Requêtes API HyperTracker" v={String(sante['requetes_hypertracker_utilisees'] ?? 0)} />
        <Mesure k="Requêtes Hyperliquid" v={String(sante['requetes_hyperliquid_consommees'] ?? 0)} />
        <Mesure k="Budget restant" v={String(sante['budget_restant'] ?? 0)} />
        <Mesure k="Séries fraîches" v={sante['series_fraiches'] == null ? NA : sante['series_fraiches'] ? 'oui' : 'non'} />
      </div>
      <Text taille={12} encre="faible" className={s.note}>
        Le cycle quotidien ne dépense <strong>aucune</strong> requête à l’API HyperTracker : ses
        sources sont les instantanés de carnet déjà sur disque et l’API publique Hyperliquid.
      </Text>

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
              Ce que dit cet écran
            </Text>
            <Text taille={12} encre="faible">
              Non pas ce que valent les wallets, mais ce que l’on sait d’eux : depuis quand, sur
              quelle fraction de la population, et avec quel instrument.
            </Text>
          </div>
        }
        releve={<div className={s.scroll}>{corps}</div>}
        inspecteur={
          <div className={s.aside}>
            <Text variante="libelle" encre="faible">
              Population mesurée
            </Text>
            <Mono taille={32} encre="clair" graisse={500}>
              {meta.n}
            </Mono>
            <Text taille={12} encre="faible">
              sur {meta.explores.toLocaleString('fr-FR')} wallets explorés — soit{' '}
              {((meta.n / meta.explores) * 100).toFixed(2)} % de la population.
            </Text>
            <Text taille={12} encre="faible">
              {lignes.filter((l) => l.pnl < 0).length} d’entre eux perdent de l’argent.
            </Text>
          </div>
        }
        etat={<BarreEtat />}
      />
    )
  }

  return (
    <LayoutMobile
      titre="Données"
      sousTitre="Fraîcheur et provenance"
      verdict={<BandeauVerdict meta={meta} ageHeures={heures} compact />}
    >
      {corps}
    </LayoutMobile>
  )
}
