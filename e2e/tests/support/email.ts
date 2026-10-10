import type { Browser, Page } from '@playwright/test'

import {
  canControlMailpit,
  links,
  Mailpit,
  startMailpit,
  stopMailpit,
  type Message,
} from '../../scripts/mailpit.ts'
import {
  Api,
  createTeamProject,
  uniqueSuffix,
  type CurrentUser,
  type OutboxEmail,
  type Project,
} from './api'
import { expect, test } from './fixtures'

export { canControlMailpit, links, Mailpit, startMailpit, stopMailpit, type Message }

/**
 * Helpers for the Phase 3 specs (email and notifications, docs/test-plans/phase-3.md).
 *
 * Mail is read back from the stack's Mailpit (`e2e/scripts/mailpit.ts`). Its inbox is
 * shared by every spec of the run, and preferences are per person, so each test that
 * reads mail or changes preferences works with **new people** (`newPeople`): accounts
 * created through the admin API with run-unique addresses (`nora.k3x9a@example.com`),
 * in a fresh private project. Nobody else gets their mail; nothing they change touches
 * the seeded story.
 *
 * The worker sends immediate email within a second or two of the request; the specs that
 * stop Mailpit (`@smtp-outage`) run in their own project after everything else
 * (playwright.config.ts), one at a time.
 */

/** A person a test created: the account plus a signed-in API client. */
export interface Someone {
  user: CurrentUser
  api: Api
  email: string
  name: string
}

/** First and last names for new people (no seeded name or email contains these). */
const NAMES = {
  nora: 'Nora Quinn',
  theo: 'Theo Marsh',
  iris: 'Iris Vale',
  owen: 'Owen Pike',
  lena: 'Lena Ford',
  ravi: 'Ravi Shah',
} as const
export type NewPerson = keyof typeof NAMES

/**
 * Creates `names` as new active accounts (Alice's admin API) and signs each in through
 * the API. Their addresses are unique to this call: `<first>.<suffix>@example.com`.
 * `platformAdmins` also makes those platform admins (their own test-email rate limit);
 * `tagNames` appends the suffix to their names too ("Lena Ford K3X"), for lists that
 * show only names (the outbox) when a spec may run twice at once.
 */
export async function newPeople<const N extends NewPerson>(
  admin: Api,
  names: readonly N[],
  options: { platformAdmins?: readonly N[]; tagNames?: boolean } = {},
): Promise<Record<N, Someone>> {
  const suffix = uniqueSuffix()
  const people = {} as Record<N, Someone>
  for (const first of names) {
    const email = `${first}.${suffix}@example.com`
    const name = options.tagNames
      ? `${NAMES[first]} ${suffix.slice(-3).toUpperCase()}`
      : NAMES[first]
    const created = await admin.createUser({
      email,
      display_name: name,
      is_platform_admin: options.platformAdmins?.includes(first) ?? false,
    })
    const user = { ...created, auth_method: 'dev_login' } as unknown as CurrentUser
    people[first] = {
      user,
      api: await Api.asUser(admin.baseURL, user),
      email,
      name,
    }
  }
  return people
}

/** Signs the people's API clients out (call in `finally`). */
export async function disposePeople(people: Record<string, Someone>) {
  for (const person of Object.values(people)) await person.api.dispose()
}

/**
 * A fresh private project (Alice is its admin) with `members` as members, and one idea
 * in Evaluating owned by `owner` (if given).
 */
export async function projectWithIdea(
  admin: Api,
  name: string,
  members: Someone[],
  options: { owner?: Someone; title?: string } = {},
): Promise<{ project: Project; key: string; title: string }> {
  const project = await createTeamProject(admin, name, {})
  for (const member of members) await admin.addMemberUser(project.slug, member.user)
  const title = options.title ?? `Self-service returns portal ${project.key}`
  const idea = await admin.createIdea(project.slug, {
    title,
    summary: 'Customers start a return from their order page without calling us.',
  })
  if (options.owner) await admin.setOwnerUser(idea.key, options.owner.user)
  await admin.changeStatus(idea.key, 'evaluating')
  return { project, key: idea.key, title }
}

/** Signs `page`'s browser context in as a person a test created (dev login, via API). */
export async function signInAs(page: Page, person: Someone) {
  const response = await page.request.post('/api/v1/auth/dev/login', {
    data: { user_id: person.user.id },
  })
  expect(response.status()).toBe(200)
}

/** Picks a person on the real login page (by their unique email). */
export async function pickOnLoginPage(page: Page, person: Someone) {
  await page.getByRole('textbox', { name: 'Filter people' }).fill(person.email)
  await page.getByRole('button', { name: new RegExp(person.name) }).click()
}

/** A browser context signed in as `person`, for a second user in one test. */
export async function browserFor(browser: Browser, person: Someone): Promise<Page> {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL })
  const page = await context.newPage()
  await signInAs(page, person)
  return page
}

/**
 * Skips the test unless the app sends email (SMTP configured) and its Mailpit answers
 * (`E2E_SMTP=0` stacks and apps without `E2E_MAILPIT_URL`).
 */
export async function requireEmail(api: Api) {
  const summary = await api.notificationSummary()
  test.skip(!summary.email_available, 'needs SMTP (the e2e stack with E2E_SMTP=1)')
  test.skip(!(await new Mailpit().isUp()), 'needs the stack’s Mailpit (E2E_MAILPIT_URL)')
}

/** Skips unless this run may stop and start Mailpit (a Docker container it controls). */
export function requireMailpitControl() {
  test.skip(!canControlMailpit(), 'needs a Mailpit container to stop (E2E_MAILPIT_CONTAINER)')
}

/** The newest email to `person` matching `subject`, received at or after `since`. */
export function emailTo(
  person: Someone,
  subject: string | RegExp,
  since: Date,
  timeoutMs = 30_000,
): Promise<Message> {
  return new Mailpit().waitForMessage(person.email, { since, subject, timeoutMs })
}

/** How many emails `person` got at or after `since` (optionally only matching `subject`). */
export async function emailCount(
  person: Someone,
  since: Date,
  subject?: string | RegExp,
): Promise<number> {
  return (await new Mailpit().messagesTo(person.email, { since, subject })).length
}

/**
 * Waits until the worker has had time to send anything immediate (everything queued
 * before this call is sent, failed or cancelled), so "no email arrived" means none was
 * sent. Polls the admin outbox (Alice) for rows still queued or sending.
 */
export async function outboxSettled(admin: Api, timeoutMs = 20_000) {
  await expect
    .poll(
      async () => {
        const config = await admin.emailConfig()
        return config.outbox.queued + config.outbox.sending
      },
      { timeout: timeoutMs, message: 'the outbox should drain (is the worker running?)' },
    )
    .toBe(0)
}

const HOUR_MS = 3_600_000
/**
 * How long after the hour the worker's hourly `notification_schedule` (cron `0 * * * *`:
 * reminders and the day's digests, about 30 of them on its first run after the seed)
 * is taken to have queued what it sends.
 */
const SCHEDULE_SETTLE_MS = 60_000

/**
 * Waits for a moment when Mailpit can be stopped for `outageMs` with no email but the
 * spec's own falling due meanwhile. After five failed connections in a row the worker
 * stops trying anyone's email for a while (app/email/delivery.py `Breaker`: postponed,
 * no attempt counted), so a spec that counts its own email's attempts during an outage
 * can't share the outage with other mail, nor start it with the breaker still open from
 * an earlier one:
 * - the hourly schedule must not run before the outage ends, and its last run must be
 *   over;
 * - a test email from `admin` (a platform admin of the spec's own: admins may send five
 *   in 10 minutes) is sent first: test emails are always tried, so it closes the breaker;
 * - everything already queued (other specs' held or retried email, this spec's set-up)
 *   that is due before the outage ends is sent first, while Mailpit is up.
 */
export async function quietOutbox(admin: Api, outageMs: number, timeoutMs = 8 * 60_000) {
  await test.step('wait until no other email falls due during the outage', async () => {
    const deadline = Date.now() + timeoutMs
    let probed = false
    for (;;) {
      const intoHour = Date.now() % HOUR_MS
      let wait = 0
      if (intoHour < SCHEDULE_SETTLE_MS) wait = SCHEDULE_SETTLE_MS - intoHour
      else if (intoHour + outageMs > HOUR_MS) wait = HOUR_MS - intoHour + SCHEDULE_SETTLE_MS
      if (wait === 0 && !probed) {
        const probe = await admin.sendTestEmail()
        await expect
          .poll(async () => (await admin.outboxEmail(probe.id)).status, {
            timeout: 60_000,
            message: 'the test email should be sent (is Mailpit up?)',
          })
          .toBe('sent')
        probed = true
        continue
      }
      if (wait === 0) {
        const horizon = Date.now() + outageMs
        const due = (await pendingEmails(admin)).filter(
          (email) =>
            email.status === 'sending' ||
            !email.next_attempt_at ||
            Date.parse(email.next_attempt_at) <= horizon,
        )
        if (due.length === 0) return
        wait = 2000
      }
      if (Date.now() + wait > deadline) {
        throw new Error(`no quiet ${outageMs / 1000} s for the outage within ${timeoutMs / 1000} s`)
      }
      await new Promise((resolve) => setTimeout(resolve, wait))
    }
  })
}

/** Every queued or sending row of the outbox (all pages). */
async function pendingEmails(admin: Api): Promise<OutboxEmail[]> {
  const rows: OutboxEmail[] = []
  let cursor: string | null = null
  do {
    const query = new URLSearchParams({ limit: '200' })
    query.append('status', 'queued')
    query.append('status', 'sending')
    if (cursor) query.append('cursor', cursor)
    const page: { items: OutboxEmail[]; next_cursor: string | null } = await admin.get(
      `/admin/email/outbox?${query}`,
    )
    rows.push(...page.items)
    cursor = page.next_cursor
  } while (cursor)
  return rows
}

/** The visible text of an email's HTML part (no head, styles, tags or attributes). */
export function visibleText(html: string): string {
  return html
    .replace(/<(head|style)\b[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&#x27;/g, "'")
    .replace(/\s+/g, ' ')
}

/** Words and numbers that reveal score data (role matrix §3; contract-phase3 §1). */
export const SCORE_WORDS = /\b(score|scores|scored|aggregate|recommend\w*|disagree\w*)\b/i
export const SCORE_NUMBER = /\b[1-5]\.\d\b/

/** Asserts that none of `texts` reveals score data. */
export function expectNoScoreData(label: string, ...texts: string[]) {
  for (const text of texts) {
    expect(text, `${label}: score words`).not.toMatch(SCORE_WORDS)
    expect(text, `${label}: score numbers`).not.toMatch(SCORE_NUMBER)
  }
}

/** The unsubscribe token in an email's footer link (`/unsubscribe?token=…`). */
export function unsubscribeLink(message: Message): string {
  const link = links(message).find((href) => href.includes('/unsubscribe?token='))
  if (!link) throw new Error('the email has no unsubscribe link')
  return link
}

/** The footer's "Unsubscribe from all email" link (the only token scoped to all). */
export function unsubscribeAllLink(message: Message): string {
  const match = /href\s*=\s*"([^"]*)"[^>]*>Unsubscribe from all email</i.exec(message.HTML)
  if (!match?.[1]) throw new Error('the email has no “Unsubscribe from all email” link')
  return match[1].replaceAll('&amp;', '&')
}
