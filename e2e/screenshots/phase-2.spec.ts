import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Browser, Cookie, Locator, Page } from '@playwright/test'

import { authConfig, userOf } from '../tests/support/api'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import { ssoSignIn, ssoSignInAs, type KeycloakUser } from '../tests/support/sso'

/**
 * Review screenshots of the Phase 2 screens from the real app: the demo data plus, with
 * SSO on, real Keycloak sign-ins first (alice, bob, carol, dave and erin link their
 * seeded accounts and sync their groups; mallory and nia are refused), so Users, Groups
 * and the Audit log show what an instance looks like after a morning of use.
 *
 * `npm run screenshots:phase2` → docs/screenshots/phase-2/<screen>-<1440-light|1440-dark|
 * 390-light>.png (`SCREENSHOT_DIR` overrides): a run with E2E_SSO=1, then one with
 * E2E_SSO=0 for the break-glass sign-in page (`@break-glass`; SSO turns it off).
 * Needs freshly seeded data and realm (the local stack resets both on start).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-2'))
mkdirSync(outDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

// One worker, one sign-in for Alice: every screenshot reuses her cookies, so the audit
// log shows the story below rather than a sign-in per screenshot.
test.describe.configure({ mode: 'serial' })

let alice: { cookies: Cookie[] } | undefined
let toolsTeamId = ''

/**
 * Alice signs in (through Keycloak when SSO is on, else the dev login); with SSO, the
 * rest of the morning follows once per stack: bob, carol, dave and erin sign in with
 * Keycloak (linked, groups synced), mallory and nia are refused.
 */
async function prepare(browser: Browser) {
  const methods = await authConfig(baseURL())
  if (!methods.sso && !methods.dev_login) return
  const context = await browser.newContext({ baseURL: baseURL() })
  const page = await context.newPage()
  if (methods.sso) await ssoSignInAs(page, 'alice')
  else await signIn(page, 'alice')
  alice = await context.storageState()

  const get = async <T>(path: string): Promise<T> => {
    const response = await page.request.get(`/api/v1${path}`)
    expect(response.status(), path).toBe(200)
    return (await response.json()) as T
  }
  const groups = await get<{ items: { id: string; name: string }[] }>('/admin/groups?q=Tools')
  toolsTeamId = groups.items.find((group) => group.name === 'Tools team')?.id ?? ''

  const carol = await userOf(baseURL(), 'carol')
  const linked = (await get<{ identities: unknown[] }>(`/admin/users/${carol.id}`)).identities
  if (methods.sso && linked.length === 0) {
    for (const user of ['bob', 'carol', 'dave', 'erin'] as const) {
      const other = await browser.newContext()
      await ssoSignInAs(await other.newPage(), user)
      await other.close()
    }
    for (const user of ['mallory', 'nia'] as KeycloakUser[]) {
      const other = await browser.newContext()
      await ssoSignIn(await other.newPage(), user)
      await other.close()
    }
  }
  await context.close()
}

/** Scrolls `heading` to the top of its scrolling container. */
async function scrollToTop(locator: Locator) {
  await locator.evaluate((element) => element.scrollIntoView({ block: 'start' }))
}

const h2 = (page: Page, name: string) => page.getByRole('heading', { level: 2, name })

interface Shot {
  name: string
  signedIn: boolean
  needs?: 'sso' | 'break_glass'
  open: (page: Page) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'login-sso',
    signedIn: false,
    needs: 'sso',
    open: async (page) => {
      await page.goto('/login')
      await expect(page.getByRole('link', { name: 'Sign in with SSO' })).toBeVisible()
      await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeVisible()
    },
  },
  {
    name: 'login-error',
    signedIn: false,
    needs: 'sso',
    open: async (page) => {
      await page.goto('/login?error=no_account&next=%2Fwork')
      await expect(page.locator('main').getByRole('alert')).toBeVisible()
      await expect(page.getByRole('link', { name: 'Sign in with SSO' })).toBeVisible()
      await expect(page.getByRole('link', { name: 'Use a different account' })).toBeVisible()
    },
  },
  {
    name: 'login-break-glass',
    signedIn: false,
    needs: 'break_glass',
    open: async (page) => {
      await page.goto('/login')
      await expect(page.getByRole('heading', { name: 'Break-glass admin' })).toBeVisible()
    },
  },
  {
    name: 'settings-users',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/users')
      await expect(h2(page, 'Users')).toBeVisible()
      await expect(page.getByRole('table', { name: 'Users' }).getByRole('row').nth(1)).toBeVisible()
    },
  },
  {
    name: 'settings-user-detail',
    signedIn: true,
    open: async (page) => {
      const carol = await userOf(baseURL(), 'carol')
      await page.goto(`/settings/users/${carol.id}`)
      await expect(page.getByRole('dialog', { name: /Carol Chen/ })).toBeVisible()
    },
  },
  {
    // The same sheet further down: the linked Keycloak account, external IDs, sessions.
    name: 'settings-user-sign-in',
    signedIn: true,
    open: async (page) => {
      const carol = await userOf(baseURL(), 'carol')
      await page.goto(`/settings/users/${carol.id}`)
      const sheet = page.getByRole('dialog', { name: /Carol Chen/ })
      await expect(sheet.getByText('Subject')).toBeVisible()
      await scrollToTop(sheet.getByRole('heading', { level: 3, name: 'Groups' }))
    },
  },
  {
    name: 'settings-add-user',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/users')
      await expect(h2(page, 'Users')).toBeVisible()
      await page.getByRole('button', { name: 'Add user' }).click()
      const dialog = page.getByRole('dialog', { name: 'Add user' })
      await dialog.getByRole('textbox', { name: 'Email' }).fill('grace.gale@example.com')
      await dialog.getByRole('textbox', { name: 'Name' }).fill('Grace Gale')
      await dialog.getByLabel('External ID 1', { exact: true }).fill('E2001')
    },
  },
  {
    name: 'settings-groups',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/groups')
      await expect(
        page.getByRole('table', { name: 'Groups' }).getByRole('row').nth(1),
      ).toBeVisible()
    },
  },
  {
    // Members first, then the identity provider mapping and the project roles.
    name: 'settings-group-detail',
    signedIn: true,
    open: async (page) => {
      await page.goto(`/settings/groups/${toolsTeamId}`)
      await expect(h2(page, 'Tools team')).toBeVisible()
      await expect(page.getByRole('button', { name: 'Test mapping' })).toBeVisible()
    },
  },
  {
    // Carol's claims without /tools/members: she would leave the managed Tools team.
    name: 'settings-test-mapping',
    signedIn: true,
    open: async (page) => {
      await page.goto(`/settings/groups/${toolsTeamId}`)
      await expect(h2(page, 'Tools team')).toBeVisible()
      await settled(page)
      await page.getByRole('button', { name: 'Test mapping' }).click()
      const box = page.getByRole('dialog', { name: 'Test mapping' })
      await box
        .getByRole('textbox', { name: 'Claims' })
        .fill(JSON.stringify({ sub: 'carol', groups: ['/innovation/members'] }, null, 2))
      await box.getByRole('combobox', { name: /Person/ }).click()
      await page.getByPlaceholder('Search by name or email…').fill('carol')
      await page.getByRole('option', { name: /Carol Chen/ }).click()
      await box.getByRole('button', { name: 'Test mapping' }).click()
      const result = box.getByRole('region', { name: 'Test result' })
      await expect(result).toBeVisible()
      await result.scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'settings-sso',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/sso')
      await expect(h2(page, 'Sign-in (SSO)')).toBeVisible()
    },
  },
  {
    name: 'settings-audit',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/audit')
      await expect(h2(page, 'Audit log')).toBeVisible()
      await expect(page.getByRole('region', { name: 'Audit entries' })).toBeVisible()
    },
  },
  {
    name: 'project-members-groups',
    signedIn: true,
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=members')
      await expect(page.getByRole('heading', { level: 3, name: 'Groups' })).toBeVisible()
      await settled(page)
      // The group with a role, the people, and (unfolded) everyone with access and why.
      const showAccess = page.getByRole('button', { name: /^Everyone with access/ })
      if ((await showAccess.getAttribute('aria-expanded')) !== 'true') await showAccess.click()
      await expect(page.getByRole('list', { name: 'Everyone with access' })).toBeVisible()
      await scrollToTop(page.getByRole('heading', { level: 3, name: 'Groups' }))
    },
  },
]

const VARIANTS = [
  {
    suffix: '1440-light',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    phone: false,
  },
  {
    suffix: '1440-dark',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    phone: false,
  },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light', phone: true },
] as const

test.beforeAll(async ({ browser }) => {
  await prepare(browser)
})

for (const variant of VARIANTS) {
  test.describe(variant.suffix, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of SHOTS) {
      const tag = shot.needs === 'break_glass' ? ['@break-glass'] : []
      test(`${shot.name}-${variant.suffix}`, { tag }, async ({ page }) => {
        const methods = await authConfig(baseURL())
        test.skip(shot.needs === 'sso' && !methods.sso, 'needs SSO (E2E_SSO=1)')
        test.skip(
          shot.needs === 'break_glass' && !methods.break_glass,
          'needs break-glass (E2E_SSO=0)',
        )
        if (shot.signedIn) {
          if (!alice) throw new Error('Alice could not sign in')
          await page.context().addCookies(alice.cookies)
        }
        await shot.open(page)
        await settled(page)
        await page.evaluate(() => document.fonts.ready)
        await page.waitForTimeout(500) // enter animations
        await page.screenshot({
          path: join(outDir, `${shot.name}-${variant.suffix}.png`),
          animations: 'disabled',
          caret: 'hide',
        })
      })
    }
  })
}
