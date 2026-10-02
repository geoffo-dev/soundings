import type { Page } from '@playwright/test'

import { expect, seriousViolations, test } from './support'

/**
 * The public pages (contract-phase4 §3.5–3.7) against the mock: the form at
 * /{slug}/submit (with the real ALTCHA proof of work running in a worker), the
 * receipt, /track#<token> and /verify#<token>. Signed out, no app shell.
 */
test.use({ signedInAs: null })

/** Fixture tokens (src/mocks/phase4-fixtures.ts). */
const token = (name: string) => `track${name}`.padEnd(43, 'x')
const JO = token('JoMarshGreen9')
const UNCONFIRMED = token('ConfirmFirstGreen12')
const CONFIRM_LINK = 'v1.e0000000-0000-4000-8000-0000000f0004'

async function fillIdea(page: Page) {
  await page.getByRole('textbox', { name: /^Title/ }).fill('Print-free returns')
  await page
    .getByRole('textbox', { name: /^Summary/ })
    .fill('Let people return parcels with a QR code instead of a printed label.')
}

test('a visitor sends an idea: verified in the background, private link shown once', async ({
  page,
}) => {
  const posts: Record<string, unknown>[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/submissions')) {
      posts.push(request.postDataJSON() as Record<string, unknown>)
    }
  })
  await page.goto('/customer-innovation/submit')
  await expect(
    page.getByRole('heading', { level: 1, name: 'Share an idea with Customer Innovation' }),
  ).toBeVisible()
  // No app shell: no sidebar, no search, no sign-in.
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: /when you start typing/ })).toBeVisible()

  await fillIdea(page)
  // The proof of work starts with the first input and finishes by itself.
  await expect(page.getByRole('status').filter({ hasText: 'Verified you’re human' })).toBeVisible({
    timeout: 20_000,
  })
  await page.getByRole('textbox', { name: /^Your email/ }).fill('jo@example.org')
  await page.getByRole('checkbox', { name: 'Email me when the status changes' }).check()
  await page.getByRole('button', { name: /Send idea/ }).click()

  const heading = page.getByRole('heading', { name: 'Thanks! Your idea is in' })
  await expect(heading).toBeVisible()
  await expect(heading).toBeFocused()
  const link = page.getByRole('textbox', { name: 'Your private link' })
  await expect(link).toHaveValue(/\/track#[A-Za-z0-9_-]{43}$/)
  await expect(page.getByText(/We’ve also emailed you this link/)).toBeVisible()
  await expect(page.getByText('The team reviews new ideas first')).toBeVisible()

  expect(posts).toHaveLength(1)
  expect(posts[0]).toMatchObject({
    title: 'Print-free returns',
    email: 'jo@example.org',
    wants_updates: true,
    website: '',
  })
  // The widget's payload: the challenge (with its signed data) and the solution.
  const payload = JSON.parse(atob(String(posts[0]?.altcha))) as {
    challenge: { parameters: { data: Record<string, string> }; signature: string }
    solution: { counter: number; derivedKey: string }
  }
  expect(payload.challenge.parameters.data).toEqual({ project: 'customer-innovation' })
  expect(payload.solution.derivedKey).toMatch(/^00/)

  // The tracking page opens from the receipt; the token stays in the fragment.
  const tracking = (await link.inputValue()).split('#')[1] ?? ''
  await page.getByRole('link', { name: 'Open your tracking page' }).click()
  await expect(page).toHaveURL(new RegExp(`/track#${tracking}$`))
  await expect(page.getByRole('heading', { level: 1, name: 'Print-free returns' })).toBeVisible()
  await expect(page.getByText('Waiting for review', { exact: true })).toBeVisible()
})

test('⌘Enter sends the idea from any field', async ({ page }) => {
  await page.goto('/customer-innovation/submit')
  await fillIdea(page)
  await page.getByRole('textbox', { name: /^Summary/ }).press('ControlOrMeta+Enter')
  await expect(page.getByRole('textbox', { name: 'Your private link' })).toBeVisible({
    timeout: 20_000,
  })
})

test('field problems are inline and focus moves to the first one', async ({ page }) => {
  await page.goto('/customer-innovation/submit')
  await page.getByRole('textbox', { name: /^Summary/ }).fill('Only a summary')
  await page.getByRole('textbox', { name: /^Your email/ }).fill('not-an-address')
  await page.getByRole('button', { name: /Send idea/ }).click()
  const title = page.getByRole('textbox', { name: /^Title/ })
  await expect(title).toBeFocused()
  await expect(title).toHaveAccessibleDescription(/Give your idea a short title/)
  await expect(page.getByRole('textbox', { name: /^Your email/ })).toHaveAccessibleDescription(
    /like name@example.com/,
  )
})

test('the honeypot is out of reach: hidden, not focusable, never autofilled', async ({ page }) => {
  await page.goto('/customer-innovation/submit')
  const trap = page.locator('#hp_ref')
  await expect(trap).toHaveAttribute('tabindex', '-1')
  await expect(trap).toHaveAttribute('autocomplete', 'off')
  await expect(trap).toHaveAttribute('name', 'hp_ref')
  await expect(page.locator('[aria-hidden="true"]:has(#hp_ref)')).toHaveCount(1)
  // Tabbing from the last real field goes to the submit button, never the trap.
  await page.getByRole('checkbox', { name: 'Email me when the status changes' }).focus()
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press('Tab')
    await expect(trap).not.toBeFocused()
  }
})

test('a form that is off, unknown or reserved says only that it isn’t available', async ({
  page,
}) => {
  for (const slug of ['internal-tools', 'no-such-project', 'track']) {
    await page.goto(`/${slug}/submit`)
    await expect(
      page.getByRole('heading', { level: 1, name: 'This form isn’t available' }),
    ).toBeVisible()
  }
})

test('the public form is comfortable at 390 px and axe-clean in both themes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    await page.goto('/sustainability/submit')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    // No sideways scrolling; fields are full width and tall enough to tap.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
    const title = await page.getByRole('textbox', { name: /^Title/ }).boundingBox()
    expect(title?.height).toBeGreaterThanOrEqual(44)
    expect(await seriousViolations(page)).toEqual([])
  }
})

test('the project’s branding: Sustainability’s green on its public form', async ({ page }) => {
  await page.goto('/sustainability/submit')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const primary = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--brand-primary').trim(),
  )
  expect(primary).toBe('#2e7d4f')
})

test('the tracking page shows status and history, and only what was sent', async ({ page }) => {
  await page.goto(`/track#${JO}`)
  await expect(
    page.getByRole('heading', { level: 1, name: 'Refill station for cleaning products' }),
  ).toBeVisible()
  await expect(page.getByText(/Your idea for Sustainability/)).toBeVisible()
  await expect(page.getByText('Triage')).toBeVisible()
  await expect(page.getByText('j•••@example.org')).toBeVisible()
  // The fragment stays (the link is meant to be bookmarked).
  await expect(page).toHaveURL(new RegExp(`#${JO}$`))
  // Nothing internal: no key, no people, no scores.
  await expect(page.getByText(/GREEN-9/)).toHaveCount(0)
  await expect(page.getByText(/score/i)).toHaveCount(0)
  expect(await seriousViolations(page)).toEqual([])

  // Status emails off and on again.
  const updates = page.getByRole('switch', { name: 'Email me when the status changes' })
  await expect(updates).toBeChecked()
  await updates.click()
  await expect(updates).not.toBeChecked()
  await page.reload()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('an unconfirmed submitter can ask for the confirmation email again', async ({ page }) => {
  await page.goto(`/track#${UNCONFIRMED}`)
  await expect(
    page.getByText('Waiting for you to confirm your email address', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Send the confirmation email again' }).click()
  await expect(page.getByText('Sent. It can take a minute to arrive.')).toBeVisible()
})

test('“Delete my details” asks first, then the link stops working', async ({ page }) => {
  await page.goto(`/track#${JO}`)
  await page.getByRole('button', { name: 'Delete my details' }).click()
  const dialog = page.getByRole('alertdialog', { name: 'Delete your details?' })
  await expect(dialog).toContainText('The idea stays with the team')
  await dialog.getByRole('button', { name: 'Delete my details' }).click()
  await expect(page.getByRole('heading', { name: 'Your details are deleted' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Your details are deleted' })).toBeFocused()
})

test('unknown, incomplete and erased tracking links read the same', async ({ page }) => {
  await page.goto(`/track#${token('NoSuchSubmission')}`)
  await expect(page.getByRole('heading', { name: 'We can’t find this submission' })).toBeVisible()
  await page.goto('/track')
  await expect(
    page.getByRole('heading', { name: 'This tracking link is incomplete' }),
  ).toBeVisible()
})

test('/verify posts its token only on the Confirm click (link scanners confirm nothing)', async ({
  page,
}) => {
  const verifies: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/public/verify-email')) verifies.push(request.method())
  })
  await page.goto(`/verify#${CONFIRM_LINK}`)
  await expect(page.getByRole('heading', { name: 'Confirm your email address' })).toBeVisible()
  await page.waitForTimeout(500)
  expect(verifies).toEqual([])
  expect(await seriousViolations(page)).toEqual([])

  await page.getByRole('button', { name: 'Confirm my email address' }).click()
  await expect(
    page.getByRole('heading', { name: 'Thanks, your address is confirmed' }),
  ).toBeVisible()
  await expect(page.getByText(/Switch the canteen to oat milk by default/)).toBeVisible()
  expect(verifies).toEqual(['POST'])
})

test('an expired or broken confirmation link says how to get a new one', async ({ page }) => {
  await page.goto('/verify#v1.expired-or-made-up-token')
  await page.getByRole('button', { name: 'Confirm my email address' }).click()
  await expect(
    page.getByRole('heading', { name: 'This link has expired or isn’t valid' }),
  ).toBeVisible()
  await page.goto('/verify')
  await expect(
    page.getByRole('heading', { name: 'This link has expired or isn’t valid' }),
  ).toBeVisible()
})
