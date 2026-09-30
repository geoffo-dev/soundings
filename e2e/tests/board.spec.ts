import type { Locator, Page } from '@playwright/test'

import { createTeamProject, type Api, type IdeaDetail, type Project } from './support/api'
import { expect, heading, signIn, test, toast } from './support/fixtures'

/**
 * The project board against the real API: the owner drags a card to another column
 * (mouse and keyboard), Undo puts it back, dropping on Closed asks for a resolution,
 * and someone who may not change the status can't drag. Test plan: ST-*.
 */

const column = (page: Page, label: string) =>
  page.getByRole('region', { name: new RegExp(`^${label}\\b`) })
const card = (scope: Page | Locator, key: string) =>
  scope.getByRole('link', { name: new RegExp(`^${key}\\b`) })
const announcer = (page: Page) => page.locator('[id^="DndLiveRegion"]')

async function drag(page: Page, from: Locator, to: Locator) {
  await from.scrollIntoViewIfNeeded()
  const a = await from.boundingBox()
  const b = await to.boundingBox()
  if (!a || !b) throw new Error('not visible')
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(a.x + a.width / 2 + 12, a.y + a.height / 2, { steps: 4 })
  await page.mouse.move(b.x + b.width / 2, b.y + 120, { steps: 12 })
  await page.mouse.up()
}

let project: Project
let idea: IdeaDetail
let alice: Api

test.beforeEach(async ({ api }) => {
  alice = await api('alice')
  project = await createTeamProject(alice, 'Board', { bob: 'member', farah: 'member' })
  idea = await alice.createIdea(project.slug, {
    title: 'Click and collect lockers',
    summary: 'Parcel lockers at stations for online orders.',
  })
  await alice.setOwner(idea.key, 'bob')
  // A second card so columns are not trivially empty.
  await alice.createIdea(project.slug, {
    title: 'Same-day delivery in London',
    summary: 'Courier partners for orders placed before noon.',
  })
})

async function openBoard(page: Page) {
  await page.goto(`/p/${project.slug}?view=board`)
  await expect(heading(page, project.name)).toBeVisible()
  await expect(card(column(page, 'New'), idea.key)).toBeVisible()
}

test('ST-01/02: the owner drags a card to Evaluating, and Undo moves it back', async ({ page }) => {
  await signIn(page, 'bob')
  await openBoard(page)
  await drag(page, card(page, idea.key), column(page, 'Evaluating'))

  await expect(card(column(page, 'Evaluating'), idea.key)).toBeVisible()
  await expect(card(column(page, 'New'), idea.key)).toHaveCount(0)
  await expect(column(page, 'Evaluating').getByRole('heading', { level: 2 })).toHaveText(
    'Evaluating1',
  )
  await expect(page).toHaveURL(new RegExp(`/p/${project.slug}`)) // the drop didn't open it
  const moved = toast(page, `${idea.key} moved to Evaluating`)
  await expect(moved).toBeVisible()
  await expect.poll(async () => (await alice.idea(idea.key)).status).toBe('evaluating')

  await moved.getByRole('button', { name: 'Undo' }).click()
  await expect(card(column(page, 'New'), idea.key)).toBeVisible()
  await expect(column(page, 'Evaluating').getByRole('heading', { level: 2 })).toHaveText(
    'Evaluating0',
  )
  await expect.poll(async () => (await alice.idea(idea.key)).status).toBe('new')

  // After a reload the board shows what the server has.
  await page.reload()
  await expect(card(column(page, 'New'), idea.key)).toBeVisible()
})

test('ST-01: the owner moves a card with the keyboard, announced to screen readers', async ({
  page,
}) => {
  await signIn(page, 'bob')
  await openBoard(page)
  const item = card(page, idea.key)
  await item.focus()
  await page.keyboard.press('Space')
  await expect(announcer(page)).toContainText(`Picked up ${idea.key}`)
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await expect(announcer(page)).toContainText(`${idea.key} is over Shortlisted`)
  await page.keyboard.press('Space')
  await expect(announcer(page)).toContainText(`${idea.key} moved to Shortlisted`)
  await expect(card(column(page, 'Shortlisted'), idea.key)).toBeFocused()
  await expect.poll(async () => (await alice.idea(idea.key)).status).toBe('shortlisted')
})

test('ST-04: dropping on Closed asks how it was closed', async ({ page }) => {
  await signIn(page, 'bob')
  await openBoard(page)
  await drag(page, card(page, idea.key), column(page, 'Closed'))
  const picker = page.getByRole('dialog', { name: `Close ${idea.key} as` })
  await expect(picker).toBeVisible()
  await picker.getByRole('button', { name: /Parked/ }).click()
  await expect(toast(page, `${idea.key} moved to Parked`)).toBeVisible()
  await expect(column(page, 'Closed').getByRole('button', { name: /Parked/ })).toContainText('1')
  await expect
    .poll(async () => {
      const current = await alice.idea(idea.key)
      return `${current.status}/${current.resolution}`
    })
    .toBe('closed/parked')
})

test('ST-03: someone who may not change the status can’t drag', async ({ page, api }) => {
  // Farah is a member of the project but doesn't own the idea.
  await signIn(page, 'farah')
  await openBoard(page)
  const item = card(page, idea.key)
  await expect(item).not.toHaveAttribute('aria-describedby', /./)
  await item.focus()
  await page.keyboard.press('Space')
  await expect(announcer(page)).not.toContainText('Picked up')
  await drag(page, item, column(page, 'Shortlisted'))
  await expect(card(column(page, 'New'), idea.key)).toBeVisible()
  await expect(card(column(page, 'Shortlisted'), idea.key)).toHaveCount(0)
  expect((await alice.idea(idea.key)).status).toBe('new')
  // …and the API agrees: a direct status change is refused.
  const farah = await api('farah')
  const response = await farah.raw('POST', `/ideas/${idea.key}/status`, { status: 'evaluating' })
  expect(response.status()).toBe(403)
})
