import { defineConfig, devices } from '@playwright/test'

/**
 * Frontend performance checks (Phase 7, docs/test-plans/performance.md) against the
 * performance stack: `e2e/perf/stack.sh up` (the production SPA build served by the
 * API, the demo story plus 10k ideas in Big Ideas). Nothing is started here.
 *
 *   npx --prefix e2e playwright test -c e2e/perf/playwright.config.ts
 *
 * PERF_BASE_URL (default http://localhost:8320), PERF_CPU_THROTTLE (default 4: a
 * mid-range laptop), PERF_RESULTS (default e2e/perf/.stack/results/frontend.json).
 * One test at a time and no retries: the numbers are the point.
 */
const baseURL = (process.env.PERF_BASE_URL ?? 'http://localhost:8320').replace(/\/$/, '')

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.perf\.ts$/,
  outputDir: './.stack/test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
    baseURL,
    locale: 'en-GB',
    timezoneId: 'Europe/London',
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    trace: 'off',
    screenshot: 'only-on-failure',
  },
})
