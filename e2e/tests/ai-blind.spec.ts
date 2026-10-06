import type { Page, Response } from '@playwright/test'

import {
  AGENT_TEXT,
  agentName,
  aiTeam,
  askAgent,
  type EvaluationList,
  readEvents,
  registerAgent,
  retireAgents,
  skipWithoutAi,
  waitRun,
} from './support/ai'
import { defaultRubricScores } from './support/api'
import { details, expect, openIdea, signIn, test } from './support/fixtures'
import { FakeAgent } from '../scripts/fake-agent'

/**
 * Blind evaluation with an AI evaluator (role matrix §3 rules 1 and 9, contract-phase6
 * §3.5–3.7): a pending human evaluator watching an AI evaluation run, live, learns only
 * what the feed already says ("submitted an evaluation"), on the page, in every API
 * response the page gets and in the run's event stream, until they submit their own;
 * the agent itself never sees the others' scores, before or after it submits; people who
 * aren't the owner or an admin read where the AI evaluation stands but can't change it.
 * Test plan: BL6-*.
 */

/** Every API response body the page receives (not event streams), for leak checks. */
function recordResponses(page: Page): string[] {
  const bodies: string[] = []
  page.on('response', (response: Response) => {
    const type = response.headers()['content-type'] ?? ''
    if (!response.url().includes('/api/') || !type.includes('json')) return
    response.text().then(
      (text) => bodies.push(`${response.url()}\n${text}`),
      () => undefined,
    )
  })
  return bodies
}

test.describe('@ai blind evaluation with an AI evaluator', () => {
  test.beforeEach(skipWithoutAi)

  test('BL6-01 a pending evaluator watches the AI evaluate, live, and sees no score data until they submit', async ({
    page,
    api,
  }) => {
    test.setTimeout(150_000)
    const alice = await api('alice')
    const farah = await api('farah')
    const team = await aiTeam(alice, 'AI blind')
    const key = await team.idea({ title: 'Self-checkout in every store' })
    // -lingers: it submits its evaluation, then keeps working (the run stays open).
    const lingering = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate'],
      name: agentName('lingers'),
    })
    try {
      const run = await askAgent(team.owner, key, 'evaluate', lingering.agent.id)
      await waitRun(alice, key, run.id, (r) => r.events.some((e) => e.type === 'result_recorded'))

      const bodies = recordResponses(page)
      await signIn(page, 'farah')
      await openIdea(page, key)
      const card = page.locator('article[id^="ai-run-"]').first()
      const steps = card.getByRole('list', { name: 'Steps' })
      await expect(steps).toContainText('Saved its evaluation')
      await expect(steps).toContainText('Evaluation submitted')
      await expect(card.getByText('Working', { exact: true })).toBeVisible() // still open
      // Farah may watch but not stop it, and can't open the evaluation.
      await expect(card.getByRole('button', { name: /^Cancel/ })).toHaveCount(0)
      await expect(card.getByRole('button', { name: 'View the evaluation' })).toHaveCount(0)
      const agentRow = details(page)
        .getByRole('list', { name: 'Evaluators' })
        .getByRole('listitem')
        .filter({ hasText: 'Idea evaluator' })
      await expect(agentRow).toContainText('AI agent')
      // Members and evaluators get no AI actions.
      await expect(page.getByRole('button', { name: 'AI actions' })).toHaveCount(0)
      await expect(details(page).getByText(/\/ 5 · \d+ evaluations?/)).toHaveCount(0)
      await expect(page.getByRole('main')).not.toContainText(AGENT_TEXT)
      await expect(page.getByRole('main')).not.toContainText(/Rationale|Cited by AI/)
      await page.getByRole('tab', { name: /^Evaluations/ }).click()
      await expect(page.getByText('Hidden until you submit').first()).toBeVisible()
      await expect(page.locator('article[id^="evaluation-card-"]')).toHaveCount(0)

      // The owner stops it; the result stays.
      await team.owner.send('POST', `/ideas/${key}/ai-runs/${run.id}/cancel`)
      await page.getByRole('tab', { name: /^Overview/ }).click()
      await expect(card.getByText('Cancelled').first()).toBeVisible({ timeout: 30_000 })
      await expect(page.getByRole('main')).not.toContainText(AGENT_TEXT)

      // Nothing the page fetched held the agent's evaluation...
      const leaked = bodies.filter((body) => AGENT_TEXT.test(body))
      expect(leaked, leaked.join('\n\n').slice(0, 2000)).toEqual([])
      // ...nor did the run's event stream, replayed from the start.
      const stream = await readEvents(farah, key, run.id)
      expect(stream.status).toBe(200)
      expect(stream.contentType).toMatch(/^text\/event-stream/)
      expect(stream.events.map((e) => e.message)).toContain('Evaluation submitted')
      expect(stream.raw).not.toMatch(AGENT_TEXT)
      expect(stream.raw).not.toMatch(/"(score|scores|recommendation|comment|sources)"/)
      const hidden = await farah.get<EvaluationList>(`/ideas/${key}/evaluations`)
      expect(hidden).toEqual({ items: [], score_hidden: true })

      // Once Farah submits, the blind lifts: she reads the AI's evaluation like any other.
      await farah.evaluate(key, defaultRubricScores(3, 3, 3, 3, 3), { recommendation: 'maybe' })
      await page.reload()
      await page.getByRole('tab', { name: /^Evaluations/ }).click()
      const ai = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasText: 'Idea evaluator' })
      await expect(ai).toContainText('fake-rationale')
      await expect(ai).toContainText('Not in score')
      // Not hers to include: she reads where it stands.
      await expect(ai.getByRole('switch')).toHaveCount(0)
      await expect(ai).toContainText('Not counted in the score')
    } finally {
      await retireAgents(alice, [lingering])
      await team.dispose()
    }
  })

  test('BL6-02 the agent never sees the others’ scores, before or after it submits', async ({
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI rule 9')
    const key = await team.idea({ title: 'Two people scored this already' })
    const probe = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate', 'research'],
      name: agentName('blind-probe'),
    })
    try {
      const fake = new FakeAgent()
      for (const kind of ['evaluate', 'research'] as const) {
        const run = await askAgent(team.owner, key, kind, probe.agent.id)
        expect((await waitRun(alice, key, run.id)).status).toBe('succeeded')
        const seen = await fake.waitFor(run.id, (r) => r.final_state !== null)
        const views = seen.blind
        expect(views.map((view) => `${String(view.tool)} ${String(view.phase)}`).sort()).toEqual([
          'get_idea after',
          'get_idea before',
          'search_ideas after',
          'search_ideas before',
        ])
        for (const view of views) {
          expect(view.score_hidden, JSON.stringify(view)).toBe(true)
          expect(view.score ?? null).toBeNull()
          expect(view.aggregate ?? null).toBeNull()
          expect(view.evaluations ?? 0).toBe(0)
          expect(view.high_disagreement ?? false).toBe(false)
        }
        const after = views.find((view) => view.tool === 'get_idea' && view.phase === 'after')
        if (kind === 'evaluate') expect(after?.my_evaluation_state).toBe('submitted')
      }
      // Bob and Carol's scores still make the aggregate; the agent's is left out.
      const idea = await alice.idea(key)
      expect(idea.aggregate?.count).toBe(2)
    } finally {
      await retireAgents(alice, [probe])
      await team.dispose()
    }
  })

  test('BL6-03 people who aren’t the owner or an admin can’t include an AI evaluation', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI include rights')
    const key = await team.idea({ title: 'A score only the owner decides' })
    const evaluator = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate'],
    })
    try {
      const run = await askAgent(team.owner, key, 'evaluate', evaluator.agent.id)
      const done = await waitRun(alice, key, run.id)
      expect(done.status).toBe('succeeded')
      const evaluationId = done.result.evaluation_id ?? ''

      // Bob (a member who submitted) reads it, without the switch or the AI menu.
      await signIn(page, 'bob')
      await openIdea(page, `${key}?tab=evaluations`)
      const ai = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasText: 'Idea evaluator' })
      await expect(ai).toContainText('Not in score')
      await expect(ai).toContainText('Not counted in the score')
      await expect(ai.getByRole('switch')).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'AI actions' })).toHaveCount(0)
      const bob = await api('bob')
      const refused = await bob.raw(
        'PUT',
        `/ideas/${key}/evaluations/${evaluationId}/include-in-aggregate`,
        { include: true },
      )
      expect(refused.status()).toBe(403)
      // Farah, still pending: 404 (the response would hold scores).
      const farah = await api('farah')
      const hidden = await farah.raw(
        'PUT',
        `/ideas/${key}/evaluations/${evaluationId}/include-in-aggregate`,
        { include: true },
      )
      expect(hidden.status()).toBe(404)
      expect((await alice.idea(key)).aggregate?.count).toBe(2)
    } finally {
      await retireAgents(alice, [evaluator])
      await team.dispose()
    }
  })
})
