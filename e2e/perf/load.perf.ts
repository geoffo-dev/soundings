import { expect, test } from '@playwright/test'

import {
  ALICE,
  BIG,
  BUDGET,
  PAT,
  interactionMs,
  longTasksIn,
  markOf,
  newSignedInPage,
  perfOf,
  record,
  resourceBytes,
  round,
  tbt,
} from './support'

/**
 * Cold loads of the production build at CPU throttling (PERF_CPU_THROTTLE, default 4x):
 * a new browser context (empty HTTP cache) signed in through the dev login, then one
 * navigation. LCP and FCP from the browser, TBT from long tasks after FCP until the
 * page has its data and has been quiet for 2 s, bytes from Resource Timing, and the
 * moment the page's main content first shows ("data shown").
 */

const ROW = 'table[aria-label="Ideas"] tbody tr a[href^="/ideas/"]'
const CARD = 'main section a[href^="/ideas/"], main [role="region"] a[href^="/ideas/"]'

const LOADS = [
  { name: 'cold load /p/big-ideas (list), Pat', who: PAT, url: `/p/${BIG}?view=list`, data: ROW },
  {
    name: 'cold load /p/big-ideas (board), Pat',
    who: PAT,
    url: `/p/${BIG}?view=board`,
    data: CARD,
  },
  {
    name: 'cold load / (My work, 1,000 due), Pat',
    who: PAT,
    url: '/',
    data: 'main a[href^="/ideas/"]',
  },
  {
    name: 'cold load /p/big-ideas (list), Alice',
    who: ALICE,
    url: `/p/${BIG}?view=list`,
    data: ROW,
  },
  { name: 'cold load / (My work), Alice', who: ALICE, url: '/', data: 'main a[href^="/ideas/"]' },
]

for (const load of LOADS) {
  test(load.name, async ({ browser }, testInfo) => {
    const context = await browser.newContext()
    const page = await newSignedInPage(context, load.who, { data: load.data })
    await page.goto(load.url, { waitUntil: 'load' })
    const dataShown = await markOf(page, 'data')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2_000) // quiet: LCP final, late long tasks counted
    const perf = await perfOf(page)
    const nav = await page.evaluate(() => {
      const [entry] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[]
      return {
        ttfb: entry?.responseStart ?? 0,
        domContentLoaded: entry?.domContentLoadedEventEnd ?? 0,
      }
    })
    const bytes = await resourceBytes(page)
    const dom = await page.evaluate(() => document.getElementsByTagName('*').length)
    const tasks = longTasksIn(perf, 0)
    const row = {
      fcpMs: round(perf.fcp),
      lcpMs: round(perf.lcp),
      lcpElement: perf.lcpElement,
      dataShownMs: round(dataShown),
      tbtMs: round(tbt(perf, perf.fcp)),
      longTasks: tasks.count,
      maxLongTaskMs: tasks.maxMs,
      ttfbMs: round(nav.ttfb),
      domContentLoadedMs: round(nav.domContentLoaded),
      jsKB: round(bytes.jsBytes / 1024),
      jsDecodedKB: round(bytes.jsDecodedBytes / 1024),
      jsFiles: bytes.jsFiles,
      cssKB: round(bytes.cssBytes / 1024),
      fontKB: round(bytes.fontBytes / 1024),
      apiRequests: bytes.apiRequests,
      apiKB: round(bytes.apiBytes / 1024),
      domNodes: dom,
    }
    record(testInfo, load.name, row)
    expect.soft(row.lcpMs, `LCP budget ${BUDGET.lcpMs} ms`).toBeLessThan(BUDGET.lcpMs)
    await context.close()
  })
}

test('warm load /p/big-ideas (list, assets cached), Pat', async ({ browser }, testInfo) => {
  const context = await browser.newContext()
  const page = await newSignedInPage(context, PAT, { data: ROW })
  await page.goto(`/p/${BIG}?view=list`, { waitUntil: 'load' })
  await markOf(page, 'data')
  await page.waitForLoadState('networkidle')
  await page.reload({ waitUntil: 'load' })
  const dataShown = await markOf(page, 'data')
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1_500)
  const perf = await perfOf(page)
  const bytes = await resourceBytes(page)
  const row = {
    fcpMs: round(perf.fcp),
    lcpMs: round(perf.lcp),
    dataShownMs: round(dataShown),
    tbtMs: round(tbt(perf, perf.fcp)),
    jsKBOverNetwork: round(bytes.jsBytes / 1024),
    apiRequests: bytes.apiRequests,
    apiKB: round(bytes.apiBytes / 1024),
    firstInputMs: round(interactionMs(perf, 0)),
  }
  record(testInfo, 'warm load /p/big-ideas (list), Pat', row)
  expect.soft(row.lcpMs, `LCP budget ${BUDGET.lcpMs} ms`).toBeLessThan(BUDGET.lcpMs)
  await context.close()
})
