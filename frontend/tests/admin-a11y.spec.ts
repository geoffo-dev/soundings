import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Admin settings: no serious or critical axe violations in light and dark, and
 * every page fits a 390px phone without sideways scrolling. Platform admin:
 * Priya Natarajan.
 */

test.use({ signedInAs: USERS.priya })

const PAGES: { path: string; heading: string; open?: (page: Page) => Promise<void> }[] = [
  { path: '/settings/users', heading: 'Users' },
  {
    path: `/settings/users/${USERS.bob}`,
    // The sheet's title (the list behind it is hidden from assistive tech while it is open).
    heading: 'Bob Chen',
    open: async (page) => {
      await expect(page.getByRole('dialog', { name: /Bob Chen/ })).toBeVisible()
    },
  },
  {
    path: '/settings/users',
    heading: 'Users',
    open: async (page) => {
      await page.getByRole('button', { name: 'Add user' }).click()
      await page
        .getByRole('dialog', { name: 'Add user' })
        .getByRole('button', { name: /^Add user/ })
        .click()
      await expect(page.getByText('Enter their name')).toBeVisible()
    },
  },
  { path: '/settings/groups', heading: 'Groups' },
  {
    path: '/settings/groups/90000000-0000-4000-8000-000000000003',
    heading: 'Tools members',
    open: async (page) => {
      await page.getByRole('button', { name: 'Test mapping' }).click()
      const box = page.getByRole('dialog', { name: 'Test mapping' })
      await box
        .getByRole('textbox', { name: 'Claims' })
        .fill('{"groups": ["/innovation/members", "/viewers"]}')
      await box.getByRole('button', { name: 'Test mapping' }).click()
      await expect(box.getByRole('region', { name: 'Test result' })).toBeVisible()
    },
  },
  { path: '/settings/sso', heading: 'Sign-in (SSO)' },
  {
    // Before SSO is configured: the three-step setup checklist instead of the rules.
    path: '/settings/sso',
    heading: 'Sign-in (SSO)',
    open: async (page) => {
      await page.evaluate(() => localStorage.setItem('soundings-mock-auth', 'break_glass'))
      await page.reload()
      await expect(page.getByRole('heading', { name: 'Set up single sign-on' })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Finding the account' })).toHaveCount(0)
    },
  },
  {
    path: '/settings/audit',
    heading: 'Audit log',
    open: async (page) => {
      await page.getByRole('button', { name: 'Details' }).first().click()
    },
  },
]

async function visit(page: Page, target: (typeof PAGES)[number]) {
  await page.goto(target.path)
  await expect(page.getByRole('heading', { level: 2, name: target.heading })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
  await target.open?.(page)
  // Let open/close animations settle before axe reads colours.
  await page.waitForTimeout(300)
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme })
    for (const target of PAGES) {
      const label = `${target.path}${target.open ? ' (open)' : ''}`
      test(`${label} has no serious accessibility violations`, async ({ page }) => {
        await visit(page, target)
        expect(await seriousViolations(page)).toEqual([])
      })
    }
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  for (const target of PAGES) {
    test(`${target.path}${target.open ? ' (open)' : ''} fits without sideways scrolling`, async ({
      page,
    }) => {
      await visit(page, target)
      const overflow = await page.evaluate(() => {
        const main = document.getElementById('main')
        return {
          page: document.documentElement.scrollWidth - window.innerWidth,
          main: main ? main.scrollWidth - main.clientWidth : 0,
        }
      })
      expect(overflow.page).toBeLessThanOrEqual(0)
      expect(overflow.main).toBeLessThanOrEqual(0)
    })
  }

  test('the section row scrolls and the users list becomes cards', async ({ page }) => {
    await visit(page, { path: '/settings/users', heading: 'Users' })
    const nav = page.getByRole('navigation', { name: 'Settings sections' })
    await nav.getByRole('link', { name: 'Audit log' }).scrollIntoViewIfNeeded()
    await nav.getByRole('link', { name: 'Audit log' }).click()
    await expect(page.getByRole('heading', { level: 2, name: 'Audit log' })).toBeVisible()
    await page.goto('/settings/users')
    // Cards: one meta line under the name (no repeated column names); the header is for
    // screen readers.
    const row = page.getByRole('row').filter({ hasText: 'Bob Chen' })
    await expect(row.getByText('SSO linked', { exact: true })).toBeVisible()
    await expect(row.getByText('Linked', { exact: true })).toBeHidden()
    await expect(row.getByText('SSO account')).toHaveCount(0)
  })
})
