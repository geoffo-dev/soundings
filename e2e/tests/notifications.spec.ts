import type { Page } from '@playwright/test'

import { daysFromNow } from './support/api'
import { disposePeople, newPeople, projectWithIdea, signInAs } from './support/email'
import { evaluateSheet, expect, heading, signIn, test } from './support/fixtures'

/**
 * In-app notifications (contract-phase3 §3.2, §3.3) on the real stack: the bell's
 * unread count, the inbox (popover and page), marking read, and where each item leads.
 * Every test works with new people in a fresh project (tests/support/email.ts), so
 * counts are exact. Test plan: NO-*.
 */

const bell = (page: Page) => page.getByRole('button', { name: /^Notifications/ })
const panel = (page: Page) => page.getByRole('dialog', { name: 'Notifications' })

/** A mention token as the SPA's picker inserts it (contract-phase3 §3.8). */
const mention = (person: { name: string; user: { id: string } }) =>
  `@[${person.name}](user:${person.user.id})`

test('NO-01: the bell counts unread notifications; opening one leads to the right place and reads the idea’s news', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const { key, title } = await projectWithIdea(alice, 'Inbox', [nora, theo], { owner: nora })
    await alice.inviteUsers(key, [theo.user], daysFromNow(5))
    const { comment } = await nora.api.comment(
      key,
      `${mention(theo)} can you check the courier API?`,
    )

    await signInAs(page, theo)
    await page.goto('/')
    await expect(heading(page, 'My work')).toBeVisible()
    await expect(bell(page)).toHaveAccessibleName('Notifications, 2 unread')

    await bell(page).click()
    const inbox = panel(page)
    await expect(inbox.getByRole('heading', { name: 'Today' })).toBeVisible()
    const mentioned = inbox.getByRole('link', {
      name: /^Unread: Nora Quinn mentioned you: “@Theo Marsh can you check the courier API\?”/,
    })
    await expect(mentioned).toContainText(key)
    await expect(mentioned).toContainText(title)
    const invited = inbox.getByRole('link', {
      name: /^Unread: Alice Anders asked you to evaluate, due /,
    })
    await expect(invited).toBeVisible()
    await expect(inbox.getByRole('link', { name: /^Unread: / })).toHaveCount(2)

    // The invitation opens the evaluate sheet; visiting the idea reads both.
    await invited.click()
    await expect(page).toHaveURL(new RegExp(`/ideas/${key}\\?evaluate=1$`))
    await expect(evaluateSheet(page)).toBeVisible()
    await expect(evaluateSheet(page)).toContainText(title)
    await page.keyboard.press('Escape')
    await expect(bell(page)).toHaveAccessibleName('Notifications')
    expect((await theo.api.notificationSummary()).unread_count).toBe(0)

    // Read items stay in the list; the mention leads to its comment.
    await bell(page).click()
    await panel(page)
      .getByRole('link', { name: /^Nora Quinn mentioned you/ })
      .click()
    await expect(page).toHaveURL(new RegExp(`/ideas/${key}#comment-${comment.id}$`))
    const article = page.locator(`article[data-comment-id="${comment.id}"]`)
    await expect(article).toBeFocused()
    await expect(article.locator('[data-mention]')).toHaveText('@Theo Marsh')
  } finally {
    await disposePeople(people)
  }
})

test('NO-02: the inbox page filters unread, marks one read when opened and all read at once', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const first = await projectWithIdea(alice, 'Inbox page', [nora, theo], { owner: nora })
    const second = await alice.createIdea(first.project.slug, {
      title: `Returns label printing ${first.project.key}`,
      summary: 'Print the label at home or in a shop.',
    })
    await alice.changeStatus(second.key, 'evaluating')
    const third = await alice.createIdea(first.project.slug, {
      title: `Exchange instead of refund ${first.project.key}`,
      summary: 'Offer an exchange first.',
    })
    await alice.inviteUsers(first.key, [theo.user], daysFromNow(5))
    await alice.inviteUsers(second.key, [theo.user])
    await alice.setOwnerUser(third.key, theo.user)

    await signInAs(page, theo)
    await page.goto('/notifications')
    await expect(heading(page, 'Notifications')).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: 'Today' })).toBeVisible()
    await expect(page.getByRole('link', { name: /^Unread: / })).toHaveCount(3)
    await expect(
      page.getByRole('link', { name: /^Unread: Alice Anders made you the owner\. / }),
    ).toContainText(third.key)
    // Invitations say when they are due (a date, never a countdown).
    await expect(
      page.getByRole('link', {
        name: new RegExp(
          `^Unread: Alice Anders asked you to evaluate, due \\w{3}, \\d+ \\w+\\. ${second.key} `,
        ),
      }),
    ).toBeVisible()

    // j moves through the rows; Enter opens the focused one.
    await page.keyboard.press('j')
    await expect(page.getByRole('link', { name: /^Unread: / }).first()).toBeFocused()

    await page.getByRole('radio', { name: 'Unread (3)' }).click()
    await expect(page).toHaveURL(/\/notifications\?unread=1$/)
    await page
      .getByRole('link', { name: new RegExp(`asked you to evaluate, due .*${first.key} `) })
      .click()
    await expect(page).toHaveURL(new RegExp(`/ideas/${first.key}\\?evaluate=1$`))
    await expect(evaluateSheet(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(bell(page)).toHaveAccessibleName('Notifications, 2 unread')

    await page.goto('/notifications?unread=1')
    await expect(page.getByRole('link', { name: /^Unread: / })).toHaveCount(2)
    await page.getByRole('button', { name: 'Mark all read' }).click()
    await expect(page.getByRole('heading', { name: 'You’re all caught up' })).toBeVisible()
    await expect(bell(page)).toHaveAccessibleName('Notifications')
    expect((await theo.api.notifications(true)).length).toBe(0)
    expect((await theo.api.notifications()).length).toBe(3)
  } finally {
    await disposePeople(people)
  }
})

test('NO-03: losing access to a project hides its notifications from the inbox and the count', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const { project, key } = await projectWithIdea(alice, 'Inbox access', [nora, theo], {
      owner: nora,
    })
    await alice.inviteUsers(key, [theo.user])
    expect((await theo.api.notificationSummary()).unread_count).toBe(1)

    await alice.send('DELETE', `/projects/${project.slug}/members/${theo.user.id}`, undefined, 204)
    expect((await theo.api.notificationSummary()).unread_count).toBe(0)
    expect(await theo.api.notifications()).toEqual([])

    await signInAs(page, theo)
    await page.goto('/notifications')
    await expect(heading(page, 'Notifications')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'No notifications yet' })).toBeVisible()
    await expect(page.locator('main')).not.toContainText(key)
    await expect(bell(page)).toHaveAccessibleName('Notifications')
  } finally {
    await disposePeople(people)
  }
})

test('NO-04: the seeded inbox: Alice’s notifications by day, with the bell and “g i”', async ({
  page,
}) => {
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  await page.keyboard.press('g')
  await page.keyboard.press('i')
  await expect(page).toHaveURL(/\/notifications$/)
  await expect(heading(page, 'Notifications')).toBeVisible()
  // The demo story: reminders, comments and mentions over the past weeks, older ones read.
  const rows = page.locator('main').getByRole('link', { name: /CUST-|TOOLS-|GREEN-/ })
  await expect(rows.first()).toBeVisible()
  expect(await rows.count()).toBeGreaterThan(3)
  await expect(page.locator('main')).not.toContainText(/\b[1-5]\.\d\b/) // no scores
})
