import { expect, test } from './support'

test.describe('signed out', () => {
  test.use({ signedInAs: null })

  test('a deep link asks you to sign in, then takes you there', async ({ page }) => {
    await page.goto('/p/internal-tools?view=list')
    await expect(page).toHaveURL(/\/login\?next=/)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Sign in to Soundings' }),
    ).toBeVisible()

    await page.getByRole('button', { name: /Alice Anders/ }).click()
    await expect(page).toHaveURL(/\/p\/internal-tools\?view=list$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Internal Tools' })).toBeVisible()
  })

  test('login works from the keyboard and lands on My work', async ({ page }) => {
    // Development sign-in alone (no SSO): picking a person is the way in.
    await page.addInitScript(() => localStorage.setItem('soundings-mock-auth', 'dev_login'))
    await page.goto('/login')
    const filter = page.getByRole('textbox', { name: 'Filter people' })
    await expect(filter).toBeFocused()
    await filter.fill('bob')
    await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeHidden()
    await page.keyboard.press('ArrowDown')
    await expect(page.getByRole('button', { name: /Bob Chen/ })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Account menu for Bob Chen' })).toBeVisible()
  })

  test('next= never redirects off-site', async ({ page }) => {
    await page.goto('/login?next=//evil.example.com/steal')
    await page.getByRole('button', { name: /Alice Anders/ }).click()
    await expect(page).toHaveURL(/localhost:\d+\/$/)
    // Signed in already, a backslash form (browsers read /\host as //host) goes home too.
    await page.goto('/login?next=/%5Cevil.example.com')
    await expect(page).toHaveURL(/localhost:\d+\/$/)
    await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  })
})

test('sign out from the user menu returns to the login page', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Account menu for Alice Anders' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  // A form post to /auth/logout/redirect (the mock IdP signs out at once).
  await expect(page).toHaveURL(/\/login\?signed_out=1$/)
  await expect(page.getByText('You’re signed out.')).toBeVisible()
  await page.goto('/')
  await expect(page).toHaveURL(/\/login\?next=/)
})

test('sign out from the palette, too', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+k')
  await page.keyboard.type('sign out')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/login\?signed_out=1$/)
})

test('an expired session sends you to sign in and back', async ({ page, context }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  // An unsent draft…
  await page.keyboard.press('n')
  await page.getByRole('textbox', { name: 'Title' }).fill('Half an idea')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeHidden()
  // The session ends elsewhere (expiry, another tab)…
  await context.clearCookies()
  // …and the next request answers 401.
  await page.keyboard.press('ControlOrMeta+k')
  await expect(
    page.getByRole('dialog', { name: 'Command palette' }).getByRole('combobox'),
  ).toBeFocused()
  await page.keyboard.type('returns')
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings&expired=1$/)
  // Said calmly on the page itself, next to the way back in.
  await expect(
    page.getByRole('status').filter({ hasText: 'Your session has ended' }),
  ).toContainText('Sign in again to carry on where you left off.')
  await expect(page.getByRole('link', { name: 'Sign in with SSO' })).toHaveAttribute(
    'href',
    '/api/v1/auth/login?next=%2Fsettings',
  )
  // …goes with the session (ASVS 8.2.3).
  expect(
    await page.evaluate(() => Object.keys(localStorage).filter((key) => key.includes('draft'))),
  ).toEqual([])
})

test('a session whose sign-in method is switched off ends at the next request', async ({
  page,
  context,
  baseURL,
}) => {
  // Signed in with SSO; then the operator turns SSO off (break-glass back on).
  await context.addCookies([{ name: 'soundings_mock_auth_method', value: 'sso', url: baseURL }])
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.evaluate(() => localStorage.setItem('soundings-mock-auth', 'break_glass'))
  await page.reload()
  await expect(page).toHaveURL(/\/login\?next=%2F/)
  await expect(page.getByRole('heading', { level: 2, name: 'Break-glass admin' })).toBeVisible()
})

test('the dev user switcher signs in as someone else', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Account menu for Alice Anders' }).click()
  await page.getByRole('menuitem', { name: /Switch user/ }).click()
  await page.getByRole('menuitem', { name: /Priya Natarajan/ }).click()
  await expect(page.getByRole('button', { name: 'Account menu for Priya Natarajan' })).toBeVisible()
  // Platform admins can create projects.
  await expect(page.getByRole('button', { name: 'New project' })).toBeVisible()
})
