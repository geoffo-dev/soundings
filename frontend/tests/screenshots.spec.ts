import { mkdirSync } from 'node:fs'
import path from 'node:path'

import { expect, test, type Page } from '@playwright/test'

/**
 * Captures review screenshots (not a regression test). Run with:
 *   npm run screenshots            # → ../docs/screenshots/phase-0/
 *   SCREENSHOT_DIR=… npm run screenshots
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 (npm run screenshots) to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-0')
mkdirSync(outDir, { recursive: true })

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  // Let enter animations finish.
  await page.waitForTimeout(400)
}

const shots = [
  { name: 'design-1440-light', path: '/design', width: 1440, height: 900, colorScheme: 'light' },
  { name: 'design-1440-dark', path: '/design', width: 1440, height: 900, colorScheme: 'dark' },
  {
    name: 'design-390-mobile-light',
    path: '/design',
    width: 390,
    height: 844,
    colorScheme: 'light',
  },
  { name: 'home-1440-light', path: '/', width: 1440, height: 900, colorScheme: 'light' },
  { name: 'home-1440-dark', path: '/', width: 1440, height: 900, colorScheme: 'dark' },
  { name: 'home-390-mobile-light', path: '/', width: 390, height: 844, colorScheme: 'light' },
] as const

for (const shot of shots) {
  test(shot.name, async ({ page }) => {
    await page.emulateMedia({ colorScheme: shot.colorScheme })
    await page.setViewportSize({ width: shot.width, height: shot.height })
    await page.goto(shot.path)
    await expect(page.locator('h1').first()).toBeVisible()
    if (shot.path === '/design') {
      await expect(
        page
          .frameLocator('iframe[title="App shell preview"]')
          .getByRole('heading', { name: 'My work' }),
      ).toBeVisible()
    }
    await settle(page)
    await page.screenshot({ path: path.join(outDir, `${shot.name}.png`), fullPage: true })
  })
}

test('overlays-1440-light', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/design#overlays')
  await page.locator('#overlays').getByRole('button', { name: 'Evaluate' }).click()
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'evaluate-sheet-1440-light.png') })
  await page.keyboard.press('Escape')
  await page.keyboard.press('ControlOrMeta+k')
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'command-palette-1440-light.png') })
})

test('evaluate-sheet-390-mobile-dark', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/design#overlays')
  await page.locator('#overlays').getByRole('button', { name: 'Evaluate' }).click()
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'evaluate-sheet-390-mobile-dark.png') })
})
