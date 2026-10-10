import type { Page } from '@playwright/test'

import { daysFromNow, type Api } from './support/api'
import {
  disposePeople,
  emailCount,
  emailTo,
  expectNoScoreData,
  links,
  Mailpit,
  newPeople,
  pickOnLoginPage,
  projectWithIdea,
  quietOutbox,
  requireEmail,
  requireMailpitControl,
  signInAs,
  startMailpit,
  stopMailpit,
  visibleText,
} from './support/email'
import { evaluateSheet, expect, openIdea, primaryAction, signIn, test } from './support/fixtures'

/**
 * Phase 3 acceptance (SPEC section 13; contract-phase3 §3.14) against the real stack:
 * the API, the worker and Mailpit. Test plan: AC3-*.
 *
 * AC3-01: the owner invites an evaluator in the browser; one branded email arrives (HTML
 * and text, unsubscribe headers); its button opens the evaluate sheet on that idea for
 * the evaluator after signing in.
 *
 * AC3-02 (`@smtp-outage`, runs after every other spec, alone): Mailpit is stopped, the
 * invitation waits in the outbox (Admin → Email shows it retrying), and it is delivered
 * once after Mailpit starts again.
 */

/**
 * A stopped Mailpit: "connection refused" on a published port (the local stack), or
 * "connection failed" when its container name no longer resolves (`make demo`, CI).
 */
const REFUSED = /connection (refused|failed)/

/** AC3-02's outage: two attempts 30 s apart (polled for up to 90 s), then Admin → Email. */
const OUTAGE_MS = 150_000

/** "Thu 8 Oct": the date as emails write it (Python's `%a %-d %b`) in the instance zone. */
function emailDay(iso: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone,
  }).formatToParts(new Date(iso))
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `${part('weekday')} ${part('day')} ${part('month')}`
}

/** `YYYY-MM-DD` for today + `days` in the browser's time zone (the date input's format). */
function dateInDays(page: Page, days: number): Promise<string> {
  return page.evaluate((n) => {
    const d = new Date()
    d.setDate(d.getDate() + n)
    const pad = (v: number) => String(v).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }, days)
}

async function linksBase(admin: Api): Promise<{ base: string; timezone: string }> {
  const config = await admin.emailConfig()
  return { base: config.links_base_url.replace(/\/$/, ''), timezone: config.timezone }
}

test('AC3-01: an invited evaluator gets one branded email whose link opens the evaluate sheet', async ({
  page,
  browser,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const { key, title } = await projectWithIdea(alice, 'Email acceptance', [nora, theo], {
      owner: nora,
    })
    const { base, timezone } = await linksBase(alice)

    // Nora, the owner, invites Theo from the idea page with a due date a week out.
    await signInAs(page, nora)
    await openIdea(page, key)
    await expect(primaryAction(page)).toHaveAccessibleName('Invite evaluators')
    const since = new Date()
    await primaryAction(page).click()
    const invite = page.getByRole('dialog', { name: 'Invite evaluators' })
    await invite.getByRole('combobox', { name: 'Evaluators' }).fill('Theo')
    await invite.getByRole('option', { name: /Theo Marsh/ }).click()
    await invite.getByLabel('Due date').fill(await dateInDays(page, 7))
    await invite.getByRole('button', { name: 'Invite', exact: true }).click()
    await expect(invite).toBeHidden()
    // The dialog closes at once; the request lands a moment later.
    await expect.poll(async () => (await alice.idea(key)).evaluation_due_at).not.toBeNull()
    const due = (await alice.idea(key)).evaluation_due_at

    // AC3-01a: one email to Theo, within seconds, branded, in both parts.
    const mail = await emailTo(theo, /Please evaluate/, since)
    expect(mail.Subject).toBe(
      `[${key}] Please evaluate "${title}" by ${emailDay(due ?? '', timezone)}`,
    )
    expect(mail.To.map((to) => to.Address)).toEqual([theo.email])
    expect(mail.From.Address).toBeTruthy()
    expect(mail.HTML).toContain('<table')
    expect(mail.HTML).toMatch(/<meta name="color-scheme" content="light dark"/)
    const html = visibleText(mail.HTML)
    for (const text of [html, mail.Text]) {
      expect(text).toContain('Soundings') // the wordmark and the footer
      expect(text).toContain(title)
      expect(text).toContain(key)
      expect(text).toContain('Nora Quinn')
    }
    expectNoScoreData('invitation', mail.Subject, html, mail.Text)

    // The button and the text part lead to the evaluate sheet of this idea.
    const evaluate = `${base}/ideas/${key}?evaluate=1`
    expect(links(mail)).toContain(evaluate)
    expect(mail.Text).toContain(evaluate)
    // The footer: preferences and this type's unsubscribe link (also in the headers).
    expect(links(mail)).toContain(`${base}/settings/notifications`)
    expect(links(mail).some((href) => href.startsWith(`${base}/unsubscribe?token=`))).toBe(true)
    const mailpit = new Mailpit()
    const headers = await mailpit.headers(mail.ID)
    const listUnsubscribe = headers['List-Unsubscribe']?.[0] ?? ''
    expect(listUnsubscribe.startsWith(`<${base}/api/v1/unsubscribe?token=`)).toBe(true)
    expect(headers['List-Unsubscribe-Post']).toEqual(['List-Unsubscribe=One-Click'])
    expect(headers['Auto-Submitted']).toEqual(['auto-generated'])
    const raw = await mailpit.raw(mail.ID)
    expect(raw).toMatch(/Content-Type: multipart\/alternative/i)
    expect(raw).toMatch(/Content-Type: text\/plain/i)
    expect(raw).toMatch(/Content-Type: text\/html/i)

    // Exactly one: give the worker a moment more, the count stays 1.
    await page.waitForTimeout(2000)
    expect(await emailCount(theo, since, /Please evaluate/)).toBe(1)

    // AC3-01b: Theo opens the button's link in a browser that isn't signed in: the login
    // page keeps it, and after signing in the evaluate sheet is open on that idea.
    const context = await browser.newContext({ baseURL: test.info().project.use.baseURL })
    const theoPage = await context.newPage()
    try {
      await theoPage.goto(evaluate)
      await expect(theoPage).toHaveURL(/\/login\?next=/)
      await pickOnLoginPage(theoPage, theo)
      await expect(theoPage).toHaveURL(new RegExp(`/ideas/${key}\\?evaluate=1$`))
      // The sheet is modal (the page behind it is hidden from assistive tech): it names
      // the idea itself.
      const sheet = evaluateSheet(theoPage)
      await expect(sheet).toBeVisible()
      await expect(sheet).toContainText(`${key} · ${title}`)
      await expect(sheet.getByRole('radiogroup', { name: 'Value', exact: true })).toBeVisible()
    } finally {
      await context.close()
    }
  } finally {
    await disposePeople(people)
  }
})

test(
  'AC3-02: with Mailpit stopped the invitation waits in the outbox, retrying; it arrives once when Mailpit is back',
  { tag: '@smtp-outage' },
  async ({ page, api }) => {
    // Up to eight minutes more for quietOutbox (the hourly schedule, other mail).
    test.setTimeout(12 * 60_000)
    requireMailpitControl()
    const alice = await api('alice')
    await requireEmail(alice)
    // Lena, a platform admin, sends quietOutbox's test email.
    const people = await newPeople(alice, ['nora', 'iris', 'lena'], { platformAdmins: ['lena'] })
    const { nora, iris, lena } = people
    const mailpit = new Mailpit()
    try {
      const { key } = await projectWithIdea(alice, 'Email outage', [nora, iris], { owner: nora })
      await signIn(page, 'alice')

      // Mailpit stays down for the two attempts and the Admin → Email checks: at most
      // OUTAGE_MS, with the worker's breaker closed and no other email due meanwhile (or
      // the breaker would postpone this one without trying it).
      await quietOutbox(lena.api, OUTAGE_MS)
      await stopMailpit()
      let since = new Date()
      let emailId = ''
      try {
        expect(await mailpit.isUp()).toBe(false)
        since = new Date()
        await nora.api.inviteUsers(key, [iris.user], daysFromNow(7))

        // The worker tries at once and again 30 s later: refused both times, still queued.
        await expect
          .poll(
            async () => {
              const rows = await alice.outbox({ status: 'queued' })
              const row = rows.find((email) => email.recipient?.id === iris.user.id)
              emailId = row?.id ?? ''
              return row ? { attempts: row.attempts, error: row.last_error } : null
            },
            { timeout: 90_000, intervals: [1000] },
          )
          .toEqual({ attempts: 2, error: expect.stringMatching(REFUSED) })

        // Admin → Email shows it queued, with the attempts, the error and the next try.
        await page.goto('/settings/email?status=queued')
        await expect(page.getByRole('heading', { level: 2, name: 'Email' })).toBeVisible()
        const row = page
          .getByRole('table', { name: 'Outbox emails' })
          .getByRole('row')
          .filter({ hasText: 'Iris Vale' })
          .filter({ hasText: key })
        await expect(row).toContainText('Queued')
        await expect(row).toContainText('2 of 12 attempts')
        await expect(row).toContainText(REFUSED)
        await expect(row).toContainText(/Next try/)
        await expect(row).toContainText(key)
        await expect(page.locator('main')).not.toContainText(iris.email)
      } finally {
        await startMailpit()
      }

      // Back up: the next attempt (about a minute after the second) delivers it, once.
      const mail = await emailTo(iris, /Please evaluate/, since, 150_000)
      expect(mail.Subject).toContain(`[${key}]`)
      await expect
        .poll(async () => (await alice.outboxEmail(emailId)).status, { timeout: 30_000 })
        .toBe('sent')
      const sent = await alice.outboxEmail(emailId)
      expect(sent.attempts).toBe(3)
      expect(sent.last_error).toBeNull()
      await page.waitForTimeout(3000) // nothing else follows
      expect(await emailCount(iris, since)).toBe(1)

      await page.goto('/settings/email?status=sent')
      await expect(
        page
          .getByRole('table', { name: 'Outbox emails' })
          .getByRole('row')
          .filter({ hasText: 'Iris Vale' })
          .filter({ hasText: key }),
      ).toContainText('Sent')
    } finally {
      if (!(await mailpit.isUp())) await startMailpit()
      await disposePeople(people)
    }
  },
)
