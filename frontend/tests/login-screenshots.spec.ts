import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test } from './support'

/** The break-glass admin (src/mocks/db.ts USERS.breakGlass). */
const BREAK_GLASS = '10000000-0000-4000-8000-00000000000e'

/**
 * Phase 2 review screenshots against the MSW mock (not a regression test): the
 * sign-in page variants, the break-glass banner and the Members tab with groups.
 *   SCREENSHOTS=1 npx playwright test login-screenshots   # → ../docs/screenshots/phase-2/mock/
 *   SCREENSHOT_DIR=… to write elsewhere
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 (npm run screenshots) to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-2/mock')
if (process.env.SCREENSHOTS) mkdirSync(outDir, { recursive: true })

async function capture(page: Page, name: string, fullPage = false) {
  await page.evaluate(() => document.fonts.ready)
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage })
}

async function configure(page: Page, auth: string) {
  await page.addInitScript((value) => localStorage.setItem('soundings-mock-auth', value), auth)
}

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844 },
} as const

test.describe('signed out', () => {
  test.use({ signedInAs: null })

  const variants = [
    ['login-sso-dev-1440-light', 'sso,dev_login', '/login', 'desktop', 'light'],
    ['login-sso-1440-dark', 'sso', '/login?expired=1', 'desktop', 'dark'],
    ['login-error-no-account-1440-light', 'sso', '/login?error=no_account', 'desktop', 'light'],
    ['login-error-390-mobile-dark', 'sso', '/login?error=identity_conflict', 'phone', 'dark'],
    ['login-signed-out-390-mobile-light', 'sso,dev_login', '/login?signed_out=1', 'phone', 'light'],
    ['login-break-glass-1440-light', 'break_glass', '/login', 'desktop', 'light'],
    ['login-break-glass-390-mobile-dark', 'break_glass,dev_login', '/login', 'phone', 'dark'],
    ['login-not-configured-1440-light', 'none', '/login', 'desktop', 'light'],
  ] as const

  for (const [name, auth, url, viewport, colorScheme] of variants) {
    test(name, async ({ page }) => {
      await configure(page, auth)
      await page.emulateMedia({ colorScheme })
      await page.setViewportSize(VIEWPORTS[viewport])
      await page.goto(url)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await capture(page, name)
    })
  }

  test('login-break-glass-errors-1440-dark', async ({ page }) => {
    await configure(page, 'break_glass')
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.setViewportSize(VIEWPORTS.desktop)
    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Username' }).fill('break-glass')
    await page.getByLabel('Password', { exact: true }).fill('wrong')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('alert')).toBeVisible()
    await capture(page, 'login-break-glass-errors-1440-dark')
  })
})

test.describe('break-glass session', () => {
  test.use({ signedInAs: BREAK_GLASS })

  for (const [viewport, colorScheme] of [
    ['desktop', 'light'],
    ['phone', 'dark'],
  ] as const) {
    test(`break-glass-banner-${viewport}-${colorScheme}`, async ({ page, context, baseURL }) => {
      await configure(page, 'break_glass')
      await context.addCookies([
        { name: 'soundings_mock_auth_method', value: 'break_glass', url: baseURL },
      ])
      await page.emulateMedia({ colorScheme })
      await page.setViewportSize(VIEWPORTS[viewport])
      await page.goto('/')
      await expect(page.getByText('Signed in with the break-glass account.')).toBeVisible()
      await capture(
        page,
        `break-glass-banner-${viewport === 'desktop' ? 1440 : 390}-${colorScheme}`,
      )
    })
  }
})

for (const [name, slug, viewport, colorScheme] of [
  ['members-groups-1440-light', 'internal-tools', 'desktop', 'light'],
  ['members-groups-1440-dark', 'internal-tools', 'desktop', 'dark'],
  ['members-groups-390-mobile-light', 'internal-tools', 'phone', 'light'],
  ['members-read-only-1440-light', 'customer-innovation', 'desktop', 'light'],
] as const) {
  test(name, async ({ page }) => {
    await page.emulateMedia({ colorScheme })
    await page.setViewportSize({ ...VIEWPORTS[viewport], height: 2000 })
    await page.goto(`/p/${slug}/settings?tab=members`)
    await page.getByRole('button', { name: /^Everyone with access/ }).click()
    await expect(page.getByRole('list', { name: 'Everyone with access' })).toBeVisible()
    await capture(page, name)
  })
}

test('members-add-group-1440-light', async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop)
  await page.goto('/p/internal-tools/settings?tab=members')
  await page.getByRole('radio', { name: 'Group' }).click()
  await page.getByRole('combobox', { name: 'Add a group' }).click()
  await expect(page.getByRole('option', { name: /Contractors/ })).toBeVisible()
  await capture(page, 'members-add-group-1440-light')
})
