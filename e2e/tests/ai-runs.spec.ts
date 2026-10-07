import {
  agentName,
  aiTeam,
  type AiAgentList,
  askAgent,
  registerAgent,
  retireAgents,
  run,
  signInAs,
  skipWithoutAi,
  runSteps,
  waitRun,
} from './support/ai'
import { details, expect, openIdea, test } from './support/fixtures'
import { FakeAgent } from '../scripts/fake-agent'

/**
 * How AI runs end, as the owner sees them on the idea page (contract-phase6 §3.3–3.4,
 * §3.15): Cancel while the agent works (A2A `tasks/cancel`; the evaluator assignment the
 * run made is taken back), an agent that fails or asks for input (Soundings' sentence,
 * "Try again"), an agent that isn't there (HTTP 404 from the controller), and the
 * deadline (`timed_out` with `tasks/cancel`). The fake agent's name suffix picks how it
 * behaves (dev/fake-agent/README.md). Test plan: RUN6-*.
 */

test.describe('@ai how runs end', () => {
  test.beforeEach(skipWithoutAi)

  test('RUN6-01 Cancel stops a working run; the assignment it made is taken back', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI cancel')
    const key = await team.idea({ title: 'Same-day delivery in the city centre' })
    const slow = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate'],
      name: agentName('slow'),
    })
    try {
      await signInAs(page, team.owner.me)
      await openIdea(page, key)
      // From the header's AI menu (Phase 7: the one place agents are asked).
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await page.getByRole('menuitem', { name: /Ask AI to evaluate/ }).click()
      const progress = page.getByRole('button', {
        name: /AI run (in progress|waiting to start)\. View progress/,
      })
      await expect(progress.first()).toBeVisible()
      // Focus stays on the menu's button, which is still there.
      await expect(page.getByRole('button', { name: 'AI actions' }).first()).toBeFocused()
      const card = page.locator('article[id^="ai-run-"]').first()
      // One line while it works: the current step, the time taken and the time left.
      await expect(card).toContainText('Read the idea', { timeout: 30_000 })
      await expect(card.getByText('Working', { exact: true })).toBeVisible()
      await expect(card).toContainText(/\d+ min left|under a minute left/)
      // While it works the menu offers its progress, not a second run.
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await expect(page.getByRole('menuitem', { name: /Evaluating…/ })).toBeVisible()
      await page.keyboard.press('Escape')

      const cancel = card.getByRole('button', { name: /^Cancel: Evaluating by Idea evaluator/ })
      await cancel.click()
      // Cancelling keeps focus on Cancel (busy, not disabled); when it ends, on the run.
      await expect(card).toContainText('Cancelled: nothing was saved.', { timeout: 30_000 })
      await expect(card).toBeFocused()
      await expect(card.getByRole('button', { name: 'Try again' })).toBeVisible()
      await expect(await runSteps(card)).toContainText('Cancelling')
      // The run assigned the agent and ends without an evaluation: it is taken off.
      const evaluators = details(page).getByRole('list', { name: 'Evaluators' })
      await expect(evaluators.getByText('Idea evaluator')).toHaveCount(0)
      await expect(
        page.getByText(/ended its run without an evaluation|run ended without an evaluation/),
      ).toBeVisible()

      const runs = await alice.get<{ items: { id: string; status: string }[] }>(
        `/ideas/${key}/ai-runs`,
      )
      const cancelled = runs.items[0]
      expect(cancelled?.status).toBe('cancelled')
      const seen = await new FakeAgent().waitFor(cancelled?.id ?? '', (r) => r.final_state !== null)
      expect(seen.cancel_requests).toBeGreaterThanOrEqual(1)
      expect(seen.final_state).toBe('canceled')
      expect(seen.a2a_requests.map((r) => r.method)).toContain('tasks/cancel')
      const again = await alice.raw('POST', `/ideas/${key}/ai-runs/${cancelled?.id ?? ''}/cancel`)
      expect(again.status()).toBe(409)
    } finally {
      await retireAgents(alice, [slow])
      await team.dispose()
    }
  })

  test('RUN6-02 failures say why in Soundings’ words and offer “Try again”', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI failures')
    const key = await team.idea({ title: 'A loyalty card for small shops' })
    const fails = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['research'],
      name: agentName('fails'),
      displayName: 'Failing researcher',
    })
    const asks = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate'],
      name: agentName('asks'),
      displayName: 'Curious evaluator',
    })
    // Registered, but its key never reaches the agent: kagent answers 404 for it.
    const missing = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['draft_section'],
      displayName: 'Missing drafter',
    })
    new FakeAgent().removeKey(missing.agent.namespace, missing.agent.name)
    try {
      const failed = await waitRun(
        alice,
        key,
        (await askAgent(team.owner, key, 'research', fails.agent.id)).id,
      )
      expect([failed.status, failed.error?.code]).toEqual(['failed', 'agent_failed'])
      const needsInput = await waitRun(
        alice,
        key,
        (await askAgent(team.owner, key, 'evaluate', asks.agent.id)).id,
      )
      expect([needsInput.status, needsInput.error?.code]).toEqual(['failed', 'agent_needs_input'])

      await signInAs(page, team.owner.me)
      await openIdea(page, key)
      const cards = page.locator('article[id^="ai-run-"]')
      await expect(cards).toHaveCount(2)
      for (const [name, words, sentence] of [
        [
          'Failing researcher',
          'The agent ran into an error and stopped.',
          'The agent stopped with an error.',
        ],
        [
          'Curious evaluator',
          'The agent asked a question, and a run can’t answer one.',
          "The agent asked for input, which a run can't give.",
        ],
      ] as const) {
        const card = cards.filter({ hasText: name })
        // The row: Soundings' plain words by error code, with a next step; the steps keep
        // the server's sentence.
        await expect(card).toContainText(words)
        await expect(card).toContainText('Try again')
        await expect(card).not.toContainText('(state ')
        await expect(await runSteps(card)).toContainText(sentence)
        await expect(card.getByRole('button', { name: 'Try again' })).toBeVisible()
      }
      // The evaluate run took its assignment back.
      await expect(
        details(page).getByRole('list', { name: 'Evaluators' }).getByText('Curious evaluator'),
      ).toHaveCount(0)

      // "Try again" asks the same agent again: a new run takes the row (focus follows it),
      // the failed one goes to History.
      await cards
        .filter({ hasText: 'Failing researcher' })
        .getByRole('button', { name: 'Try again' })
        .click()
      await expect(page.getByRole('button', { name: 'History (1)' })).toBeVisible()
      await expect(cards).toHaveCount(2)
      await expect(cards.filter({ hasText: 'Failing researcher' })).toBeFocused()

      // An agent the controller doesn't know (404): no retries, Soundings' sentence.
      const shortlisted = await team.idea({
        title: 'A proposal nobody can draft',
        status: 'shortlisted',
      })
      const lost = await waitRun(
        alice,
        shortlisted,
        (await askAgent(team.owner, shortlisted, 'draft_section', missing.agent.id, 'risks')).id,
      )
      expect([lost.status, lost.error?.code]).toEqual(['failed', 'agent_unreachable'])
      expect(lost.error?.message).toBe("Couldn't reach the agent. (HTTP 404)")
      expect(lost.events.map((e) => e.type)).not.toContain('retrying')
    } finally {
      await retireAgents(alice, [fails, asks, missing])
      await team.dispose()
    }
  })

  test('RUN6-03 the deadline stops a run that takes too long', async ({ page, api }) => {
    const alice = await api('alice')
    const { settings } = await alice.get<AiAgentList>('/admin/ai-agents')
    test.skip(
      settings.run_timeout_seconds > 120,
      `the run time limit here is ${settings.run_timeout_seconds} s (E2E_AI_RUN_TIMEOUT=PT1M)`,
    )
    test.setTimeout((settings.run_timeout_seconds + 90) * 1000)
    const team = await aiTeam(alice, 'AI deadline')
    const key = await team.idea({ title: 'A survey of every customer' })
    const slow = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['research'],
      name: agentName('slow'),
      displayName: 'Slow researcher',
    })
    try {
      const started = await askAgent(team.owner, key, 'research', slow.agent.id)
      const running = await waitRun(alice, key, started.id, (r) => r.status === 'running')
      expect(running.deadline_at).not.toBeNull()
      await signInAs(page, team.owner.me)
      await openIdea(page, key)
      const card = page.locator('article[id^="ai-run-"]').first()
      await expect(card).toContainText(/\d+ min left|under a minute left/)
      // The row says the limit it hit, and what to do.
      await expect(card).toContainText(
        /The agent didn’t finish within (\d+ seconds|1 minute|\d+ minutes)\./,
        {
          timeout: (settings.run_timeout_seconds + 30) * 1000,
        },
      )
      await expect(card).toContainText('Try again: it may have been busy.')
      const over = await run(alice, key, started.id)
      expect([over.status, over.error?.code]).toEqual(['timed_out', 'timed_out'])
      const seen = await new FakeAgent().waitFor(started.id, (r) => r.cancel_requests > 0)
      expect(seen.cancel_requests).toBeGreaterThanOrEqual(1)
    } finally {
      await retireAgents(alice, [slow])
      await team.dispose()
    }
  })
})
