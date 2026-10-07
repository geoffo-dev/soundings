import type { Page } from '@playwright/test'

import {
  agentName,
  aiTeam,
  askAgent,
  registerAgent,
  type RegisteredAgent,
  requestRun,
  retireAgents,
  skipWithoutAi,
  waitRun,
} from './support/ai'
import { Api, type CurrentUser, type Person, uniqueSuffix } from './support/api'
import { expect, seriousViolations, settled, signIn, test } from './support/fixtures'

/**
 * axe (WCAG 2.2 AA rules) on the Phase 6 screens against the real app with the fake
 * kagent agent, light and dark: Admin settings → AI agents (the list, the register sheet,
 * the key shown once, a test result), the idea page with the AI menu, a live run card and
 * finished ones with a research note, the Evaluations tab with an AI evaluation and its
 * "Include in score" switch, the same idea as a pending evaluator (blind) and the proposal
 * editor with a draft in progress and an AI suggestion. Then the same at 390 px (no
 * sideways scrolling, sheets and dialogs fill the screen) and "Research this" with the
 * keyboard only. Test plan: A11Y6-*, MO6-*, K6-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''

interface Prepared {
  projectName: string
  projectSlug: string
  /** Bob and Carol scored; the agent's evaluation and research note are in. */
  doneKey: string
  /** Where the slow agent works (asked again by each screen that shows it). */
  liveKey: string
  /** Shortlisted, a proposal with an AI suggestion for Risks. */
  proposalKey: string
  /** The ideas' owner, who asks for the runs (20 an hour each). */
  owner: CurrentUser
  normal: RegisteredAgent
  slow: RegisteredAgent
  slowDrafter: RegisteredAgent
}
let prepared: Promise<Prepared> | undefined

/** Once per worker: a project with three agents and an idea in each state. */
function prepare(): Promise<Prepared> {
  prepared ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    try {
      const team = await aiTeam(alice, 'A11y agents')
      const projectIds = [team.project.id]
      const normal = await registerAgent(alice, { projectIds })
      const slow = await registerAgent(alice, {
        projectIds,
        purposes: ['evaluate'],
        name: agentName('slow'),
        displayName: 'Careful evaluator',
      })
      const slowDrafter = await registerAgent(alice, {
        projectIds,
        purposes: ['draft_section'],
        name: agentName('slow'),
        displayName: 'Careful drafter',
      })
      const doneKey = await team.idea({ title: 'Parcel lockers by the door' })
      for (const kind of ['evaluate', 'research'] as const) {
        const run = await askAgent(team.owner, doneKey, kind, normal.agent.id)
        expect((await waitRun(alice, doneKey, run.id)).status).toBe('succeeded')
      }
      const liveKey = await team.idea({ title: 'Same-day delivery in the city centre' })
      const proposalKey = await team.idea({ title: 'Lockers in ten stores', status: 'shortlisted' })
      await alice.writeSections(proposalKey, {
        summary: 'Lockers in ten stores.',
        risks: 'Customers may not want lockers.',
      })
      const draft = await askAgent(
        team.owner,
        proposalKey,
        'draft_section',
        normal.agent.id,
        'risks',
      )
      expect((await waitRun(alice, proposalKey, draft.id)).status).toBe('succeeded')
      await team.dispose()
      return {
        projectName: team.project.name,
        projectSlug: team.project.slug,
        owner: team.owner.me,
        doneKey,
        liveKey,
        proposalKey,
        normal,
        slow,
        slowDrafter,
      }
    } finally {
      await alice.dispose()
    }
  })()
  return prepared
}

test.afterAll(async () => {
  if (!prepared) return
  const data = await prepared.catch(() => undefined)
  if (!data) return
  const alice = await Api.as(baseURL(), 'alice')
  try {
    await retireAgents(alice, [data.normal, data.slow, data.slowDrafter])
  } finally {
    await alice.dispose()
  }
})

/** Asks the slow agent again (or finds its run still working) and waits for it to work. */
async function slowRun(data: Prepared, kind: 'evaluate' | 'draft_section') {
  const alice = await Api.asUser(baseURL(), data.owner)
  try {
    const key = kind === 'evaluate' ? data.liveKey : data.proposalKey
    const agent = kind === 'evaluate' ? data.slow : data.slowDrafter
    const section = kind === 'draft_section' ? 'summary' : undefined
    const response = await requestRun(alice, key, kind, agent.agent.id, section)
    expect([200, 201]).toContain(response.status())
    const run = (await response.json()) as { id: string }
    await waitRun(alice, key, run.id, (r) => r.events.some((e) => e.type === 'tool_called'))
  } finally {
    await alice.dispose()
  }
}

async function openAgents(page: Page) {
  await page.goto('/settings/ai-agents')
  await expect(page.getByText('Settings in effect')).toBeVisible()
  await settled(page)
}

async function openRegister(page: Page, data: Prepared) {
  await openAgents(page)
  await page.getByRole('button', { name: 'Register agent' }).first().click()
  const sheet = page.getByRole('dialog', { name: 'Register agent' })
  await sheet.getByLabel('Display name').fill('Axe evaluator')
  await sheet.getByLabel('Namespace').fill('soundings')
  await sheet.getByLabel('Agent name').fill(agentName())
  await sheet.getByRole('checkbox', { name: 'Evaluate ideas' }).check()
  await sheet.getByRole('checkbox', { name: data.projectName }).check()
  return sheet
}

interface Screen {
  name: string
  as: Person
  open: (page: Page, data: Prepared) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'Admin settings → AI agents',
    as: 'alice',
    open: async (page, data) => {
      await openAgents(page)
      await expect(page.getByRole('row').filter({ hasText: data.slow.agent.name })).toBeVisible()
    },
  },
  {
    name: 'the register agent sheet',
    as: 'alice',
    open: async (page, data) => {
      await openRegister(page, data)
    },
  },
  {
    name: 'the agent’s key, shown once',
    as: 'alice',
    open: async (page, data) => {
      const sheet = await openRegister(page, data)
      const posted = page.waitForResponse(
        (r) => r.url().endsWith('/admin/ai-agents') && r.request().method() === 'POST',
      )
      await sheet.getByRole('button', { name: /^Register agent/ }).click()
      const created = (await (await posted).json()) as RegisteredAgent['created']
      await expect(page.getByRole('dialog', { name: 'Copy the agent’s key' })).toBeVisible()
      // The dialog stays; the key is no use to anyone.
      const alice = await Api.as(baseURL(), 'alice')
      await retireAgents(alice, [{ agent: created.agent, secret: '', created }])
      await alice.dispose()
    },
  },
  {
    name: 'a test connection result',
    as: 'alice',
    open: async (page, data) => {
      await openAgents(page)
      const name = data.normal.agent.display_name
      const row = page.getByRole('row').filter({ hasText: data.normal.agent.name })
      const menu = row.getByRole('button', { name: `Actions for ${name}` })
      if (await menu.isVisible()) {
        await menu.click()
        await page.getByRole('menuitem', { name: 'Test connection' }).click()
      } else {
        await row.getByRole('button', { name: 'Test', exact: true }).click() // phones
      }
      await expect(page.getByRole('dialog', { name: `${name} answered` })).toBeVisible()
    },
  },
  {
    name: 'the idea’s AI menu',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.doneKey}`)
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await expect(page.getByRole('menuitem', { name: /Research this/ })).toBeVisible()
    },
  },
  {
    name: 'a live run card (owner)',
    as: 'alice',
    open: async (page, data) => {
      await slowRun(data, 'evaluate')
      await page.goto(`/ideas/${data.liveKey}`)
      const card = page.locator('article[id^="ai-run-"]').first()
      await expect(card.getByText('Working', { exact: true })).toBeVisible()
      await expect(card.getByRole('button', { name: /^Cancel:/ })).toBeVisible()
    },
  },
  {
    name: 'finished runs and a research note',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.doneKey}`)
      await expect(page.locator('article[id^="research-note-"]')).toBeVisible()
      // Runs that did their job fold under History (Phase 7).
      await page.getByRole('button', { name: /^History \(\d+\)$/ }).click()
      await page
        .getByRole('list', { name: 'Earlier AI runs' })
        .locator('article[id^="ai-run-"]')
        .first()
        .getByRole('button', { name: 'Steps' })
        .click()
    },
  },
  {
    name: 'an AI evaluation with its switch',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.doneKey}?tab=evaluations`)
      await expect(page.getByRole('switch', { name: /Include .* in the score/ })).toBeVisible()
    },
  },
  {
    name: 'the same idea as a pending evaluator',
    as: 'farah',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.doneKey}?tab=evaluations`)
      await expect(page.getByText('Hidden until you submit').first()).toBeVisible()
    },
  },
  {
    name: 'the proposal editor with a draft in progress and an AI suggestion',
    as: 'alice',
    open: async (page, data) => {
      await slowRun(data, 'draft_section')
      await page.goto(`/ideas/${data.proposalKey}?tab=proposal`)
      await expect(page.getByText('Careful drafter is drafting Summary')).toBeVisible()
      await expect(
        page.locator('#proposal-section-risks article[id^="proposal-suggestion-"]'),
      ).toBeVisible()
    },
  },
]

test.describe('@ai Phase 6 accessibility', () => {
  test.beforeEach(skipWithoutAi)

  for (const colorScheme of ['light', 'dark'] as const) {
    test.describe(`${colorScheme} theme`, () => {
      test.use({ colorScheme })

      for (const screen of SCREENS) {
        test(`A11Y6: ${screen.name} has no serious or critical violations`, async ({ page }) => {
          test.setTimeout(120_000)
          const data = await prepare()
          await signIn(page, screen.as)
          await screen.open(page, data)
          await settled(page)
          await expect(page.locator('html')).toHaveClass(
            colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
          )
          await page.waitForTimeout(300) // enter animations: axe sees final colours
          expect(await seriousViolations(page)).toEqual([])
        })
      }
    })
  }

  test.describe('on a phone (390 px)', () => {
    test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

    test('MO6-01: the Phase 6 screens fit at 390 px without sideways scrolling', async ({
      page,
    }) => {
      test.setTimeout(240_000)
      const data = await prepare()
      const overflow = () =>
        page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )
      for (const screen of SCREENS) {
        await test.step(screen.name, async () => {
          await page.context().clearCookies()
          await signIn(page, screen.as)
          await screen.open(page, data)
          await page.waitForTimeout(200)
          expect(await overflow(), screen.name).toBe(0)
          // Sheets and full-screen dialogs take the width; inset dialogs keep a 16 px gutter.
          const dialog = page.getByRole('dialog').first()
          if (await dialog.isVisible()) {
            const box = await dialog.boundingBox()
            expect(box?.width ?? 0, screen.name).toBeGreaterThanOrEqual(358)
            expect((box?.x ?? 0) + (box?.width ?? 0), screen.name).toBeLessThanOrEqual(390)
          }
        })
      }
    })
  })

  test('K6-01: “Research this” with the keyboard only, then to the note', async ({ page, api }) => {
    const data = await prepare()
    const alice = await api('alice')
    const { key } = await alice.createIdea(data.projectSlug, {
      title: `Keyboard research ${uniqueSuffix()}`,
      summary: 'Asked with the keyboard.',
    })
    await alice.setOwner(key, 'alice')
    await signIn(page, 'alice')
    await page.goto(`/ideas/${key}`)
    const menu = page.getByRole('button', { name: 'AI actions' }).first()
    await menu.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('menu')).toBeVisible()
    const research = page.getByRole('menuitem', { name: /Research this/ })
    for (
      let i = 0;
      i < 4 && !(await research.evaluate((el) => el === document.activeElement));
      i++
    ) {
      await page.keyboard.press('ArrowDown')
    }
    await expect(research).toBeFocused()
    await page.keyboard.press('Enter')
    // Its row on Overview is in view and says so itself (no toast on top of it).
    await expect(page.locator('article[id^="ai-run-"]').first()).toBeVisible()
    await expect(menu).toBeFocused() // the menu returns focus to its button
    const read = page.getByRole('button', { name: 'Read the note' })
    await expect(read).toBeVisible({ timeout: 30_000 })
    await read.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('article[id^="research-note-"]')).toBeFocused()
  })
})
