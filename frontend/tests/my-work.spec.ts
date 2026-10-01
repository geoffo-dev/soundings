import { expect, test } from './support'

test('lists evaluations due, most urgent first, with one primary action', async ({ page }) => {
  await page.goto('/')
  const due = page.locator('#evaluations')
  const rows = due.getByRole('listitem')
  await expect(rows).toHaveCount(4)
  await expect(rows.first()).toContainText('Gift cards with personal video messages')
  await expect(rows.first()).toContainText('Overdue 2 days')
  await expect(rows.nth(2)).toContainText('Draft saved')
  await expect(rows.last()).toContainText('No due date')

  await rows
    .first()
    .getByRole('link', { name: /^Evaluate CUST-7/ })
    .click()
  await expect(page).toHaveURL(/\/ideas\/CUST-7\?evaluate=1$/)
})

test('j/k and arrows move between rows, Enter opens, e evaluates', async ({ page }) => {
  await page.goto('/')
  await expect(
    page.getByRole('link', { name: 'Gift cards with personal video messages', exact: true }),
  ).toBeVisible()
  await page.keyboard.press('j')
  await expect(
    page.getByRole('link', { name: 'Gift cards with personal video messages', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('j')
  await expect(
    page.getByRole('link', { name: 'Self-serve returns portal', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(
    page.getByRole('link', { name: 'Shared test data service', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('k')
  await expect(
    page.getByRole('link', { name: 'Self-serve returns portal', exact: true }),
  ).toBeFocused()

  await page.keyboard.press('e')
  await expect(page).toHaveURL(/\/ideas\/CUST-1\?evaluate=1$/)
  // The URL changes before the idea page renders: wait for the sheet itself (back
  // before that would leave My work in place, focus still on the row).
  await expect(page.getByRole('dialog', { name: 'Evaluate' })).toBeVisible()

  await page.goBack()
  await expect(page.getByRole('heading', { name: 'My work', level: 1 })).toBeVisible()
  await page.keyboard.press('j')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/CUST-7$/)
})

test('groups owned ideas by status, with closed ones collapsed', async ({ page }) => {
  await page.goto('/')
  const owned = page.locator('#owned')
  await expect(owned.getByRole('heading', { name: /^Evaluating/ })).toBeVisible()
  await expect(owned.getByText('Carbon-neutral shipping option')).toBeHidden()
  await owned.getByRole('button', { name: /Show closed/ }).click()
  await expect(owned.getByText('Carbon-neutral shipping option')).toBeVisible()
})

test('the sidebar shows My work counts and the projects', async ({ page }) => {
  await page.goto('/settings')
  const nav = page.getByRole('navigation', { name: 'Main' })
  await expect(nav.getByRole('link', { name: 'Evaluations, 4 due, 1 overdue' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Ideas I own, 6 open' })).toBeVisible()
  await nav.getByRole('link', { name: 'Internal Tools' }).click()
  await expect(page).toHaveURL(/\/p\/internal-tools$/)
  await expect(nav.getByRole('link', { name: 'Internal Tools' })).toHaveAttribute(
    'data-current',
    'true',
  )
  // Breadcrumbs name the project.
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText('Internal Tools')
})

test('shows an error with a retry when My work fails to load', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-fail', '/me/work'))
  await page.goto('/')
  // The error shows after the client's retries (about 3 s): allow for a busy machine.
  await expect(page.getByRole('alert')).toContainText('We couldn’t load your work', {
    timeout: 10_000,
  })
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(
    page.getByRole('link', { name: 'Gift cards with personal video messages', exact: true }),
  ).toBeVisible()
})

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('stacks sections without sideways scrolling; the urgent Evaluate is full width', async ({
    page,
  }) => {
    await page.goto('/')
    const primary = page.getByRole('link', { name: /^Evaluate CUST-7/ })
    await expect(primary).toBeVisible()
    const box = await primary.boundingBox()
    expect(box?.height).toBeGreaterThanOrEqual(44)
    expect(box?.width).toBeGreaterThan(300)
    const overflow = await page.evaluate(() => {
      const main = document.querySelector('main')
      return {
        page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        main: main ? main.scrollWidth - main.clientWidth : 0,
      }
    })
    expect(overflow).toEqual({ page: 0, main: 0 })

    await page.getByRole('button', { name: 'Open navigation' }).click()
    const drawer = page.getByRole('dialog', { name: 'Navigation' })
    await drawer.getByRole('link', { name: 'Customer Innovation' }).click()
    await expect(drawer).toBeHidden()
    await expect(page).toHaveURL(/\/p\/customer-innovation$/)
  })
})
