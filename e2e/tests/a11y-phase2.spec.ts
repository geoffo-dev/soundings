import type { Page } from '@playwright/test'

import { Api, userOf } from './support/api'
import { expect, seriousViolations, settled, signIn, test } from './support/fixtures'

/**
 * axe (WCAG 2.2 AA rules) on the Phase 2 screens against the real app and the seeded data
 * (its five groups, Alice as platform admin), light and dark: no serious or critical
 * violations. Then every admin page at 390 px: no sideways scrolling. Read-only, except
 * that nothing is saved by any of these steps. Test plan: A11Y2-* and MO2-*.
 */

interface Screen {
  name: string
  signedIn: boolean
  open: (page: Page) => Promise<void>
}

const h2 = (page: Page, name: string | RegExp) => page.getByRole('heading', { level: 2, name })

async function seededGroupId(baseURL: string, name: string): Promise<string> {
  const alice = await Api.as(baseURL, 'alice')
  try {
    return (await alice.groupByName(name)).id
  } finally {
    await alice.dispose()
  }
}

const baseURL = () => test.info().project.use.baseURL ?? ''

const SCREENS: Screen[] = [
  {
    name: 'login with an error',
    signedIn: false,
    open: async (page) => {
      await page.goto('/login?error=no_account')
      await expect(page.locator('main').getByRole('alert')).toBeVisible()
      await settled(page)
    },
  },
  {
    name: 'login after signing out',
    signedIn: false,
    open: async (page) => {
      await page.goto('/login?signed_out=1')
      await expect(page.getByText('You’re signed out.')).toBeVisible()
      await settled(page)
    },
  },
  {
    name: 'settings: users',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/users')
      await expect(h2(page, 'Users')).toBeVisible()
      await expect(page.getByRole('table', { name: 'Users' }).getByRole('row').nth(1)).toBeVisible()
    },
  },
  {
    name: 'settings: user detail',
    signedIn: true,
    open: async (page) => {
      const carol = await userOf(baseURL(), 'carol')
      await page.goto(`/settings/users/${carol.id}`)
      await expect(page.getByRole('dialog', { name: /Carol Chen/ })).toBeVisible()
      await settled(page)
    },
  },
  {
    name: 'settings: add user',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/users')
      await page.getByRole('button', { name: 'Add user' }).click()
      const dialog = page.getByRole('dialog', { name: 'Add user' })
      // With the inline errors showing.
      await dialog.getByRole('button', { name: /^Add user/ }).click()
      await expect(dialog.getByText('Enter an email address')).toBeVisible()
    },
  },
  {
    name: 'settings: groups',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/groups')
      await expect(
        page.getByRole('table', { name: 'Groups' }).getByRole('row').nth(1),
      ).toBeVisible()
    },
  },
  {
    name: 'settings: group detail with a test mapping result',
    signedIn: true,
    open: async (page) => {
      const id = await seededGroupId(baseURL(), 'Tools team')
      await page.goto(`/settings/groups/${id}`)
      await expect(h2(page, 'Tools team')).toBeVisible()
      await settled(page)
      const box = page.getByRole('region', { name: 'Test mapping' })
      await box
        .getByRole('textbox', { name: 'Claims' })
        .fill('{ "groups": ["/tools/members", "/viewers", 42] }')
      await box.getByRole('button', { name: 'Test mapping' }).click()
      await expect(box.getByRole('region', { name: 'Test result' })).toBeVisible()
    },
  },
  {
    name: 'settings: sign-in (SSO)',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/sso')
      await expect(h2(page, 'Sign-in (SSO)')).toBeVisible()
      await settled(page)
    },
  },
  {
    name: 'settings: audit log with details open',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/audit')
      await expect(h2(page, 'Audit log')).toBeVisible()
      await settled(page)
      await page.getByRole('button', { name: 'Details' }).first().click()
    },
  },
  {
    name: 'project settings: members with groups',
    signedIn: true,
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=members')
      await expect(page.getByRole('list', { name: 'Everyone with access' })).toBeVisible()
      await settled(page)
      await page.getByRole('radio', { name: 'Group' }).click()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y2: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        if (screen.signedIn) await signIn(page, 'alice')
        await screen.open(page)
        await expect(page.locator('html')).toHaveClass(
          colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
        )
        // Let enter animations finish so axe sees final colours.
        await page.waitForTimeout(300)
        expect(await seriousViolations(page)).toEqual([])
      })
    }
  })
}

test.describe('on a phone (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('MO2-01: the sign-in page and every admin page fit without sideways scrolling', async ({
    page,
  }) => {
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      await test.step(screen.name, async () => {
        await page.context().clearCookies()
        if (screen.signedIn) await signIn(page, 'alice')
        await screen.open(page)
        await page.waitForTimeout(200)
        expect(await overflow(), screen.name).toBe(0)
      })
    }
  })
})
