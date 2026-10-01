import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Phase 2 review screenshots of Admin settings against the MSW mock (not a
 * regression test): Users (list, sheet, add), Groups (list, a group with a
 * mapping test result), Sign-in (SSO) and the Audit log.
 *   SCREENSHOTS=1 npx playwright test admin-screenshots   # → ../docs/screenshots/phase-2/mock/
 *   SCREENSHOT_DIR=… to write elsewhere
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 (npm run screenshots) to capture')
test.use({ signedInAs: USERS.priya })

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-2/mock')
if (process.env.SCREENSHOTS) mkdirSync(outDir, { recursive: true })

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844 },
} as const

interface Shot {
  name: string
  url: string
  heading: string
  open?: (page: Page) => Promise<void>
}

const SHOTS: Shot[] = [
  { name: 'admin-users', url: '/settings/users', heading: 'Users' },
  { name: 'admin-user-sheet', url: `/settings/users/${USERS.bob}`, heading: 'Bob Chen' },
  {
    name: 'admin-add-user',
    url: '/settings/users',
    heading: 'Users',
    open: async (page) => {
      await page.getByRole('button', { name: 'Add user' }).click()
      const dialog = page.getByRole('dialog', { name: 'Add user' })
      await dialog.getByRole('textbox', { name: 'Email' }).fill('nia.lee@example.com')
      await dialog.getByRole('textbox', { name: 'Name' }).fill('Nia Lee')
      await dialog.getByLabel('External ID 1', { exact: true }).fill('E1042')
    },
  },
  { name: 'admin-groups', url: '/settings/groups', heading: 'Groups' },
  {
    name: 'admin-group-test-mapping',
    url: '/settings/groups/90000000-0000-4000-8000-000000000003',
    heading: 'Tools members',
    open: async (page) => {
      await page.getByRole('button', { name: 'Test mapping' }).click()
      const box = page.getByRole('dialog', { name: 'Test mapping' })
      await box
        .getByRole('textbox', { name: 'Claims' })
        .fill(JSON.stringify({ sub: 'k-2', groups: ['/innovation/members', '/viewers'] }, null, 2))
      await box.getByRole('combobox', { name: /Person/ }).click()
      await page.getByPlaceholder('Search by name or email…').fill('bob')
      await page.getByRole('option', { name: /Bob Chen/ }).click()
      await box.getByRole('button', { name: 'Test mapping' }).click()
      const result = box.getByRole('region', { name: 'Test result' })
      await expect(result).toBeVisible()
    },
  },
  { name: 'admin-sso', url: '/settings/sso', heading: 'Sign-in (SSO)' },
  {
    name: 'admin-audit',
    url: '/settings/audit',
    heading: 'Audit log',
    open: async (page) => {
      await page.getByRole('button', { name: 'Details' }).nth(2).click()
    },
  },
]

const VARIANTS = [
  ['1440-light', 'desktop', 'light'],
  ['1440-dark', 'desktop', 'dark'],
  ['390-mobile-light', 'phone', 'light'],
] as const

for (const shot of SHOTS) {
  for (const [suffix, viewport, colorScheme] of VARIANTS) {
    test(`${shot.name}-${suffix}`, async ({ page }) => {
      await page.emulateMedia({ colorScheme })
      await page.setViewportSize(VIEWPORTS[viewport])
      await page.goto(shot.url)
      await expect(page.getByRole('heading', { level: 2, name: shot.heading })).toBeVisible()
      await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
      await shot.open?.(page)
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(400)
      await page.screenshot({ path: path.join(outDir, `${shot.name}-${suffix}.png`) })
    })
  }
}
