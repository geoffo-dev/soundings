import type { Page } from '@playwright/test'

import { expect, seriousViolations, test } from './support'

/**
 * The sign-in page (contract-phase2 §3.1, §4.2) in each configuration the mock
 * can play (`soundings-mock-auth`, src/mocks/auth-config.ts): SSO with the dev
 * login (the default), SSO only, break-glass while SSO is off, nothing at all.
 */

test.use({ signedInAs: null })

/** Sets the mock's sign-in configuration (and other knobs) before the page loads. */
async function configure(page: Page, settings: Record<string, string>) {
  await page.addInitScript((values) => {
    for (const [key, value] of Object.entries(values)) localStorage.setItem(key, value)
  }, settings)
}

const heading = (page: Page) =>
  page.getByRole('heading', { level: 1, name: 'Sign in to Soundings' })
const ssoLink = (page: Page) => page.getByRole('link', { name: 'Sign in with SSO' })

test('SSO and the dev login: SSO is the focused primary action, people below a divider', async ({
  page,
}) => {
  await page.goto('/login?next=%2Fp%2Finternal-tools%3Fview%3Dlist')
  await expect(heading(page)).toBeVisible()
  await expect(ssoLink(page)).toBeFocused()
  // Focused without its ring (it would look pressed); the first key press shows it.
  const outline = () => ssoLink(page).evaluate((link) => getComputedStyle(link).outlineStyle)
  expect(await outline()).toBe('none')
  await page.keyboard.press('Shift')
  await expect.poll(outline).toBe('solid')
  // A real navigation to the API, which redirects to the identity provider.
  await expect(ssoLink(page)).toHaveAttribute(
    'href',
    '/api/v1/auth/login?next=%2Fp%2Finternal-tools%3Fview%3Dlist',
  )
  await expect(page.getByRole('heading', { level: 2, name: 'Development sign-in' })).toBeVisible()
  await page.getByRole('button', { name: /Bob Chen/ }).click()
  await expect(page).toHaveURL(/\/p\/internal-tools\?view=list$/)
})

test('SSO only: Enter goes through the identity provider and back to where you were', async ({
  page,
}) => {
  await configure(page, { 'soundings-mock-auth': 'sso', 'soundings-mock-sso-user': 'bob' })
  await page.goto('/p/internal-tools')
  await expect(page).toHaveURL(/\/login\?next=%2Fp%2Finternal-tools/)
  await expect(ssoLink(page)).toBeFocused()
  await expect(page.getByRole('heading', { name: 'Development sign-in' })).toHaveCount(0)
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await page.keyboard.press('Enter')
  await expect(page.getByText('Taking you to your organisation’s sign-in page…')).toBeVisible()
  await expect(page).toHaveURL(/\/p\/internal-tools$/)
  await expect(page.getByRole('button', { name: 'Account menu for Bob Chen' })).toBeVisible()
})

test('an SSO failure comes back as a calm message with the button again', async ({ page }) => {
  await configure(page, {
    'soundings-mock-auth': 'sso',
    'soundings-mock-sso-error': 'no_account',
  })
  await page.goto('/login?next=/ideas/CUST-1')
  await ssoLink(page).click()
  await expect(page).toHaveURL(/\/login\?error=no_account&next=%2Fideas%2FCUST-1/)
  await expect(page.getByRole('alert')).toContainText('You don’t have a Soundings account yet')
  await expect(page.getByRole('alert')).toContainText('Ask an administrator to add you')
  await expect(ssoLink(page)).toHaveAttribute('href', '/api/v1/auth/login?next=%2Fideas%2FCUST-1')
})

test('after no_account or identity_conflict, “Use a different account” asks the IdP to switch', async ({
  page,
}) => {
  await configure(page, { 'soundings-mock-auth': 'sso,dev_login' })
  const otherAccount = page.getByRole('link', { name: 'Use a different account' })
  for (const code of ['no_account', 'identity_conflict']) {
    await page.goto(`/login?error=${code}&next=%2Fideas%2FCUST-1`)
    await expect(otherAccount, code).toHaveAttribute(
      'href',
      '/api/v1/auth/login?next=%2Fideas%2FCUST-1&prompt=select_account',
    )
    // Signing in again stays the focused primary action; the switch is the next stop.
    await expect(ssoLink(page)).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(otherAccount).toBeFocused()
    expect(await seriousViolations(page), code).toEqual([])
  }
  // Only where the IdP signed in someone Soundings can't use.
  for (const query of ['error=sso_failed', 'error=account_disabled', 'signed_out=1', '']) {
    await page.goto(`/login?${query}`)
    await expect(ssoLink(page)).toBeVisible()
    await expect(otherAccount, query).toHaveCount(0)
  }
})

const ERRORS: [string, string, 'alert' | 'status'][] = [
  ['sso_unavailable', 'Single sign-on isn’t available right now', 'alert'],
  ['too_many_attempts', 'Too many sign-in attempts from your network', 'alert'],
  ['login_expired', 'That sign-in took too long or was already used', 'alert'],
  ['login_cancelled', 'Sign-in was cancelled', 'status'],
  ['sso_failed', 'We couldn’t verify your sign-in', 'alert'],
  ['no_account', 'You don’t have a Soundings account yet', 'alert'],
  ['account_disabled', 'Your account is deactivated', 'alert'],
  ['identity_conflict', 'Your account needs an administrator to finish linking it', 'alert'],
  ['made_up_code', 'Something went wrong signing you in', 'alert'],
]

test('every sign-in error code has its own plain-language message', async ({ page }) => {
  await configure(page, { 'soundings-mock-auth': 'sso' })
  for (const [code, title, role] of ERRORS) {
    await page.goto(`/login?error=${code}`)
    await expect(page.getByRole(role).filter({ hasText: title }), code).toBeVisible()
    await expect(page.getByText(code)).toHaveCount(0)
    await expect(ssoLink(page)).toBeVisible()
  }
})

test('signing out says so, and Back doesn’t bring the app back', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: /Alice Anders/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.getByRole('button', { name: 'Account menu for Alice Anders' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login\?signed_out=1$/)
  await expect(page.getByRole('status').filter({ hasText: 'You’re signed out.' })).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(/\/login/)
  await expect(heading(page)).toBeVisible()
})

test.describe('break-glass admin (SSO not configured)', () => {
  test.beforeEach(async ({ page }) => {
    await configure(page, { 'soundings-mock-auth': 'break_glass,dev_login' })
  })

  test('signs in, shows the banner in every page, and signs out', async ({ page }) => {
    await page.goto('/login?next=/settings')
    await expect(page.getByRole('heading', { level: 2, name: 'Break-glass admin' })).toBeVisible()
    await expect(ssoLink(page)).toHaveCount(0)
    const username = page.getByRole('textbox', { name: 'Username' })
    await expect(username).toBeFocused()

    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByText('Enter the username.')).toBeVisible()
    await expect(username).toBeFocused()

    await username.fill('break-glass')
    await page.getByLabel('Password', { exact: true }).fill('correct horse battery staple')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/settings$/)
    const banner = page.getByRole('status').filter({
      hasText: 'Signed in with the break-glass account.',
    })
    await expect(banner).toBeVisible()
    await page.goto('/')
    await expect(banner).toBeVisible()
    await banner.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login\?signed_out=1$/)
  })

  test('lands on the sign-in settings, and the password can be shown', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Username' }).fill('break-glass')
    const password = page.getByLabel('Password', { exact: true })
    await password.fill('correct horse battery staple')
    const show = page.getByRole('button', { name: 'Show password' })
    await expect(show).toHaveAttribute('aria-pressed', 'false')
    await expect(password).toHaveAttribute('type', 'password')
    await show.click()
    await expect(show).toHaveAttribute('aria-pressed', 'true')
    await expect(password).toHaveAttribute('type', 'text')
    await password.press('Enter')
    // Not My work ("you're not in any projects yet"): setting up SSO is what it is for.
    await expect(page).toHaveURL(/\/settings\/sso$/)
    await expect(page.getByRole('heading', { name: 'Set up single sign-on' })).toBeVisible()
  })

  test('wrong passwords: one message for both fields, then a pause', async ({ page }) => {
    await page.goto('/login')
    const password = page.getByLabel('Password', { exact: true })
    await page.getByRole('textbox', { name: 'Username' }).fill('break-glass')
    for (let attempt = 1; attempt <= 5; attempt++) {
      await password.fill(`guess ${attempt}`)
      await page.keyboard.press('Enter')
      await expect(page.getByRole('alert')).toContainText('That username and password don’t match')
      // The password is cleared and focused for the next try.
      await expect(password).toHaveValue('')
      await expect(password).toBeFocused()
    }
    await password.fill('correct horse battery staple')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('alert')).toContainText('Too many attempts')
    await expect(page.getByRole('alert')).toContainText('about 15 minutes')
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeDisabled()
  })
})

test('with no sign-in method configured, it says so', async ({ page }) => {
  await configure(page, { 'soundings-mock-auth': 'none' })
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign-in isn’t set up yet' })).toBeVisible()
  await expect(page.getByText('the operator guide explains how')).toBeVisible()
})

test('when the sign-in options can’t load, it offers to try again', async ({ page }) => {
  await configure(page, { 'soundings-mock-fail': '/auth/config' })
  await page.goto('/login')
  await expect(page.getByRole('alert')).toContainText('We couldn’t load the sign-in options')
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(ssoLink(page)).toBeVisible()
})

for (const colorScheme of ['light', 'dark'] as const) {
  test(`every variant has no serious accessibility violations (${colorScheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme })
    const variants: [string, string][] = [
      ['sso,dev_login', '/login?signed_out=1'],
      ['sso', '/login?error=identity_conflict'],
      ['sso', '/login?error=account_disabled'],
      ['sso', '/login?expired=1'],
      ['break_glass,dev_login', '/login?error=login_cancelled'],
      ['none', '/login'],
    ]
    for (const [auth, path] of variants) {
      await configure(page, { 'soundings-mock-auth': auth })
      await page.goto(path)
      await expect(heading(page)).toBeVisible()
      await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
      expect(await seriousViolations(page), `${auth} ${path}`).toEqual([])
    }
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('every variant fits the screen', async ({ page }) => {
    for (const auth of ['sso,dev_login', 'sso', 'break_glass,dev_login']) {
      await configure(page, { 'soundings-mock-auth': auth })
      await page.goto('/login?error=identity_conflict')
      await expect(heading(page)).toBeVisible()
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, auth).toBe(0)
    }
  })
})
