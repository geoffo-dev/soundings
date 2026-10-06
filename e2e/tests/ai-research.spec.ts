import {
  aiTeam,
  type AiRunList,
  registerAgent,
  retireAgents,
  type ResearchNote,
  signInAs,
  skipWithoutAi,
  waitRun,
} from './support/ai'
import { expect, openIdea, signIn, test, toast } from './support/fixtures'
import { FakeAgent } from '../scripts/fake-agent'

/**
 * "Research this" (SPEC section 9, contract-phase6 §3.8): the owner asks an agent from the
 * idea's AI menu; it reads the idea through `/mcp` and writes a research note
 * (`add_research_note`, only during its research run) that lands in the activity feed
 * with the AI label: untrusted Markdown (no raw HTML, http/https links with their host),
 * numbered sources under "Cited by AI, not checked", Delete for the owner and admins only.
 * Test plan: AR6-*.
 */

test.describe('@ai research notes', () => {
  test.beforeEach(skipWithoutAi)

  test('AR6-01 “Research this” adds a cited research note to the feed', async ({ page, api }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI research')
    const key = await team.idea({ title: 'Reusable delivery boxes' })
    const researcher = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['research'],
      displayName: 'Idea researcher',
    })
    try {
      await signInAs(page, team.owner.me)
      await openIdea(page, key)
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      // This agent only researches: evaluation is explained, not offered.
      await expect(page.getByRole('menuitem', { name: /Ask AI to evaluate/ })).toBeDisabled()
      await expect(page.getByRole('menuitem', { name: /Ask AI to evaluate/ })).toContainText(
        'No AI agent serves this project',
      )
      await page.getByRole('menuitem', { name: /Research this/ }).click()
      await expect(toast(page, 'Asked Idea researcher to research this idea')).toBeVisible()

      const card = page.locator('article[id^="ai-run-"]').first()
      await expect(card.getByRole('list', { name: 'Steps' })).toContainText(
        'Wrote the research note',
        { timeout: 30_000 },
      )
      await expect(card).toContainText('Research note saved')
      await card.getByRole('button', { name: 'Read the note' }).click()
      const note = page.locator('article[id^="research-note-"]')
      await expect(note).toBeFocused()
      await expect(
        note.getByRole('heading', { name: /Research note by Idea researcher/ }),
      ).toBeVisible()
      await expect(note).toContainText('AI agent')
      // The agent's Markdown, rendered: its headings and list, its words as text.
      await expect(note.getByRole('heading', { name: `Research note on ${key}` })).toBeVisible()
      await expect(note.getByRole('heading', { name: 'Findings' })).toBeVisible()
      await expect(note.getByText(/none fits this team's workflow exactly/)).toBeVisible()
      const sources = note.getByRole('list', { name: 'Cited by AI, not checked' })
      await expect(sources.getByRole('listitem')).toHaveCount(3)
      const links = sources.getByRole('link')
      await expect(links).toHaveCount(3)
      for (const link of await links.all()) {
        await expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow')
        await expect(link).toHaveAttribute('target', '_blank')
        await expect(link).toHaveAttribute(
          'href',
          /^https:\/\/example\.org\/fake-agent\/research\//,
        )
      }
      await expect(sources).toContainText('example.org')
      await expect(note).toContainText('Check the facts before you rely on them')

      // The run and the note through the API: one note, attached to its run.
      const runs = await alice.get<AiRunList>(`/ideas/${key}/ai-runs`)
      const done = runs.items[0]
      expect(done?.status).toBe('succeeded')
      const stored = await alice.get<ResearchNote>(
        `/ideas/${key}/research-notes/${done?.result.note_id ?? ''}`,
      )
      expect(stored.sources).toHaveLength(3)
      expect(stored.run_id).toBe(done?.id)
      const seen = await new FakeAgent().waitFor(done?.id ?? '', (r) => r.final_state !== null)
      expect(seen.tool_calls.map((c) => c.tool)).toEqual(['get_idea', 'add_research_note'])

      // Bob (a member) reads it but can't delete it; Alice (the owner) can.
      const bob = await page.context().browser()?.newContext({
        baseURL: test.info().project.use.baseURL,
      })
      if (!bob) throw new Error('no browser')
      const bobPage = await bob.newPage()
      await signIn(bobPage, 'bob')
      await openIdea(bobPage, key)
      const bobsNote = bobPage.locator('article[id^="research-note-"]')
      await expect(bobsNote).toContainText('Research note by Idea researcher')
      await expect(bobsNote.getByRole('button', { name: /Research note actions/ })).toHaveCount(0)
      await bob.close()

      await note.getByRole('button', { name: /Research note actions/ }).click()
      await page.getByRole('menuitem', { name: 'Delete note…' }).click()
      await page.getByRole('alertdialog').getByRole('button', { name: 'Delete note' }).click()
      await expect(toast(page, 'Research note deleted')).toBeVisible()
      await expect(note).toHaveCount(0)
      await expect(
        page.getByText(/research note, since deleted|deleted a research note/),
      ).toBeVisible()
      const deleted = await alice.get<ResearchNote>(`/ideas/${key}/research-notes/${stored.id}`)
      expect([deleted.deleted, deleted.body_md, deleted.sources]).toEqual([true, '', []])
    } finally {
      await retireAgents(alice, [researcher])
      await team.dispose()
    }
  })

  test('AR6-02 each research run writes its own note; members get no AI actions', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI research rights')
    const key = await team.idea({ title: 'Recycled packaging for every order' })
    const researcher = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['research'],
    })
    try {
      // Two runs, two notes, each its run's.
      const first = await waitRun(
        alice,
        key,
        (
          await team.owner.send<{ id: string }>(
            'POST',
            `/ideas/${key}/ai-runs/research`,
            { agent_id: researcher.agent.id },
            201,
          )
        ).id,
      )
      const second = await waitRun(
        alice,
        key,
        (
          await team.owner.send<{ id: string }>(
            'POST',
            `/ideas/${key}/ai-runs/research`,
            { agent_id: researcher.agent.id },
            201,
          )
        ).id,
      )
      expect([first.status, second.status]).toEqual(['succeeded', 'succeeded'])
      expect(first.result.note_id).not.toBe(second.result.note_id)

      await signIn(page, 'kenji') // a member, not the owner
      await openIdea(page, key)
      await expect(page.locator('article[id^="research-note-"]')).toHaveCount(2)
      await expect(page.getByRole('button', { name: 'AI actions' })).toHaveCount(0)
      const kenji = await api('kenji')
      const refused = await kenji.raw('POST', `/ideas/${key}/ai-runs/research`, {
        agent_id: researcher.agent.id,
      })
      expect(refused.status()).toBe(403)
      const runs = await kenji.get<AiRunList>(`/ideas/${key}/ai-runs`)
      expect(runs.permissions.can_research).toBe(false)
      expect(runs.permissions.research_blocked_by).toBe('not_allowed')
      expect(runs.items.map((r) => r.can_cancel)).toEqual([false, false])
    } finally {
      await retireAgents(alice, [researcher])
      await team.dispose()
    }
  })
})
