import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Project settings (wireframe 07) and the create-project dialog. Alice is the
 * only admin of Internal Tools and a plain member of Customer Innovation.
 */

const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

async function openSettings(page: Page, tab = '') {
  await page.goto(`/p/internal-tools/settings${tab ? `?tab=${tab}` : ''}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Project settings' })).toBeVisible()
}

test('general: validates, saves, and says when there is nothing to save', async ({ page }) => {
  await openSettings(page)
  const save = page.getByRole('button', { name: /Save changes/ })
  await save.click()
  await expect(page.getByText('No changes to save.')).toBeVisible()

  const name = page.getByRole('textbox', { name: 'Name' })
  await name.fill('')
  await save.click()
  await expect(page.getByText('Give the project a name.')).toBeVisible()
  await expect(name).toBeFocused()

  await name.fill('Platform Tools')
  await page.getByRole('radio', { name: /Internal/ }).check()
  await page.getByRole('switch', { name: /volunteer/ }).click()
  await page.getByRole('textbox', { name: 'Evaluation window' }).fill('10')
  await expect(page.getByText('Unsaved changes')).toBeVisible()
  await page.keyboard.press('ControlOrMeta+s')
  await expect(toast(page, 'Settings saved')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText('Platform Tools')

  await expect(page.getByText('Unsaved changes')).toBeHidden()

  // Back on the board and in again: the form shows what the server saved.
  await page.getByRole('link', { name: 'Back to ideas' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Platform Tools' })).toBeVisible()
  await page.getByRole('link', { name: 'Project settings' }).click()
  await expect(page.getByRole('textbox', { name: 'Name' })).toHaveValue('Platform Tools')
  await expect(page.getByRole('radio', { name: /Internal/ })).toBeChecked()
  await expect(page.getByRole('switch', { name: /volunteer/ })).not.toBeChecked()
  await expect(page.getByRole('textbox', { name: 'Evaluation window' })).toHaveValue('10')
})

test('members: add, change a role and remove, with Undo; the last admin is protected', async ({
  page,
}) => {
  await openSettings(page, 'members')
  const list = page.getByRole('list', { name: /members/ })
  const row = (name: string) => list.getByRole('listitem').filter({ hasText: name })

  // Alice is the only admin: she can't demote or remove herself.
  await expect(
    row('Alice Anders').getByRole('combobox', { name: 'Role of Alice Anders' }),
  ).toBeDisabled()
  await expect(
    row('Alice Anders').getByRole('button', { name: 'Remove Alice Anders' }),
  ).toBeDisabled()

  await page.getByRole('combobox', { name: 'Add a person' }).click()
  await page.getByPlaceholder('Search by name or email…').last().fill('carol')
  await page.getByRole('option', { name: /Carol Díaz/ }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(toast(page, 'Carol Díaz added as member')).toBeVisible()
  await expect(row('Carol Díaz')).toBeVisible()

  await row('Bob Chen').getByRole('combobox', { name: 'Role of Bob Chen' }).click()
  await page.getByRole('option', { name: 'Admin' }).click()
  await expect(toast(page, 'Bob Chen is now an admin')).toBeVisible()
  // With a second admin, Alice's role can change.
  await expect(
    row('Alice Anders').getByRole('combobox', { name: 'Role of Alice Anders' }),
  ).toBeEnabled()
  await toast(page, 'Bob Chen is now an admin').getByRole('button', { name: 'Undo' }).click()
  await expect(row('Bob Chen').getByRole('combobox', { name: 'Role of Bob Chen' })).toHaveText(
    'Member',
  )

  await row('Dave Okafor').getByRole('button', { name: 'Remove Dave Okafor' }).click()
  await expect(row('Dave Okafor')).toHaveCount(0)
  await toast(page, 'Dave Okafor removed').getByRole('button', { name: 'Undo' }).click()
  await expect(row('Dave Okafor')).toBeVisible()
})

test('rubric: inline validation, limits, reorder and save', async ({ page }) => {
  await openSettings(page, 'rubric')
  const criteria = page.getByRole('list', { name: 'Criteria' })
  const item = (name: string) => criteria.getByRole('listitem', { name })
  await expect(criteria.getByRole('listitem')).toHaveCount(5)

  // Errors show once you leave a field.
  const value = criteria.getByRole('listitem').first().getByRole('textbox', { name: 'Name' })
  await value.fill('')
  await expect(page.getByText('Give the criterion a name.')).toBeHidden()
  await value.press('Tab')
  await expect(page.getByText('Give the criterion a name.')).toBeVisible()
  await value.fill('feasibility')
  await value.press('Tab')
  await expect(page.getByText('Another criterion is called “feasibility”.')).toBeVisible()
  await value.fill('Value')

  const weight = item('Effort').getByRole('textbox', { name: 'Weight' })
  await weight.fill('0')
  await weight.press('Tab')
  await expect(item('Effort').getByText('Use a number from 0.01 to 10.')).toBeVisible()
  await weight.fill('2')
  await expect(item('Effort')).toContainText('33% of the score')

  // 3 to 6 criteria.
  await item('Risk').getByRole('button', { name: 'Remove Risk' }).click()
  await item('Strategic fit').getByRole('button', { name: 'Remove Strategic fit' }).click()
  await expect(criteria.getByRole('listitem')).toHaveCount(3)
  await expect(item('Value').getByRole('button', { name: 'Remove Value' })).toBeDisabled()
  const add = page.getByRole('button', { name: 'Add criterion' })
  for (const count of [4, 5, 6]) {
    await add.click()
    // The new row's name field takes focus.
    await expect(
      criteria
        .getByRole('listitem')
        .nth(count - 1)
        .getByRole('textbox', { name: 'Name' }),
    ).toBeFocused()
  }
  await expect(criteria.getByRole('listitem')).toHaveCount(6)
  await expect(add).toBeDisabled()
  // New rows start empty: saving points at the first gap.
  await page.getByRole('button', { name: /Save rubric/ }).click()
  await expect(
    criteria.getByRole('listitem').nth(3).getByRole('textbox', { name: 'Name' }),
  ).toBeFocused()
  await expect(page.getByText('Give the criterion a name.').first()).toBeVisible()

  for (const [index, name] of [
    [3, 'Reach'],
    [4, 'Urgency'],
    [5, 'Learning'],
  ] as const) {
    await criteria
      .getByRole('listitem')
      .nth(index)
      .getByRole('textbox', { name: 'Name' })
      .fill(name)
  }
  // Guidance for 1/3/5.
  await item('Reach').getByRole('button', { name: 'Guidance' }).click()
  await item('Reach')
    .getByRole('textbox', { name: /score of 5/ })
    .fill('Everyone uses it')

  // Alt+↑ moves a criterion up.
  await item('Learning').getByRole('textbox', { name: 'Name' }).focus()
  await page.keyboard.press('Alt+ArrowUp')
  await expect(criteria.getByRole('listitem').nth(4)).toHaveAccessibleName('Learning')
  await expect(item('Learning').getByRole('textbox', { name: 'Name' })).toBeFocused()

  await page.getByRole('button', { name: /Save rubric/ }).click()
  await expect(toast(page, 'Rubric saved')).toBeVisible()
  await expect(page.getByText('What happens to existing evaluations')).toBeVisible()
  await expect(page.getByText('Unsaved changes')).toBeHidden()
  await expect(criteria.getByRole('listitem')).toHaveCount(6)
  await expect(criteria.getByRole('listitem').nth(4)).toHaveAccessibleName('Learning')
  await expect(item('Reach').getByRole('button', { name: 'Guidance · 1 hint' })).toBeVisible()
})

test('status labels: rename with a live preview, then the board uses them', async ({ page }) => {
  await openSettings(page, 'statuses')
  const newLabel = page.getByRole('textbox', { name: 'New', exact: true })
  await newLabel.fill('Inbox')
  const preview = page.getByRole('heading', { name: 'Preview' }).locator('..')
  await expect(preview).toContainText('Inbox')
  await page.getByRole('button', { name: /Save changes/ }).click()
  await expect(toast(page, 'Status labels saved')).toBeVisible()

  await page.getByRole('link', { name: 'Back to ideas' }).click()
  await page.getByRole('radio', { name: 'Board' }).click()
  await expect(page.getByRole('region', { name: /^Inbox\b/ })).toBeVisible()

  await page.getByRole('link', { name: 'Project settings' }).click()
  await page.getByRole('tab', { name: 'Status labels' }).click()
  await expect(newLabel).toHaveValue('Inbox')
  await page.getByRole('button', { name: 'Reset New to its default name' }).click()
  await expect(newLabel).toHaveValue('New')
  await expect(page.getByText('Unsaved changes')).toBeVisible()
})

test('members of a project see its settings read-only', async ({ page }) => {
  await page.goto('/p/customer-innovation/settings')
  await expect(
    page.getByText('Only project admins can change these settings.').first(),
  ).toBeVisible()
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('tab')).toHaveText(['General', 'Members', 'Rubric'])
  await page.getByRole('tab', { name: 'Rubric' }).click()
  await expect(page).toHaveURL(/tab=rubric/)
  await expect(page.getByText('Strategic fit')).toBeVisible()
})

for (const colorScheme of ['light', 'dark'] as const) {
  test(`settings have no serious accessibility violations (${colorScheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme })
    for (const tab of ['', 'members', 'rubric', 'statuses']) {
      await openSettings(page, tab)
      await expect(page.getByRole('tabpanel')).toBeVisible()
      expect(await seriousViolations(page), `tab ${tab || 'general'}`).toEqual([])
    }
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('settings fit the screen', async ({ page }) => {
    for (const tab of ['', 'members', 'rubric']) {
      await openSettings(page, tab)
      const overflow = await page.evaluate(() => {
        const main = document.querySelector('main')
        return main ? main.scrollWidth - main.clientWidth : 0
      })
      expect(overflow, `tab ${tab || 'general'}`).toBe(0)
    }
  })
})

test.describe('creating a project', () => {
  test.use({ signedInAs: USERS.priya })

  test('suggests a URL and key from the name, then opens the new project', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'New project' }).click()
    const dialog = page.getByRole('dialog', { name: 'New project' })
    await expect(dialog.getByRole('textbox', { name: 'Name' })).toBeFocused()
    await page.keyboard.type('Customer Innovation')
    await expect(dialog.getByRole('textbox', { name: 'URL' })).toHaveValue('customer-innovation')
    await expect(dialog.getByRole('textbox', { name: 'Idea key' })).toHaveValue('CUST')
    await dialog.getByRole('button', { name: /Create project/ }).click()
    await expect(dialog.getByText('Another project uses this URL. Try another.')).toBeVisible()
    await expect(dialog.getByRole('textbox', { name: 'URL' })).toBeFocused()

    await dialog.getByRole('textbox', { name: 'Name' }).fill('Field Research')
    await expect(dialog.getByRole('textbox', { name: 'URL' })).toHaveValue('field-research')
    await expect(dialog.getByRole('textbox', { name: 'Idea key' })).toHaveValue('FIEL')
    await dialog.getByRole('textbox', { name: 'Idea key' }).fill('FR')
    await expect(dialog).toContainText('FR-1, FR-2…')
    await dialog.getByRole('radio', { name: /Internal/ }).check()
    await dialog.getByRole('textbox', { name: 'Description' }).fill('What we learn from customers.')
    await page.keyboard.press('ControlOrMeta+Enter')

    await expect(page).toHaveURL(/\/p\/field-research$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Field Research' })).toBeVisible()
    await expect(page.getByText('No ideas yet')).toBeVisible()
    await expect(page.getByText('Press N to add the first one', { exact: false })).toBeVisible()
    await expect(toast(page, 'Field Research created')).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})
