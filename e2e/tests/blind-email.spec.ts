import type { Page } from '@playwright/test'

import { defaultRubricScores, type NotificationItem } from './support/api'
import {
  disposePeople,
  emailTo,
  expectNoScoreData,
  Mailpit,
  newPeople,
  projectWithIdea,
  requireEmail,
  signInAs,
  visibleText,
  type Someone,
} from './support/email'
import { expect, heading, test } from './support/fixtures'

/**
 * Blind evaluation in email and the inbox (role matrix §3 rules 1 and 8; contract-phase3
 * §1, §3.11): with a submitted evaluation, an aggregate and a recommendation on the idea,
 * nothing a pending evaluator receives (invitation, mention, comment and status emails;
 * inbox items in the API and on screen) carries score data or the other evaluator's
 * comment, and neither does the owner's "all evaluations are in" email: emails never
 * carry scores, for anyone. Test plan: BE-*.
 */

const PRIVATE_COMMENT = 'Courier contract renewal is the real risk here'
const SCORE_KEYS =
  /^(score|scores|aggregate|overall|n|high_disagreement|recommendation|recommendations|means|rank)$/

/** Every key in `value` (depth first). */
function* keys(value: unknown): Generator<string> {
  if (Array.isArray(value)) {
    for (const item of value) yield* keys(item)
  } else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      yield key
      yield* keys(item)
    }
  }
}

function expectBlindItems(items: NotificationItem[]) {
  expect(items.length).toBeGreaterThan(0)
  for (const item of items) {
    const found = [...keys(item)].filter((key) => SCORE_KEYS.test(key))
    expect(found, item.type).toEqual([])
    expect(JSON.stringify(item)).not.toContain(PRIVATE_COMMENT)
  }
}

/** Every email to `person` since `since`, read in full, newest first. */
async function mailsTo(person: Someone, since: Date) {
  const mailpit = new Mailpit()
  const summaries = await mailpit.messagesTo(person.email, { since })
  return Promise.all(summaries.map((summary) => mailpit.message(summary.ID)))
}

async function inboxText(page: Page): Promise<string> {
  await page.goto('/notifications')
  await expect(heading(page, 'Notifications')).toBeVisible()
  await expect(
    page
      .locator('main')
      .getByRole('link', { name: /Unread: / })
      .first(),
  ).toBeVisible()
  return page.locator('main').innerText()
}

test('BE-01: a pending evaluator’s emails and inbox carry no score data; the owner’s “all in” email neither', async ({
  page,
  api,
}) => {
  test.slow()
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['nora', 'theo', 'iris'])
  const { nora, theo, iris } = people
  try {
    const { key, title } = await projectWithIdea(alice, 'Blind email', [nora, theo, iris], {
      owner: nora,
    })
    // Iris wants everything at once, so every type she gets is mailed.
    await iris.api.setPreferences({ status_changed: 'immediate', comment: 'immediate' })
    const since = new Date()

    // Theo evaluates and submits: the idea now has an aggregate and a recommendation.
    await nora.api.inviteUsers(key, [theo.user, iris.user])
    await theo.api.evaluate(key, defaultRubricScores(5, 4, 2, 5, 1), {
      recommendation: 'go',
      comment: PRIVATE_COMMENT,
    })
    // The owner (not an evaluator) sees the aggregate in the app; Iris doesn't.
    expect((await nora.api.idea(key)).aggregate).not.toBeNull()
    expect((await iris.api.idea(key)).score_hidden).toBe(true)

    // News for Iris, still pending: a mention, a comment, a status change.
    await nora.api.comment(key, `@[Iris Vale](user:${iris.user.id}) when you have a moment?`)
    await theo.api.comment(key, 'Submitted mine, thanks Nora.')
    await alice.changeStatus(key, 'shortlisted')

    await emailTo(iris, /moved to Shortlisted/, since)
    await emailTo(iris, /Theo Marsh commented/, since)
    await emailTo(iris, /Nora Quinn mentioned you/, since)
    await emailTo(iris, /Please evaluate/, since)
    const mails = await mailsTo(iris, since)
    expect(mails.length).toBeGreaterThanOrEqual(4)
    for (const mail of mails) {
      const html = visibleText(mail.HTML)
      expectNoScoreData(`to Iris: ${mail.Subject}`, mail.Subject, html, mail.Text)
      for (const text of [mail.HTML, mail.Text]) expect(text).not.toContain(PRIVATE_COMMENT)
    }

    // The inbox, as the API sends it and as the page shows it.
    expectBlindItems(await iris.api.notifications())
    await signInAs(page, iris)
    const text = await inboxText(page)
    expect(text).toContain(title)
    expect(text).not.toMatch(/\b[1-5]\.\d\b/)
    expect(text).not.toContain(PRIVATE_COMMENT)
    expect(text).not.toMatch(/\b(score|aggregate|recommend)/i)

    // Iris submits too: Nora hears that all evaluations are in, with a count only.
    const ownerSince = new Date()
    await iris.api.evaluate(key, defaultRubricScores(2, 3, 4, 2, 4), {
      recommendation: 'no',
      comment: 'Not this quarter.',
    })
    const allIn = await emailTo(nora, /evaluations are in/, ownerSince)
    expect(allIn.Subject).toBe(`[${key}] All 2 evaluations are in for "${title}"`)
    expectNoScoreData('to Nora', allIn.Subject, visibleText(allIn.HTML), allIn.Text)
    for (const text of [allIn.HTML, allIn.Text]) {
      expect(text).not.toContain(PRIVATE_COMMENT)
      expect(text).not.toContain('Not this quarter.')
    }
    expectBlindItems(await nora.api.notifications())
  } finally {
    await disposePeople(people)
  }
})

test('BE-02: the seeded blind idea: Alice’s reminder for CUST-14 (pending) and her inbox carry no score data', async ({
  page,
  api,
}) => {
  // Seeded story: Alice is a pending evaluator on CUST-14 (due in two days, so the
  // worker's first schedule run sent her the 2-day reminder) and on CUST-11.
  const alice = await api('alice')
  const items = await alice.notifications()
  expectBlindItems(items.filter((item) => ['CUST-14', 'CUST-11'].includes(item.idea.key)))
  for (const item of items) {
    const found = [...keys(item)].filter((key) => SCORE_KEYS.test(key))
    expect(found, `${item.type} ${item.idea.key}`).toEqual([])
  }
  const reminders = (await new Mailpit().messagesTo('alice@example.com')).filter((message) =>
    message.Subject.startsWith('[CUST-14] Reminder:'),
  )
  for (const summary of reminders) {
    const mail = await new Mailpit().message(summary.ID)
    expectNoScoreData('seeded reminder', mail.Subject, visibleText(mail.HTML), mail.Text)
  }
  await signInAs(page, { user: alice.me } as Someone)
  await page.goto('/notifications')
  await expect(heading(page, 'Notifications')).toBeVisible()
  await expect(page.locator('main').getByRole('link').first()).toBeVisible()
  await expect(page.locator('main')).not.toContainText(/\b[1-5]\.\d\b/)
})
