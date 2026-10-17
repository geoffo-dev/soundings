import type { Browser, Page } from '@playwright/test'

import { uniqueSuffix } from './support/api'
import {
  disposePeople,
  links,
  Mailpit,
  requireEmail,
  signInAs,
  visibleText,
  type Message,
} from './support/email'
import {
  bestPracticeViolations,
  expect,
  seriousViolations,
  settled,
  signIn,
  test,
} from './support/fixtures'
import {
  confirmationToken,
  conversation,
  ideaEmailsSettled,
  messagesPart,
  messagesSheet,
  messagingTeam,
  openMessages,
  sendPublicIdea,
  sendTeamMessage,
  teamMessages,
  trackedMessages,
  type MessagingTeam,
} from './support/messages'
import { fillPublicForm, humanCheckDone, PHONE, Visitor } from './support/public'

/**
 * Phase 11 (contract-phase11; test plan docs/test-plans/phase-11.md, SM-*): the team talks
 * to the person who sent a public idea, and the tracking link is emailed once the address
 * is confirmed, against the real stack (API, worker, Mailpit).
 *
 * Each test has a private project of its own with its public form on, owned ideas going to
 * Nora (a new person) and Theo (another) as a plain member, so nobody seeded gets mail or
 * notifications. The submitter is a signed-out browser or a `Visitor` (the public API, the
 * ALTCHA solved in Node) with a run-unique address.
 */

const PROJECT = 'Customer Innovation'

async function phoneFor(browser: Browser, baseURL: string): Promise<Page> {
  const context = await browser.newContext({ ...PHONE, baseURL })
  return context.newPage()
}

function text(message: Message): string {
  return `${message.Subject}\n${visibleText(message.HTML)}\n${message.Text}`.replace(/\s+/g, ' ')
}

/** Public pages and submitter emails never name a person (contract-phase11 §8). */
function expectNobodyNamed(label: string, shown: string, team: MessagingTeam, ...more: string[]) {
  for (const value of [
    team.owner.name,
    team.owner.email,
    team.member.name,
    'Alice Anders',
    'alice@',
    ...more,
  ]) {
    expect(shown, `${label} names nobody (${value})`).not.toContain(value)
  }
}

test('SM-01: the submitter sends an idea with an address, gets the link once confirmed, reads the team’s message and replies', async ({
  browser,
  api,
  baseURL,
}) => {
  test.setTimeout(240_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const mailpit = new Mailpit()
  const since = new Date()
  const email = `sam.${uniqueSuffix()}@example.org`
  const title = `Reusable delivery boxes ${team.project.key}`
  try {
    // --- The form says what the address is for; the receipt that the link follows ------
    const phone = await phoneFor(browser, baseURL ?? '')
    await phone.goto(`/${team.project.slug}/submit`)
    await expect(
      phone.getByText(
        'We’ll ask you to confirm it, then email you your private link. The team may write to you about this idea; you reply on your tracking page. Only the team’s admins can see your address.',
      ),
    ).toBeVisible()
    await expect(phone.getByText(/never show it to anyone/)).toHaveCount(0)
    await fillPublicForm(phone, {
      title,
      summary: 'Boxes customers hand back for a deposit.',
      name: 'Sam Public',
      email,
    })
    await humanCheckDone(phone)
    await phone.getByRole('button', { name: 'Send idea' }).tap()
    await expect(
      phone.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
    ).toBeFocused()
    // The confirm step leads (UX review m2); the link's warning is the link email's (m3).
    await expect(phone.getByText('Open the link we’ve just emailed you')).toBeVisible()
    await expect(
      phone.getByText(/Once you confirm, we’ll email you this link, and the team’s messages too\./),
    ).toBeVisible()
    await expect(
      phone.getByText(/anyone who has it can see where your idea stands, reply to the team/),
    ).toBeVisible()
    const privateLink = await phone.getByRole('textbox', { name: 'Your private link' }).inputValue()
    expect(await seriousViolations(phone)).toEqual([])

    // --- The confirmation email: no tracking link, and a sentence that it follows -------
    const confirmation = await mailpit.waitForMessage(email, {
      since,
      subject: `Confirm your idea for ${team.project.name}`,
    })
    expect(text(confirmation)).toContain(
      "Once you confirm, we'll email you a private link to follow your idea.",
    )
    expect(links(confirmation).filter((href) => href.includes('/track'))).toEqual([])
    const verifyLink = links(confirmation).find((href) => href.includes('/verify#'))
    if (!verifyLink) throw new Error('no confirmation link')
    await phone.goto(verifyLink)
    await phone.getByRole('button', { name: 'Confirm my email address' }).tap()
    await expect(
      phone.getByText('We’ve emailed you a private link to follow your idea.'),
    ).toBeVisible()
    expect(await seriousViolations(phone)).toEqual([])

    // --- The link email, once: its button is the private link -----------------------------
    const linkEmail = await mailpit.waitForMessage(email, {
      since,
      subject: `Your link to follow your idea for ${team.project.name}`,
    })
    expect(text(linkEmail)).toContain('See where your idea stands')
    expect(text(linkEmail)).toContain(
      'Keep this link private: anyone who has it can see where your idea stands, reply to the team and delete your details.',
    )
    expect(links(linkEmail)).toContain(privateLink)
    expectNobodyNamed('the link email', text(linkEmail), team)
    expect((await mailpit.headers(linkEmail.ID))['Reply-To']).toBeUndefined()
    // A second click: nothing more is sent.
    await phone.reload()
    await phone.getByRole('button', { name: 'Confirm my email address' }).tap()
    await expect(
      phone.getByText(
        'Your private tracking link (shown when you sent the idea) says what happens next.',
      ),
    ).toBeVisible()

    // --- The owner writes: an email signed by the team, and the tracking page ------------
    const [listed] = (await alice.listIdeas(team.project.slug)).items.filter(
      (item) => item.title === title,
    )
    if (!listed) throw new Error('the idea did not reach the team')
    const key = listed.key
    await alice.setOwnerUser(key, team.owner.user)
    const question = 'Thanks, Sam! Which stores did you have in mind?\n<b>We’d like two</b>.'
    await sendTeamMessage(team.owner.api, key, question)
    const messageEmail = await mailpit.waitForMessage(email, {
      since,
      subject: `A message about your idea for ${team.project.name}`,
    })
    const shown = text(messageEmail)
    expect(shown).toContain(`A message from the ${team.project.name} team`)
    expect(shown).toContain('Which stores did you have in mind?')
    expect(shown).toContain('<b>We’d like two</b>') // escaped, shown as typed
    expect(messageEmail.HTML).not.toContain('<b>We’d like two</b>')
    expect(shown).toContain(`The ${team.project.name} team`)
    expect(shown).toContain("Replies to this email aren't read: reply on your tracking page.")
    expect(links(messageEmail)).toContain(privateLink)
    expectNobodyNamed('the message email', shown, team, key)
    expect((await mailpit.headers(messageEmail.ID))['Reply-To']).toBeUndefined()

    await phone.goto(privateLink)
    await phone.reload()
    const section = trackedMessages(phone)
    await expect(section).toContainText(
      `The ${team.project.name} team wrote to you about your idea. We’ll also email you when they write again.`,
    )
    const rows = conversation(section)
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(`The ${team.project.name} team`)
    await expect(rows.first()).toContainText('<b>We’d like two</b>.')
    await expect(section.getByRole('link')).toHaveCount(0)
    expectNobodyNamed(
      'the tracking page',
      (await phone.locator('main').innerText()) ?? '',
      team,
      key,
    )

    // --- They reply (Ctrl+Enter), shown as "You"; the owner is told ----------------------
    const box = section.getByRole('textbox', { name: 'Reply to the team' })
    await box.fill('The two in the city centre.\nHappy to help with a trial.')
    await box.press('Control+Enter')
    await expect(rows).toHaveCount(2)
    await expect(rows.last()).toContainText('You')
    await expect(rows.last()).toContainText('The two in the city centre.')
    await expect(box).toHaveValue('')
    expect(await seriousViolations(phone)).toEqual([])
    await expect
      .poll(async () =>
        (await team.owner.api.notifications()).filter((item) => item.type === 'submitter_replied'),
      )
      .toHaveLength(1)
    const [newest] = await teamMessages(team.owner.api, key)
    expect(newest).toMatchObject({ direction: 'submitter', author: null })
  } finally {
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-02: the owner reads and writes in the panel with the keyboard; a member sees nothing of it', async ({
  page,
  browser,
  api,
  baseURL,
}) => {
  test.setTimeout(180_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  try {
    const email = `sam.${uniqueSuffix()}@example.org`
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Deposit boxes ${team.project.key}`,
      email,
      confirm: true,
    })
    await signInAs(page, team.owner)
    await page.goto(`/ideas/${idea.key}`)
    const part = messagesPart(page)
    await expect(part).toContainText('No messages yet.')
    expect(await seriousViolations(page)).toEqual([])
    expect(await bestPracticeViolations(page)).toEqual([])
    await part.getByRole('button', { name: 'Message the submitter…' }).click()
    await expect(page).toHaveURL(/\?submission=1$/)
    const sheet = messagesSheet(page, 'Sam Public')
    await expect(sheet).toBeVisible()
    await expect(sheet).toContainText(
      'Ask Sam Public something about their idea. They read and answer on their private tracking page.',
    )
    await expect(sheet).toContainText(
      `Emailed to them and shown on their tracking page, signed “The ${team.project.name} team”.`,
    )
    const box = sheet.getByRole('textbox', { name: 'Message to Sam Public' })
    await expect(box).toBeFocused()
    await box.fill('Thanks, Sam!\nWhich stores did you have in mind? https://example.org/x')
    await page.keyboard.press('Control+Enter')
    const rows = conversation(sheet)
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(team.owner.name)
    await expect(rows.first()).toContainText('By email too')
    await expect(rows.first()).toContainText('https://example.org/x')
    await expect(sheet.getByRole('link')).toHaveCount(0) // plain text, never a link
    await expect(box).toHaveValue('')
    await expect(box).toBeFocused()
    expect(await seriousViolations(page)).toEqual([])

    // An unsent message stays a draft: closed, reloaded, it is still there.
    await box.fill('Half a thought')
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()
    await expect(page).not.toHaveURL(/submission=/)
    await expect(part.getByRole('button', { name: 'Open messages' })).toBeFocused()
    await expect(part).toContainText(/1 message · The team wrote/)
    await page.reload()
    await part.getByRole('button', { name: 'Open messages' }).click()
    await expect(sheet.getByRole('textbox', { name: 'Message to Sam Public' })).toHaveValue(
      'Half a thought',
    )
    await sheet.getByRole('button', { name: /^Send/ }).click()
    await expect(rows).toHaveCount(2)
    // The conversation reads oldest first; the API pages newest first.
    await expect(rows.last()).toContainText('Half a thought')
    expect((await teamMessages(team.owner.api, idea.key)).map((m) => m.body)).toEqual([
      'Half a thought',
      'Thanks, Sam!\nWhich stores did you have in mind? https://example.org/x',
    ])

    // Theo, a member: no Messages part, ?submission=1 opens nothing, nothing is asked.
    const theo = await browser.newContext({ baseURL })
    const theoPage = await theo.newPage()
    const asked: string[] = []
    theoPage.on('request', (request) => {
      if (request.url().includes('/submission/messages')) asked.push(request.url())
    })
    await signInAs(theoPage, team.member)
    await theoPage.goto(`/ideas/${idea.key}?submission=1`)
    await expect(theoPage.getByRole('heading', { level: 1 })).toBeVisible()
    await settled(theoPage)
    await expect(theoPage).not.toHaveURL(/submission=/)
    await expect(messagesPart(theoPage)).toHaveCount(0)
    await expect(theoPage.getByRole('dialog')).toHaveCount(0)
    await expect(theoPage.getByText(/Half a thought|Which stores|Open messages/)).toHaveCount(0)
    expect(asked).toEqual([])
    const theirs = await team.member.api.submission(idea.key)
    expect(theirs.messages).toBeNull()
    expect(theirs.permissions.can_message).toBe(false)
    const refused = await team.member.api.raw('GET', `/ideas/${idea.key}/submission/messages`)
    expect(refused.status()).toBe(403)
    await theo.close()
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-03: an unconfirmed address: the panel says the tracking page only, and no message is emailed', async ({
  page,
  browser,
  api,
  baseURL,
}) => {
  test.setTimeout(180_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  const since = new Date()
  try {
    const email = `ana.${uniqueSuffix()}@example.org`
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Refill station ${team.project.key}`,
      email,
    })
    await signInAs(page, team.owner)
    await openMessages(page, idea.key, 'Sam Public')
    const sheet = messagesSheet(page, 'Sam Public')
    // Said plainly above the box when no email will reach them (UX review M1).
    await expect(sheet).toContainText('They won’t get an email')
    await expect(sheet).toContainText(
      `Shown on their tracking page only, signed “The ${team.project.name} team”.`,
    )
    await sheet.getByRole('textbox', { name: 'Message to Sam Public' }).fill('Thanks, Ana!')
    await sheet.getByRole('button', { name: /^Send/ }).click()
    await expect(conversation(sheet).first()).toContainText('Tracking page only')

    const track = await phoneFor(browser, baseURL ?? '')
    await track.goto(`/track#${idea.token}`)
    await expect(trackedMessages(track)).toContainText(
      'New messages appear on this page; confirm your email address to get them by email too.',
    )
    await ideaEmailsSettled(alice, idea.key)
    const received = await new Mailpit().messagesTo(email, { since })
    expect(received.map((message) => message.Subject)).toEqual([
      `Confirm your idea for ${team.project.name}`,
    ])
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-04: once the submitter deletes their details, the panel says there is no one to write to', async ({
  page,
  api,
  baseURL,
}) => {
  test.setTimeout(120_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  try {
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Bottle returns ${team.project.key}`,
      email: `erin.${uniqueSuffix()}@example.org`,
      confirm: true,
    })
    await sendTeamMessage(team.owner.api, idea.key, 'A question for you.')
    await visitor.replied(idea.token, 'Happy to help.')
    expect((await visitor.erase(idea.token)).status()).toBe(204)
    expect((await visitor.track(idea.token)).status()).toBe(404)

    await signInAs(page, team.owner)
    await page.goto(`/ideas/${idea.key}`)
    const part = messagesPart(page)
    await expect(part).toContainText('None: their details were erased.')
    await expect(part.getByRole('button')).toHaveCount(0)
    await page.goto(`/ideas/${idea.key}?submission=1`)
    const sheet = messagesSheet(page)
    await expect(sheet).toContainText('Their details were erased')
    await expect(sheet).toContainText('Any messages with them were deleted with their details')
    // Said once (UX review p2): no footer under the empty conversation repeating it.
    await expect(sheet.getByText('Their details were erased')).toHaveCount(1)
    await expect(sheet.getByRole('textbox')).toHaveCount(0)
    expect(await seriousViolations(page)).toEqual([])
    expect(await teamMessages(team.owner.api, idea.key)).toEqual([])
    const refused = await team.owner.api.raw('POST', `/ideas/${idea.key}/submission/messages`, {
      body: 'Hello?',
    })
    expect(refused.status()).toBe(409)
    expect((await refused.json()).code).toBe('submitter_erased')
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-05: “The submitter replied”: the inbox opens the conversation, one email an hour, and its preference', async ({
  page,
  api,
  baseURL,
}) => {
  test.setTimeout(180_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  const mailpit = new Mailpit()
  try {
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Cargo bikes ${team.project.key}`,
      email: null,
    })
    await sendTeamMessage(team.owner.api, idea.key, 'Which streets?')
    const since = new Date()
    await visitor.replied(idea.token, 'The high street, mostly. Call me on 0123?')
    const sentence = `The person who sent ${idea.key} through the public form replied to the team.`

    const replied = await mailpit.waitForMessage(team.owner.email, {
      since,
      subject: `[${idea.key}] The submitter replied about "${idea.title}"`,
    })
    const mailed = text(replied)
    expect(mailed).toContain(sentence)
    expect(mailed).not.toContain('high street') // never the reply's text
    expect(mailed).not.toContain('0123')
    expect(links(replied).some((href) => href.endsWith(`/ideas/${idea.key}?submission=1`))).toBe(
      true,
    )

    await signInAs(page, team.owner)
    await page.goto('/notifications')
    const row = page.getByRole('link', { name: new RegExp(sentence.replace(/[.?]/g, '\\$&')) })
    await expect(row).toBeVisible()
    await expect(page.getByText('high street')).toHaveCount(0)
    expect(await seriousViolations(page)).toEqual([])
    await row.click()
    await expect(page).toHaveURL(new RegExp(`/ideas/${idea.key}\\?submission=1$`))
    await expect(messagesSheet(page, 'Sam Public')).toBeVisible()
    await expect(conversation(messagesSheet(page, 'Sam Public'))).toHaveCount(2)

    // A second reply within the hour: the inbox only.
    await visitor.replied(idea.token, 'And the station.')
    await expect
      .poll(async () =>
        (await team.owner.api.notifications()).filter((item) => item.type === 'submitter_replied'),
      )
      .toHaveLength(2)
    await ideaEmailsSettled(alice, idea.key)
    expect(
      await mailpit.messagesTo(team.owner.email, { since, subject: 'The submitter replied' }),
    ).toHaveLength(1)
    // Theo, a member who never wrote: nothing.
    expect(
      (await team.member.api.notifications()).filter((item) => item.type === 'submitter_replied'),
    ).toEqual([])

    // Its preference: immediate by default, and it can be changed.
    await page.goto('/settings/notifications')
    const preference = page.getByRole('radiogroup', { name: 'The submitter replied', exact: true })
    await expect(preference.getByRole('radio', { name: 'Immediate' })).toBeChecked()
    await preference.getByRole('radio', { name: 'Daily digest' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
    const saved = await team.owner.api.preferences()
    expect(saved.items.find((item) => item.type === 'submitter_replied')?.mode).toBe('digest')
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-06: “Remove my email address” stops the email and keeps the link and the conversation', async ({
  page,
  browser,
  api,
  baseURL,
}) => {
  test.setTimeout(180_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  try {
    const email = `gina.${uniqueSuffix()}@example.org`
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Repair cafe ${team.project.key}`,
      email,
      confirm: true,
    })
    expect((await sendTeamMessage(team.owner.api, idea.key, 'When does it open?')).emailed).toBe(
      true,
    )
    const phone = await phoneFor(browser, baseURL ?? '')
    await phone.goto(`/track#${idea.token}`)
    await phone.getByRole('button', { name: 'Remove my email address' }).tap()
    const dialog = phone.getByRole('alertdialog', { name: 'Remove your email address?' })
    await expect(dialog).toContainText('Your link and your messages stay.')
    await dialog.getByRole('button', { name: 'Remove my email address' }).tap()
    await expect(
      phone.getByText('We don’t have an email address for you any more. Check this page for news.'),
    ).toBeVisible()
    await expect(trackedMessages(phone)).toContainText('New messages appear on this page')
    await expect(conversation(trackedMessages(phone))).toHaveCount(1)

    await signInAs(page, team.owner)
    await openMessages(page, idea.key, 'Sam Public')
    await expect(messagesSheet(page, 'Sam Public')).toContainText('They won’t get an email')
    await expect(messagesSheet(page, 'Sam Public')).toContainText(
      `Shown on their tracking page only, signed “The ${team.project.name} team”.`,
    )
    expect((await sendTeamMessage(team.owner.api, idea.key, 'Still there?')).emailed).toBe(false)
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-07: an admin asks before approving; the review queue says they replied and opens the messages', async ({
  page,
  api,
  baseURL,
}) => {
  test.setTimeout(120_000)
  const alice = await api('alice')
  const team = await messagingTeam(alice, PROJECT, { moderated: true })
  const visitor = await Visitor.open(baseURL ?? '')
  try {
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Shared lockers ${team.project.key}`,
      email: null,
    })
    await sendTeamMessage(alice, idea.key, 'Before we approve it: which stores?')
    await visitor.replied(idea.token, 'The two in the city centre.')
    // Held ideas are in nobody's inbox (contract-phase11 §6).
    expect(
      (await alice.notifications()).filter(
        (item) => item.type === 'submitter_replied' && item.idea.key === idea.key,
      ),
    ).toEqual([])

    await signIn(page, 'alice')
    await page.goto(`/p/${team.project.slug}/review`)
    await page.getByRole('link', { name: `They replied: the messages about ${idea.key}` }).click()
    const sheet = messagesSheet(page, 'Sam Public')
    await expect(sheet).toBeVisible()
    await expect(conversation(sheet)).toHaveCount(2)
    await expect(sheet).toContainText('They won’t get an email')
    expect(await seriousViolations(page)).toEqual([])
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-08: confirming twice emails the tracking link once', async ({ api, baseURL }) => {
  test.setTimeout(120_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  const since = new Date()
  try {
    const email = `finn.${uniqueSuffix()}@example.org`
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Tote bag library ${team.project.key}`,
      email,
      since,
    })
    const token = await confirmationToken(email, team.project.name, since)
    expect((await visitor.verify(token)).tracking_link_emailed).toBe(true)
    expect((await visitor.verify(token)).tracking_link_emailed).toBe(false)
    await ideaEmailsSettled(alice, idea.key)
    const received = (await new Mailpit().messagesTo(email, { since })).map((m) => m.Subject)
    expect(received.sort()).toEqual(
      [
        `Confirm your idea for ${team.project.name}`,
        `Your link to follow your idea for ${team.project.name}`,
      ].sort(),
    )
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})

test('SM-09: Admin → Email names the submitter emails and masks the address; the audit log says who wrote, never the text', async ({
  page,
  api,
  baseURL,
}) => {
  test.setTimeout(120_000)
  const alice = await api('alice')
  await requireEmail(alice)
  const team = await messagingTeam(alice, PROJECT)
  const visitor = await Visitor.open(baseURL ?? '')
  try {
    const email = `ivy.${uniqueSuffix()}@example.org`
    const idea = await sendPublicIdea(alice, team, visitor, {
      title: `Bulk refills ${team.project.key}`,
      email,
      confirm: true,
    })
    const body = 'Which refills would you want first? Quokkazeppelin.'
    await sendTeamMessage(team.owner.api, idea.key, body)
    await ideaEmailsSettled(alice, idea.key)
    const rows = await alice.outbox({ type: 'submission_message' })
    expect(rows.some((row) => row.status === 'sent')).toBe(true)
    expect(JSON.stringify(rows)).not.toContain(email)
    expect(JSON.stringify(rows)).not.toContain('Quokkazeppelin')

    await signIn(page, 'alice')
    await page.goto('/settings/email?status=all')
    const table = page.getByRole('table', { name: 'Outbox emails' })
    await expect(
      table.getByRole('row').filter({ hasText: 'Team message (public submitter)' }).first(),
    ).toBeVisible()
    await expect(
      table.getByRole('row').filter({ hasText: 'Tracking link (public submitter)' }).first(),
    ).toBeVisible()
    await expect(page.locator('main')).not.toContainText(email)
    await expect(page.locator('main')).not.toContainText('Quokkazeppelin')

    const detail = await alice.idea(idea.key)
    await page.goto(`/settings/audit?target=idea:${detail.id}`)
    const entries = page.getByRole('region', { name: 'Audit entries' })
    await expect(
      entries.getByText(`${team.owner.name} messaged the submitter of ${idea.key}`).first(),
    ).toBeVisible()
    await expect(entries).not.toContainText('Quokkazeppelin')
    const audited = await alice.audit({ action: 'submission.message' })
    const mine = audited.filter((entry) => entry.target_id === detail.id)
    expect(mine).toHaveLength(1)
    expect(JSON.stringify(mine)).not.toContain('Quokkazeppelin')
    expect(JSON.stringify(mine)).not.toContain(email)
  } finally {
    await visitor.dispose()
    await disposePeople({ nora: team.owner, theo: team.member })
  }
})
