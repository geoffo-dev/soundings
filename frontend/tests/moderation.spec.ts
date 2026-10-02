import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Moderation and public submitters (contract-phase4 §3.6, §3.9) against the
 * mock: the board's "waiting for review" notice, the queue at
 * /p/$slug/review with Approve / Reject and their Undo toasts, the held
 * idea's banner, the public form settings and erasing a submitter's details.
 * Sustainability has two ideas waiting (GREEN-10, GREEN-11); Priya (platform
 * admin) moderates them; Alice is a member elsewhere.
 */

const queue = (page: Page) => page.getByRole('list', { name: 'Ideas waiting for review' })
/** A request from the page (the mock's database lives there: a reload starts afresh). */
const status = (page: Page, url: string) =>
  page.evaluate((path) => fetch(path).then((response) => response.status), url)
const toastGone = (page: Page) =>
  expect(page.getByRole('button', { name: 'Undo' })).toHaveCount(0, { timeout: 12_000 })

test.describe('as a project admin', () => {
  test.use({ signedInAs: USERS.priya })

  test('the board says ideas are waiting, and held ideas are on no board', async ({ page }) => {
    await page.goto('/p/sustainability')
    await expect(page.getByRole('heading', { level: 1, name: 'Sustainability' })).toBeVisible()
    await expect(
      page.getByText('2 ideas from the public form are waiting for review.'),
    ).toBeVisible()
    await expect(page.getByText('Plant a wildflower strip by the car park')).toHaveCount(0)
    await page.getByRole('link', { name: 'Review' }).click()
    await expect(page).toHaveURL(/\/p\/sustainability\/review$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Review new ideas' })).toBeVisible()
    await expect(queue(page).getByRole('article')).toHaveCount(2)
  })

  test('approve waits for its Undo toast; Undo puts the idea back untouched', async ({ page }) => {
    const posts: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/submission\/(approve|reject)$/.test(request.url())) {
        posts.push(new URL(request.url()).pathname)
      }
    })
    await page.goto('/p/sustainability/review')
    await expect(queue(page).getByRole('article')).toHaveCount(2)

    await page.getByRole('button', { name: 'Approve GREEN-10' }).click()
    await expect(page.getByText('GREEN-10 approved: it’s in New now')).toBeVisible()
    await expect(queue(page).getByRole('article')).toHaveCount(1)
    await expect(page.getByText(/1 waiting, oldest first/)).toBeVisible()
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(queue(page).getByRole('article')).toHaveCount(2)
    expect(posts).toEqual([])

    // Again, and let the toast close: now it is sent, and the idea is on the board.
    await page.getByRole('button', { name: 'Approve GREEN-10' }).click()
    await toastGone(page)
    expect(posts).toEqual(['/api/v1/ideas/GREEN-10/submission/approve'])
    await page.getByRole('link', { name: 'Back to ideas' }).click()
    await expect(page.getByText('Plant a wildflower strip by the car park')).toBeVisible()
    await expect(page.getByText('1 idea from the public form is waiting for review.')).toBeVisible()
  })

  test('reject deletes the idea once the toast closes', async ({ page }) => {
    await page.goto('/p/sustainability/review')
    await page.getByRole('button', { name: 'Reject and delete GREEN-11' }).click()
    await expect(page.getByText('GREEN-11 rejected and deleted')).toBeVisible()
    await toastGone(page)
    await expect(queue(page).getByRole('article')).toHaveCount(1)
    // The mock's data lives in the page (a reload starts afresh), so ask it from here.
    expect(await status(page, '/api/v1/ideas/GREEN-11')).toBe(404)
  })

  test('an empty queue says what it is for', async ({ page }) => {
    await page.goto('/p/customer-innovation/review')
    await expect(page.getByRole('heading', { name: 'Nothing waiting for review' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Public form settings' })).toHaveAttribute(
      'href',
      /\/p\/customer-innovation\/settings\?tab=public-form/,
    )
  })

  test('a held idea opens read-only with Approve and Reject', async ({ page }) => {
    await page.goto('/ideas/GREEN-10')
    const banner = page.getByRole('region', { name: 'Waiting for review' })
    await expect(banner).toContainText('Only project admins can see it')
    await expect(page.getByRole('button', { name: /^Watch/ })).toHaveCount(0)
    await expect(page.getByText('Sent without a name')).toBeVisible()
    await banner.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText('GREEN-10 approved: it’s in New now')).toBeVisible()
    await toastGone(page)
    await expect(banner).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Watch/ })).toBeVisible()
  })

  test('erasing a submitter’s details confirms first and names what goes', async ({ page }) => {
    await page.goto('/ideas/GREEN-9')
    const panel = page.getByRole('region', { name: 'Public form' })
    await expect(panel).toContainText('Sent by Jo Marsh')
    await expect(panel).toContainText('jo.marsh@example.org')
    await expect(page.getByText(/Submitted by Jo Marsh via the public form/)).toBeVisible()

    await panel.getByRole('button', { name: /Erase submitter details/ }).click()
    const dialog = page.getByRole('alertdialog', { name: 'Erase the submitter’s details?' })
    await expect(dialog).toContainText('Jo Marsh’s name, email address and private tracking link')
    await expect(dialog).toContainText('can’t be undone')
    await dialog.getByRole('button', { name: 'Erase details' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByText('Submitter details erased')).toBeVisible()
    await expect(panel).toContainText('Submitter’s details erased')
    await expect(panel).not.toContainText('jo.marsh@example.org')
    await expect(panel.getByRole('button', { name: /Erase submitter details/ })).toHaveCount(0)
  })

  test('public form settings: only what changed is saved, and the form follows', async ({
    page,
  }) => {
    const patches: unknown[] = []
    page.on('request', (request) => {
      if (request.method() === 'PATCH' && request.url().endsWith('/public-form')) {
        patches.push(request.postDataJSON())
      }
    })
    await page.goto('/p/customer-innovation/settings?tab=public-form')
    await expect(page.getByRole('tab', { name: 'Public form', selected: true })).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Link to share' })).toHaveValue(
      /\/customer-innovation\/submit$/,
    )
    const moderation = page.getByRole('switch', {
      name: 'Review new ideas before the team sees them',
    })
    await expect(moderation).toBeChecked()
    await moderation.click()
    await page
      .getByRole('textbox', { name: 'Intro' })
      .fill('Tell us how to make **returns** easier.')
    await page.getByRole('button', { name: /Save changes/ }).click()
    await expect(page.getByText('Public form saved')).toBeVisible()
    expect(patches).toEqual([
      { moderation_required: false, intro_md: 'Tell us how to make **returns** easier.' },
    ])

    // The public form follows at once (asked from this page: a reload resets the mock).
    const form = await page.evaluate(() =>
      fetch('/api/v1/public/projects/customer-innovation').then(
        (response) => response.json() as Promise<{ intro_md: string; moderated: boolean }>,
      ),
    )
    expect(form).toMatchObject({
      intro_md: 'Tell us how to make **returns** easier.',
      moderated: false,
    })
  })

  test('turning the form off says the link stops working', async ({ page }) => {
    await page.goto('/p/customer-innovation/settings?tab=public-form')
    const enabled = page.getByRole('switch', { name: 'Accept ideas through the public form' })
    await expect(enabled).toBeChecked()
    await enabled.click()
    await page.getByRole('button', { name: /Save changes/ }).click()
    await expect(page.getByText('The public form is off')).toBeVisible()
    await expect(page.getByText(/this link shows “This form isn’t available”/)).toBeVisible()
    expect(await status(page, '/api/v1/public/projects/customer-innovation')).toBe(404)
  })

  test('the queue is axe-clean in both themes and comfortable at 390 px', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme })
      await page.goto('/p/sustainability/review')
      await expect(queue(page).getByRole('article')).toHaveCount(2)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        390,
      )
      const approve = await page.getByRole('button', { name: 'Approve GREEN-10' }).boundingBox()
      expect(approve?.height).toBeGreaterThanOrEqual(32)
      expect(await seriousViolations(page)).toEqual([])
    }
    await page.goto('/p/sustainability/settings?tab=public-form')
    await expect(page.getByRole('switch', { name: /Accept ideas/ })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})

test.describe('as a member', () => {
  test('no notice, no queue, no public form or branding settings', async ({ page }) => {
    await page.goto('/p/customer-innovation')
    await expect(page.getByRole('heading', { level: 1, name: 'Customer Innovation' })).toBeVisible()
    await expect(page.getByText(/waiting for review/)).toHaveCount(0)
    await page.goto('/p/customer-innovation/review')
    await expect(
      page.getByRole('heading', { name: 'Only project admins review new ideas' }),
    ).toBeVisible()
    await page.goto('/p/customer-innovation/settings?tab=public-form')
    await expect(page.getByRole('tab', { name: 'Public form' })).toHaveCount(0)
    await expect(page.getByRole('tab', { name: 'Branding' })).toHaveCount(0)
  })

  test('a held idea is a 404 for anyone but admins', async ({ page }) => {
    await page.goto('/ideas/GREEN-10')
    await expect(
      page.getByRole('heading', {
        level: 1,
        name: 'This idea doesn’t exist or you don’t have access',
      }),
    ).toBeVisible()
    await expect(page.getByText('Plant a wildflower strip by the car park')).toHaveCount(0)
  })
})
