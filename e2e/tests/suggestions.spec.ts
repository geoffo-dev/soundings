import type { Browser, Page } from '@playwright/test'

import { Api, createTeamProject, uniqueSuffix, type Person } from './support/api'
import { expect, signIn, test, toast } from './support/fixtures'
import { KeyClient } from './support/mcp'

/**
 * Proposal suggestions from an MCP client to the owner's editor, against the real stack
 * (contract-phase5 §3.4, §4.3 `propose_proposal_section`): Carol's key suggests a
 * section's text; Bob, the owner, sees it by its section ("via assistant", what it changes)
 * and accepts it (a normal versioned save) or discards it (after its Undo toast);
 * members and viewers see it read-only; one pending suggestion per author and section;
 * a section saved since says so. Test plan: SG-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''
const region = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const card = (page: Page, author: string) =>
  page
    .locator('article[id^="proposal-suggestion-"]')
    .filter({ has: page.getByText(author, { exact: true }) })

interface Story {
  key: string
  slug: string
  projectId: string
  carol: KeyClient
  bob: Api
  /** Revokes Carol's key and closes the client. */
  done: () => Promise<void>
}

/** A shortlisted idea owned by Bob with a started proposal, and Carol's write+mcp key. */
async function story(api: (person: Person) => Promise<Api>): Promise<Story> {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Suggestions', {
    bob: 'member',
    carol: 'member',
    dave: 'member',
    erin: 'viewer',
  })
  const idea = await alice.createIdea(project.slug, {
    title: 'Refill stations for cleaning products',
    summary: 'Customers bring their own bottles and refill them in store.',
  })
  await alice.setOwner(idea.key, 'bob')
  await alice.changeStatus(idea.key, 'shortlisted')
  const bob = await api('bob')
  await bob.startProposal(idea.key)
  await bob.writeSections(idea.key, {
    summary: 'Refill stations in ten stores.',
    problem: 'Single-use bottles are most of our plastic waste.',
  })
  const carol = await api('carol')
  const key = await carol.createApiKey({
    name: `Proposal helper ${uniqueSuffix()}`,
    scopes: ['write', 'mcp'],
    project_ids: [project.id],
  })
  const client = await KeyClient.open(baseURL(), key.secret)
  const done = async () => {
    await client.dispose()
    await carol.revokeApiKey(key.key.id)
  }
  return { key: idea.key, slug: project.slug, projectId: project.id, carol: client, bob, done }
}

async function editor(browser: Browser, person: Person, key: string) {
  const context = await browser.newContext({
    baseURL: baseURL(),
    viewport: { width: 1440, height: 900 },
  })
  const page = await context.newPage()
  await signIn(page, person)
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByTestId('proposal-editor')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
  return page
}

interface Suggested {
  suggestion: { id: string; source: string; status: string; base_version: number }
  replaced_suggestion_id: string | null
}

test('SG-01: an MCP suggestion reaches the owner’s editor; accepting saves it as a new version', async ({
  browser,
  api,
}) => {
  const s = await story(api)
  try {
    const proposal = await s.carol.ok<{
      can_suggest: boolean
      proposal: { sections: { key: string; version: number }[] }
    }>('get_proposal', { idea: s.key })
    expect(proposal.can_suggest).toBe(true)
    const before = proposal.proposal.sections.find((section) => section.key === 'summary')
    const text =
      'Refill stations in **all 40 stores** by the end of the year, starting with the ten busiest.'
    const made = await s.carol.ok<Suggested>('propose_proposal_section', {
      idea: s.key,
      section_key: 'summary',
      body_md: text,
    })
    expect(made.suggestion).toMatchObject({ source: 'mcp', status: 'pending' })
    expect(made.suggestion.base_version).toBe(before?.version)
    expect(made.replaced_suggestion_id).toBeNull()

    const page = await editor(browser, 'bob', s.key)
    await expect(page.getByRole('button', { name: /^1 suggestion/ })).toBeVisible()
    const summary = region(page, '1. Summary')
    await expect(summary.getByRole('heading', { name: '1 suggestion for Summary' })).toBeVisible()
    const carol = card(page, 'Carol Chen')
    await expect(carol).toContainText('via assistant')
    await expect(carol.getByText('Removed:').first()).toBeAttached()
    await expect(carol.getByText('Added:').first()).toBeAttached()
    await carol.getByRole('radio', { name: 'Suggested text' }).click()
    await expect(carol.locator('strong', { hasText: 'all 40 stores' })).toBeVisible()

    await carol.getByRole('button', { name: 'Accept: Carol Chen’s suggestion for Summary' }).click()
    await expect(toast(page, 'Carol Chen’s suggestion accepted')).toBeVisible()
    await expect(card(page, 'Carol Chen')).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Summary', exact: true })).toHaveValue(text)
    // Saved as the next version, by Bob; nothing pending any more.
    const view = await s.bob.proposal(s.key)
    const saved = view.proposal?.sections.find((section) => section.key === 'summary')
    expect(saved?.body_md).toBe(text)
    expect(saved?.version).toBe((before?.version ?? 0) + 1)
    expect(saved?.updated_by?.display_name).toBe('Bob Brown')
    expect((await s.bob.suggestions(s.key)).items).toEqual([])
    // The client sees the accepted text.
    const after = await s.carol.ok<{ proposal: { sections: { key: string; body_md: string }[] } }>(
      'get_proposal',
      { idea: s.key },
    )
    expect(after.proposal.sections.find((section) => section.key === 'summary')?.body_md).toBe(text)
    await page.context().close()
  } finally {
    await s.done()
  }
})

test('SG-02: discarding hides it at once with Undo, then the client may suggest again', async ({
  browser,
  api,
}) => {
  const s = await story(api)
  try {
    await s.carol.ok('propose_proposal_section', {
      idea: s.key,
      section_key: 'risks',
      body_md: 'Customers may refill with the wrong product.',
    })
    const page = await editor(browser, 'bob', s.key)
    const risks = region(page, '7. Risks')
    await risks.getByRole('button', { name: 'Discard Carol Chen’s suggestion for Risks' }).click()
    await expect(risks.getByRole('article')).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Risks', exact: true })).toBeFocused()
    await expect(toast(page, 'Carol Chen’s suggestion discarded')).toBeVisible()
    // The discard goes when its Undo toast closes (about 6 s); until then it is pending.
    expect((await s.bob.suggestions(s.key)).items).toHaveLength(1)
    await expect
      .poll(async () => (await s.bob.suggestions(s.key)).items.length, { timeout: 20_000 })
      .toBe(0)
    const text = await s.bob.proposal(s.key)
    expect(text.proposal?.sections.find((section) => section.key === 'risks')?.body_md).toBe('')

    // A new suggestion is a new pending one.
    const again = await s.carol.ok<Suggested>('propose_proposal_section', {
      idea: s.key,
      section_key: 'risks',
      body_md: 'Spills at the refill station.',
    })
    expect(again.replaced_suggestion_id).toBeNull()
    await page.reload()
    await expect(region(page, '7. Risks').getByRole('article')).toHaveCount(1)
    await page.context().close()
  } finally {
    await s.done()
  }
})

test('SG-03: one pending suggestion per author and section; a section saved since says so', async ({
  browser,
  api,
}) => {
  const s = await story(api)
  try {
    const first = await s.carol.ok<Suggested>('propose_proposal_section', {
      idea: s.key,
      section_key: 'problem',
      body_md: 'Bottles are 60% of our plastic waste.',
    })
    const second = await s.carol.ok<Suggested>('propose_proposal_section', {
      idea: s.key,
      section_key: 'problem',
      body_md: 'Bottles are 62% of our plastic waste (2025 audit).',
    })
    expect(second.replaced_suggestion_id).toBe(first.suggestion.id)
    const pending = (await s.bob.suggestions(s.key)).items
    expect(pending.map((item) => item.id)).toEqual([second.suggestion.id])

    // Bob saves Problem meanwhile: the suggestion was written against an older version.
    const view = await s.bob.proposal(s.key)
    const problem = view.proposal?.sections.find((section) => section.key === 'problem')
    await s.bob.saveSection(
      s.key,
      'problem',
      'Single-use bottles: 3 tonnes a month.',
      problem?.version ?? 1,
    )

    const page = await editor(browser, 'bob', s.key)
    const carol = card(page, 'Carol Chen')
    await expect(carol).toHaveCount(1)
    await expect(carol).toContainText('The section has changed since this was suggested')
    await carol.getByRole('radio', { name: 'Suggested text' }).click()
    await expect(carol).toContainText('62% of our plastic waste')
    await carol.getByRole('button', { name: 'Accept: Carol Chen’s suggestion for Problem' }).click()
    await expect(toast(page, 'Carol Chen’s suggestion accepted')).toBeVisible()
    const after = await s.bob.proposal(s.key)
    expect(after.proposal?.sections.find((section) => section.key === 'problem')?.body_md).toBe(
      'Bottles are 62% of our plastic waste (2025 audit).',
    )
    // A stale base_version above the section's is refused.
    expect(
      await s.carol.fails('propose_proposal_section', {
        idea: s.key,
        section_key: 'problem',
        body_md: 'Too new.',
        base_version: 99,
      }),
    ).toBe('validation_error')
    await page.context().close()
  } finally {
    await s.done()
  }
})

test('SG-04: members and viewers see suggestions read-only; viewers can’t suggest', async ({
  browser,
  api,
}) => {
  const s = await story(api)
  const erin = await api('erin')
  const viewerKey = await erin.createApiKey({
    name: `Viewer helper ${uniqueSuffix()}`,
    scopes: ['write', 'mcp'],
    project_ids: [s.projectId],
  })
  const viewer = await KeyClient.open(baseURL(), viewerKey.secret)
  try {
    await s.carol.ok('propose_proposal_section', {
      idea: s.key,
      section_key: 'solution',
      body_md: 'A refill wall by the tills.',
    })
    expect(
      await viewer.fails('propose_proposal_section', {
        idea: s.key,
        section_key: 'solution',
        body_md: 'Viewers can’t suggest.',
      }),
    ).toBe('forbidden')
    for (const person of ['dave', 'erin'] as const) {
      const page = await editor(browser, person, s.key)
      const carol = card(page, 'Carol Chen')
      await expect(carol).toContainText('via assistant')
      await expect(carol.getByRole('button', { name: /^Accept/ })).toHaveCount(0)
      await expect(carol.getByRole('button', { name: /^Discard/ })).toHaveCount(0)
      await page.context().close()
    }
    // Only the owner (or an admin) decides: Dave's session gets 403.
    const dave = await api('dave')
    const [pending] = (await dave.suggestions(s.key)).items
    expect((await dave.suggestions(s.key)).permissions.can_decide).toBe(false)
    const refused = await dave.raw(
      'POST',
      `/ideas/${s.key}/proposal/suggestions/${pending?.id ?? ''}/discard`,
    )
    expect(refused.status()).toBe(403)
  } finally {
    await viewer.dispose()
    await erin.revokeApiKey(viewerKey.key.id)
    await s.done()
  }
})
