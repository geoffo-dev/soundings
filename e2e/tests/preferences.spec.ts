import type { Page } from '@playwright/test'

import { daysFromNow, type Api, type OutboxEmail } from './support/api'
import {
  disposePeople,
  emailCount,
  emailTo,
  newPeople,
  projectWithIdea,
  requireEmail,
  signInAs,
  type Someone,
} from './support/email'
import { expect, signIn, test } from './support/fixtures'

/**
 * Email preferences (contract-phase3 §3.4) on the real stack: Settings → Notifications
 * saves per type; `immediate` mails at once, `digest` and `off` don't (the inbox gets
 * everything either way). The digest email itself is built by the hourly schedule at
 * the digest hour, so it is checked where the clock can be moved: the backend's
 * tests/notifications/test_digest.py and the Mailpit acceptance
 * (backend/tests/acceptance/test_phase3_acceptance.py, AC3-API-3). Test plan: PR-*.
 */

const row = (page: Page, label: string) =>
  page.getByRole('radiogroup', { name: label, exact: true })

async function openPreferences(page: Page) {
  await page.goto('/settings/notifications')
  await expect(page.getByRole('heading', { level: 2, name: 'Email notifications' })).toBeVisible()
  await expect(page.getByRole('radiogroup')).toHaveCount(7)
}

async function choose(page: Page, label: string, mode: 'Immediate' | 'Daily digest' | 'Off') {
  await row(page, label).getByRole('radio', { name: mode }).click()
  await expect(row(page, label).getByRole('radio', { name: mode })).toBeChecked()
  await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
}

/** Outbox rows (any status) for `person` of `type`, as Admin → Email lists them. */
async function outboxRows(admin: Api, person: Someone, type: string): Promise<OutboxEmail[]> {
  return (await admin.outbox({ type })).filter((email) => email.recipient?.id === person.user.id)
}

test('PR-01: defaults per type; a change saves at once and “Reset” goes back to the default', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['theo'])
  const { theo } = people
  try {
    await signInAs(page, theo)
    await openPreferences(page)
    for (const label of [
      'Owner assignments',
      'Evaluation requests',
      'Evaluation reminders',
      'All evaluations are in',
      'Mentions',
    ]) {
      await expect(row(page, label).getByRole('radio', { name: 'Immediate' })).toBeChecked()
    }
    for (const label of ['Status changes', 'New comments']) {
      await expect(row(page, label).getByRole('radio', { name: 'Daily digest' })).toBeChecked()
    }
    const { digest_hour, timezone } = await theo.api.preferences()
    await expect(
      page.getByText(`${String(digest_hour).padStart(2, '0')}:00 (${timezone})`),
    ).toBeVisible()

    await choose(page, 'New comments', 'Off')
    let saved = await theo.api.preferences()
    expect(saved.items.find((item) => item.type === 'comment')?.mode).toBe('off')
    await page.getByRole('button', { name: 'Reset New comments to the default' }).click()
    await expect(
      row(page, 'New comments').getByRole('radio', { name: 'Daily digest' }),
    ).toBeChecked()
    saved = await theo.api.preferences()
    expect(saved.items.find((item) => item.type === 'comment')).toMatchObject({
      mode: 'digest',
      default_mode: 'digest',
    })

    // Survives a reload (stored on the server, not in the browser).
    await choose(page, 'Evaluation reminders', 'Daily digest')
    await page.reload()
    await expect(
      row(page, 'Evaluation reminders').getByRole('radio', { name: 'Daily digest' }),
    ).toBeChecked()
  } finally {
    await disposePeople(people)
  }
})

test('PR-02: “Off” for invitations: the inbox still gets it, no email is queued or sent', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const { key } = await projectWithIdea(alice, 'Prefs off', [nora, theo], { owner: nora })
    await signInAs(page, theo)
    await openPreferences(page)
    await choose(page, 'Evaluation requests', 'Off')

    const since = new Date()
    await nora.api.inviteUsers(key, [theo.user], daysFromNow(4))
    const inbox = await theo.api.notifications()
    expect(inbox.map((item) => [item.type, item.idea.key])).toEqual([['evaluator_invited', key]])
    expect(await outboxRows(alice, theo, 'evaluator_invited')).toEqual([])
    await page.waitForTimeout(3000)
    expect(await emailCount(theo, since)).toBe(0)
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Notifications, 1 unread' })).toBeVisible()
  } finally {
    await disposePeople(people)
  }
})

test('PR-03: “Daily digest” for mentions: in-app now, no email now (it waits for the digest)', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['nora', 'theo', 'iris'])
  const { nora, theo, iris } = people
  try {
    const { key } = await projectWithIdea(alice, 'Prefs digest', [nora, theo, iris], {
      owner: nora,
    })
    await signInAs(page, theo)
    await openPreferences(page)
    await choose(page, 'Mentions', 'Daily digest')

    // Nora mentions both: Iris (default: immediate) gets an email; Theo doesn't, yet.
    const since = new Date()
    await nora.api.comment(
      key,
      `@[Theo Marsh](user:${theo.user.id}) and @[Iris Vale](user:${iris.user.id}): the courier API?`,
    )
    const mail = await emailTo(iris, /Nora Quinn mentioned you/, since)
    expect(mail.Subject).toContain(`[${key}]`)
    const inbox = await theo.api.notifications()
    expect(inbox.map((item) => item.type)).toEqual(['mention'])
    expect(await outboxRows(alice, theo, 'mention')).toEqual([])
    expect(await emailCount(theo, since)).toBe(0)
  } finally {
    await disposePeople(people)
  }
})

test('PR-04: “Immediate” for status changes mails the evaluator; the owner’s default digest doesn’t', async ({
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const { key, title } = await projectWithIdea(alice, 'Prefs status', [nora, theo], {
      owner: nora,
    })
    await alice.inviteUsers(key, [theo.user])
    await theo.api.setPreferences({ status_changed: 'immediate' })

    const since = new Date()
    await alice.changeStatus(key, 'shortlisted')
    const mail = await emailTo(theo, /moved to/, since)
    expect(mail.Subject).toBe(`[${key}] "${title}" moved to Shortlisted`)
    expect(mail.Text).toContain('Evaluating')
    expect(mail.Text).toContain('Shortlisted')
    // Nora (owner, default: digest) has it in the inbox only.
    expect((await nora.api.notifications()).map((item) => item.type)).toContain('status_changed')
    expect(await outboxRows(alice, nora, 'status_changed')).toEqual([])
    expect(await emailCount(nora, since, /moved to/)).toBe(0)
  } finally {
    await disposePeople(people)
  }
})

test('PR-05: without SMTP the page says nothing is emailed for now; choices still save', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  test.skip(
    (await alice.notificationSummary()).email_available,
    'only on a stack without SMTP (E2E_SMTP=0)',
  )
  await signIn(page, 'erin')
  await openPreferences(page)
  await expect(page.getByText('Email isn’t set up on this server yet')).toBeVisible()
  await choose(page, 'Mentions', 'Daily digest')
  await choose(page, 'Mentions', 'Immediate')
})
