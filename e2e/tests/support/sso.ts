import { expect, test, type Page } from '@playwright/test'

import { KeycloakAdmin, keycloakUrl, PASSWORD } from '../../scripts/keycloak.ts'
import { authConfig, type AuthConfig } from './api'

/**
 * Single sign-on helpers for the Phase 2 specs (docs/test-plans/phase-2.md). They drive
 * the real Keycloak of the e2e stack (`E2E_SSO=1`, `<prefix>kc` on `E2E_KC_PORT`) or of
 * CI (`E2E_KC_URL`) through the browser, and change memberships through its admin REST
 * API (`e2e/scripts/keycloak.ts`).
 *
 * Specs that need SSO are tagged `@sso` (the CI SSO jobs run only those) and call
 * `requireSso()` first, so they skip against an app without SSO (the plain e2e jobs).
 */

/** Dev realm users (dev/README.md); every password is "password". */
export const KC = {
  alice: { name: 'Alice Anders', groups: ['/innovation/admins', '/tools/members'] },
  bob: { name: 'Bob Brown', groups: ['/innovation/members'] },
  carol: { name: 'Carol Chen', groups: ['/innovation/members', '/tools/members'] },
  dave: { name: 'Dave Davies', groups: ['/tools/members'] },
  erin: { name: 'Erin Evans', groups: ['/viewers'] },
  grace: { name: 'Grace Gale', groups: ['/tools/members'] }, // employee_no E2001 only
  mallory: { name: 'Mallory Mills', groups: ['/innovation/admins'] }, // unverified farah@…
  kenji: { name: 'Kenji Watanabe', groups: [] as string[] }, // no groups claim
  nia: { name: 'Nia Lee', groups: [] as string[] }, // verified, no account
} as const
export type KeycloakUser = keyof typeof KC

function baseURLOf(page?: Page): string {
  const url = test.info().project.use.baseURL
  if (url) return url
  if (page) return new URL(page.url()).origin
  throw new Error('baseURL is not configured')
}

/** The app's sign-in methods (cached). */
export function signInMethods(): Promise<AuthConfig> {
  return authConfig(baseURLOf())
}

/** Skips the current test (or describe block's tests) unless the app has SSO on. */
export async function requireSso() {
  test.skip(!(await signInMethods()).sso, 'needs single sign-on (E2E_SSO=1, see e2e/README.md)')
}

/**
 * A fresh admin connection to Keycloak. Its access token lives about a minute, so
 * connect where it is used (cleanup in `finally` too) rather than once per file.
 */
export function keycloak(): Promise<KeycloakAdmin> {
  return KeycloakAdmin.connect()
}

/** Runs `body` with `username` removed from `groupPath` in Keycloak, then restores it. */
export async function withoutKeycloakGroup(
  username: KeycloakUser,
  groupPath: string,
  body: () => Promise<void>,
) {
  await (await keycloak()).removeFromGroup(username, groupPath)
  try {
    await body()
  } finally {
    await (await keycloak()).addToGroup(username, groupPath)
  }
}

const kcOrigin = () => new URL(keycloakUrl()).origin

/**
 * On /login (or `from`, a page that sends you there), clicks "Sign in with SSO", signs
 * in at Keycloak with the dev realm password and waits until the browser is back on the
 * app (signed in, or on /login with an error). The browser context must not have a
 * Keycloak session yet (a fresh context, or after signing out through Keycloak).
 */
export async function ssoSignIn(
  page: Page,
  username: KeycloakUser,
  options: { next?: string; origin?: string } = {},
) {
  const login = options.next ? `/login?next=${encodeURIComponent(options.next)}` : '/login'
  await page.goto(options.origin ? new URL(login, options.origin).href : login)
  const link = page.getByRole('link', { name: 'Sign in with SSO' })
  await expect(link).toBeVisible()
  await link.click()
  await signInAtKeycloak(page, username)
}

/** Keycloak's login form: username, password, "Sign In"; then back on the app. */
export async function signInAtKeycloak(page: Page, username: KeycloakUser) {
  await page.waitForURL((url) => url.origin === kcOrigin())
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(PASSWORD)
  await page.locator('#kc-login').click()
  await page.waitForURL((url) => url.origin !== kcOrigin())
}

/** Signs in through Keycloak and checks the app greets `username`. */
export async function ssoSignInAs(
  page: Page,
  username: KeycloakUser,
  displayName: string = KC[username].name,
  options: { next?: string; origin?: string } = {},
) {
  await ssoSignIn(page, username, options)
  await expect(page.getByRole('button', { name: `Account menu for ${displayName}` })).toBeVisible()
  const me = await page.request.get(new URL('/api/v1/auth/me', page.url()).href)
  expect(me.status()).toBe(200)
  expect(((await me.json()) as { auth_method: string }).auth_method).toBe('sso')
}

/**
 * "Sign out" from the account menu: a form post that ends the session and, for an SSO
 * session, Keycloak's too (id_token_hint, no confirmation page), back to
 * /login?signed_out=1.
 */
export async function signOutInUi(page: Page) {
  await page.getByRole('button', { name: /^Account menu for / }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await page.waitForURL(/\/login\?signed_out=1$/)
  await expect(page.getByRole('status').filter({ hasText: 'You’re signed out.' })).toBeVisible()
}

/** The sidebar's project links. */
export const sidebarProjects = (page: Page) =>
  page.getByRole('navigation', { name: 'Main' }).getByRole('region', { name: 'Projects' })

/** Opens a project and expects it to be there (`true`) or "doesn't exist" (`false`). */
export async function expectProjectAccess(page: Page, slug: string, name: string, open: boolean) {
  await page.goto(`/p/${slug}`)
  if (open) {
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
    await expect(sidebarProjects(page).getByRole('link', { name })).toBeVisible()
  } else {
    await expect(
      page.getByRole('heading', { name: 'This project doesn’t exist or you don’t have access' }),
    ).toBeVisible()
    await expect(sidebarProjects(page).getByRole('link', { name })).toHaveCount(0)
  }
}

/** The callout the sign-in page shows after a redirect back (`?error=`, `?signed_out=1`). */
export const loginNotice = (page: Page) => page.locator('main').getByRole('alert')
