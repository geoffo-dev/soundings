import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { APIRequestContext, BrowserContext, Page, TestInfo } from '@playwright/test'

/**
 * Helpers for the frontend performance specs (*.perf.ts): sign-in through the dev
 * login, CPU throttling over CDP, in-page observers (LCP, long tasks, Event Timing,
 * frame sampling, "first seen" marks for selectors) and a results file.
 */

export const CPU_THROTTLE = Number(process.env.PERF_CPU_THROTTLE ?? 4)
export const BIG = 'big-ideas'
export const PAT = 'perf01@example.com' // owes 1,000 evaluations in Big Ideas (blind)
export const ALICE = 'alice@example.com' // platform admin, project admin

/** Budgets from the Phase 7 brief (docs/test-plans/performance.md). */
export const BUDGET = {
  lcpMs: 1500,
  interactionMs: 100,
  /** Reference values, reported but not enforced: Lighthouse "good" TBT; one dropped frame in ten. */
  tbtMs: 200,
  droppedFrameShare: 0.1,
}

const here = dirname(fileURLToPath(import.meta.url))
const resultsFile = resolve(
  process.env.PERF_RESULTS ?? resolve(here, '.stack/results/frontend.json'),
)

// --- Sign-in ------------------------------------------------------------------------------
export async function signIn(request: APIRequestContext, email: string): Promise<string> {
  const users = (await (await request.get('/api/v1/auth/dev/users')).json()) as {
    id: string
    email: string
  }[]
  const user = users.find((u) => u.email === email)
  if (!user) throw new Error(`no dev-login user ${email}: run e2e/perf/stack.sh up first`)
  const response = await request.post('/api/v1/auth/dev/login', { data: { user_id: user.id } })
  if (!response.ok()) throw new Error(`dev login failed: ${response.status()}`)
  return user.id
}

export async function newSignedInPage(
  context: BrowserContext,
  email: string,
  watch: Record<string, string> = {},
): Promise<Page> {
  await signIn(context.request, email)
  const page = await context.newPage()
  await page.addInitScript(installObservers, watch)
  const cdp = await context.newCDPSession(page)
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_THROTTLE })
  return page
}

// --- In-page observers (serialised into the page: no closures) ------------------------------
export type Perf = {
  fcp: number
  lcp: number
  lcpElement: string
  longTasks: { start: number; duration: number }[]
  events: { name: string; start: number; duration: number; interactionId: number }[]
  marks: Record<string, number>
}

declare global {
  interface Window {
    __perf: Perf
    __perfWatch: (name: string, selector: string) => void
    __perfFrames?: number[]
    __perfFramesStop?: boolean
  }
}

function installObservers(watch: Record<string, string>) {
  const perf: Perf = { fcp: 0, lcp: 0, lcpElement: '', longTasks: [], events: [], marks: {} }
  window.__perf = perf
  const observe = (type: string, onEntry: (entry: PerformanceEntry) => void, extra = {}) => {
    try {
      new PerformanceObserver((list) => list.getEntries().forEach(onEntry)).observe({
        type,
        buffered: true,
        ...extra,
      } as PerformanceObserverInit)
    } catch {
      /* not supported */
    }
  }
  observe('paint', (e) => {
    if (e.name === 'first-contentful-paint') perf.fcp = e.startTime
  })
  observe('largest-contentful-paint', (e) => {
    perf.lcp = e.startTime
    const element = (e as PerformanceEntry & { element?: Element }).element
    perf.lcpElement = element
      ? `${element.tagName.toLowerCase()} ${element.textContent?.slice(0, 40) ?? ''}`
      : ''
  })
  observe('longtask', (e) => perf.longTasks.push({ start: e.startTime, duration: e.duration }))
  observe(
    'event',
    (e) => {
      const timing = e as PerformanceEntry & { interactionId?: number }
      perf.events.push({
        name: e.name,
        start: e.startTime,
        duration: e.duration,
        interactionId: timing.interactionId ?? 0,
      })
    },
    { durationThreshold: 16 },
  )
  // "First seen" marks: when a selector first matches (DOM mutation time, then the next
  // frame, which is when it can be on screen).
  window.__perfWatch = (name: string, selector: string) => {
    const check = () => {
      if (perf.marks[name] !== undefined || !document.querySelector(selector)) return false
      perf.marks[name] = performance.now()
      requestAnimationFrame(() => (perf.marks[`${name}:frame`] = performance.now()))
      return true
    }
    if (check()) return
    const observer = new MutationObserver(() => check() && observer.disconnect())
    const start = () =>
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
      })
    if (document.documentElement) start()
    else document.addEventListener('DOMContentLoaded', start)
  }
  for (const [name, selector] of Object.entries(watch)) window.__perfWatch(name, selector)
}

export async function perfOf(page: Page): Promise<Perf> {
  return page.evaluate(() => JSON.parse(JSON.stringify(window.__perf)) as Perf)
}

/** Watch for a selector from now on; read the mark with {@link markOf}. */
export async function watch(page: Page, name: string, selector: string) {
  await page.evaluate(([n, s]) => window.__perfWatch(n!, s!), [name, selector])
}

export async function now(page: Page): Promise<number> {
  return page.evaluate(() => performance.now())
}

export async function markOf(page: Page, name: string, timeoutMs = 30_000): Promise<number> {
  const handle = await page.waitForFunction(
    (n) => window.__perf.marks[`${n}:frame`] ?? undefined,
    name,
    { timeout: timeoutMs, polling: 50 },
  )
  return (await handle.jsonValue()) as number
}

/** Total blocking time: the part of each long task over 50 ms, after `from`. */
export function tbt(perf: Perf, from = 0, to = Infinity): number {
  return perf.longTasks
    .filter((t) => t.start >= from && t.start < to)
    .reduce((sum, t) => sum + Math.max(0, t.duration - 50), 0)
}

export function longTasksIn(perf: Perf, from: number, to = Infinity) {
  const tasks = perf.longTasks.filter((t) => t.start >= from && t.start < to)
  return {
    count: tasks.length,
    totalMs: round(tasks.reduce((sum, t) => sum + t.duration, 0)),
    maxMs: round(Math.max(0, ...tasks.map((t) => t.duration))),
  }
}

/** The slowest interaction (Event Timing: input to the next paint) after `from`. */
export function interactionMs(perf: Perf, from: number): number {
  const durations = perf.events
    .filter((e) => e.interactionId > 0 && e.start >= from - 1)
    .map((e) => e.duration)
  return durations.length ? Math.max(...durations) : 0
}

export async function resourceBytes(page: Page) {
  return page.evaluate(() => {
    const entries = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    // transferSize: bytes over the network (0 when served from the HTTP cache).
    const sum = (test: (e: PerformanceResourceTiming) => boolean) =>
      entries.filter(test).reduce((total, e) => total + e.transferSize, 0)
    const path = (e: PerformanceResourceTiming) => new URL(e.name).pathname
    return {
      jsBytes: sum((e) => path(e).endsWith('.js')),
      jsDecodedBytes: entries
        .filter((e) => path(e).endsWith('.js'))
        .reduce((total, e) => total + e.decodedBodySize, 0),
      jsFiles: entries.filter((e) => path(e).endsWith('.js')).length,
      cssBytes: sum((e) => path(e).endsWith('.css')),
      fontBytes: sum((e) => path(e).endsWith('.woff2')),
      apiBytes: sum((e) => path(e).startsWith('/api/')),
      apiRequests: entries.filter((e) => path(e).startsWith('/api/')).length,
    }
  })
}

// --- Frames -------------------------------------------------------------------------------
export async function startFrames(page: Page) {
  await page.evaluate(() => {
    window.__perfFrames = []
    window.__perfFramesStop = false
    const tick = (t: number) => {
      window.__perfFrames!.push(t)
      if (!window.__perfFramesStop) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

export async function stopFrames(page: Page) {
  const frames = await page.evaluate(() => {
    window.__perfFramesStop = true
    return window.__perfFrames ?? []
  })
  const deltas = frames.slice(1).map((t, i) => t - frames[i]!)
  const sorted = [...deltas].sort((a, b) => a - b)
  const pick = (q: number) =>
    sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? 0
  // A frame "drops" when the gap is over 1.5 frames (60 Hz): count the missed ones.
  const dropped = deltas.reduce((n, d) => n + (d > 25 ? Math.round(d / 16.7) - 1 : 0), 0)
  return {
    frames: frames.length,
    p50FrameMs: round(pick(0.5)),
    p95FrameMs: round(pick(0.95)),
    maxFrameMs: round(sorted.at(-1) ?? 0),
    droppedFrames: dropped,
    droppedShare: round(dropped / Math.max(1, dropped + frames.length), 3),
  }
}

// --- Results ------------------------------------------------------------------------------
export function round(value: number, digits = 1): number {
  const f = 10 ** digits
  return Math.round(value * f) / f
}

type Row = Record<string, number | string | boolean>

/** Prints the metrics, adds them to the results file and returns budget misses. */
export function record(testInfo: TestInfo, name: string, row: Row): void {
  const line = Object.entries(row)
    .map(([k, v]) => `${k}=${typeof v === 'number' ? round(v) : v}`)
    .join(' ')
  console.log(`[perf] ${name}: ${line}`)
  mkdirSync(dirname(resultsFile), { recursive: true })
  let all: Record<string, Row> = {}
  try {
    all = JSON.parse(readFileSync(resultsFile, 'utf8')) as Record<string, Row>
  } catch {
    /* first result */
  }
  all[name] = { ...row, cpuThrottle: CPU_THROTTLE, at: new Date().toISOString() }
  writeFileSync(resultsFile, JSON.stringify(all, null, 2) + '\n')
  void testInfo.attach(name, {
    body: JSON.stringify(row, null, 2),
    contentType: 'application/json',
  })
}
