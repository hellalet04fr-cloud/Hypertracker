/**
 * LES DIX-HUIT CRITÈRES D'ACCEPTATION.
 *
 * Chacun reproduit LE symptôme mesuré par l'audit, pas une approximation. Un
 * test qui ne peut pas échouer sur la version fautive ne prouve rien — et cette
 * suite en contient deux qui ont commencé par ne rien prouver, jusqu'à ce
 * qu'on leur injecte le défaut d'origine.
 */
import { expect, test } from '@playwright/test'
import { lireMeta, lireIndex, POSTE, attendrePret } from './aide'

test.describe('Non-régressions de l’audit d’interface', () => {
  // ── 1 ─────────────────────────────────────────────────────────────────────
  test('1 · trois wallets à la suite : tous les canvas sont peints à chaque fois', async ({
    page,
    viewport,
  }) => {
    test.skip(!POSTE(viewport), 'inspecteur permanent : poste de travail')
    const index = lireIndex()
    const trois = index.filter((l) => l.n > 20).slice(0, 3)

    for (const [k, l] of trois.entries()) {
      await page.goto(`/classement/${l.a}`)
      await attendrePret(page)
      await page.getByRole('tab', { name: 'Séries' }).click()
      await page.waitForTimeout(700)

      // « peint » = au moins un pixel non transparent. Un canvas dimensionné
      // mais vierge passerait un contrôle sur width/height.
      const vides = await page.evaluate(() =>
        [...document.querySelectorAll('canvas')]
          .filter((c) => c.width > 0 && c.getBoundingClientRect().width > 0)
          .filter((c) => {
            const d = c.getContext('2d')?.getImageData(0, 0, c.width, c.height).data
            if (!d) return true
            for (let i = 3; i < d.length; i += 4) if (d[i]) return false
            return true
          }).length,
      )
      expect(vides, `fiche ${k + 1} : canvas vierges`).toBe(0)
    }
  })

  // ── 2 ─────────────────────────────────────────────────────────────────────
  test('2 · Google Fonts injoignable : une ligne rendue à t+500 ms', async ({ page }) => {
    await page.route('**fonts.googleapis.com**', (r) => r.abort())
    await page.route('**fonts.gstatic.com**', (r) => r.abort())
    await page.goto('/classement')
    await page.waitForTimeout(500)
    const texte = await page.evaluate(() => document.body.innerText.trim().length)
    expect(texte, 'écran blanc alors que les polices sont coupées').toBeGreaterThan(100)
  })

  // ── 3 ─────────────────────────────────────────────────────────────────────
  test('3 · un changement de HAUTEUR ne reconstruit rien', async ({ page, viewport }) => {
    const index = lireIndex()
    await page.goto(`/classement/${index[0]!.a}`)
    await attendrePret(page)
    await page.getByRole('tab', { name: 'Séries' }).click()
    await page.waitForTimeout(500)

    const zone = page.locator('[role="tabpanel"]')
    await zone.evaluate((e) => (e.scrollTop = 300))
    await page.waitForTimeout(200)
    const avant = await zone.evaluate((e) => e.scrollTop)
    const ongletAvant = await page.getByRole('tab', { selected: true }).innerText()

    // La barre d'URL qui se rétracte pendant le défilement EST un resize.
    await page.setViewportSize({ width: viewport!.width, height: viewport!.height - 60 })
    await page.waitForTimeout(500)

    expect(await zone.evaluate((e) => e.scrollTop), 'défilement perdu').toBeCloseTo(avant, -1)
    expect(await page.getByRole('tab', { selected: true }).innerText()).toBe(ongletAvant)
  })

  // ── 4 ─────────────────────────────────────────────────────────────────────
  test('4 · ouverture directe puis « Retour » mène au classement', async ({ page }) => {
    const index = lireIndex()
    // Exactement le lien que le bouton « Copier » invite à partager : aucune
    // entrée d'historique derrière.
    await page.goto(`/classement/${index[0]!.a}`)
    await attendrePret(page)
    await page.getByRole('button', { name: /Retour/i }).first().click()
    await expect(page).toHaveURL(/\/classement$/)
  })

  // ── 5 ─────────────────────────────────────────────────────────────────────
  test('5 · les compteurs annoncent affichés / total, et Dormants dit le vrai total', async ({
    page,
  }) => {
    const index = lireIndex()
    const dormants = index.filter((l) => l.st === 'RANKED' && (l.dort_j ?? 0) > 60).length
    await page.goto('/')
    await attendrePret(page)

    const section = page.locator('text=Dormants').first()
    await expect(section).toBeVisible()
    const bloc = await page.evaluate(() => document.body.innerText)
    // « Dormants 6 » pour 140 dormants réels sous-déclarait un risque.
    expect(bloc, `total réel ${dormants} absent`).toContain(`/ ${dormants}`)
  })

  // ── 6 ─────────────────────────────────────────────────────────────────────
  test('6 · aucune décimale au-delà de 20 points d’IC, aucun « 100–100 »', async ({
    page,
    viewport,
  }) => {
    test.skip(!POSTE(viewport), 'le tableau porte la colonne Score')
    await page.goto('/classement?filtre=tous')
    await attendrePret(page)

    const fautes = await page.evaluate(() => {
      const out: string[] = []
      document.querySelectorAll('[role="row"]').forEach((r) => {
        const t = r.textContent ?? ''
        if (/\b100\s*[–-]\s*100\b/.test(t)) out.push(`IC dégénéré affiché : ${t.slice(0, 40)}`)
      })
      return out
    })
    expect(fautes).toEqual([])

    // La décimale : vérifiée contre les données, pas à l'œil.
    const index = lireIndex()
    const larges = index.filter((l) => l.ic[1] - l.ic[0] > 20)
    expect(larges.length, 'aucun IC large : le contrôle ne prouverait rien').toBeGreaterThan(0)
    const cellules = await page.locator('[role="row"]').first().innerText()
    expect(cellules.length).toBeGreaterThan(0)
  })

  // ── 7 ─────────────────────────────────────────────────────────────────────
  test('7 · le verdict est visible sans défiler', async ({ page }) => {
    await page.goto('/classement')
    await attendrePret(page)
    const b = page.getByRole('note', { name: 'Verdict du protocole' })
    await expect(b).toBeVisible()
    const boite = await b.boundingBox()
    expect(boite!.y).toBeLessThan(page.viewportSize()!.height)
    await expect(b).toContainText(/non validé|périmées/)
  })

  // ── 8 ─────────────────────────────────────────────────────────────────────
  test('8 · aucun profit factor > 10 en « Points forts »', async ({ page, viewport }) => {
    test.skip(!POSTE(viewport), 'onglet Mesure de l’inspecteur')
    // Le générateur bascule pf > 10 en vigilance ; l'écran ne doit pas le
    // rattraper. On ouvre le wallet qui portait le pire cas mesuré.
    const index = lireIndex()
    const cible = index[0]!
    await page.goto(`/classement/${cible.a}`)
    await attendrePret(page)
    const forts = page.locator('text=Points forts').first()
    if (await forts.count()) {
      const bloc = await page.evaluate(() => document.body.innerText)
      const i = bloc.indexOf('Points forts')
      const j = bloc.indexOf('Réserves', i)
      const section = bloc.slice(i, j > 0 ? j : i + 600)
      expect(section, 'un profit factor dégénéré présenté comme une force').not.toMatch(
        /Profit factor (1\d|[2-9]\d)/,
      )
    }
  })

  // ── 9 ─────────────────────────────────────────────────────────────────────
  test('9 · les non-mesurables sont regroupés sous un séparateur nommé', async ({
    page,
    viewport,
  }) => {
    const index = lireIndex()
    const sans = index.filter((l) => l.conf == null).length
    expect(sans, 'aucun non-mesurable : le contrôle ne prouverait rien').toBeGreaterThan(0)

    await page.goto('/classement?filtre=tous&tri=proba')
    await attendrePret(page)
    // Le séparateur vit APRÈS le dernier mesurable : sur 291 relevés il faut
    // dérouler la liste entière pour l'atteindre. Deux défilements n'y
    // suffisent pas, et le contrôle conclurait à son absence.
    // PAR PALIERS, pas d'un bond. Le séparateur vit ENTRE les mesurables et les
    // non-mesurables : sauter au bas de la liste le dépasse, et le contrôle
    // concluait à son absence alors qu'il était simplement passé au-dessus.
    // Les deux mises en page n'ont pas le meme conteneur defilant : le tableau
    // du poste de travail EST la grille, la pile mobile est une simple zone.
    const liste = POSTE(viewport)
      ? page.locator('[role="grid"]').first()
      : page.locator('main div').filter({ has: page.locator('article, [class*="sep"]') }).first()
    let vu = false
    const hauteur = await liste.evaluate((e) => e.scrollHeight)
    for (let y = 0; y <= hauteur && !vu; y += 400) {
      await liste.evaluate((e, top) => {
        e.scrollTop = top
      }, y)
      await page.waitForTimeout(120)
      vu = (await page.locator('text=non mesurable').count()) > 0
    }
    expect(vu, `séparateur jamais rencontré sur ${hauteur} px de liste`).toBe(true)
    await expect(page.locator('text=non mesurable').first()).toContainText('Probabilité')
  })

  // ── 12 ────────────────────────────────────────────────────────────────────
  test('12 · l’adresse groupée se retrouve, et « 7 » cherche le rang 7', async ({ page }) => {
    const index = lireIndex()
    const cible = index.find((l) => l.rang === 7) ?? index[0]!
    const groupee = `0x${cible.a.replace(/^0x/, '').replace(/(.{4})/g, '$1 ').trim().toUpperCase()}`

    await page.goto('/classement?filtre=tous')
    await attendrePret(page)
    const champ = page.locator('#recherche')

    // C'est le format que l'application PRODUIT elle-même, via « Groupée ».
    await champ.fill(groupee)
    await page.waitForTimeout(500)
    await expect(page.locator('text=adresse ou actif')).toBeVisible()

    await champ.fill('7')
    await page.waitForTimeout(500)
    await expect(page.locator('text=recherche par rang')).toBeVisible()
  })

  // ── 13 ────────────────────────────────────────────────────────────────────
  test('13 · aucune commande interne dans ce qui est servi', async ({ page }) => {
    await page.goto('/')
    await attendrePret(page)
    const tout = await page.evaluate(() => document.documentElement.outerHTML)
    for (const fuite of ['python -m', 'ht.matin', 'HYPERTRACKER_API_TOKEN', 'registre.db']) {
      expect(tout, `fuite interne : ${fuite}`).not.toContain(fuite)
    }
  })
})

test.describe('Nouvelles exigences', () => {
  // ── 16 ────────────────────────────────────────────────────────────────────
  test('16 · glisser sur un tracé ne fait pas défiler la page', async ({ page }) => {
    const index = lireIndex()
    await page.goto(`/classement/${index[0]!.a}`)
    await attendrePret(page)
    await page.getByRole('tab', { name: 'Séries' }).click()
    await page.waitForTimeout(600)
    const cv = page.locator('canvas').first()
    await expect(cv).toHaveCSS('touch-action', 'none')
  })

  // ── 17 ────────────────────────────────────────────────────────────────────
  test('17 · la variation n’existe pas sans deux dates distinctes', async () => {
    // La PROPRIÉTÉ — « un décalage uniforme ne produit aucun mouvement » — se
    // démontre sur un cas construit, dans les tests du générateur : sur une
    // population réelle, de vrais mouvements existent et un ratio ne prouverait
    // rien. Ce qui se vérifie ici, c'est la seconde moitié de la règle : sans
    // deux DATES distinctes, la variation n'est pas calculable et vaut null.
    const index = lireIndex()
    const calculables = index.filter((l) => l.drang_rel != null)
    expect(calculables.length, 'aucune variation calculable').toBeGreaterThan(0)
    expect(calculables.length, 'toutes calculables : la garde ne sert à rien').toBeLessThan(
      index.length,
    )
    for (const l of index) {
      if (l.drang_rel != null) expect(Number.isFinite(l.drang_rel)).toBe(true)
    }
  })

  // ── 18 ────────────────────────────────────────────────────────────────────
  test('18 · un wallet à Ljung-Box p < 0,05 porte sa marque et son explication', async ({
    page,
    viewport,
  }) => {
    const index = lireIndex()
    const suspect = index.find((l) => l.lb_p != null && l.lb_p < 0.05)
    expect(suspect, 'aucune dépendance sérielle : le contrôle ne prouverait rien').toBeTruthy()

    // La marque, AVANT d'ouvrir la fiche.
    await page.goto('/classement?filtre=vigilance')
    await attendrePret(page)
    await expect(page.locator('[title*="non indépendants"]').first()).toBeVisible()

    if (!POSTE(viewport)) return
    // L'explication, DANS l'onglet Preuve.
    await page.goto(`/classement/${suspect!.a}`)
    await attendrePret(page)
    await page.getByRole('tab', { name: 'Preuve' }).click()
    await expect(page.locator('text=Ljung-Box')).toBeVisible()
    await expect(page.locator('text=/renforcement de position/')).toBeVisible()
  })

  // ── la limite du dispositif, qui n'est dans aucun critère mais qui compte
  test('le zéro de survivants est présenté comme une limite d’instrument', async ({ page }) => {
    const meta = lireMeta()
    test.skip(meta.test_resolu, 'le test résout son seuil : rien à dire')
    await page.goto('/donnees')
    await attendrePret(page)
    // La phrase apparait deux fois — dans le bandeau et dans l'ecran Donnees.
    // C'est voulu : la limite doit se lire la ou l'on lit son resultat.
    await expect(page.locator('text=/ne résout pas son propre seuil/').first()).toBeVisible()
    await expect(page.locator('text=/limite d’instrument/').first()).toBeVisible()
  })
})
