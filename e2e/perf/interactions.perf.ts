import { expect, test, type Page } from '@playwright/test'

import {
  BIG,
  BUDGET,
  PAT,
  interactionMs,
  longTasksIn,
  markOf,
  newSignedInPage,
  now,
  perfOf,
  record,
  round,
  signIn,
  startFrames,
  stopFrames,
  watch,
} from './support'

/**
 * Interactions on Big Ideas (10k ideas) as Pat Pending (a member who owes 1,000 blind
 * evaluations), at CPU throttling (default 4x). "Response" is the Event Timing duration
 * of the interaction: from the input to the next frame painted after its handlers (what
 * INP measures), against the 100 ms budget. "Result" is when the new content first shows
 * (DOM change, then a frame), which includes the network.
 */

const table = (page: Page) => page.getByRole('table', { name: 'Ideas' })
const ROWS = 'table[aria-label="Ideas"] tbody tr a[href^="/ideas/"]'

async function openList(page: Page, search = '') {
  await page.goto(`/p/${BIG}?view=list${search}`)
  await expect(table(page).locator('tbody tr a[href^="/ideas/"]').first()).toBeVisible()
  await page.waitForLoadState('networkidle')
}

function softBudget(name: string, value: number) {
  expect
    .soft(value, `${name}: response budget ${BUDGET.interactionMs} ms`)
    .toBeLessThan(BUDGET.interactionMs)
}

test('list: scroll through 10k ideas (wheel, infinite loading)', async ({ context }, testInfo) => {
  const page = await newSignedInPage(context, PAT)
  await openList(page)
  const box = await table(page).boundingBox()
  if (!box) throw new Error('no table')
  await page.mouse.move(box.x + box.width / 2, box.y + Math.min(box.height / 2, 400))
  const pages = { count: 0 }
  page.on('request', (r) => {
    if (r.url().includes(`/projects/${BIG}/ideas`) && r.url().includes('cursor=')) pages.count++
  })
  const from = await now(page)
  await startFrames(page)
  for (let i = 0; i < 80; i++) {
    await page.mouse.wheel(0, 400)
    await page.waitForTimeout(25)
  }
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  const frames = await stopFrames(page)
  const windowMs = (await now(page)) - from
  const perf = await perfOf(page)
  const rendered = await page.locator(ROWS).count()
  const loaded = await page.evaluate(() =>
    Number(document.querySelector('table[aria-label="Ideas"]')?.getAttribute('aria-rowcount')),
  )
  const row = {
    windowMs: round(windowMs),
    ...frames,
    ...prefix('longTasks', longTasksIn(perf, from)),
    pagesLoaded: pages.count,
    rowsInDom: rendered,
    ariaRowCount: loaded,
    heapMB: await heapMB(page),
  }
  record(testInfo, 'list scroll (80 wheel ticks)', row)
  expect.soft(frames.droppedShare, 'dropped frame share').toBeLessThan(BUDGET.droppedFrameShare)
})

test('board: scroll a column (wheel, load more)', async ({ context }, testInfo) => {
  const page = await newSignedInPage(context, PAT)
  await page.goto(`/p/${BIG}?view=board`)
  const column = page.getByRole('region', { name: /^Evaluating\b/ })
  await expect(column.getByRole('link').first()).toBeVisible()
  await page.waitForLoadState('networkidle')
  const card = await column.getByRole('link').nth(1).boundingBox()
  if (!card) throw new Error('no card')
  await page.mouse.move(card.x + card.width / 2, card.y + card.height / 2)
  const from = await now(page)
  await startFrames(page)
  for (let i = 0; i < 60; i++) {
    await page.mouse.wheel(0, 300)
    await page.waitForTimeout(25)
  }
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  const frames = await stopFrames(page)
  const windowMs = (await now(page)) - from
  const perf = await perfOf(page)
  const row = {
    windowMs: round(windowMs),
    ...frames,
    ...prefix('longTasks', longTasksIn(perf, from)),
    cardsInColumn: await column.getByRole('link').count(),
    domNodes: await page.evaluate(() => document.getElementsByTagName('*').length),
    heapMB: await heapMB(page),
  }
  record(testInfo, 'board column scroll (60 wheel ticks)', row)
  expect.soft(frames.droppedShare, 'dropped frame share').toBeLessThan(BUDGET.droppedFrameShare)
})

test('list: sort by score and filter "Needs evaluators"', async ({ context }, testInfo) => {
  const page = await newSignedInPage(context, PAT)
  await openList(page)
  for (const step of [
    {
      name: 'sort by score',
      click: () => page.getByRole('button', { name: 'Score', exact: true }).click(),
      url: /sort=/,
    },
    {
      name: 'filter needs evaluators',
      click: () => page.getByRole('button', { name: 'Needs evaluators' }).click(),
      url: /needs_evaluators/,
    },
  ]) {
    const first = await page.locator(ROWS).first().getAttribute('href')
    await watch(
      page,
      `${step.name}:busy`,
      'table[aria-label="Ideas"] [aria-busy="true"], [aria-busy="true"] table[aria-label="Ideas"]',
    )
    const from = await now(page)
    await step.click()
    await expect(page).toHaveURL(step.url)
    await expect(page.locator(ROWS).first()).not.toHaveAttribute('href', first ?? '')
    await page.waitForFunction(
      () => !document.querySelector('[aria-busy="true"] table, table [aria-busy="true"]'),
    )
    const done = await now(page)
    await page.waitForTimeout(300)
    const perf = await perfOf(page)
    const busy = perf.marks[`${step.name}:busy:frame`]
    const row = {
      responseMs: round(interactionMs(perf, from)),
      busyShownMs: busy ? round(busy - from) : -1,
      resultMs: round(done - from),
      ...prefix('longTasks', longTasksIn(perf, from)),
    }
    record(testInfo, `list ${step.name}`, row)
    softBudget(step.name, row.responseMs)
  }
})

test('command palette: open and search "pricing"', async ({ context }, testInfo) => {
  const page = await newSignedInPage(context, PAT)
  await openList(page)
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  const from = await now(page)
  await page.keyboard.press('ControlOrMeta+k')
  await expect(palette.getByRole('combobox')).toBeFocused()
  const opened = await now(page)
  await page.keyboard.type('pricing', { delay: 80 })
  const typed = await now(page)
  const hit = palette.getByRole('group', { name: 'Ideas' }).getByRole('option').first()
  await expect(hit).toContainText(/pricing/i)
  const shown = await now(page)
  await page.waitForTimeout(300)
  const perf = await perfOf(page)
  const keys = perf.events.filter((e) => e.interactionId > 0 && e.start >= opened - 1)
  const row = {
    openResponseMs: round(
      interactionMs({ ...perf, events: perf.events.filter((e) => e.start < opened) }, from),
    ),
    openShownMs: round(opened - from),
    worstKeystrokeMs: round(Math.max(0, ...keys.map((e) => e.duration))),
    resultsAfterLastKeyMs: round(shown - typed),
    ...prefix('longTasks', longTasksIn(perf, from)),
  }
  record(testInfo, 'command palette search', row)
  softBudget('palette open', row.openResponseMs)
  softBudget('palette keystroke', row.worstKeystrokeMs)
})

test('open an idea from the list', async ({ context }, testInfo) => {
  const page = await newSignedInPage(context, PAT)
  await openList(page)
  const link = page.locator(ROWS).nth(3)
  const title = (await link.textContent())?.trim() ?? ''
  await watch(page, 'idea heading', '[aria-label="Idea details"]')
  const from = await now(page)
  await link.click()
  await expect(page).toHaveURL(/\/ideas\/BIG-\d+/)
  const heading = (await markOf(page, 'idea heading')) - from
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.waitForLoadState('networkidle')
  const settled = (await now(page)) - from
  await page.waitForTimeout(300)
  const perf = await perfOf(page)
  const row = {
    responseMs: round(interactionMs(perf, from)),
    pageShownMs: round(heading),
    networkIdleMs: round(settled),
    title: title.slice(0, 40),
    ...prefix('longTasks', longTasksIn(perf, from)),
  }
  record(testInfo, 'open idea from list', row)
  softBudget('open idea', row.responseMs)
})

test('open the evaluate sheet', async ({ context }, testInfo) => {
  await signIn(context.request, PAT)
  const work = (await (await context.request.get('/api/v1/me/work')).json()) as {
    evaluations_due: { idea: { key: string } }[]
  }
  const key = work.evaluations_due[0]?.idea.key
  if (!key) throw new Error('Pat owes nothing: reseed')
  const page = await newSignedInPage(context, PAT)
  await page.goto(`/ideas/${key}`)
  const action = page.locator('[data-primary-action]:visible')
  await expect(action).toHaveAccessibleName('Evaluate')
  await page.waitForLoadState('networkidle')
  const from = await now(page)
  await action.click()
  const sheet = page.getByRole('dialog', { name: /^(Evaluate|Your evaluation)$/ })
  await expect(sheet).toBeVisible()
  const shown = (await now(page)) - from
  await expect(sheet.getByRole('radiogroup').first()).toBeVisible()
  const ready = (await now(page)) - from
  await page.waitForTimeout(300)
  const perf = await perfOf(page)
  const row = {
    responseMs: round(interactionMs(perf, from)),
    sheetShownMs: round(shown),
    scoresReadyMs: round(ready),
    ...prefix('longTasks', longTasksIn(perf, from)),
  }
  record(testInfo, 'open evaluate sheet', row)
  softBudget('evaluate sheet', row.responseMs)
})

function prefix(name: string, values: Record<string, number>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(values).map(([k, v]) => [`${name}${k[0]!.toUpperCase()}${k.slice(1)}`, v]),
  )
}

async function heapMB(page: Page): Promise<number> {
  return page.evaluate(() => {
    const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory
    return memory ? Math.round(memory.usedJSHeapSize / 1024 / 1024) : -1
  })
}
