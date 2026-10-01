import type { Page } from '@playwright/test'

import { keycloakUrl } from '../scripts/keycloak.ts'
import { Api, userOf, type AuditEntry } from './support/api'
import { expect, test } from './support/fixtures'
import { loginNotice, requireSso, signInMethods, ssoSignIn, ssoSignInAs } from './support/sso'

/**
 * Sign-in errors and the break-glass admin (contract-phase2 §3.2, §3.3, §3.8, §4.2)
 * against the real stack. Each refusal lands on /login with one calm sentence (never the
 * raw code or IdP text), the SSO button again, no session, and an audit entry with no
 * actor. Test plan: LE-* and BG-*.
 *
 * Keycloak users (dev/README.md): mallory has an unverified address naming seeded Farah;
 * nia is verified but has no account; kenji has no employee_no in Keycloak.
 */

const BREAK_GLASS = {
  username: process.env.E2E_BREAK_GLASS_USERNAME ?? 'admin',
  password: process.env.E2E_BREAK_GLASS_PASSWORD ?? 'e2e-break-glass-password',
}

/** Now, a little earlier, for `since` filters (the server and the browser share a clock). */
const startedAt = () => new Date(Date.now() - 2000).toISOString()

async function deniedSince(api: Api, since: string, reason: string): Promise<AuditEntry[]> {
  const entries = await api.audit({ action: 'session.sign_in_denied', since })
  return entries.filter((entry) => entry.details.reason === reason)
}

async function expectSignedOut(page: Page) {
  const me = await page.request.get('/api/v1/auth/me')
  expect(me.status()).toBe(401)
  await expect(page.getByRole('link', { name: 'Sign in with SSO' })).toBeVisible()
}

/**
 * Starts a real sign-in (attempt row, state cookie) and returns its `state`, as read
 * from the authorization request to Keycloak; the browser is then on Keycloak's form.
 */
async function startAttempt(page: Page): Promise<string> {
  await page.goto('/login')
  const kcOrigin = new URL(keycloakUrl()).origin
  const authorization = page.waitForRequest((request) => request.url().startsWith(kcOrigin))
  await page.getByRole('link', { name: 'Sign in with SSO' }).click()
  const state = new URL((await authorization).url()).searchParams.get('state')
  if (!state) throw new Error('no state in the authorization request')
  return state
}

test.describe('SSO sign-in errors', { tag: '@sso' }, () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async () => {
    await requireSso()
  })

  test('LE-01: an unverified email naming someone else is refused, and next is kept', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const since = startedAt()
    await ssoSignIn(page, 'mallory', { next: '/work' })

    await expect(page).toHaveURL(/\/login\?error=no_account&next=%2Fwork$/)
    await expect(loginNotice(page)).toContainText('You don’t have a Soundings account yet')
    await expect(loginNotice(page)).toContainText('Ask an administrator to add you')
    await expect(page.getByText('no_account')).toHaveCount(0)
    await expectSignedOut(page)
    // Signing in again from here still goes back to /work afterwards.
    await expect(page.getByRole('link', { name: 'Sign in with SSO' })).toHaveAttribute(
      'href',
      '/api/v1/auth/login?next=%2Fwork',
    )

    // Not linked to Farah, whose address it is: no actor, no target, the reason.
    const [denied] = await deniedSince(alice, since, 'email_not_verified')
    expect(denied).toMatchObject({ actor_id: null, target_id: null, target_type: null })
    expect(denied?.details).toMatchObject({ method: 'sso' })
    expect(JSON.stringify(denied?.details)).not.toContain('@')
    const farah = await alice.adminUser((await userOf(alice.baseURL, 'farah')).id)
    expect(farah.identities).toEqual([])
  })

  test('LE-02: someone with no account is refused', async ({ page, api }) => {
    const alice = await api('alice')
    const since = startedAt()
    await ssoSignIn(page, 'nia')

    await expect(page).toHaveURL(/\/login\?error=no_account$/)
    await expect(loginNotice(page)).toContainText('You don’t have a Soundings account yet')
    await expectSignedOut(page)
    expect(await deniedSince(alice, since, 'no_match')).toHaveLength(1)
    // Auto-create is off: nobody was created.
    expect(await alice.adminUserByEmail('nia@example.org')).toBeUndefined()
  })

  test('LE-03: a deactivated account is refused; reactivated, it signs in', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const existing = await alice.adminUserByEmail('nia@example.org')
    const nia =
      existing ?? (await alice.createUser({ email: 'nia@example.org', display_name: 'Nia Lee' }))
    await alice.updateUser(nia.id, { is_active: false })
    const since = startedAt()

    await ssoSignIn(page, 'nia')
    await expect(page).toHaveURL(/\/login\?error=account_disabled$/)
    await expect(loginNotice(page)).toContainText('Your account is deactivated')
    await expectSignedOut(page)
    const [denied] = await deniedSince(alice, since, 'account_disabled')
    // The target is the account it matched; the actor stays empty.
    expect(denied).toMatchObject({ actor_id: null, target_type: 'user', target_id: nia.id })

    await alice.updateUser(nia.id, { is_active: true })
    await page.context().clearCookies() // a fresh Keycloak login, like a new browser
    await ssoSignInAs(page, 'nia', 'Nia Lee')
    const links = await alice.audit({ action: 'user.identity_link', target_id: nia.id })
    expect(links[0]?.details.matched_by).toBe('email')
  })

  test('LE-04: an account with an external ID is never linked by email alone', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const kenji = await userOf(alice.baseURL, 'kenji')
    await alice.setExternalIds(kenji.id, [{ kind: 'employee_no', value: 'E7777' }])
    try {
      const since = startedAt()
      await ssoSignIn(page, 'kenji') // verified kenji@example.com, but no employee_no
      await expect(page).toHaveURL(/\/login\?error=identity_conflict$/)
      await expect(loginNotice(page)).toContainText(
        'Your account needs an administrator to finish linking it',
      )
      await expectSignedOut(page)
      const [denied] = await deniedSince(alice, since, 'external_id_missing')
      expect(denied).toMatchObject({ actor_id: null, target_id: kenji.id })
      expect((await alice.adminUser(kenji.id)).identities).toEqual([])
    } finally {
      await alice.setExternalIds(kenji.id, [])
    }
  })

  test('LE-05: cancelled at the identity provider', async ({ page, api }) => {
    const alice = await api('alice')
    const since = startedAt()
    const state = await startAttempt(page)
    // What Keycloak sends back when the user declines: error=access_denied.
    await page.goto(`/api/v1/auth/callback?error=access_denied&state=${state}`)
    await expect(page).toHaveURL(/\/login\?error=login_cancelled$/)
    await expect(
      page.locator('main').getByRole('status').filter({ hasText: 'Sign-in was cancelled' }),
    ).toBeVisible()
    await expectSignedOut(page)
    expect(await deniedSince(alice, since, 'login_cancelled')).toHaveLength(1)
  })

  test('LE-06: an answer that can’t be verified, and IdP text is never shown', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const since = startedAt()
    const state = await startAttempt(page)
    await page.goto(
      `/api/v1/auth/callback?code=not-a-real-code&state=${state}` +
        `&error_description=${encodeURIComponent('<b>Injected IdP text</b>')}`,
    )
    await expect(page).toHaveURL(/\/login\?error=sso_failed$/)
    await expect(loginNotice(page)).toContainText('We couldn’t verify your sign-in')
    await expect(page.getByText('Injected IdP text')).toHaveCount(0)
    await expectSignedOut(page)
    expect(await deniedSince(alice, since, 'sso_failed')).toHaveLength(1)
  })

  test('LE-07: a forged or replayed callback is “took too long”, and the attempt is single use', async ({
    page,
  }) => {
    await page.goto('/api/v1/auth/callback?code=x&state=forged')
    await expect(page).toHaveURL(/\/login\?error=login_expired$/)
    await expect(loginNotice(page)).toContainText('That sign-in took too long or was already used')

    // A real attempt answered twice: the second answer finds nothing.
    const state = await startAttempt(page)
    await page.goto(`/api/v1/auth/callback?error=access_denied&state=${state}`)
    await expect(page).toHaveURL(/error=login_cancelled/)
    await page.goto(`/api/v1/auth/callback?error=access_denied&state=${state}`)
    await expect(page).toHaveURL(/\/login\?error=login_expired$/)
    await expectSignedOut(page)
  })
})

test('LE-08: an unknown error code gets a generic message, never the code', async ({ page }) => {
  await page.goto('/login?error=%3Cscript%3Ealert(1)%3C%2Fscript%3E')
  await expect(loginNotice(page)).toContainText('Something went wrong signing you in')
  await expect(page.getByText('<script>', { exact: false })).toHaveCount(0)
})

test.describe('break-glass admin', () => {
  test(
    'BG-01: off once SSO is configured: no form, and the endpoint is gone',
    { tag: '@sso' },
    async ({ page }) => {
      await requireSso()
      expect((await signInMethods()).break_glass).toBe(false)
      await page.goto('/login')
      await expect(page.getByRole('link', { name: 'Sign in with SSO' })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Break-glass admin' })).toHaveCount(0)
      // Even with the right credentials (configured on the e2e stack and in CI).
      const response = await page.request.post('/api/v1/auth/break-glass', { data: BREAK_GLASS })
      expect(response.status()).toBe(404)
    },
  )

  test('BG-02: signs in while SSO is off, shows the banner, and every use is audited', async ({
    page,
    api,
  }) => {
    test.skip(
      !(await signInMethods()).break_glass,
      'break-glass is not available here (E2E_SSO=0 with E2E_BREAK_GLASS=1)',
    )
    const alice = await api('alice')
    const since = startedAt()
    await page.goto('/login')
    const form = page.getByRole('form', { name: 'Break-glass admin' })
    await form.getByRole('textbox', { name: 'Username' }).fill(BREAK_GLASS.username)
    await form.getByLabel('Password', { exact: true }).fill(`${BREAK_GLASS.password}-wrong`)
    await form.getByRole('button', { name: 'Sign in' }).click()
    await expect(form.getByRole('alert')).toContainText('That username and password don’t match')

    await form.getByLabel('Password', { exact: true }).fill(BREAK_GLASS.password)
    await form.getByRole('button', { name: 'Sign in' }).click()
    await expect(
      page.getByRole('status').filter({ hasText: 'Signed in with the break-glass account.' }),
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Account menu for Break-glass admin' }),
    ).toBeVisible()

    // An admin action in this session carries auth_method break_glass.
    await page.goto('/settings/users')
    await expect(page.getByRole('heading', { level: 2, name: 'Users' })).toBeVisible()
    const signIns = await alice.audit({ action: 'session.sign_in', since })
    const mine = signIns.find((entry) => entry.details.method === 'break_glass')
    expect(mine?.actor?.display_name).toBe('Break-glass admin')
    const denied = await deniedSince(alice, since, 'invalid_credentials')
    expect(denied).toHaveLength(1)
    expect(denied[0]).toMatchObject({ actor_id: null, target_id: null })
    // Neither the submitted username nor the password is recorded.
    expect(Object.keys(denied[0]?.details ?? {})).not.toContain('username')
    expect(JSON.stringify(denied)).not.toContain(BREAK_GLASS.password)

    await page
      .getByRole('status')
      .filter({ hasText: 'Signed in with the break-glass account.' })
      .getByRole('button', { name: 'Sign out' })
      .click()
    await expect(page).toHaveURL(/\/login\?signed_out=1$/)
  })
})
