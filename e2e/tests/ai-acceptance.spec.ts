import type { Page } from '@playwright/test'

import {
  AGENT_TEXT,
  aiTeam,
  type EvaluationList,
  readEvents,
  registerAgent,
  retireAgents,
  type AiRunList,
  signInAs,
  skipWithoutAi,
} from './support/ai'
import { details, expect, openIdea, test, toast } from './support/fixtures'
import { KeyClient } from './support/mcp'

/**
 * Phase 6 acceptance through the UI (SPEC section 13, contract-phase6 §3.14): "Ask AI to
 * evaluate" produces a badged, cited evaluation excluded from the aggregate by default.
 * Against the real stack with Soundings' fake kagent agent (E2E_AI=1): the owner asks from
 * the idea's AI menu, the worker sends the run over A2A, the agent reads the idea through
 * `/mcp` with its own key and submits; the page follows the run live over SSE, the agent
 * appears among the evaluators with the AI badge, its evaluation (a rationale and sources
 * per criterion) stays out of the score until the owner includes it, and out again.
 * Test plan: AC6-01.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''

/** The sidebar's score line: "3.0 / 5 · 2 evaluations". */
async function scoreLine(page: Page): Promise<string> {
  const line = details(page).getByText(/^\/ 5 · \d+ evaluations?$/)
  await expect(line).toBeVisible()
  return (await line.locator('..').innerText()).replace(/\s+/g, ' ').trim()
}

test.describe('@ai Ask AI to evaluate', () => {
  test.beforeEach(skipWithoutAi)

  test('AC6-01 a badged, cited evaluation, left out of the score until the owner includes it', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI acceptance')
    const key = await team.idea({ title: 'Parcel lockers by the door' })
    const evaluator = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate', 'research'],
    })
    try {
      await signInAs(page, team.owner.me)
      const streamed = page.waitForRequest(
        (request) => /\/ai-runs\/[^/]+\/events/.test(request.url()),
        { timeout: 30_000 },
      )
      await openIdea(page, key)
      const before = await scoreLine(page)
      expect(before).toBe('3.0 / 5 · 2 evaluations')

      // The owner asks from the idea's AI menu (one agent: no choice to make).
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await expect(page.getByRole('menuitem', { name: /Research this/ })).toBeVisible()
      await page.getByRole('menuitem', { name: /Ask AI to evaluate/ }).click()
      await expect(toast(page, 'Asked Idea evaluator to evaluate this idea')).toBeVisible()
      const evaluators = details(page).getByRole('list', { name: 'Evaluators' })
      const agentRow = evaluators.getByRole('listitem').filter({ hasText: 'Idea evaluator' })
      await expect(agentRow).toBeVisible()
      await expect(agentRow).toContainText('AI agent') // the badge, as assistive tech reads it

      // Live progress over the event stream (not the polling fallback).
      await streamed
      const card = page.locator('article[id^="ai-run-"]').first()
      await expect(card.getByRole('heading', { name: /Idea evaluator/ })).toBeVisible()
      const steps = card.getByRole('list', { name: 'Steps' })
      for (const step of [
        'Waiting to start',
        'Sending the request to the agent',
        'The agent started',
        'Read the rubric',
        'Read the idea',
        'Saved its evaluation',
        'Evaluation submitted',
        'Done',
      ]) {
        await expect(steps).toContainText(step, { timeout: 30_000 })
      }
      await expect(card.getByText('Evaluation submitted').last()).toBeVisible()
      await expect(card.getByText('Live updates aren’t available here')).toHaveCount(0)
      await expect(card).not.toContainText(AGENT_TEXT)
      await expect(agentRow.getByRole('img', { name: 'Submitted', exact: true })).toBeVisible()

      // Left out of the score: unchanged.
      expect(await scoreLine(page)).toBe(before)

      // The evaluation: AI badge, "Not in score", a rationale and sources per criterion.
      await card.getByRole('button', { name: 'View the evaluation' }).click()
      await expect(page.getByRole('tab', { name: /^Evaluations/, selected: true })).toBeVisible()
      const ai = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasText: 'Idea evaluator' })
      await expect(ai).toBeFocused()
      await expect(ai).toContainText('AI agent')
      await expect(ai).toContainText('Not in score')
      for (const criterion of ['Value', 'Feasibility', 'Effort', 'Strategic fit', 'Risk']) {
        await expect(ai).toContainText(`fake-rationale: ${criterion} for ${key}`)
      }
      await expect(ai.getByText('Rationale', { exact: true })).toHaveCount(5)
      const sources = ai.getByRole('list', { name: 'Sources cited by AI, not checked' })
      await expect(sources).toHaveCount(5)
      await expect(sources.getByRole('link')).toHaveCount(10)
      const link = sources.first().getByRole('link').first()
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow')
      await expect(link).toHaveAttribute('target', '_blank')
      await expect(link).toHaveAttribute('href', /^https:\/\/example\.org\/fake-agent\//)
      await expect(sources.first()).toContainText('example.org')
      await expect(ai).toContainText('Its sources are cited by AI, not checked')
      // People's evaluations are in the score, with no sources.
      const people = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasNotText: 'Idea evaluator' })
      await expect(people).toHaveCount(2)
      await expect(people.getByText('Not in score')).toHaveCount(0)

      // The owner includes it: the score and n change; leaves it out again: back.
      const include = ai.getByRole('switch', {
        name: 'Include Idea evaluator’s evaluation in the score',
      })
      await expect(include).not.toBeChecked()
      await include.click()
      await expect(include).toBeChecked()
      await expect(toast(page, 'Idea evaluator’s evaluation now counts in the score')).toBeVisible()
      await expect(ai).not.toContainText('Not in score')
      await expect.poll(() => scoreLine(page)).toBe('2.9 / 5 · 3 evaluations')
      await include.click()
      await expect(include).not.toBeChecked()
      await expect(ai).toContainText('Not in score')
      await expect.poll(() => scoreLine(page)).toBe(before)
      const stored = await alice.get<EvaluationList>(`/ideas/${key}/evaluations`)
      expect(stored.items.filter((e) => e.is_ai).map((e) => e.include_in_aggregate)).toEqual([
        false,
      ])

      // The run is over and its stream says so (204 on reconnect); it held no score data.
      const runs = await alice.get<AiRunList>(`/ideas/${key}/ai-runs`)
      const done = runs.items[0]
      expect(done?.status).toBe('succeeded')
      const replay = await readEvents(alice, key, done?.id ?? '', done?.event_count)
      expect(replay.status).toBe(204)

      // With no run open the agent's key does nothing: nothing listed, REST refused.
      const agentKey = await KeyClient.open(baseURL(), evaluator.secret)
      try {
        await agentKey.connect()
        expect((await agentKey.ok<{ projects: unknown[] }>('list_projects')).projects).toEqual([])
        expect(await agentKey.fails('get_idea', { idea: key })).toBe('ai_run_not_active')
        const rest = await agentKey.rest('GET', `/ideas/${key}`)
        expect(rest.status()).toBe(403)
        expect(((await rest.json()) as { code: string }).code).toBe('insufficient_scope')
      } finally {
        await agentKey.dispose()
      }
    } finally {
      await retireAgents(alice, [evaluator])
      await team.dispose()
    }
  })
})
