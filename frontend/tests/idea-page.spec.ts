import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/** The idea page (wireframe 03) against the mock API, signed in as Alice. */

const heading = (page: Page, name: string | RegExp) => page.getByRole('heading', { level: 1, name })
const details = (page: Page) => page.getByRole('complementary', { name: 'Idea details' })
const activity = (page: Page) => page.getByRole('list', { name: 'Activity, oldest first' })

/** `YYYY-MM-DD` for today + `days` in the browser's time zone. */
async function dayInDays(page: Page, days: number): Promise<string> {
  return page.evaluate((n) => {
    const d = new Date()
    d.setDate(d.getDate() + n)
    const pad = (v: number) => String(v).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }, days)
}

test('shows the idea: description, activity, evaluators and the score', async ({ page }) => {
  await page.goto('/ideas/cust-2')
  // Keys are canonical in upper case.
  await expect(page).toHaveURL(/\/ideas\/CUST-2$/)
  await expect(heading(page, 'Print-free returns with a QR code')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText(
    'Customer Innovation',
  )
  await expect(page.getByText("Works with the carrier's existing label API")).toBeVisible()
  await expect(activity(page)).toContainText('Bob Chen submitted an evaluation')
  await expect(page.getByRole('article', { name: 'Dave Okafor' })).toContainText(
    'I can take a look at this on Thursday.',
  )

  const sidebar = details(page)
  await expect(sidebar.getByRole('list', { name: 'Evaluators' }).getByRole('listitem')).toHaveCount(
    3,
  )
  await expect(sidebar.getByRole('img', { name: '2 of 3 evaluations submitted' })).toBeVisible()
  await expect(sidebar.getByText('3.1', { exact: true })).toBeVisible()
  await expect(sidebar.getByText('High disagreement')).toBeVisible()
  await expect(sidebar.getByRole('meter')).toHaveCount(5)
  // The owner's next step isn't obvious yet (one evaluation missing): no primary action.
  await expect(page.locator('[data-primary-action]')).toHaveCount(0)
})

test('an unknown idea shows the same not-found page as a hidden one', async ({ page }) => {
  await page.goto('/ideas/CUST-999')
  await expect(page.getByText('This idea doesn’t exist or you don’t have access')).toBeVisible()
  await page.goto('/ideas/TOOL-1')
  await expect(heading(page, /.+/)).toBeVisible()
})

test.describe('as a user without access', () => {
  test.use({ signedInAs: USERS.ivan })

  test('a private project’s idea is not found', async ({ page }) => {
    await page.goto('/ideas/TOOL-1')
    await expect(page.getByText('This idea doesn’t exist or you don’t have access')).toBeVisible()
  })
})

test('the owner changes the status, and Undo puts it back', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await expect(heading(page, 'Print-free returns with a QR code')).toBeVisible()
  await page.keyboard.press('s')
  const dialog = page.getByRole('dialog', { name: 'Change status' })
  await dialog.getByRole('option', { name: 'Shortlisted' }).click()
  await expect(dialog).toBeHidden()

  const status = details(page).getByRole('button', { name: /^Status:/ })
  await expect(status).toHaveAccessibleName('Status: Shortlisted. Change status')
  await expect(activity(page)).toContainText('moved it from Evaluating to Shortlisted')

  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(status).toHaveAccessibleName('Status: Evaluating. Change status')
  await expect(activity(page)).toContainText('moved it from Shortlisted to Evaluating')
})

test('closing an idea asks for a resolution', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await details(page)
    .getByRole('button', { name: /^Status:/ })
    .click()
  const dialog = page.getByRole('dialog', { name: 'Change status' })
  await dialog.getByRole('option', { name: 'Closed' }).click()
  await expect(dialog.getByRole('option', { name: 'Accepted' })).toBeVisible()
  await dialog.getByRole('option', { name: 'Parked' }).click()
  await expect(details(page).getByRole('button', { name: /^Status:/ })).toHaveAccessibleName(
    'Status: Parked. Change status',
  )
  // A closed idea can't be evaluated any more.
  await expect(details(page).getByText('Evaluation ended when the idea was closed.')).toBeVisible()
})

test('the owner invites evaluators and sets a due date', async ({ page }) => {
  await page.goto('/ideas/CUST-5')
  await expect(heading(page, 'Loyalty tiers for B2B customers')).toBeVisible()
  await expect(details(page).getByText('Invite 2–4 people to evaluate this idea.')).toBeVisible()

  // The page's one primary action for an owner without evaluators.
  await page.locator('[data-primary-action]:visible').click()
  const dialog = page.getByRole('dialog', { name: 'Invite evaluators' })
  await dialog.getByRole('combobox', { name: 'Evaluators' }).fill('bo')
  await dialog.getByRole('option', { name: /Bob Chen/ }).click()
  await dialog.getByRole('combobox', { name: 'Evaluators' }).fill('carol')
  await dialog.getByRole('option', { name: /Carol Díaz/ }).click()
  await expect(dialog.getByRole('list', { name: 'Selected people' })).toContainText('Bob Chen')

  // The first invite pre-fills the project's 7-day window; pick 10 days instead.
  const due = dialog.getByLabel('Due date')
  await expect(due).toHaveValue(await dayInDays(page, 7))
  await due.fill(await dayInDays(page, 10))
  await dialog.getByRole('button', { name: /Invite 2 people/ }).click()
  await expect(dialog).toBeHidden()

  const list = details(page).getByRole('list', { name: 'Evaluators' })
  await expect(list.getByRole('listitem')).toHaveCount(2)
  await expect(list).toContainText('Bob Chen')
  await expect(list).toContainText('Carol Díaz')
  await expect(list.getByRole('img', { name: 'Not submitted yet' })).toHaveCount(2)
  await expect(details(page).getByRole('button', { name: /Change due date/ })).toBeVisible()
  await expect(activity(page)).toContainText('invited Carol Díaz to evaluate')
  await expect(activity(page)).toContainText('set the due date to')
  await expect(page.getByText('Invited Bob Chen and Carol Díaz')).toBeVisible()

  // Removing an evaluator is deferred with Undo.
  await list.getByRole('button', { name: 'Remove Bob Chen as evaluator' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(2)
})

test('comments: add, edit, and delete with Undo', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await expect(heading(page, 'Print-free returns with a QR code')).toBeVisible()

  // "c" focuses the comment box; ⌘/Ctrl+Enter posts.
  await page.keyboard.press('c')
  const box = page.getByRole('textbox', { name: 'Write a comment' })
  await expect(box).toBeFocused()
  await box.fill('Could we pilot this in **one region** first?')
  await page.keyboard.press('ControlOrMeta+Enter')
  const mine = page.getByRole('article', { name: 'Alice Anders' })
  await expect(mine).toContainText('Could we pilot this in one region first?')
  await expect(mine.locator('strong')).toHaveText('one region')
  await expect(box).toHaveValue('')

  await mine.getByRole('button', { name: /Comment actions/ }).click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  const editor = mine.getByRole('textbox', { name: 'Edit your comment' })
  await editor.fill('Could we pilot this in two regions first?')
  await mine.getByRole('button', { name: 'Save' }).click()
  await expect(mine).toContainText('two regions')
  await expect(mine).toContainText('edited')

  // Esc cancels an edit.
  await mine.getByRole('button', { name: /Comment actions/ }).click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  await mine.getByRole('textbox', { name: 'Edit your comment' }).fill('Never mind')
  await page.keyboard.press('Escape')
  await expect(mine).toContainText('two regions')

  await mine.getByRole('button', { name: /Comment actions/ }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await expect(mine).toBeHidden()
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(page.getByRole('article', { name: 'Alice Anders' })).toContainText('two regions')
})

test('title and summary edit inline; Esc cancels', async ({ page }) => {
  await page.goto('/ideas/CUST-5')
  await expect(heading(page, 'Loyalty tiers for B2B customers')).toBeVisible()
  await page.getByRole('button', { name: 'Edit title' }).click()
  const title = page.getByRole('textbox', { name: 'Title' })
  await title.fill('Loyalty tiers for business customers')
  await title.press('Enter')
  await expect(heading(page, 'Loyalty tiers for business customers')).toBeVisible()

  await page.getByRole('button', { name: 'Edit summary' }).click()
  await page.getByRole('textbox', { name: 'Summary' }).fill('')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Keep a sentence or two')
  await page.keyboard.press('Escape')
  await expect(page.getByText('Volume-based tiers with better delivery terms')).toBeVisible()

  await page.getByRole('button', { name: 'Add details' }).click()
  await page.getByRole('textbox', { name: 'Description' }).fill('- Gold\n- Silver')
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(page.getByRole('region', { name: 'Description' }).getByRole('listitem')).toHaveCount(
    2,
  )
})

test('tabs, shortcuts and palette actions', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await expect(heading(page, 'Print-free returns with a QR code')).toBeVisible()
  await page.keyboard.press('2')
  await expect(page).toHaveURL(/tab=evaluations/)
  await expect(page.getByRole('tab', { name: /Evaluations/ })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByText('2 submitted of 3')).toBeVisible()
  await page.keyboard.press('3')
  await expect(page.getByText('Available once the idea is shortlisted')).toBeVisible()
  await page.keyboard.press('1')
  await expect(page).not.toHaveURL(/tab=/)

  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette.getByRole('option', { name: /Change status/ })).toBeVisible()
  await expect(palette.getByRole('option', { name: /Invite evaluators/ })).toBeVisible()
  await expect(palette.getByRole('option', { name: /Close evaluation/ })).toBeVisible()
  await page.keyboard.type('invite')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Invite evaluators' })).toBeVisible()
  await page.keyboard.press('Escape')

  await page.keyboard.press('?')
  const sheet = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  for (const label of ['Change status', 'Assign owner', 'Write a comment', 'Evaluate']) {
    await expect(sheet.getByText(label, { exact: false }).first()).toBeVisible()
  }
})

test.describe('a viewer', () => {
  test.use({ signedInAs: USERS.emma })

  test('sees the idea and scores but no controls', async ({ page }) => {
    await page.goto('/ideas/CUST-2')
    await expect(heading(page, 'Print-free returns with a QR code')).toBeVisible()
    await expect(details(page).getByText('3.1', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit title' })).toHaveCount(0)
    await expect(details(page).getByRole('button', { name: /Change status/ })).toHaveCount(0)
    await expect(details(page).getByRole('button', { name: /Invite evaluators/ })).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Write a comment' })).toHaveCount(0)
    await expect(page.locator('[data-primary-action]')).toHaveCount(0)
  })
})

test('an archived project’s ideas are read-only', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  // Alice is an admin of Internal Tools: archive it, then open one of its ideas.
  await page.evaluate(async () => {
    const csrf = /soundings_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? ''
    await fetch('/api/v1/projects/internal-tools', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ archived: true }),
    })
    window.history.pushState({}, '', '/ideas/TOOL-2')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await expect(
    page.getByText('This project is archived, so its ideas are read-only.'),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Edit title' })).toHaveCount(0)
  await expect(page.locator('[data-primary-action]')).toHaveCount(0)
  await expect(page.getByText('This project is archived, so comments are closed.')).toBeVisible()
})

test('tags are edited inline: add, remove, Esc cancels', async ({ page }) => {
  await page.goto('/ideas/CUST-5')
  const sidebar = details(page)
  const tags = sidebar.getByRole('list', { name: 'Tags' })
  await expect(tags.getByRole('listitem')).toHaveCount(2)

  await sidebar.getByRole('button', { name: 'Edit tags' }).click()
  const input = sidebar.getByRole('combobox', { name: 'Tags' })
  await expect(input).toBeFocused()
  await input.fill('pricing')
  await input.press('Enter')
  await sidebar.getByRole('button', { name: 'Remove tag b2b' }).click()
  await sidebar.getByRole('button', { name: 'Done' }).click()
  await expect(tags.getByRole('listitem')).toHaveText(['loyalty', 'pricing'])
  await expect(activity(page)).toContainText('edited the tags')

  await sidebar.getByRole('button', { name: 'Edit tags' }).click()
  await sidebar.getByRole('combobox', { name: 'Tags' }).fill('discarded')
  await page.keyboard.press('Escape')
  await expect(tags.getByRole('listitem')).toHaveText(['loyalty', 'pricing'])
})

test.describe('a platform admin', () => {
  test.use({ signedInAs: USERS.priya })

  test('assigns an owner with the picker, and Undo clears it again', async ({ page }) => {
    // CUST-6 "Live chat handover to specialists" has no owner.
    await page.goto('/ideas/CUST-6')
    await expect(heading(page, 'Live chat handover to specialists')).toBeVisible()
    const primary = page.locator('[data-primary-action]:visible')
    await expect(primary).toHaveAccessibleName('Assign owner')
    await page.keyboard.press('a')
    const dialog = page.getByRole('dialog', { name: 'Assign owner' })
    await dialog.getByRole('combobox', { name: 'Owner' }).fill('hannah')
    await dialog.getByRole('option', { name: /Hannah Weber/ }).click()
    await expect(dialog).toBeHidden()
    await expect(details(page).getByRole('button', { name: /^Owner: Hannah Weber/ })).toBeVisible()
    await expect(activity(page)).toContainText('made Hannah Weber the owner')

    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(details(page).getByRole('button', { name: 'Assign', exact: true })).toBeVisible()
    await expect(details(page).getByRole('button', { name: /^Owner:/ })).toHaveCount(0)
    await expect(primary).toHaveAccessibleName('Assign owner')
  })
})
