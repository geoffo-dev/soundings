import {
  agentName,
  aiTeam,
  type AiRunList,
  registerAgent,
  retireAgents,
  signInAs,
  skipWithoutAi,
} from './support/ai'
import type { ProposalSuggestionList } from './support/api'
import { expect, signIn, test } from './support/fixtures'
import { FakeAgent } from '../scripts/fake-agent'

/**
 * "Draft with AI" in the proposal editor (contract-phase6 §3.9, §3.15): the owner asks an
 * agent for one section; it reads the idea and the proposal through `/mcp` and proposes
 * text with `propose_proposal_section` (Phase 5 suggestions, `source: ai`), only for that
 * section (c22); the suggestion appears under the section with the AI badge and is
 * accepted like any other. Test plan: AD6-*.
 */

const RISKS = 'Some customers may not want lockers. We pilot in two stores first.'

test.describe('@ai drafting proposal sections', () => {
  test.beforeEach(skipWithoutAi)

  test('AD6-01 “Draft with AI” brings an AI suggestion for the section, which the owner accepts', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI drafts')
    const key = await team.idea({ title: 'Lockers for click and collect', status: 'shortlisted' })
    await alice.writeSections(key, { risks: RISKS, summary: 'Lockers in ten stores.' })
    const drafter = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['draft_section'],
      displayName: 'Proposal drafter',
    })
    try {
      await signInAs(page, team.owner.me)
      await page.goto(`/ideas/${key}?tab=proposal`)
      await expect(page.getByTestId('proposal-editor')).toBeVisible()
      const risks = page.locator('#proposal-section-risks')
      await risks.getByRole('button', { name: 'Draft Risks with AI' }).click()
      // In place: the agent's progress with Cancel, then its suggestion under the section.
      const suggestion = risks.locator('article[id^="proposal-suggestion-"]')
      await expect(suggestion).toBeVisible({ timeout: 30_000 })
      await expect(suggestion).toContainText('Proposal drafter')
      await expect(suggestion).toContainText('AI agent')
      await expect(suggestion).toContainText(`Draft by Soundings' fake agent for ${key}`)
      // Only Risks got one.
      await expect(page.locator('article[id^="proposal-suggestion-"]')).toHaveCount(1)

      const listed = await alice.get<ProposalSuggestionList>(`/ideas/${key}/proposal/suggestions`)
      expect(listed.items.map((s) => [s.section_key, s.source, s.status])).toEqual([
        ['risks', 'ai', 'pending'],
      ])
      const runs = await alice.get<AiRunList>(`/ideas/${key}/ai-runs`)
      expect(runs.items[0]?.result.suggestion_id).toBe(listed.items[0]?.id)
      const seen = await new FakeAgent().waitFor(
        runs.items[0]?.id ?? '',
        (r) => r.final_state !== null,
      )
      expect(seen.tool_calls.map((c) => c.tool)).toEqual([
        'get_idea',
        'get_proposal',
        'propose_proposal_section',
      ])
      expect(seen.section_key).toBe('risks')

      await suggestion.getByRole('button', { name: /^Accept/ }).click()
      await expect(suggestion).toHaveCount(0)
      const proposal = await alice.proposal(key)
      const section = proposal.proposal?.sections.find((s) => s.key === 'risks')
      expect(section?.body_md).toContain(RISKS)
      expect(section?.body_md).toContain(`Draft by Soundings' fake agent for ${key}`)
    } finally {
      await retireAgents(alice, [drafter])
      await team.dispose()
    }
  })

  test('AD6-02 a draft can be cancelled; members and ideas without a proposal get no “Draft with AI”', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI draft rules')
    const key = await team.idea({ title: 'A slow draft', status: 'shortlisted' })
    const evaluating = await team.idea({ title: 'Still being evaluated' })
    const slow = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['draft_section'],
      name: agentName('slow'),
      displayName: 'Slow drafter',
    })
    try {
      await signInAs(page, team.owner.me)
      await page.goto(`/ideas/${key}?tab=proposal`)
      const summary = page.locator('#proposal-section-summary')
      await summary.getByRole('button', { name: 'Draft Summary with AI' }).click()
      const cancel = summary.getByRole('button', { name: 'Cancel the draft of Summary' })
      await expect(cancel).toBeFocused()
      await expect(summary).toContainText('Slow drafter is drafting Summary')
      await expect(summary).toContainText('Read the idea', { timeout: 30_000 })
      await cancel.click()
      await expect(summary.getByRole('alert')).toContainText(
        'The draft by Slow drafter was cancelled',
        { timeout: 30_000 },
      )
      await expect(summary.getByRole('button', { name: 'Try again' })).toBeVisible()
      await expect(page.locator('article[id^="proposal-suggestion-"]')).toHaveCount(0)

      // Not while the idea is being evaluated (c7), and never for a member.
      const blocked = await alice.get<AiRunList>(`/ideas/${evaluating}/ai-runs`)
      expect(blocked.permissions.can_draft_section).toBe(false)
      expect(blocked.permissions.draft_section_blocked_by).toBe('proposal_not_available')
      const refused = await alice.raw('POST', `/ideas/${evaluating}/ai-runs/section-draft`, {
        agent_id: slow.agent.id,
        section_key: 'risks',
      })
      expect(refused.status()).toBe(404) // no proposal yet (contract §2)
      const bob = await api('bob')
      const asMember = await bob.get<AiRunList>(`/ideas/${key}/ai-runs`)
      expect(asMember.permissions.draft_section_blocked_by).toBe('not_allowed')
      await signIn(page, 'bob')
      await page.goto(`/ideas/${key}?tab=proposal`)
      await expect(page.getByTestId('proposal-editor')).toBeVisible()
      await expect(page.getByRole('button', { name: /with AI$/ })).toHaveCount(0)
    } finally {
      await retireAgents(alice, [slow])
      await team.dispose()
    }
  })
})
