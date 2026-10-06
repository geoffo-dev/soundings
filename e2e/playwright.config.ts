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
 *
 * Phase 3: the stack runs the worker and Mailpit. Specs that stop Mailpit ("the SMTP
 * server is down") are tagged @smtp-outage and run in their own project, `smtp-outage`,
 * after every other spec and one at a time, so no other spec waits for mail meanwhile
 * (`--project=smtp-outage --no-deps` runs only them). `npm run screenshots:phase3`
 * (SCREENSHOTS=phase-3) runs screenshots/phase-3.spec.ts (docs/screenshots/phase-3/).
 *
 * Phase 4: specs that change what every other spec sees (the global branding: "Acme
 * Ideas" in every title and email) or exhaust a per-address throttle on purpose (every
 * spec shares 127.0.0.1) are tagged @serial and run in the `serial` project, after
 * `e2e` and before `smtp-outage`, one at a time; they put things back when they finish.
 * `npm run screenshots:phase4` (SCREENSHOTS=phase-4) runs screenshots/phase-4.spec.ts
 * (docs/screenshots/phase-4/, with pdf/ and emails/).
 *
 * Phase 5: specs use API keys and `/mcp` as a client would (tests/support/mcp.ts: a
 * bearer key, no cookie, an X-Forwarded-For address of their own so refused keys don't
 * add up on 127.0.0.1). Nothing new to run. `npm run screenshots:phase5`
 * (SCREENSHOTS=phase-5) runs screenshots/phase-5.spec.ts (docs/screenshots/phase-5/).
 *
 * Phase 6: AI specs are tagged @ai and skip unless AI assistance is on and Soundings' fake
 * kagent agent answers (`E2E_AI=1` starts it next to the local stack; against
 * `E2E_BASE_URL` set E2E_FAKE_AGENT_URL and E2E_FAKE_AGENT_KEYS_DIR). Each registers agents
 * of its own (tests/support/ai.ts), so they run side by side. `npm run
 * screenshots:phase6` (SCREENSHOTS=phase-6, E2E_AI=1) runs screenshots/phase-6.spec.ts
 * (docs/screenshots/phase-6/).
 */
const external = process.env.E2E_BASE_URL
const baseURL = (external ?? `http://localhost:${process.env.E2E_PORT ?? 8100}`).replace(/\/$/, '')
const screenshots = Boolean(process.env.SCREENSHOTS)
const screenshotSpec =
  process.env.SCREENSHOTS === 'phase-2'
    ? /screenshots\/phase-2\.spec\.ts$/
    : process.env.SCREENSHOTS === 'phase-3'
      ? /screenshots\/phase-3\.spec\.ts$/
      : process.env.SCREENSHOTS === 'phase-4'
        ? /screenshots\/phase-4\.spec\.ts$/
        : process.env.SCREENSHOTS === 'phase-5'
          ? /screenshots\/phase-5\.spec\.ts$/
          : process.env.SCREENSHOTS === 'phase-6'
            ? /screenshots\/phase-6\.spec\.ts$/
            : /screenshots\/phase-1\.spec\.ts$/
const desktop = { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }
const smtpOutage = /@smtp-outage/
const serial = /@serial/
const serialOrOutage = /@serial|@smtp-outage/

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
          use: desktop,
        },
      ]
    : [
        {
          name: 'e2e',
          testMatch: /tests\/.*\.spec\.ts$/,
          grepInvert: serialOrOutage,
          use: desktop,
        },
        {
          // Changes global state (branding, per-address throttles): after `e2e`, one
          // test at a time, so no other spec sees it.
          name: 'serial',
          testMatch: /tests\/.*\.spec\.ts$/,
          grep: serial,
          grepInvert: smtpOutage,
          dependencies: ['e2e'],
          workers: 1,
          use: desktop,
        },
        {
          // Stops and starts Mailpit: after everything else, one test at a time.
          name: 'smtp-outage',
          testMatch: /tests\/.*\.spec\.ts$/,
          grep: smtpOutage,
          dependencies: ['serial'],
          workers: 1,
          use: desktop,
        },
      ],
})
