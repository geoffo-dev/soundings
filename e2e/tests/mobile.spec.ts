import type { Page } from '@playwright/test'

import { createTeamProject, defaultRubricScores } from './support/api'
import {
  evaluateSheet,
  expect,
  heading,
  seriousViolations,
  settled,
  signIn,
  test,
} from './support/fixtures'

/**
 * A phone (390 × 844, touch) against the real stack: from My work to a submitted
 * evaluation and the reveal, with 44 px targets and nothing scrolling sideways.
 * Test plan: MO-*.
 */
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

const CRITERIA = ['Value', 'Feasibility', 'Effort', 'Strategic fit', 'Risk'] as const

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector('main')
    return {
      page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      main: main ? main.scrollWidth - main.clientWidth : 0,
    }
  })
}

test('MO-01/02: evaluate on a phone, from My work to the reveal', async ({ page, api }) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Phone', {
    bob: 'member',
    carol: 'member',
    zanele: 'member',
  })
  const idea = await alice.createIdea(project.slug, {
    title: 'Scan a receipt to return an item',
    summary: 'No order number needed: scan the paper receipt in the app.',
  })
  await alice.setOwner(idea.key, 'bob')
  const bob = await api('bob')
  await bob.invite(idea.key, ['carol', 'zanele'])
  await (
    await api('carol')
  ).evaluate(idea.key, defaultRubricScores(4, 3, 3, 4, 2), {
    recommendation: 'go',
    comment: 'Works offline too, which matters in stores.',
  })

  await signIn(page, 'zanele')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  expect(await horizontalOverflow(page)).toEqual({ page: 0, main: 0 })
  const row = page.locator('#evaluations').getByRole('listitem').filter({ hasText: idea.key })
  const evaluate = row.getByRole('link', { name: new RegExp(`^Evaluate ${idea.key}`) })
  await expect(evaluate).toBeVisible()
  await evaluate.tap()

  await expect(page).toHaveURL(new RegExp(`/ideas/${idea.key}\\?evaluate=1`))
  const sheet = evaluateSheet(page)
  await expect(sheet).toBeVisible()
  const box = await sheet.boundingBox()
  expect(box?.width).toBe(390)
  expect(box?.height).toBeGreaterThan(800)

  for (const criterion of CRITERIA) {
    const radio = sheet
      .getByRole('radiogroup', { name: criterion, exact: true })
      .getByRole('radio', { name: '4', exact: true })
    const target = await radio.boundingBox()
    expect(Math.round(target?.height ?? 0)).toBeGreaterThanOrEqual(44)
    await radio.tap()
    await expect(radio).toBeChecked()
  }
  await sheet
    .getByRole('radiogroup', { name: 'Overall recommendation' })
    .getByRole('radio', { name: 'Go' })
    .tap()
  const submit = sheet.getByRole('button', { name: /^Submit/ })
  await expect(submit).toBeInViewport()
  expect(Math.round((await submit.boundingBox())?.height ?? 0)).toBeGreaterThanOrEqual(44)
  await submit.tap()

  const reveal = page.getByRole('dialog', { name: 'Your evaluation' })
  await expect(reveal).toBeVisible()
  await expect(reveal.getByRole('img', { name: /^Carol Chen: \d out of 5$/ })).toHaveCount(5)
  await expect(reveal.getByText('2 evaluations')).toBeVisible()
  await reveal.getByRole('button', { name: 'Done' }).tap()
  await expect(reveal).toBeHidden()

  // The page now shows the score; the sticky Evaluate bar is gone.
  await expect(page.getByRole('img', { name: /^Score \d\.\d out of 5/ })).toBeVisible()
  await expect(page.locator('[data-primary-action]:visible')).toHaveCount(0)
  expect(await horizontalOverflow(page)).toEqual({ page: 0, main: 0 })

  const mine = await (
    await api('zanele')
  ).get<{ state: string }>(`/ideas/${idea.key}/evaluations/me`)
  expect(mine.state).toBe('submitted')
  // …and it has left My work.
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  await expect(page.locator('#evaluations').getByText(idea.key)).toHaveCount(0)
})

test('MO-02: board, list, idea page and settings fit the screen, with no axe violations', async ({
  page,
}) => {
  await signIn(page, 'alice')
  for (const path of [
    '/p/customer-innovation?view=list',
    '/p/customer-innovation?view=board',
    '/ideas/CUST-12',
    '/p/customer-innovation/settings?tab=rubric',
  ]) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await settled(page)
    expect(await horizontalOverflow(page), path).toEqual({ page: 0, main: 0 })
    expect(await seriousViolations(page), path).toEqual([])
  }
})
