import type { Page } from '@playwright/test'

import { bestPracticeViolations, expect, seriousViolations, test, USERS } from './support'

/**
 * Phase 11 (contract-phase11): messages between the team and the person who sent an
 * idea through the public form, against the mock. GREEN-13 (owner Grace; Sam Okafor's
 * address confirmed; four messages), GREEN-14 (Ana's address unconfirmed: tracking
 * page only; Carol wrote), GREEN-15 (details erased), GREEN-10 (held for moderation;
 * Carol asked and the submitter replied), GREEN-9 (the team hasn't written). Alice is
 * a Sustainability member who owns none of them: she sees nothing of any of it.
 */

const token = (name: string) => `track${name}`.padEnd(43, 'x')
const SAM = token('SamOkaforGreen13')
const ANA = token('AnaRuizGreen14')
const JO = token('JoMarshGreen9')
const CONFIRM_LINK = 'v1.e0000000-0000-4000-8000-0000000f0004'

const sheet = (page: Page) => page.getByRole('dialog', { name: 'Messages with Sam Okafor' })
const messages = (page: Page) => page.getByRole('list', { name: 'Messages, oldest first' })

test.describe('the team (Grace owns GREEN-13)', () => {
  test.use({ signedInAs: USERS.grace })

  test('reads the conversation and sends a message with Ctrl+Enter', async ({ page }) => {
    await page.goto('/ideas/GREEN-13')
    const panel = page.getByRole('group', { name: 'Messages' })
    await expect(panel).toContainText('4 messages · They replied 40 minutes ago')
    expect(await seriousViolations(page)).toEqual([])
    expect(await bestPracticeViolations(page)).toEqual([])
    await panel.getByRole('button', { name: 'Open messages' }).click()
    await expect(page).toHaveURL(/\?submission=1$/)
    const dialog = sheet(page)
    await expect(dialog).toBeVisible()
    const rows = messages(page).getByRole('listitem')
    await expect(rows).toHaveCount(4)
    await expect(rows.first()).toContainText('Grace Kim')
    // The channel, not a delivery claim (UX review m1).
    await expect(rows.first()).toContainText('By email too')
    await expect(rows.nth(1)).toContainText('Submitter (Sam Okafor)')
    // Plain text: a URL in a reply is never a link.
    await expect(rows.nth(1)).toContainText('https://example.org/crates')
    await expect(dialog.getByRole('link')).toHaveCount(0)
    await expect(dialog).toContainText(
      'Emailed to them and shown on their tracking page, signed “The Sustainability team”.',
    )
    const box = dialog.getByRole('textbox', { name: 'Message to Sam Okafor' })
    await expect(box).toBeFocused()
    await box.fill('We’ll order 600 crates.\nThanks again!')
    await page.keyboard.press('Control+Enter')
    await expect(rows).toHaveCount(5)
    await expect(rows.last()).toContainText('We’ll order 600 crates.')
    await expect(rows.last()).toContainText('By email too')
    await expect(box).toHaveValue('')
    await expect(box).toBeFocused()
    await expect(dialog.getByRole('status').filter({ hasText: 'Message sent' })).toHaveCount(1)
    expect(await seriousViolations(page)).toEqual([])

    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(page).not.toHaveURL(/submission=/)
    // Back to the button that opened it.
    await expect(panel.getByRole('button', { name: 'Open messages' })).toBeFocused()
    await expect(panel).toContainText('5 messages · The team wrote')
    // Email reaches them: no "tracking page only" warning anywhere.
    await expect(panel).not.toContainText('won’t get an email')
  })

  test('keeps an unsent message as a draft, and the text when sending fails', async ({ page }) => {
    await page.goto('/ideas/GREEN-13?submission=1')
    const box = sheet(page).getByRole('textbox', { name: 'Message to Sam Okafor' })
    await box.fill('Half a thought')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Open messages' }).click()
    await expect(box).toHaveValue('Half a thought')

    await page.evaluate(() => localStorage.setItem('soundings-mock-fail', '/submission/messages'))
    await sheet(page).getByRole('button', { name: /^Send/ }).click()
    await expect(sheet(page).getByRole('alert')).toContainText('Not sent')
    await expect(box).toHaveValue('Half a thought')
    await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
    await sheet(page).getByRole('button', { name: /^Send/ }).click()
    await expect(messages(page).getByRole('listitem').last()).toContainText('Half a thought')
    await expect(sheet(page).getByRole('alert')).toHaveCount(0)
    await page.reload()
    await expect(sheet(page).getByRole('textbox')).toHaveValue('')
  })

  test('says there is no one to write to once the details are erased', async ({ page }) => {
    await page.goto('/ideas/GREEN-15')
    const panel = page.getByRole('group', { name: 'Messages' })
    await expect(panel).toContainText('None: their details were erased.')
    await expect(panel.getByRole('button')).toHaveCount(0)
    await page.goto('/ideas/GREEN-15?submission=1')
    const dialog = page.getByRole('dialog', { name: 'Messages with the submitter' })
    await expect(dialog).toContainText('Their details were erased')
    // Said once (UX review p2): no footer repeating it under the empty conversation.
    await expect(dialog.getByText('Their details were erased')).toHaveCount(1)
    await expect(dialog.getByText(/no one to write to/)).toHaveCount(1)
    await expect(dialog.getByRole('textbox')).toHaveCount(0)
  })

  test('on a phone, Details → Open messages opens the conversation', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/ideas/GREEN-13')
    await page.getByRole('button', { name: 'Details' }).click()
    await page
      .getByRole('dialog', { name: 'Details' })
      .getByRole('button', { name: 'Open messages' })
      .click()
    await expect(page.getByRole('dialog', { name: 'Details' })).toBeHidden()
    await expect(sheet(page)).toBeVisible()
    await expect(messages(page).getByRole('listitem')).toHaveCount(4)
    // Touch: the sheet itself takes focus, so the keyboard doesn't hide the conversation.
    expect(await seriousViolations(page)).toEqual([])

    // Closing goes back to Details, where it was opened (UX review p8), on its button.
    await page.keyboard.press('Escape')
    await expect(sheet(page)).toBeHidden()
    const details = page.getByRole('dialog', { name: 'Details' })
    await expect(details).toBeVisible()
    await expect(details.getByRole('button', { name: 'Open messages' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(details).toBeHidden()
    await expect(page.getByRole('button', { name: 'Details' })).toBeFocused()
  })
})

test.describe('everyone else (Alice, a member)', () => {
  test('sees no Messages section, and ?submission=1 opens nothing', async ({ page }) => {
    const asked: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/submission/messages')) asked.push(request.url())
    })
    await page.goto('/ideas/GREEN-13?submission=1')
    await expect(page.getByRole('heading', { name: 'Public form' })).toBeVisible()
    await expect(page).not.toHaveURL(/submission=/)
    await expect(page.getByRole('group', { name: 'Messages' })).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByText(/They replied|Open messages|Sam Okafor:/)).toHaveCount(0)
    expect(asked).toEqual([])
  })
})

test.describe('the moderators (Carol, Sustainability’s admin)', () => {
  test.use({ signedInAs: USERS.carol })

  test('the queue says when a held idea’s sender replied, and opens the messages', async ({
    page,
  }) => {
    await page.goto('/p/sustainability/review')
    await page.getByRole('link', { name: 'They replied: the messages about GREEN-10' }).click()
    const dialog = page.getByRole('dialog', { name: 'Messages with the submitter' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('listitem')).toHaveCount(2)
    // No address: said plainly above the box (UX review M1), and the box is described by it.
    await expect(dialog).toContainText('They won’t get an email')
    await expect(dialog).toContainText('Shown on their tracking page only')
    await expect(dialog.getByRole('textbox')).toHaveAccessibleDescription(
      /They won’t get an email.+only if they open their private link again\./,
    )
    expect(await seriousViolations(page)).toEqual([])
  })

  test('the panel lists Messages before the destructive Erase', async ({ page }) => {
    await page.goto('/ideas/GREEN-13')
    const panel = page.getByRole('region', { name: 'Public form', exact: true })
    const buttons = panel.getByRole('button')
    await expect(buttons).toHaveCount(2)
    await expect(buttons.first()).toHaveText(/Open messages/)
    await expect(buttons.last()).toHaveText(/Erase submitter details/)
  })

  test('the panel says before anyone writes that no email will reach them', async ({ page }) => {
    await page.goto('/ideas/GREEN-14')
    const panel = page.getByRole('group', { name: 'Messages' })
    await expect(panel).toContainText('Tracking page only: they won’t get an email.')
  })

  test('“The submitter replied” in the inbox opens the conversation', async ({ page }) => {
    await page.goto('/notifications')
    const row = page.getByRole('link', {
      name: /The person who sent GREEN-13 through the public form replied to the team/,
    })
    await expect(row).toBeVisible()
    await row.click()
    await expect(page).toHaveURL(/\/ideas\/GREEN-13\?submission=1$/)
    await expect(sheet(page)).toBeVisible()
  })
})

test.describe('the submitter’s tracking page', () => {
  test.use({ signedInAs: null })

  test('shows the team’s messages as the team, theirs as You, and replies', async ({ page }) => {
    await page.goto(`/track#${SAM}`)
    const section = page.getByRole('region', { name: 'Messages', exact: true })
    await expect(section).toContainText(
      'The Sustainability team wrote to you about your idea. We’ll also email you when they write again.',
    )
    const rows = section.getByRole('list', { name: 'Messages, oldest first' }).getByRole('listitem')
    await expect(rows).toHaveCount(4)
    await expect(rows.first()).toContainText('The Sustainability team')
    await expect(rows.nth(1)).toContainText('You')
    // No person is ever named on a public page.
    await expect(page.getByText(/Grace Kim|Carol Díaz/)).toHaveCount(0)
    expect(await bestPracticeViolations(page)).toEqual([])
    const box = section.getByRole('textbox', { name: 'Reply to the team' })
    await box.fill('Shall I bring a sample crate?')
    await page.keyboard.press('Control+Enter')
    await expect(rows).toHaveCount(5)
    await expect(rows.last()).toContainText('Shall I bring a sample crate?')
    await expect(box).toHaveValue('')
    await expect(box).toBeFocused()
    expect(await seriousViolations(page)).toEqual([])
  })

  test('the message email’s Reply button lands on the reply box', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/track?reply=1#${SAM}`)
    const box = page.getByRole('textbox', { name: 'Reply to the team' })
    await expect(box).toBeFocused()
    await expect(box).toBeInViewport()
  })

  test('warns before the replies run out until the team writes back', async ({ page }) => {
    await page.goto(`/track#${SAM}`)
    const section = page.getByRole('region', { name: 'Messages', exact: true })
    const box = section.getByRole('textbox', { name: 'Reply to the team' })
    // One reply since the team's latest message: seven more make eight, two left.
    for (let n = 1; n <= 7; n += 1) {
      await box.fill(`Reply number ${n}`)
      await page.keyboard.press('Control+Enter')
      await expect(box).toHaveValue('')
    }
    await expect(box).toHaveAccessibleDescription(
      'Only the team sees your reply. You can send 2 more replies until the team writes back.',
    )
    await box.fill('Reply number 8')
    await page.keyboard.press('Control+Enter')
    await expect(box).toHaveAccessibleDescription(/You can send 1 more reply until/)
    await box.fill('Reply number 9')
    await page.keyboard.press('Control+Enter')
    await expect(section).toContainText('You can reply again once the team writes back.')
    await expect(section.getByRole('textbox')).toHaveCount(0)
  })

  test('no Messages section until the team writes', async ({ page }) => {
    await page.goto(`/track#${JO}`)
    await expect(page.getByRole('heading', { name: 'Email updates' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Messages', exact: true })).toHaveCount(0)
  })

  test('an unconfirmed address: messages on this page only', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/track#${ANA}`)
    await expect(page.getByRole('region', { name: 'Messages', exact: true })).toContainText(
      'confirm your email address to get them by email too',
    )
    expect(await seriousViolations(page)).toEqual([])
  })

  test('“Remove my email address” stops the email and keeps the link', async ({ page }) => {
    await page.goto(`/track#${SAM}`)
    await page.getByRole('button', { name: 'Remove my email address' }).click()
    const dialog = page.getByRole('alertdialog', { name: 'Remove your email address?' })
    await expect(dialog).toContainText('Your link and your messages stay.')
    await dialog.getByRole('button', { name: 'Remove my email address' }).click()
    await expect(page.getByRole('heading', { name: 'Email updates' })).toBeFocused()
    await expect(
      page.getByText('We don’t have an email address for you any more. Check this page for news.'),
    ).toBeVisible()
    await expect(page.getByRole('region', { name: 'Messages', exact: true })).toContainText(
      'New messages appear on this page',
    )
  })

  test('the confirm page says the tracking link was emailed (first confirmation)', async ({
    page,
  }) => {
    await page.goto(`/sustainability/verify#${CONFIRM_LINK}`)
    await page.getByRole('button', { name: 'Confirm my email address' }).click()
    await expect(
      page.getByText('We’ve emailed you a private link to follow your idea.'),
    ).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})
