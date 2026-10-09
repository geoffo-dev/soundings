import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Settings → Notifications (contract-phase3 §3.4) and the public unsubscribe
 * page (§3.5) against the mock. Alice gets new comments immediately (the
 * default is the daily digest); everything else is at its default.
 */

const row = (page: Page, label: string) =>
  page.getByRole('radiogroup', { name: label, exact: true })

test('every type has Immediate / Daily digest / Off with the defaults; saves as you choose', async ({
  page,
}) => {
  await page.goto('/settings/notifications')
  await expect(page.getByRole('heading', { level: 2, name: 'Email notifications' })).toBeVisible()
  // One heading for the page: no "Email" section heading stacked under it.
  await expect(page.getByRole('heading', { level: 3 })).toHaveCount(0)
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  await expect(nav.getByRole('link', { name: 'Notifications' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  // Phase 3's seven types and Phase 8b's two research types.
  await expect(page.getByRole('radiogroup')).toHaveCount(9)
  await expect(row(page, 'Mentions').getByRole('radio', { name: 'Immediate' })).toBeChecked()
  await expect(
    row(page, 'Status changes').getByRole('radio', { name: 'Daily digest' }),
  ).toBeChecked()
  await expect(page.getByText('08:00 (Europe/London)')).toBeVisible()

  // Alice's own choice differs from the default: "Reset" goes back to it.
  // In the options' own words.
  await expect(page.getByText('Default: Daily digest')).toBeVisible()
  const patches: unknown[] = []
  page.on('request', (request) => {
    if (request.method() === 'PATCH') patches.push(request.postDataJSON())
  })
  await page.getByRole('button', { name: 'Reset New comments to the default' }).click()
  await expect(row(page, 'New comments').getByRole('radio', { name: 'Daily digest' })).toBeChecked()
  await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
  await expect(page.getByText('Default: Daily digest')).toHaveCount(0)

  // Keyboard: arrow keys move and choose within a row.
  await row(page, 'Evaluation reminders').getByRole('radio', { name: 'Immediate' }).focus()
  // Held like a real key press (Radix chooses on focus while an arrow key is down).
  await page.keyboard.down('ArrowRight')
  await expect(
    row(page, 'Evaluation reminders').getByRole('radio', { name: 'Daily digest' }),
  ).toBeChecked()
  await page.keyboard.up('ArrowRight')
  await expect
    .poll(() => patches)
    .toEqual([{ comment: 'digest' }, { evaluation_reminder: 'digest' }])
})

test('turning off all email can be undone', async ({ page }) => {
  await page.goto('/settings/notifications')
  await page.getByRole('button', { name: 'Turn off all email' }).click()
  for (const label of ['Evaluation requests', 'Mentions', 'Status changes']) {
    await expect(row(page, label).getByRole('radio', { name: 'Off' })).toBeChecked()
  }
  await expect(page.getByRole('button', { name: 'Turn off all email' })).toBeDisabled()
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(row(page, 'New comments').getByRole('radio', { name: 'Immediate' })).toBeChecked()
  await expect(
    row(page, 'Status changes').getByRole('radio', { name: 'Daily digest' }),
  ).toBeChecked()
})

test('a failed save rolls back with a message', async ({ page }) => {
  await page.goto('/settings/notifications')
  await expect(row(page, 'Mentions')).toBeVisible()
  // The mock answers 500 for this path from now on.
  await page.evaluate(() =>
    localStorage.setItem('soundings-mock-fail', '/me/notification-preferences'),
  )
  await row(page, 'Mentions').getByRole('radio', { name: 'Off' }).click()
  await expect(page.getByText('Couldn’t save your email preferences')).toBeVisible()
  await expect(row(page, 'Mentions').getByRole('radio', { name: 'Immediate' })).toBeChecked()
})

test('without SMTP the page says nothing is emailed for now; the controls still work', async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-email', 'off'))
  await page.goto('/settings/notifications')
  await expect(page.getByText('Email isn’t set up on this server yet')).toBeVisible()
  // The digest isn't promised as if it were running.
  await expect(page.getByText(/^Once email is on, the daily digest arrives at 08:00/)).toBeVisible()
  await row(page, 'Mentions').getByRole('radio', { name: 'Off' }).click()
  await expect(row(page, 'Mentions').getByRole('radio', { name: 'Off' })).toBeChecked()
})

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('rows stack and fit without sideways scrolling', async ({ page }) => {
    await page.goto('/settings/notifications')
    await expect(row(page, 'Mentions')).toBeVisible()
    const overflow = await page.evaluate(() => {
      const main = document.getElementById('main')
      return {
        page: document.documentElement.scrollWidth - window.innerWidth,
        main: main ? main.scrollWidth - main.clientWidth : 0,
      }
    })
    expect(overflow.page).toBeLessThanOrEqual(0)
    expect(overflow.main).toBeLessThanOrEqual(0)
  })
})

/* ------------------------------------------------------------------ */
/* The unsubscribe page (public)                                       */
/* ------------------------------------------------------------------ */

/** The mock's token (src/mocks/notifications.ts `unsubscribeToken`). */
function token(userId: string, scope: string): string {
  const b64 = (text: string) =>
    Buffer.from(text, 'binary')
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  const payload = b64(JSON.stringify({ v: 1, u: userId, s: scope }))
  let hash = 0x811c9dc5
  for (const char of `soundings/unsubscribe/v1:${payload}`) {
    hash ^= char.charCodeAt(0)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `${payload}.${b64(`mock-${hash.toString(16)}`)}`
}

test.describe('the unsubscribe page', () => {
  test.use({ signedInAs: null })

  test('says what stops, changes nothing until confirmed, then confirms', async ({ page }) => {
    const posts: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/unsubscribe') && request.method() === 'POST') {
        posts.push(request.url())
      }
    })
    await page.goto(`/unsubscribe?token=${token(USERS.alice, 'evaluation_reminder')}`)
    // The type's name as the email's footer says it, and a whole sentence about what stops.
    await expect(
      page.getByRole('heading', { level: 1, name: 'Unsubscribe from evaluation reminders?' }),
    ).toBeVisible()
    await expect(
      page.getByText(
        'Soundings will stop emailing a•••@example.com when an evaluation you still owe is nearly due.',
      ),
    ).toBeVisible()
    await expect(page).toHaveTitle('Unsubscribe · Soundings')
    expect(posts).toEqual([])
    await page.getByRole('button', { name: 'Unsubscribe', exact: true }).click()
    const done = page.getByRole('heading', { level: 1, name: 'You’re unsubscribed' })
    await expect(done).toBeFocused()
    await expect(
      page.getByText('Soundings won’t email a•••@example.com about evaluation reminders any more.'),
    ).toBeVisible()
    expect(posts).toHaveLength(1)
    expect(posts[0]).not.toContain('all=')
    // A type's link stops only that type (lead decision L8): no "all" button here;
    // the email's own "Unsubscribe from all email" link or the preferences do that.
    await expect(page.getByRole('button', { name: /all Soundings email/ })).toHaveCount(0)
    await page.getByRole('link', { name: 'Email preferences' }).click()
    await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fnotifications/)
  })

  test('the “all email” link stops every type', async ({ page }) => {
    const posts: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/unsubscribe') && request.method() === 'POST') {
        posts.push(request.url())
      }
    })
    await page.goto(`/unsubscribe?token=${token(USERS.alice, 'all')}`)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Unsubscribe from all Soundings email?' }),
    ).toBeVisible()
    await expect(page.getByRole('listitem')).toHaveCount(9)
    await page.getByRole('button', { name: 'Unsubscribe', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'You’re unsubscribed' })).toBeFocused()
    await expect(page.getByText('Soundings won’t email a•••@example.com any more.')).toBeVisible()
    expect(posts).toHaveLength(1)
    expect(posts[0]).not.toContain('all=')
  })

  test('the digest link lists the types in the digest', async ({ page }) => {
    await page.goto(`/unsubscribe?token=${token(USERS.alice, 'digest')}`)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Stop the daily digest?' }),
    ).toBeVisible()
    await expect(page.getByRole('listitem')).toHaveText(['Status changes'])
  })

  test('a broken or forged link says so and offers sign-in', async ({ page }) => {
    const forged = token(USERS.alice, 'all').replace(/.$/, 'x')
    for (const url of [
      `/unsubscribe?token=${forged}`,
      '/unsubscribe',
      '/unsubscribe?token=short',
    ]) {
      await page.goto(url)
      await expect(
        page.getByRole('heading', { level: 1, name: 'This unsubscribe link doesn’t work' }),
      ).toBeVisible()
      await expect(
        page.getByRole('link', { name: 'Sign in to your email preferences' }),
      ).toHaveAttribute('href', '/login?next=%2Fsettings%2Fnotifications')
    }
  })
})
