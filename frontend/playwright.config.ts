import { defineConfig, devices } from '@playwright/test'

/**
 * Page tests run against the Vite dev server with MSW mocks, so they need no
 * backend. Override the port with PW_PORT (e.g. when running agents in parallel).
 * Full end-to-end tests against the real stack live in /e2e (owned by QA).
 */
const port = Number(process.env.PW_PORT ?? 5174)
const baseURL = `http://localhost:${port}`

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run dev:mock -- --port ${port} --strictPort`,
    // No hot reload: an edit elsewhere in the tree must not reload a page mid-test.
    env: { VITE_NO_HMR: '1' },
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
