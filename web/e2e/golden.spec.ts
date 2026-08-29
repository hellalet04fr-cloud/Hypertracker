/**
 * GOLDEN FILES — pour que la densité ne dérive pas à chaque commit.
 *
 * Quatre largeurs, deux compositions. Ces captures ne jugent pas le goût :
 * elles constatent qu'un espacement, une hauteur de ligne ou un alignement
 * n'ont pas bougé sans qu'on le décide.
 *
 * Les canvas sont masqués : leur contenu dépend du sous-pixel et du moteur de
 * rendu, et une différence d'un pixel dans une courbe n'est pas une dérive de
 * densité. Ce qu'on fige, c'est la CHARPENTE.
 */
import { expect, test } from '@playwright/test'
import { attendrePret, lireIndex } from './aide'

const FIGER = `
  /* Le temps relatif et le décodage sont mesurés à l'exécution : les figer
     évite un golden file qui échoue une heure plus tard sans raison. */
  [class*="age"], [class*="pousse"] { visibility: hidden !important; }
  canvas { visibility: hidden !important; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
`

test.describe('Golden files', () => {
  test('accueil', async ({ page }, info) => {
    await page.goto('/')
    await attendrePret(page)
    await page.addStyleTag({ content: FIGER })
    await expect(page).toHaveScreenshot(`accueil-${info.project.name}.png`, { fullPage: false })
  })

  test('classement', async ({ page }, info) => {
    await page.goto('/classement')
    await attendrePret(page)
    await page.addStyleTag({ content: FIGER })
    await expect(page).toHaveScreenshot(`classement-${info.project.name}.png`, { fullPage: false })
  })

  test('fiche', async ({ page }, info) => {
    const index = lireIndex()
    await page.goto(`/classement/${index[0]!.a}`)
    await attendrePret(page)
    await page.addStyleTag({ content: FIGER })
    await expect(page).toHaveScreenshot(`fiche-${info.project.name}.png`, { fullPage: false })
  })

  test('donnees', async ({ page }, info) => {
    await page.goto('/donnees')
    await attendrePret(page)
    await page.addStyleTag({ content: FIGER })
    await expect(page).toHaveScreenshot(`donnees-${info.project.name}.png`, { fullPage: false })
  })
})
