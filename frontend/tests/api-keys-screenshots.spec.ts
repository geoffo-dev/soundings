import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the Phase 5 screens against the MSW mock (not a
 * regression test): Settings → API keys with its dialogs, Admin settings → API
 * keys and suggestions in the proposal editor. Run with `npm run screenshots`
 * (every *screenshots.spec.ts) or
 *   SCREENSHOTS=1 npx playwright test tests/api-keys-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-5/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-5/mock')

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  scheme: Scheme
  width?: number
  height?: number
  user?: string
  /** What must be on screen before acting (default: the settings heading or the editor). */
  ready?: (page: Page) => Promise<void>
  act?: (page: Page) => Promise<void>
}

const CAROL = '10000000-0000-4000-8000-000000000004'
const IVAN = USERS.ivan

async function createDialog(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Create key' }).click()
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await dialog.getByLabel('Name').fill('Claude Code')
  await dialog.getByRole('button', { name: 'AI evaluator' }).click()
}

async function secretDialog(page: Page) {
  await createDialog(page)
  await page
    .getByRole('dialog', { name: 'Create API key' })
    .getByRole('button', { name: /^Create key/ })
    .click()
  await page.getByRole('dialog', { name: 'Copy your new key' }).waitFor()
}

const settingsReady = async (page: Page) => {
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}
const editorReady = async (page: Page) => {
  await expect(page.getByTestId('proposal-editor')).toBeVisible()
  await expect(page.locator('article[id^="proposal-suggestion-"]').first()).toBeVisible()
}

const firstSuggestion = async (page: Page) => {
  await page.getByRole('button', { name: /^4 suggestions/ }).click()
  await page.waitForTimeout(600) // smooth scroll
}

const shots: Shot[] = [
  ...(['light', 'dark'] as const).flatMap((scheme): Shot[] => [
    { name: 'api-keys-1440', path: '/settings/api-keys', scheme },
    { name: 'api-keys-create-1440', path: '/settings/api-keys', scheme, act: createDialog },
    { name: 'api-keys-secret-1440', path: '/settings/api-keys', scheme, act: secretDialog },
    { name: 'admin-api-keys-1440', path: '/settings/all-api-keys', scheme, user: USERS.priya },
    {
      name: 'proposal-suggestions-1440',
      path: '/ideas/CUST-3?tab=proposal',
      scheme,
      ready: editorReady,
      act: firstSuggestion,
    },
  ]),
  ...(['light', 'dark'] as const).flatMap((scheme): Shot[] => [
    { name: 'api-keys-390', path: '/settings/api-keys', scheme, width: 390, height: 844 },
    {
      name: 'api-keys-secret-390',
      path: '/settings/api-keys',
      scheme,
      width: 390,
      height: 844,
      act: secretDialog,
    },
    {
      name: 'admin-api-keys-390',
      path: '/settings/all-api-keys',
      scheme,
      width: 390,
      height: 844,
      user: USERS.priya,
    },
    {
      name: 'proposal-suggestions-390',
      path: '/ideas/CUST-3?tab=proposal',
      scheme,
      width: 390,
      height: 844,
      ready: editorReady,
      act: firstSuggestion,
    },
  ]),
  { name: 'api-keys-empty-1440', path: '/settings/api-keys', scheme: 'light', user: IVAN },
  {
    name: 'api-keys-connect-1440',
    path: '/settings/api-keys',
    scheme: 'light',
    act: async (page) => {
      await page.getByRole('heading', { name: 'Connect an MCP client' }).scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'api-keys-revoke-1440',
    path: '/settings/api-keys',
    scheme: 'light',
    act: async (page) => {
      await page.getByRole('button', { name: 'Revoke Claude Desktop' }).click()
      await page.getByRole('alertdialog').waitFor()
    },
  },
  {
    name: 'admin-api-keys-user-1440',
    path: `/settings/all-api-keys?user_id=${USERS.alice}`,
    scheme: 'light',
    user: USERS.priya,
  },
  {
    name: 'admin-sign-out-everywhere-1440',
    path: `/settings/users/${USERS.bob}`,
    scheme: 'light',
    user: USERS.priya,
    ready: async (page) => {
      await expect(page.getByRole('dialog', { name: /Bob Chen/ })).toBeVisible()
    },
    act: async (page) => {
      await page.getByRole('button', { name: 'Sign out everywhere' }).click()
      await page.getByRole('alertdialog').waitFor()
    },
  },
  {
    name: 'proposal-suggestion-conflict-1440',
    path: '/ideas/CUST-3?tab=proposal',
    scheme: 'light',
    ready: editorReady,
    act: async (page) => {
      await page.evaluate(async () => {
        const view = (await (await fetch('/api/v1/ideas/CUST-3/proposal')).json()) as {
          proposal: { sections: { key: string; version: number }[] }
        }
        const base = view.proposal.sections.find((s) => s.key === 'summary')?.version ?? 1
        await fetch('/api/v1/ideas/CUST-3/proposal/sections/summary', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'playwright' },
          body: JSON.stringify({
            body_md: 'A monthly coffee and tea box for repeat customers.',
            base_version: base,
          }),
        })
      })
      await page
        .getByRole('button', { name: 'Accept: Carol Díaz’s suggestion for Summary' })
        .click()
      await page.getByRole('button', { name: /^Accept anyway/ }).waitFor()
      await page.getByRole('button', { name: /^Accept anyway/ }).scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'proposal-suggestions-member-1440',
    path: '/ideas/CUST-3?tab=proposal',
    scheme: 'light',
    user: CAROL,
    ready: editorReady,
    act: firstSuggestion,
  },
  {
    name: 'audit-api-keys-1440',
    path: '/settings/audit?action=api_keys',
    scheme: 'light',
    user: USERS.priya,
  },
]

for (const shot of shots) {
  test.describe(`${shot.name} (${shot.scheme})`, () => {
    test.use({
      viewport: { width: shot.width ?? 1440, height: shot.height ?? 900 },
      colorScheme: shot.scheme,
      ...(shot.user ? { signedInAs: shot.user } : {}),
    })
    test('capture', async ({ page }) => {
      mkdirSync(outDir, { recursive: true })
      await page.goto(shot.path)
      await (shot.ready ?? settingsReady)(page)
      await page.waitForLoadState('networkidle')
      await shot.act?.(page)
      await page.waitForTimeout(300)
      await page.screenshot({ path: path.join(outDir, `${shot.name}-${shot.scheme}.png`) })
    })
  })
}
