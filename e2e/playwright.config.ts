import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against the real stack: the FastAPI app serving the built SPA,
 * PostgreSQL, the demo data (`soundings seed`) and the dev login. No mocks.
 *
 * - `E2E_BASE_URL` set (CI, `make e2e` after `make demo`): test that app as it is;
 *   nothing is started or reseeded.
 * - Otherwise global-setup.ts runs scripts/start-stack.sh: Postgres (Docker), migrate,
 *   `seed --reset`, a Vite build and `soundings api` on http://localhost:8100
 *   (`E2E_PORT`). global-teardown.ts stops it unless `E2E_KEEP_STACK=1`.
 *
 * Tests that change data create their own project (tests/support/api.ts), so the
 * suite can run in parallel and more than once against the same database. Read-only
 * tests rely on the seeded story (backend/app/seed/content.py).
 *
 * `npm run screenshots` (SCREENSHOTS=1 or phase-1) runs only the screenshots project
 * with screenshots/phase-1.spec.ts (docs/screenshots/phase-1/); `npm run
 * screenshots:phase2` (SCREENSHOTS=phase-2) runs screenshots/phase-2.spec.ts
 * (docs/screenshots/phase-2/).
 *
 * Phase 2: specs that need single sign-on are tagged @sso and skip unless the app has it
 * (`E2E_SSO=1` starts Keycloak next to the local stack; see e2e/README.md).
 */
const external = process.env.E2E_BASE_URL
const baseURL = (external ?? `http://localhost:${process.env.E2E_PORT ?? 8100}`).replace(/\/$/, '')
const screenshots = Boolean(process.env.SCREENSHOTS)
const screenshotSpec =
  process.env.SCREENSHOTS === 'phase-2'
    ? /screenshots\/phase-2\.spec\.ts$/
    : /screenshots\/phase-1\.spec\.ts$/

export default defineConfig({
  testDir: '.',
  outputDir: './test-results',
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // A shared 4-CPU machine and one uvicorn worker: two browsers is plenty.
  workers: Number(process.env.E2E_WORKERS ?? 2),
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    locale: 'en-GB',
    timezoneId: 'Europe/London',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: screenshots
    ? [
        {
          name: 'screenshots',
          testMatch: screenshotSpec,
          use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
        },
      ]
    : [
        {
          name: 'e2e',
          testMatch: /tests\/.*\.spec\.ts$/,
          use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
        },
      ],
})
