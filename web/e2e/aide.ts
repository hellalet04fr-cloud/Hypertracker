/**
 * Utilitaires de test. Les données sont lues sur DISQUE, jamais reconstruites :
 * un contrôle qui compare l'écran à sa propre idée des données ne compare rien.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import type { Page, ViewportSize } from '@playwright/test'
import type { Ligne, Meta } from '../src/domain/types'

const ICI = dirname(fileURLToPath(import.meta.url))
const DATA = join(ICI, '..', 'public', 'data')

export const lireMeta = (): Meta => JSON.parse(readFileSync(join(DATA, 'meta.json'), 'utf8')) as Meta
export const lireIndex = (): Ligne[] =>
  JSON.parse(readFileSync(join(DATA, 'index.json'), 'utf8')) as Ligne[]

/** Le seuil de bascule est celui de `useLayout`, pas une valeur devinée ici. */
export const SEUIL_POSTE = 1024
export const POSTE = (v: ViewportSize | null): boolean => (v?.width ?? 0) >= SEUIL_POSTE

/**
 * Attend que les données soient là. Le squelette porte `aria-busy` : l'attendre
 * plutôt qu'un délai fixe évite les tests qui passent sur une machine rapide et
 * échouent sur une lente.
 */
export async function attendrePret(page: Page): Promise<void> {
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), null, {
    timeout: 20_000,
  })
  await page.waitForTimeout(150)
}
