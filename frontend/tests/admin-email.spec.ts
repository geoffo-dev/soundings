import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Admin settings → Email (contract-phase3 §3.10) and the admin email banners
 * (§3.1) against the mock. Platform admin: Priya Natarajan. Mock knob
 * `soundings-mock-email`: `off` (no SMTP) or `failing` (SMTP down).
 */

test.use({ signedInAs: USERS.priya })

async function emailKnob(page: Page, value: 'off' | 'failing') {
  await page.addInitScript((knob) => localStorage.setItem('soundings-mock-email', knob), value)
}

const outbox = (page: Page) => page.getByRole('table', { name: 'Outbox emails' })

test('shows the settings in effect without secrets, and opens the outbox on failed emails', async ({
  page,
}) => {
  await page.goto('/settings/email')
  await expect(page.getByRole('heading', { level: 2, name: 'Email' })).toBeVisible()
  await expect(page.getByText('Email is on')).toBeVisible()
  await expect(page.getByText('smtp.example.com:587')).toBeVisible()
  await expect(page.getByText('STARTTLS', { exact: true })).toBeVisible()
  await expect(page.getByText('Set (never shown)')).toHaveCount(2)
  await expect(page.getByText('/etc/soundings/smtp-ca/ca.crt')).toBeVisible()
  await expect(
    page.getByText('2 days before and on the due date, at 08:00 (Europe/London)'),
  ).toBeVisible()

  // Failed first: three failures, two still recent enough to retry.
  await expect(page.getByRole('button', { name: 'Remove status filter' })).toBeVisible()
  await expect(outbox(page).getByRole('row')).toHaveCount(4) // header + 3
  await expect(outbox(page)).toContainText('SMTP 535: authentication failed')
  await expect(outbox(page)).toContainText('Too old to send')
  await expect(outbox(page).getByRole('button', { name: /^Retry/ })).toHaveCount(2)
  // Masked addresses only, never a full one.
  await expect(page.locator('main')).not.toContainText('hannah.weber@example.com')
})

test('retry queues a failed email at once; "Show all" lists everything', async ({ page }) => {
  await page.goto('/settings/email')
  const row = outbox(page).getByRole('row').filter({ hasText: 'Hannah Weber' })
  await row.getByRole('button', { name: /^Retry/ }).click()
  await expect(row).toContainText('Queued')
  await expect(row.getByRole('button', { name: /^Retry/ })).toHaveCount(0)

  await page.getByRole('button', { name: 'Show all' }).click()
  await expect(page).toHaveURL(/status=all/)
  await expect(outbox(page)).toContainText('Daily digest')
  await page.getByRole('button', { name: 'Load older emails' }).click()
  await expect(outbox(page)).toContainText('Test email from Priya Natarajan')
  await expect(outbox(page)).toContainText('o•••@example.com')
  await expect(outbox(page)).toContainText('Not sent')
})

test('the counters filter the outbox', async ({ page }) => {
  await page.goto('/settings/email?status=all')
  await page.getByRole('button', { name: /^Queued/ }).click()
  await expect(page).toHaveURL(/status=queued/)
  await expect(outbox(page).getByRole('row')).toHaveCount(2)
  await expect(outbox(page)).toContainText('connection timed out')
  await expect(outbox(page)).toContainText('Next try')
})

test('sends a test email to yourself and reports it sent', async ({ page }) => {
  await page.goto('/settings/email')
  await page.getByRole('button', { name: 'Send test email' }).click()
  await expect(page.getByText('Queued, waiting for the worker…')).toBeVisible()
  await expect(page.getByText('Sent to Priya Natarajan')).toBeVisible({ timeout: 10_000 })
})

test('refuses a list of addresses with a field error', async ({ page }) => {
  await page.goto('/settings/email')
  await page.getByRole('textbox', { name: 'Send to' }).fill('a@example.com, b@example.com')
  await page.getByRole('button', { name: 'Send test email' }).click()
  const field = page.getByRole('textbox', { name: 'Send to' })
  await expect(field).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByText('Enter one email address, such as ops@example.com')).toBeVisible()
})

test.describe('with SMTP down', () => {
  test.beforeEach(async ({ page }) => emailKnob(page, 'failing'))

  test('the test email shows the error and what to check; admins see the banner', async ({
    page,
  }) => {
    await page.goto('/')
    const banner = page.getByTestId('email-banner')
    await expect(banner).toContainText('Some emails aren’t going out.')
    await banner.getByRole('link', { name: 'Open Email settings' }).click()
    await expect(page).toHaveURL(/\/settings\/email$/)
    await expect(page.getByTestId('email-banner')).toHaveCount(0) // the page says it itself
    await expect(page.getByText('Some emails aren’t going out')).toBeVisible()

    await page.getByRole('textbox', { name: 'Send to' }).fill('ops@example.com')
    await page.getByRole('button', { name: 'Send test email' }).click()
    const result = page.getByRole('alert').filter({ hasText: 'The test email failed' })
    await expect(result).toContainText('connection refused', { timeout: 10_000 })
    await expect(result).toContainText('check the host, port')
  })

  test('the banner can be dismissed for the session', async ({ page }) => {
    await page.goto('/')
    await page
      .getByTestId('email-banner')
      .getByRole('button', { name: 'Dismiss for this session' })
      .click()
    await expect(page.getByTestId('email-banner')).toHaveCount(0)
    await page.goto('/settings/sso')
    await expect(page.getByRole('heading', { level: 2, name: 'Sign-in (SSO)' })).toBeVisible()
    await expect(page.getByTestId('email-banner')).toHaveCount(0)
  })
})

test.describe('without SMTP', () => {
  test.beforeEach(async ({ page }) => emailKnob(page, 'off'))

  test('explains how to set it up; the test email waits; admins see a calm banner', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(page.getByTestId('email-banner')).toContainText(
      'Email isn’t set up: people only get in-app notifications.',
    )
    await page.getByRole('link', { name: 'Set up email' }).click()
    await expect(page.getByRole('heading', { name: 'Set up email' })).toBeVisible()
    await expect(page.getByText('smtp.host', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Send test email' })).toBeDisabled()
    await expect(page.getByRole('heading', { name: 'Server' })).toHaveCount(0)
  })
})

test.describe('as someone who isn’t a platform admin', () => {
  test.use({ signedInAs: USERS.alice })

  test('the page is a plain 404 and there is no banner', async ({ page }) => {
    await emailKnob(page, 'off')
    await page.goto('/settings/email')
    await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
    await expect(page.getByTestId('email-banner')).toHaveCount(0)
  })
})
