import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test } from './support'

/**
 * Captures review screenshots against the MSW mock (not a regression test). Run with:
 *   npm run screenshots            # all *screenshots.spec.ts → ../docs/screenshots/phase-1/mock/
 *   SCREENSHOT_DIR=… npm run screenshots
 * The real-stack review set is e2e/'s (`npm --prefix e2e run screenshots`), written
 * to ../docs/screenshots/phase-1/ itself; the names overlap, so keep them apart.
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 (npm run screenshots) to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-1/mock')
// Only when capturing: loading a skipped file must not create folders.
if (process.env.SCREENSHOTS) mkdirSync(outDir, { recursive: true })

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  // Let enter animations finish.
  await page.waitForTimeout(400)
}

const shots = [
  { name: 'my-work-1440-light', path: '/', width: 1440, height: 900, colorScheme: 'light' },
  { name: 'my-work-1440-dark', path: '/', width: 1440, height: 900, colorScheme: 'dark' },
  { name: 'my-work-390-mobile-light', path: '/', width: 390, height: 844, colorScheme: 'light' },
  { name: 'design-1440-light', path: '/design', width: 1440, height: 900, colorScheme: 'light' },
  { name: 'design-1440-dark', path: '/design', width: 1440, height: 900, colorScheme: 'dark' },
] as const

for (const shot of shots) {
  test(shot.name, async ({ page }) => {
    await page.emulateMedia({ colorScheme: shot.colorScheme })
    await page.setViewportSize({ width: shot.width, height: shot.height })
    await page.goto(shot.path)
    await expect(page.locator('h1').first()).toBeVisible()
    await settle(page)
    await page.screenshot({ path: path.join(outDir, `${shot.name}.png`), fullPage: true })
  })
}

test.describe('signed out', () => {
  test.use({ signedInAs: null })

  for (const [name, width, height, colorScheme] of [
    ['login-1440-light', 1440, 900, 'light'],
    ['login-390-mobile-dark', 390, 844, 'dark'],
  ] as const) {
    test(name, async ({ page }) => {
      await page.emulateMedia({ colorScheme })
      await page.setViewportSize({ width, height })
      await page.goto('/login')
      await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeVisible()
      await settle(page)
      await page.screenshot({ path: path.join(outDir, `${name}.png`) })
    })
  }
})

test('overlays', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+k')
  await page.keyboard.type('return')
  await expect(page.getByRole('option', { name: /Self-serve returns portal/ })).toBeVisible()
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'command-palette-1440-light.png') })
  await page.keyboard.press('Escape')
  await page.keyboard.press('n')
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'new-idea-1440-light.png') })
})

test('new-idea-390-mobile-dark', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('n')
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'new-idea-390-mobile-dark.png') })
})
