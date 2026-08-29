/**
 * ACCESSIBILITÉ VÉRIFIABLE, PAS DÉCLARATIVE.
 *
 * Deux audits parcourent le DOM RENDU et échouent en dessous du seuil. Chacun
 * porte une SENTINELLE : il injecte lui-même le défaut d'origine et refuse de
 * rendre son verdict s'il ne le détecte pas. Un audit de contraste écrit dans
 * une session précédente passait du premier coup — parce qu'une classe de
 * caractères mal échappée l'empêchait de lire une seule couleur. Un contrôle
 * qui ne peut pas échouer ne prouve rien.
 */
import { expect, test } from '@playwright/test'
import { POSTE, attendrePret, lireIndex } from './aide'

const AUDIT_CONTRASTE = `(() => {
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4) }
  const L = ([r,g,b]) => 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b)
  const rgb = (s) => { const m = String(s).match(/[0-9.]+/g); return m ? m.slice(0,3).map(Number) : null }
  const alpha = (s) => { const m = String(s).match(/[0-9.]+/g); return m && m.length > 3 ? +m[3] : 1 }
  const melange = (fg, bg, a) => fg.map((v,i) => v*a + bg[i]*(1-a))
  const fondDe = (el) => {
    let n = el
    while (n && n !== document.documentElement) {
      const st = getComputedStyle(n), c = rgb(st.backgroundColor)
      if (c && alpha(st.backgroundColor) > 0.9) return c
      n = n.parentElement
    }
    return rgb(getComputedStyle(document.body).backgroundColor) || [0,0,0]
  }
  const ratio = (a, b) => { const la = L(a), lb = L(b)
    return (Math.max(la,lb) + 0.05) / (Math.min(la,lb) + 0.05) }
  const mauvais = []
  document.querySelectorAll('*').forEach((el) => {
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || +st.opacity === 0 || st.display === 'none') return
    if (!el.getClientRects().length) return
    const propre = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
    if (!propre) return
    const fg = rgb(st.color)
    if (!fg || alpha(st.color) < 0.05) return
    const bg = fondDe(el)
    const px = parseFloat(st.fontSize), gras = +st.fontWeight >= 600
    const seuil = (px >= 24 || (px >= 18.66 && gras)) ? 3 : 4.5
    const r = ratio(alpha(st.color) < 1 ? melange(fg, bg, alpha(st.color)) : fg, bg)
    if (r < seuil - 0.005) mauvais.push({
      t: el.tagName.toLowerCase() + '.' + String(el.className || '').split(' ')[0],
      px: Math.round(px*10)/10, r: Math.round(r*100)/100, seuil,
      txt: (el.textContent || '').trim().slice(0, 26) })
  })
  return mauvais
})()`

/**
 * La cible est la surface qu'on VISE, pas celle qu'on voit : un pseudo-element
 * peut etendre la prise au-dela du dessin sans toucher a la mise en page. On
 * mesure donc la boite du controle ELARGIE de ses pseudo-elements, en lisant
 * leur `inset` negatif — sinon l'audit condamnerait une technique correcte.
 */
const AUDIT_CIBLES = (min: number) => `[...document.querySelectorAll(
    'button, input, select, [role="button"], a[href]')]
  .filter((e) => {
    const st = getComputedStyle(e)
    if (st.visibility === 'hidden' || st.display === 'none') return false
    const r = e.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return false
    let h = r.height, w = r.width
    for (const p of ['::before', '::after']) {
      const ps = getComputedStyle(e, p)
      if (ps.content === 'none') continue
      const t = parseFloat(ps.top) || 0, b = parseFloat(ps.bottom) || 0
      const l = parseFloat(ps.left) || 0, rr = parseFloat(ps.right) || 0
      if (ps.position === 'absolute') {
        h = Math.max(h, r.height - t - b)
        w = Math.max(w, r.width - l - rr)
      }
    }
    return h < ${min} - 0.5 || w < ${min} - 0.5
  })
  .map((e) => {
    const r = e.getBoundingClientRect()
    return e.tagName.toLowerCase() + '.' + String(e.className||'').split(' ')[0]
      + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)
  })`

test.describe('Accessibilité', () => {
  test('l’audit de contraste sait détecter un texte fautif', async ({ page }) => {
    await page.goto('/')
    await attendrePret(page)
    // #4C5D6B portait la moitié du texte de la version précédente, à 2,84:1.
    const trouve = await page.evaluate(`(() => {
      const d = document.createElement('div')
      d.style.cssText = 'color:#4C5D6B;font-size:11px;position:fixed;top:0;left:0;z-index:9999'
      d.textContent = 'sentinelle'
      document.body.appendChild(d)
      const r = ${AUDIT_CONTRASTE}.filter((x) => x.txt === 'sentinelle').length
      d.remove()
      return r
    })()`)
    expect(trouve, 'la sentinelle à 2,84:1 est passée inaperçue : audit inopérant').toBe(1)
  })

  for (const route of ['/', '/classement', '/donnees']) {
    test(`contraste AA sur ${route}`, async ({ page }) => {
      await page.goto(route)
      await attendrePret(page)
      const m = (await page.evaluate(AUDIT_CONTRASTE)) as Array<Record<string, unknown>>
      expect(
        m.slice(0, 5).map((x) => `${x['t']} ${x['px']}px ${x['r']}:1 < ${x['seuil']} « ${x['txt']} »`),
      ).toEqual([])
    })
  }

  test('contraste AA sur la fiche, onglet Preuve ouvert', async ({ page, viewport }) => {
    test.skip(!POSTE(viewport), 'onglets de l’inspecteur')
    const index = lireIndex()
    await page.goto(`/classement/${index[0]!.a}`)
    await attendrePret(page)
    await page.getByRole('tab', { name: 'Preuve' }).click()
    await page.waitForTimeout(600)
    const m = (await page.evaluate(AUDIT_CONTRASTE)) as Array<Record<string, unknown>>
    expect(m.slice(0, 5).map((x) => `${x['t']} ${x['r']}:1 « ${x['txt']} »`)).toEqual([])
  })

  test('l’audit de cibles sait détecter une cible trop petite', async ({ page }) => {
    await page.goto('/classement')
    await attendrePret(page)
    const trouve = await page.evaluate(`(() => {
      const b = document.createElement('button')
      b.style.cssText = 'width:20px;height:20px;position:fixed;top:0;left:0;z-index:9999'
      b.className = 'sentinelle'
      document.body.appendChild(b)
      const r = ${AUDIT_CIBLES(44)}.filter((x) => x.includes('sentinelle')).length
      b.remove()
      return r
    })()`)
    expect(trouve, 'la cible de 20 px est passée inaperçue : audit inopérant').toBe(1)
  })

  for (const route of ['/', '/classement']) {
    test(`cibles tactiles sur ${route}`, async ({ page, viewport }) => {
      await page.goto(route)
      await attendrePret(page)
      // 44 px au doigt, 32 à la souris : ce ne sont pas les mêmes usages.
      const min = POSTE(viewport) ? 32 : 44
      const c = (await page.evaluate(AUDIT_CIBLES(min))) as string[]
      expect([...new Set(c)].slice(0, 6)).toEqual([])
    })
  }

  test('le libellé vit sur l’élément focusable, jamais sur le conteneur de ligne', async ({
    page,
    viewport,
  }) => {
    await page.goto('/classement')
    await attendrePret(page)
    if (POSTE(viewport)) {
      // Un aria-label sur la ligne REMPLACE son contenu pour un lecteur
      // d'écran : le nombre de trades, l'activité et la description du rail
      // deviendraient invisibles.
      const fautes = await page.evaluate(
        () => [...document.querySelectorAll('[role="row"]')].filter((r) => r.hasAttribute('aria-label')).length,
      )
      expect(fautes).toBe(0)
    }
    const decrits = await page.evaluate(
      () =>
        [...document.querySelectorAll('a[aria-label], button[aria-label]')].filter((e) =>
          /Ouvrir/i.test(e.getAttribute('aria-label') ?? ''),
        ).length,
    )
    expect(decrits, 'aucun élément focusable ne porte le libellé d’ouverture').toBeGreaterThan(0)
  })

  test('le rail porte les trois canaux en mots', async ({ page }) => {
    await page.goto('/classement')
    await attendrePret(page)
    const labels = await page.evaluate(() =>
      [...document.querySelectorAll('svg[role="img"], a[aria-label], button[aria-label]')]
        .map((e) => e.getAttribute('aria-label') ?? '')
        .filter((t) => /Score/i.test(t)),
    )
    expect(labels.length).toBeGreaterThan(0)
    expect(labels[0]).toMatch(/Intervalle/i)
    expect(labels[0]).toMatch(/Qualité/i)
  })

  test('le focus est visible sur tout élément atteignable', async ({ page }) => {
    await page.goto('/classement')
    await attendrePret(page)
    // Plusieurs tabulations, et on NOMME le fautif : un contrôle qui dit
    // seulement « faux » oblige à refaire son travail à la main.
    const sansAnneau: string[] = []
    for (let k = 0; k < 12; k++) {
      await page.keyboard.press('Tab')
      const r = await page.evaluate(() => {
        const e = document.activeElement as HTMLElement | null
        if (!e || e === document.body) return null
        const st = getComputedStyle(e)
        const anneau =
          (st.outlineStyle !== 'none' && parseFloat(st.outlineWidth) > 0) || st.boxShadow !== 'none'
        return anneau
          ? null
          : `${e.tagName.toLowerCase()}.${String(e.className || '').split(' ')[0]}`
      })
      if (r) sansAnneau.push(r)
    }
    expect([...new Set(sansAnneau)]).toEqual([])
  })

  test('15 · parcours complet au clavier des quatre écrans', async ({ page, viewport }) => {
    test.skip(!POSTE(viewport), 'raccourcis du poste de travail')
    await page.goto('/classement')
    await attendrePret(page)

    // Sélection, puis déplacement, puis épingle, puis ouverture — sans souris.
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('j')
    await page.waitForTimeout(200)
    const selection = await page.evaluate(
      () => document.querySelector('[aria-selected="true"]')?.textContent ?? '',
    )
    expect(selection.length, 'aucune ligne sélectionnée au clavier').toBeGreaterThan(0)

    await page.keyboard.press('/')
    await page.waitForTimeout(150)
    expect(await page.evaluate(() => document.activeElement?.id)).toBe('recherche')
    await page.keyboard.press('Escape')

    await page.keyboard.press('Enter')
    await page.waitForTimeout(600)
    await expect(page).toHaveURL(/\/classement\/0x/)

    for (const [k, nom] of [['2', 'Preuve'], ['3', 'Séries'], ['4', 'Cycle de vie']] as const) {
      await page.keyboard.press(k)
      await page.waitForTimeout(250)
      await expect(page.getByRole('tab', { name: nom, selected: true })).toBeVisible()
    }

    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
    await expect(page).toHaveURL(/\/classement$/)
  })
})
