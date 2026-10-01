import { keycloakUrl } from '../scripts/keycloak.ts'
import { expect, test } from './support/fixtures'
import { requireSso, signInAtKeycloak, signOutInUi, ssoSignInAs } from './support/sso'

/**
 * The SSO sign-in flow in a real browser against Keycloak (contract-phase2 §3.2, §3.9):
 * deep links survive the round trip, unsafe `next` values don't, each configured host
 * signs in on itself, the browser holds no IdP token, and signing out ends the Keycloak
 * session too. Dave (verified email, /tools/members) signs in; nothing here changes
 * data. Test plan: SI-*.
 */

test.describe('SSO sign-in', { tag: '@sso' }, () => {
  test.beforeEach(async () => {
    await requireSso()
  })

  test('SI-01: a deep link survives the sign-in', async ({ page }) => {
    await page.goto('/p/customer-innovation?view=list')
    await expect(page).toHaveURL(/\/login\?next=/)
    await page.getByRole('link', { name: 'Sign in with SSO' }).click()
    await signInAtKeycloak(page, 'dave')
    await expect(page).toHaveURL(/\/p\/customer-innovation\?view=list$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Customer Innovation' })).toBeVisible()
  })

  test('SI-02: an unsafe next lands on My work instead', async ({ page }) => {
    for (const next of ['//evil.example/x', '/api/v1/auth/me', 'https://evil.example/']) {
      await page.context().clearCookies()
      await page.goto(`/api/v1/auth/login?next=${encodeURIComponent(next)}`)
      await signInAtKeycloak(page, 'dave')
      expect(new URL(page.url()).pathname, next).toBe('/')
      await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
    }
  })

  test('SI-03: the browser never holds an IdP token; the session cookie is HttpOnly', async ({
    page,
    baseURL,
  }) => {
    await ssoSignInAs(page, 'dave')
    const cookies = await page.context().cookies(baseURL)
    const names = cookies.map((cookie) => cookie.name).sort()
    expect(names).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/soundings_session$/),
        expect.stringMatching(/soundings_csrf$/),
      ]),
    )
    // The short-lived login-attempt cookie is gone after the callback.
    expect(names.some((name) => name.endsWith('soundings_oidc'))).toBe(false)
    const session = cookies.find((cookie) => cookie.name.endsWith('soundings_session'))
    expect(session).toMatchObject({ httpOnly: true, sameSite: 'Lax' })
    // No JWT (three base64url parts starting with eyJ) anywhere the page can read.
    const jwt = /eyJ[\w-]+\.[\w-]+\.[\w-]+/
    for (const cookie of cookies) expect(cookie.value, cookie.name).not.toMatch(jwt)
    const storage = await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    )
    expect(storage).not.toMatch(jwt)
    const me = await (await page.request.get('/api/v1/auth/me')).text()
    expect(me).not.toMatch(jwt)
  })

  test('SI-04: signing out ends the Keycloak session too', async ({ page }) => {
    await ssoSignInAs(page, 'dave')
    await signOutInUi(page)
    // Back at Keycloak, the password is asked for again (no silent sign-in).
    await page.getByRole('link', { name: 'Sign in with SSO' }).click()
    await page.waitForURL((url) => url.origin === new URL(keycloakUrl()).origin)
    await expect(page.locator('#password')).toBeVisible()
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401)
  })

  test('SI-05: each configured host signs in on itself (multi-domain)', async ({
    page,
    baseURL,
  }) => {
    // The local stack lists http://localhost:<port> and http://127.0.0.1:<port> in
    // SOUNDINGS_BASE_URLS (and the realm allows both); CI's app has one host.
    const url = new URL(baseURL ?? '')
    test.skip(url.hostname !== 'localhost', 'needs the local stack (two base URLs)')
    const other = `${url.protocol}//127.0.0.1:${url.port}`

    const authorization = page.waitForRequest((request) =>
      request.url().startsWith(new URL(keycloakUrl()).origin),
    )
    await page.goto(`${other}/login`)
    await page.getByRole('link', { name: 'Sign in with SSO' }).click()
    const redirectUri = new URL((await authorization).url()).searchParams.get('redirect_uri')
    expect(redirectUri).toBe(`${other}/api/v1/auth/callback`)
    await signInAtKeycloak(page, 'dave')
    expect(new URL(page.url()).origin).toBe(other)
    await expect(page.getByRole('button', { name: 'Account menu for Dave Davies' })).toBeVisible()
    // The session belongs to that host only.
    expect((await page.request.get(`${baseURL}/api/v1/auth/me`)).status()).toBe(401)
  })
})
