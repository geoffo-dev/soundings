import type { Page } from '@playwright/test'

import { uniqueSuffix, type Api } from './support/api'
import {
  disposePeople,
  emailCount,
  expectNoScoreData,
  Mailpit,
  newPeople,
  requireEmail,
  requireMailpitControl,
  signInAs,
  startMailpit,
  stopMailpit,
  visibleText,
  type Someone,
} from './support/email'
import { expect, signIn, test } from './support/fixtures'

/**
 * Admin settings → Email (contract-phase3 §3.10) and the admin email banners (§3.1) on
 * the real stack: the settings in effect without secrets, the test email (it arrives in
 * Mailpit; no server details, no unsubscribe link; audited without the address), and,
 * with Mailpit stopped (`@smtp-outage`), a failed send shown with its reason, the
 * "emails aren't going out" banner, and Retry delivering it once Mailpit is back. Each
 * test sends its test emails as a new platform admin (the limit is 5 per admin per 10
 * minutes). Test plan: AE-*.
 */

const banner = (page: Page) => page.getByTestId('email-banner')
const outboxTable = (page: Page) => page.getByRole('table', { name: 'Outbox emails' })

async function openEmailPage(page: Page, query = '') {
  await page.goto(`/settings/email${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Email' })).toBeVisible()
}

/** A fresh platform admin (signed in on `page`) and a unique address to send to. */
async function newAdmin(alice: Api, page: Page): Promise<{ people: Record<'lena', Someone> }> {
  const people = await newPeople(alice, ['lena'], { platformAdmins: ['lena'], tagNames: true })
  await signInAs(page, people.lena)
  return { people }
}

test('AE-01: shows the settings in effect, credentials never; only platform admins get the page', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const config = await alice.emailConfig()
  await signIn(page, 'alice')
  await openEmailPage(page)
  await expect(
    page
      .getByRole('navigation', { name: 'Settings sections' })
      .getByRole('link', { name: 'Email' }),
  ).toHaveAttribute('aria-current', 'page')
  await expect(page.getByText('Email is on')).toBeVisible()
  const server = page.locator('#server')
  await expect(server).toContainText(`${config.host}:${config.port}`)
  await expect(server).toContainText(
    { none: 'None (plain SMTP)', starttls: 'STARTTLS', tls: 'TLS' }[config.security],
  )
  await expect(server).toContainText(config.from_address ?? '')
  await expect(server).toContainText(config.links_base_url)
  // Credentials: whether they are set, never their value (the API has none to give).
  expect(Object.keys(config)).not.toContain('password')
  expect(Object.keys(config)).not.toContain('username')
  await expect(server).toContainText(config.password_set ? 'Set (never shown)' : 'Not set')
  await expect(page.locator('main')).toContainText(
    `Every day at ${String(config.digest_hour).padStart(2, '0')}:00 (${config.timezone})`,
  )

  // Anyone else: a plain 404 page, and 403 from the API.
  const bob = await api('bob')
  expect((await bob.raw('GET', '/admin/email')).status()).toBe(403)
  expect((await bob.raw('POST', '/admin/email/test', {})).status()).toBe(403)
  await signIn(page, 'bob')
  await page.goto('/settings/email')
  await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
  await expect(banner(page)).toHaveCount(0)
})

test('AE-02: a test email arrives, says who sent it and from where, with no server details or unsubscribe link; the audit log has no address', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const { people } = await newAdmin(alice, page)
  const { lena } = people
  try {
    const config = await alice.emailConfig()
    const to = `ops.${uniqueSuffix()}@example.com`
    await openEmailPage(page)

    // One address only: a list is refused.
    const list = await lena.api.raw('POST', '/admin/email/test', {
      to: `${to},postmaster@example.com`,
    })
    expect(list.status()).toBe(422)

    const since = new Date()
    await page.getByRole('textbox', { name: 'Send to' }).fill(to)
    await page.getByRole('button', { name: 'Send test email' }).click()
    await expect(page.getByText(`Sent to ${to[0]}•••@example.com`)).toBeVisible({
      timeout: 30_000,
    })

    const mailpit = new Mailpit()
    const mail = await mailpit.waitForMessage(to, { since, subject: 'Soundings test email' })
    expect(mail.Subject).toBe('Soundings test email')
    const html = visibleText(mail.HTML)
    for (const text of [html, mail.Text]) {
      expect(text).toContain(config.links_base_url)
      expect(text).toContain(lena.name)
      expect(text).not.toContain(`${config.host}:${config.port}`) // no server details
      expect(text).not.toContain('/unsubscribe')
    }
    expectNoScoreData('test email', mail.Subject, html, mail.Text)
    const headers = await mailpit.headers(mail.ID)
    expect(headers['List-Unsubscribe']).toBeUndefined()
    expect(await emailCount({ email: to } as Someone, since)).toBe(1)

    // Audited as Lena, without the address.
    const entries = await alice.audit({ action: 'email.test_send', actor_id: lena.user.id })
    expect(entries).toHaveLength(1)
    expect(entries[0]?.details).toMatchObject({ to_self: false })
    expect(JSON.stringify(entries)).not.toContain(to)

    // The outbox lists it as sent, with the address masked.
    await openEmailPage(page, '?status=sent&type=test')
    const row = outboxTable(page)
      .getByRole('row')
      .filter({ hasText: `Test email from ${lena.name}` })
    await expect(row).toContainText('Sent')
    await expect(row).toContainText(`${to[0]}•••@example.com`)
    await expect(page.locator('main')).not.toContainText(to)
  } finally {
    await disposePeople(people)
  }
})

test(
  'AE-03: with Mailpit stopped a test email fails with its reason, admins see the banner, and Retry delivers it once Mailpit is back',
  { tag: '@smtp-outage' },
  async ({ page, browser, api }) => {
    test.setTimeout(3 * 60_000)
    requireMailpitControl()
    const alice = await api('alice')
    await requireEmail(alice)
    const { people } = await newAdmin(alice, page)
    const { lena } = people
    const mailpit = new Mailpit()
    const to = `ops.${uniqueSuffix()}@example.com`
    try {
      await openEmailPage(page)
      await stopMailpit()
      try {
        await page.getByRole('textbox', { name: 'Send to' }).fill(to)
        await page.getByRole('button', { name: 'Send test email' }).click()
        const result = page.getByRole('alert').filter({ hasText: 'The test email failed' })
        // Refused on a published port; "failed" when the container name doesn't resolve.
        await expect(result).toContainText(/connection (refused|failed)/, { timeout: 30_000 })
        await expect(result).toContainText('check the host, port')

        // Platform admins now see the banner everywhere but here; others never do.
        await page.goto('/')
        await expect(banner(page)).toContainText('Some emails aren’t going out.')
        expect((await lena.api.notificationSummary()).email_trouble).toBe(true)
        expect((await (await api('bob')).notificationSummary()).email_trouble).toBe(false)
        const bobPage = await browser.newPage({ baseURL: test.info().project.use.baseURL })
        await signIn(bobPage, 'bob')
        await bobPage.goto('/')
        await expect(bobPage.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
        await expect(banner(bobPage)).toHaveCount(0)
        await bobPage.close()
      } finally {
        await startMailpit()
      }

      // The banner leads to the page, which opens on failed email.
      await banner(page).getByRole('link', { name: 'Open Email settings' }).click()
      await expect(page).toHaveURL(/\/settings\/email$/)
      await expect(page.getByRole('button', { name: 'Remove status filter' })).toBeVisible()
      const row = outboxTable(page)
        .getByRole('row')
        .filter({ hasText: `Test email from ${lena.name}` })
      await expect(row).toContainText('Failed')
      await expect(row).toContainText('1 of 1 attempt')
      await expect(row).toContainText(/connection (refused|failed)/)

      const since = new Date()
      await row.getByRole('button', { name: `Retry: Test email from ${lena.name}` }).click()
      await expect(row).toContainText(/Queued|Sending|Sent/)
      const mail = await mailpit.waitForMessage(to, { since, subject: 'Soundings test email' })
      expect(mail.To.map((address) => address.Address)).toEqual([to])
      await page.waitForTimeout(2000)
      expect(await emailCount({ email: to } as Someone, since)).toBe(1)

      const [sent] = (await alice.outbox({ type: 'test' })).filter(
        (email) => email.requested_by?.id === lena.user.id,
      )
      expect(sent).toMatchObject({ status: 'sent', last_error: null, retryable: false })
      const retried = await alice.audit({ action: 'email.retry', actor_id: lena.user.id })
      expect(retried).toHaveLength(1)
      expect(JSON.stringify(retried)).not.toContain(to)
      // Mail flows again and nothing failed in the last day: the banner clears itself.
      expect((await lena.api.notificationSummary()).email_trouble).toBe(false)
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
      await expect(banner(page)).toHaveCount(0)
    } finally {
      if (!(await mailpit.isUp())) await startMailpit()
      await disposePeople(people)
    }
  },
)

test('AE-04: without SMTP admins see a calm banner and the setup steps; the test email is refused; in-app still works', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  test.skip(
    (await alice.notificationSummary()).email_available,
    'only on a stack without SMTP (E2E_SMTP=0)',
  )
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(banner(page)).toContainText(
    'Email isn’t set up: people only get in-app notifications.',
  )
  await banner(page).getByRole('link', { name: 'Set up email' }).click()
  await expect(page.getByRole('heading', { name: 'Set up email' })).toBeVisible()
  await expect(page.getByText('smtp.host', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send test email' })).toBeDisabled()
  const refused = await alice.raw('POST', '/admin/email/test', {})
  expect(refused.status()).toBe(409)
  expect(((await refused.json()) as { code: string }).code).toBe('smtp_not_configured')
  const config = await alice.emailConfig()
  expect(config.configured).toBe(false)

  // Someone who isn't a platform admin sees no banner.
  await signIn(page, 'bob')
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await expect(banner(page)).toHaveCount(0)
})
