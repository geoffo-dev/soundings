import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the Phase 6 screens against the MSW mock (not a
 * regression test): the idea page's AI menu and live run card, the AI
 * evaluation with rationale, sources and "Include in score", a research note,
 * "Draft with AI" in the proposal editor and Admin settings → AI agents with its
 * sheet and key dialog. Run with `npm run screenshots` or
 *   SCREENSHOTS=1 npx playwright test tests/ai-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-6/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-6/mock')
const CAROL = '10000000-0000-4000-8000-000000000004'

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  scheme: Scheme
  width?: number
  height?: number
  user?: string
  /** soundings-mock-ai-outcome for runs started in `act` (default: they succeed). */
  outcome?: string
  pace?: number
  act?: (page: Page) => Promise<void>
}

const ideaReady = async (page: Page) => {
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

const scrollMain = (page: Page, to: number | 'end') =>
  page.locator('#main').evaluate((main, target) => {
    main.scrollTo(0, target === 'end' ? main.scrollHeight : target)
  }, to)

async function askEvaluation(page: Page) {
  await page.getByRole('button', { name: 'AI actions' }).first().click()
  await page.getByRole('menuitem', { name: /Ask AI to evaluate/ }).click()
}

const shots: Shot[] = [
  ...(['light', 'dark'] as const).flatMap((scheme): Shot[] => [
    {
      name: 'ai-menu-1440',
      path: '/ideas/CUST-2',
      scheme,
      act: async (page) => {
        await page.getByRole('button', { name: 'AI actions' }).first().click()
        await page.getByRole('menuitem', { name: 'Research this' }).hover()
      },
    },
    {
      name: 'ai-run-live-1440',
      path: '/ideas/CUST-2',
      scheme,
      outcome: 'slow',
      act: async (page) => {
        await askEvaluation(page)
        // One line while it works: its current step.
        await expect(
          page.locator('article[id^="ai-run-"]').getByText('Read the rubric').first(),
        ).toBeVisible()
        await scrollMain(page, 260)
      },
    },
    {
      name: 'ai-evaluation-1440',
      path: '/ideas/CUST-7?tab=evaluations',
      scheme,
      user: CAROL,
      act: async (page) => {
        await page
          .locator('article[id^="evaluation-card-"]')
          .filter({ hasText: 'Idea evaluator' })
          .scrollIntoViewIfNeeded()
      },
    },
    {
      name: 'ai-research-note-1440',
      path: '/ideas/CUST-4',
      scheme,
      act: async (page) => {
        await page.locator('article[id^="research-note-"]').scrollIntoViewIfNeeded()
      },
    },
    {
      name: 'ai-draft-section-1440',
      path: '/ideas/CUST-3?tab=proposal',
      scheme,
      outcome: 'slow',
      act: async (page) => {
        const risks = page.locator('#proposal-section-risks')
        await risks.getByRole('button', { name: 'Draft Risks with AI' }).click()
        await expect(risks.getByText(/is drafting Risks/)).toBeVisible()
        await risks.scrollIntoViewIfNeeded()
      },
    },
    { name: 'ai-agents-1440', path: '/settings/ai-agents', scheme, user: USERS.priya },
    {
      name: 'ai-agents-register-1440',
      path: '/settings/ai-agents',
      scheme,
      user: USERS.priya,
      act: async (page) => {
        await page.getByRole('button', { name: 'Register agent' }).click()
        const sheet = page.getByRole('dialog', { name: 'Register agent' })
        await sheet.getByRole('textbox', { name: 'Display name' }).fill('Market analyst')
        await sheet.getByRole('textbox', { name: 'Namespace' }).fill('soundings')
        await sheet.getByRole('textbox', { name: 'Agent name' }).fill('market-analyst')
      },
    },
    {
      name: 'ai-agents-key-1440',
      path: '/settings/ai-agents',
      scheme,
      user: USERS.priya,
      act: async (page) => {
        await page.getByRole('button', { name: 'Register agent' }).click()
        const sheet = page.getByRole('dialog', { name: 'Register agent' })
        await sheet.getByRole('textbox', { name: 'Display name' }).fill('Market analyst')
        await sheet.getByRole('textbox', { name: 'Namespace' }).fill('soundings')
        await sheet.getByRole('textbox', { name: 'Agent name' }).fill('market-analyst')
        await sheet.getByRole('checkbox', { name: 'Research ideas' }).click()
        await sheet.getByRole('checkbox', { name: 'Customer Innovation' }).click()
        await sheet.getByRole('button', { name: /^Register agent/ }).click()
        await page.getByRole('dialog', { name: 'Copy the agent’s key' }).waitFor()
      },
    },
  ]),
  ...(['light', 'dark'] as const).flatMap((scheme): Shot[] => [
    {
      name: 'ai-run-live-390',
      path: '/ideas/CUST-2',
      scheme,
      width: 390,
      height: 844,
      outcome: 'slow',
      act: async (page) => {
        await askEvaluation(page)
        await expect(
          page.locator('article[id^="ai-run-"]').getByText('Read the rubric').first(),
        ).toBeVisible()
        await page.locator('article[id^="ai-run-"]').scrollIntoViewIfNeeded()
      },
    },
    {
      name: 'ai-evaluation-390',
      path: '/ideas/CUST-7?tab=evaluations',
      scheme,
      width: 390,
      height: 844,
      user: CAROL,
      act: async (page) => {
        await page
          .locator('article[id^="evaluation-card-"]')
          .filter({ hasText: 'Idea evaluator' })
          .scrollIntoViewIfNeeded()
      },
    },
    {
      name: 'ai-agents-390',
      path: '/settings/ai-agents',
      scheme,
      width: 390,
      height: 844,
      user: USERS.priya,
    },
  ]),
  {
    name: 'ai-run-failed-1440',
    path: '/ideas/CUST-2',
    scheme: 'light',
    outcome: 'fail',
    act: async (page) => {
      await askEvaluation(page)
      await expect(page.getByText('The agent ran into an error and stopped.').first()).toBeVisible()
      await scrollMain(page, 260)
    },
  },
  {
    name: 'ai-runs-history-1440',
    path: '/ideas/CUST-4',
    scheme: 'light',
    act: async (page) => {
      await scrollMain(page, 260)
    },
  },
  {
    name: 'ai-pending-evaluator-1440',
    path: '/ideas/CUST-7',
    scheme: 'light',
  },
  {
    name: 'ai-agents-test-1440',
    path: '/settings/ai-agents',
    scheme: 'light',
    user: USERS.priya,
    act: async (page) => {
      await page.getByRole('button', { name: 'Actions for Idea evaluator' }).click()
      await page.getByRole('menuitem', { name: 'Test connection' }).click()
      await page.getByRole('dialog', { name: 'Idea evaluator answered' }).waitFor()
    },
  },
  {
    name: 'ai-agents-off-1440',
    path: '/settings/ai-agents',
    scheme: 'light',
    user: USERS.priya,
    outcome: 'ai-off',
  },
  {
    name: 'audit-ai-1440',
    path: '/settings/audit?action=ai',
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
      await page.addInitScript(
        ({ outcome, pace }) => {
          localStorage.setItem('soundings-mock-ai-pace', String(pace))
          if (outcome === 'ai-off') localStorage.setItem('soundings-mock-ai', 'off')
          else if (outcome) localStorage.setItem('soundings-mock-ai-outcome', outcome)
        },
        { outcome: shot.outcome ?? '', pace: shot.pace ?? 250 },
      )
      await page.goto(shot.path)
      await ideaReady(page)
      await page.waitForLoadState('networkidle')
      await shot.act?.(page)
      await page.waitForTimeout(400)
      await page.screenshot({ path: path.join(outDir, `${shot.name}-${shot.scheme}.png`) })
    })
  })
}
