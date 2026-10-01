import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * @mentions in comments (contract-phase3 §3.8): "@" opens a picker of the
 * project's people; the box shows "@Name" (tinted) while the comment stores
 * `@[Name](user:<id>)`, shown as a chip.
 */

const composer = (page: Page) => page.getByRole('textbox', { name: 'Write a comment' })
const picker = (page: Page) => page.getByRole('listbox', { name: 'People to mention' })

test('mention someone with the keyboard and post', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await composer(page).click()
  await page.keyboard.type('Thanks @da')
  await expect(picker(page).getByRole('option', { name: /Dave Okafor/ })).toBeVisible()
  await expect(picker(page)).not.toContainText('Alice Anders') // not yourself
  await expect(composer(page)).toHaveAttribute('aria-activedescendant', /.+/)
  await page.keyboard.press('Enter')
  await expect(picker(page)).toBeHidden()
  await page.keyboard.type('can you check this?')
  // Names, never ids, in the box; the mention is tinted behind the text.
  await expect(composer(page)).toHaveValue('Thanks @Dave Okafor can you check this?')
  await expect(
    page.locator('[data-mention-tint="10000000-0000-4000-8000-000000000005"]'),
  ).toHaveText('@Dave Okafor')

  // Preview shows the chip.
  await page.getByRole('radio', { name: 'Preview' }).click()
  await expect(page.getByRole('region', { name: 'Write a comment (preview)' })).toContainText(
    'Thanks @Dave Okafor can you check this?',
  )
  await page.getByRole('radio', { name: 'Write' }).click()

  await composer(page).press('ControlOrMeta+Enter')
  const comment = page
    .locator('article[data-comment-id]')
    .filter({ hasText: 'can you check this?' })
  await expect(comment.locator('[data-mention]')).toHaveText('@Dave Okafor')
  await expect(comment.getByRole('link')).toHaveCount(0)

  // Editing it shows the name again, never the token.
  await comment.getByRole('button', { name: /Comment actions/ }).click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  const edit = page.getByRole('textbox', { name: 'Edit your comment' })
  await expect(edit).toHaveValue('Thanks @Dave Okafor can you check this?')
  await expect(page.getByText('Markdown · @ to mention', { exact: true })).toBeVisible()
})

test('the mouse can pick too; Esc closes the list without leaving the field', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await composer(page).click()
  await page.keyboard.type('@')
  await expect(picker(page).getByRole('option')).not.toHaveCount(0)
  await expect(picker(page)).not.toContainText('Ivan Petrov') // no role in this project
  await page.keyboard.press('Escape')
  await expect(picker(page)).toBeHidden()
  await expect(composer(page)).toBeFocused()
  await page.keyboard.type('ca')
  await expect(picker(page)).toBeHidden() // dismissed for this "@"
  await page.keyboard.type(' and @ca')
  await picker(page)
    .getByRole('option', { name: /Carol Díaz/ })
    .click()
  await expect(composer(page)).toBeFocused()
  await expect(composer(page)).toHaveValue('@ca and @Carol Díaz ')
})

test('mentions of you are highlighted; others’ are plain chips', async ({ page }) => {
  await page.goto('/ideas/GREEN-7')
  const comment = page.locator('article[data-comment-id]').filter({ hasText: 'supplier audits' })
  await expect(comment.locator('[data-mention]')).toHaveText('@Alice Anders')
  await expect(comment.locator('[data-mention]')).toHaveAttribute('data-mention-self')
})

test.describe('as someone else', () => {
  test.use({ signedInAs: USERS.emma })

  test('the same mention is a neutral chip', async ({ page }) => {
    await page.goto('/ideas/GREEN-7')
    const comment = page.locator('article[data-comment-id]').filter({ hasText: 'supplier audits' })
    await expect(comment.locator('[data-mention]')).toHaveText('@Alice Anders')
    await expect(comment.locator('[data-mention]')).not.toHaveAttribute('data-mention-self')
  })
})
