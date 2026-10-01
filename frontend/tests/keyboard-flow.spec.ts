import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Keyboard flows from the Phase 1 UX review: focus comes back after overlays and
 * inline edits close, pickers work as "type a name, press Enter", ⌘/Ctrl+Enter
 * submits Invite, ⌘K highlights its top row, and settings ask before throwing
 * edits away.
 */

test.describe('as a platform admin on an idea', () => {
  test.use({ signedInAs: USERS.priya })

  // CUST-1 "Self-serve returns portal": evaluating, owned by Bob, three evaluators.
  async function openIdea(page: Page) {
    await page.goto('/ideas/CUST-1')
    await expect(
      page.getByRole('heading', { level: 1, name: 'Self-serve returns portal' }),
    ).toBeVisible()
  }

  test('focus goes back to where it was when an overlay closes', async ({ page }) => {
    await openIdea(page)
    const invite = page.getByRole('button', { name: 'Invite evaluators' }).first()
    await invite.focus()

    // Opened from a button, a shortcut, the palette, the "?" sheet and the pickers.
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog', { name: 'Invite evaluators' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(invite).toBeFocused()

    for (const key of ['n', 'ControlOrMeta+k', '?', 's', 'a']) {
      await page.keyboard.press(key)
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog')).toBeHidden()
      await expect(invite, `after ${key}`).toBeFocused()
    }

    // A dialog opened from a menu returns to the menu's button.
    const more = page.getByRole('button', { name: 'More actions' })
    await more.click()
    await page.getByRole('menuitem', { name: /Delete idea/ }).click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(more).toBeFocused()
  })

  test('inline edits and toggles keep focus on what replaces them', async ({ page }) => {
    await openIdea(page)
    await page.getByRole('button', { name: 'Edit title' }).click()
    await page.keyboard.press('End')
    await page.keyboard.type(' v2')
    await page.keyboard.press('Enter')
    await expect(
      page.getByRole('heading', { level: 1, name: 'Self-serve returns portal v2' }),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit title' })).toBeFocused()

    const sidebar = page.getByRole('complementary', { name: 'Idea details' })
    await sidebar.getByRole('button', { name: 'Close evaluation' }).click()
    await expect(sidebar.getByRole('button', { name: 'Reopen' })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(sidebar.getByRole('button', { name: 'Close evaluation' })).toBeFocused()
  })

  test('the owner picker: type a name, press Enter', async ({ page }) => {
    await openIdea(page)
    await page.keyboard.press('a')
    const dialog = page.getByRole('dialog', { name: 'Change owner' })
    await page.keyboard.type('farid')
    await expect(dialog.getByRole('option', { name: /Farid Haddad/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    // "Remove owner" steps aside while you search, so Enter can't pick it by accident.
    await expect(dialog.getByRole('option', { name: 'Remove owner' })).toBeHidden()
    await page.keyboard.press('Enter')
    await expect(dialog).toBeHidden()
    await expect(page.getByRole('button', { name: /^Owner: Farid Haddad/ }).first()).toBeVisible()
  })

  test('Invite: type, Enter picks, ⌘/Ctrl+Enter invites', async ({ page }) => {
    await openIdea(page)
    await page.getByRole('button', { name: 'Invite evaluators' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Invite evaluators' })
    await page.keyboard.type('hann')
    await expect(dialog.getByRole('option', { name: /Hannah Weber/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await page.keyboard.press('Enter')
    await expect(dialog.getByRole('list', { name: 'Selected people' })).toContainText(
      'Hannah Weber',
    )

    // With focus still in the search field: invites, doesn't toggle Hannah off again.
    await page.keyboard.press('ControlOrMeta+Enter')
    await expect(dialog).toBeHidden()
    // The toast (the activity feed soon says "… invited Hannah Weber" too).
    await expect(
      page.locator('[data-sonner-toast]', { hasText: 'Invited Hannah Weber' }),
    ).toBeVisible()
  })
})

test('⌘K highlights the top row, and commands sit above ideas', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  const selected = palette.getByRole('option', { selected: true })

  for (const [query, top] of [
    ['new', /New idea/],
    ['sign', /Sign out/],
    ['returns', /Self-serve returns portal/],
  ] as const) {
    await page.keyboard.press('ControlOrMeta+k')
    await expect(palette.getByRole('combobox')).toBeFocused()
    await page.keyboard.type(query)
    await expect(palette.getByRole('option').first()).toHaveText(top)
    await expect(selected).toHaveText(top)
    await page.keyboard.press('Escape')
  }
})

test('settings ask before leaving with unsaved changes', async ({ page }) => {
  await page.goto('/p/internal-tools/settings?tab=rubric')
  await expect(page.getByRole('heading', { level: 1, name: 'Project settings' })).toBeVisible()
  const firstName = page
    .getByRole('list', { name: 'Criteria' })
    .getByRole('listitem')
    .first()
    .getByRole('textbox', { name: 'Name' })
  await firstName.fill('Customer value')
  // The save bar stays in view while there are changes.
  await expect(page.getByRole('button', { name: /Save rubric/ })).toBeInViewport()

  await page.getByRole('link', { name: 'My work' }).first().click()
  const confirm = page.getByRole('alertdialog', { name: 'Leave without saving?' })
  await expect(confirm).toContainText('the rubric')
  await confirm.getByRole('button', { name: 'Keep editing' }).click()
  await expect(page).toHaveURL(/\/settings/)
  await expect(firstName).toHaveValue('Customer value')

  await page.getByRole('link', { name: 'My work' }).first().click()
  await confirm.getByRole('button', { name: 'Discard changes' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
})

test('an unsent New idea draft stays with its author', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('n')
  await page.getByRole('textbox', { name: 'Title' }).fill('Alice: confidential plan')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Account menu for Alice Anders' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await page.getByRole('button', { name: /Bob Chen/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('n')
  await expect(page.getByRole('textbox', { name: 'Title' })).toHaveValue('')
  expect(
    await page.evaluate(() => Object.keys(localStorage).filter((key) => key.includes('draft'))),
  ).toEqual([])
})
