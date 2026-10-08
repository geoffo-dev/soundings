import { readFileSync } from 'node:fs'

import type { Page } from '@playwright/test'

import {
  aiTeam,
  askAgent,
  registerAgent,
  requestRun,
  retireAgents,
  skipWithoutAi,
  waitRun,
} from './support/ai'
import { Api, createTeamProject, type Project } from './support/api'
import { expect, heading, settled, signIn, test, toast } from './support/fixtures'
import { readPdf } from './support/pdf'
import { DEFAULT_SECTIONS, proposalTemplate, setProposalTemplate } from './support/research'

/**
 * Phase 8, per-project proposal templates (contract-phase8 §2), against the real API:
 * a project admin renames, reorders, adds and removes sections in Project settings →
 * Proposal (removing one with text asks first and keeps it under "Removed sections";
 * Restore brings it back with its text); the proposal editor, the PDF and the Markdown
 * export follow at once; a member reads the template only; text typed into a section
 * removed meanwhile is kept; the seeded Internal Tools and Sustainability proposals.
 * Test plan: TPL-*.
 */

const rows = (page: Page) => page.getByRole('list', { name: 'Sections' }).getByRole('listitem')
const titleField = (page: Page, index: number) =>
  rows(page).nth(index).getByRole('textbox', { name: 'Title' })
const sectionHeading = (page: Page, title: string) =>
  page.getByRole('heading', { level: 2, name: new RegExp(`^\\d+\\. ${escape(title)}$`) })

function escape(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')
}

const COST_TEXT = 'Two kiosks at £4,000 each and an hour of staff time a day.'
const MARKET_TEXT = 'Shoppers buying gifts in December: about a third of our footfall.'

/** A project with the default template and a proposal Bob owns, with two sections written. */
async function withProposal(alice: Api): Promise<{ project: Project; key: string }> {
  const project = await createTeamProject(alice, 'Templates', { bob: 'member', carol: 'member' })
  const idea = await alice.createIdea(project.slug, {
    title: 'Gift wrap kiosks',
    summary: 'Self-service gift wrapping by the tills.',
  })
  await alice.setOwner(idea.key, 'bob')
  await alice.changeStatus(idea.key, 'shortlisted')
  const bob = await Api.as(alice.baseURL, 'bob')
  try {
    await bob.startProposal(idea.key)
    await bob.writeSections(idea.key, { market: MARKET_TEXT, cost: COST_TEXT })
  } finally {
    await bob.dispose()
  }
  return { project, key: idea.key }
}

async function openTemplate(page: Page, slug: string, count: number) {
  await page.goto(`/p/${slug}/settings?tab=proposal-template`)
  await expect(page.getByRole('heading', { name: 'Proposal template' })).toBeVisible()
  await expect(rows(page)).toHaveCount(count)
}

async function download(page: Page, format: RegExp) {
  // The menu of the previous export must be gone before it opens again.
  await expect(page.getByRole('menu')).toHaveCount(0)
  await page.getByRole('button', { name: 'Export' }).click()
  const item = page.getByRole('menuitem', { name: format })
  await expect(item).toBeVisible()
  const file = page.waitForEvent('download')
  await item.click()
  return readFileSync(await (await file).path())
}

test('TPL-01: an admin edits the template; the editor and both exports follow; Restore brings text back', async ({
  page,
  api,
}) => {
  test.setTimeout(120_000)
  const alice = await api('alice')
  const { project, key } = await withProposal(alice)
  await signIn(page, 'alice')
  await openTemplate(page, project.slug, 8)
  for (const [index, title] of DEFAULT_SECTIONS.entries()) {
    await expect(titleField(page, index)).toHaveValue(title)
  }

  // Rename Market & users, move Risks up, add Pilot plan, remove Cost & effort.
  await titleField(page, 3).fill('Customers')
  await page.getByRole('button', { name: 'Move Risks', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Move up' }).click()
  await expect(titleField(page, 5)).toHaveValue('Risks')
  await page.getByRole('button', { name: 'Add section' }).click()
  const added = rows(page).last()
  await expect(added.getByRole('textbox', { name: 'Title' })).toBeFocused()
  await added.getByRole('textbox', { name: 'Title' }).fill('Pilot plan')
  await added
    .getByRole('textbox', { name: 'Hint' })
    .fill('Where we try it first, and for how long.')
  // No confirmation: the text is kept (Removed sections restores it, UX review S1), and
  // focus moves to the row that took its place (M2).
  await page.getByRole('button', { name: 'Remove Cost & effort' }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(rows(page)).toHaveCount(8)
  await expect(titleField(page, 4)).toBeFocused()
  await expect(titleField(page, 4)).toHaveValue('Risks')
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Proposal template saved')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Removed sections' })).toBeVisible()
  await expect(page.getByText(/Text in 1 proposal/)).toBeVisible()

  // The keys never change: the built-in ones stay, the new one is a slug of its title.
  const template = await proposalTemplate(alice, project.slug)
  expect(template.sections.map((section) => section.key)).toEqual([
    'summary',
    'problem',
    'solution',
    'market',
    'risks',
    'benefits',
    'next_steps',
    'pilot_plan',
  ])
  expect(template.removed_sections.map((section) => [section.key, section.proposal_count])).toEqual(
    [['cost', 1]],
  )

  // The proposal editor follows at once (Bob, the owner).
  await signIn(page, 'bob')
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(sectionHeading(page, 'Customers')).toBeVisible()
  await expect(sectionHeading(page, 'Pilot plan')).toBeVisible()
  await expect(sectionHeading(page, 'Cost & effort')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Customers', exact: true })).toHaveValue(
    MARKET_TEXT,
  )
  // The hint: a line under the heading, read with the field (UX review m3).
  await expect(
    page.getByRole('textbox', { name: 'Pilot plan', exact: true }),
  ).toHaveAccessibleDescription(/^Where we try it first, and for how long\./)
  const outline = page.getByRole('navigation', { name: 'Outline' })
  await expect(outline.getByRole('link')).toHaveText([
    /Summary/,
    /Problem/,
    /Solution/,
    /Customers/,
    /Risks/,
    /Benefits \/ revenue/,
    /Next steps \/ the ask/,
    /Pilot plan/,
  ])
  expect(await page.getByText(COST_TEXT).count()).toBe(0)

  // Both exports.
  const markdown = (await download(page, /Markdown/)).toString('utf8')
  const headings = markdown
    .split('\n')
    .filter((line) => line.startsWith('## '))
    .map((line) => line.slice(3))
  expect(headings).toEqual([
    'Summary',
    'Problem',
    'Solution',
    'Customers',
    'Risks',
    'Benefits / revenue',
    'Next steps / the ask',
    'Pilot plan',
  ])
  expect(markdown).toContain(`## Customers\n\n${MARKET_TEXT}\n`)
  expect(markdown).not.toContain(COST_TEXT)
  const pdf = await readPdf(await download(page, /PDF/))
  const text = pdf.pages.join('\n').replace(/\s+/g, ' ')
  expect(text).toContain('Customers')
  expect(text).toContain('Pilot plan')
  expect(text).toContain(MARKET_TEXT)
  expect(text).not.toContain(COST_TEXT)
  expect(text).not.toContain('Cost & effort')
  expect(text.indexOf('Customers')).toBeLessThan(text.indexOf('Pilot plan'))

  // Restore: the section and its text come back.
  await signIn(page, 'alice')
  await openTemplate(page, project.slug, 8)
  await page.getByRole('button', { name: 'Restore Cost & effort' }).click()
  await expect(rows(page)).toHaveCount(9)
  await expect(titleField(page, 8)).toBeFocused()
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Proposal template saved')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Removed sections' })).toHaveCount(0)
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByRole('textbox', { name: 'Cost & effort', exact: true })).toHaveValue(
    COST_TEXT,
  )
})

test('TPL-02: a member reads the template without changing it', async ({ page, api }) => {
  const alice = await api('alice')
  const { project } = await withProposal(alice)
  await signIn(page, 'bob')
  await page.goto(`/p/${project.slug}/settings?tab=proposal-template`)
  const tabpanel = page.getByRole('tabpanel', { name: 'Proposal template' })
  await expect(
    tabpanel.getByText('Every proposal in this project has these sections'),
  ).toBeVisible()
  await expect(tabpanel.getByText('Market & users')).toBeVisible()
  await expect(tabpanel.getByRole('textbox')).toHaveCount(0)
  // …and the API refuses a member's save.
  const bob = await api('bob')
  const response = await bob.raw('PUT', `/projects/${project.slug}/proposal-template`, {
    sections: [{ title: 'Only this' }],
  })
  expect(response.status()).toBe(403)
})

/** Bob's editor open while Alice removes the empty Risks section (deleted outright). */
async function removeRisksWhileOpen(page: Page, alice: Api) {
  const { project, key } = await withProposal(alice)
  await signIn(page, 'bob')
  await page.goto(`/ideas/${key}?tab=proposal`)
  const risks = page.getByRole('textbox', { name: 'Risks', exact: true })
  await expect(risks).toBeVisible()
  const template = await proposalTemplate(alice, project.slug)
  await setProposalTemplate(
    alice,
    project.slug,
    template.sections
      .filter((section) => section.key !== 'risks')
      .map(({ key: sectionKey, title, hint }) => ({ key: sectionKey, title, hint })),
  )
  const typed = 'Kiosks jam when the paper roll runs out.'
  await risks.fill(typed)
  // The autosave answers 404 and the text is kept here.
  await expect(page.getByRole('textbox', { name: 'Your text for Risks' })).toHaveValue(typed, {
    timeout: 15_000,
  })
  return { key, typed }
}

test('TPL-03: text typed into a section removed meanwhile is kept and the editor says it was removed', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  await removeRisksWhileOpen(page, alice)
  await expect(page.getByText('“Risks” was removed from the template')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: /Risks$/ })).toHaveCount(0)
})

test('TPL-03b: after a reload the kept text is still there, marked as removed', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { typed } = await removeRisksWhileOpen(page, alice)
  await page.reload()
  await expect(page.getByText('“Risks” was removed from the template')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Your text for Risks' })).toHaveValue(typed)
  await expect(
    page.getByText('Your text is kept here; copy it, or ask an admin to restore the section.'),
  ).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: /Risks$/ })).toHaveCount(0)
})

test('TPL-04: the seeded proposals follow their projects’ templates', async ({ page }) => {
  // Internal Tools: Summary, Problem, Solution, Effort & rollout, Risks, The ask, then the
  // research appendix (the step is on).
  await signIn(page, 'kenji')
  await page.goto('/ideas/TOOLS-3?tab=proposal')
  await expect(heading(page, /test data generator/i)).toBeVisible()
  await settled(page)
  await expect(page.getByRole('navigation', { name: 'Outline' }).getByRole('link')).toHaveText([
    /Summary/,
    /Problem/,
    /Solution/,
    /Effort & rollout/,
    /Risks/,
    /The ask/,
    'Research and consultation',
  ])
  await expect(
    page.getByRole('textbox', { name: 'The ask', exact: true }),
  ).toHaveAccessibleDescription(/^People, time or budget we need, and from whom\./)
  const appendix = page.getByRole('region', { name: 'Research and consultation' })
  await expect(appendix).toContainText('Departments or teams consulted')
  await expect(appendix).toContainText('QA (test automation), 2 Sep')
  await expect(appendix).toContainText('Answered by Kenji Watanabe')

  // Sustainability: the default eight plus Carbon impact after Benefits / revenue.
  await signIn(page, 'zanele')
  await page.goto('/ideas/GREEN-4?tab=proposal')
  await expect(sectionHeading(page, 'Carbon impact')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Carbon impact', exact: true })).toHaveValue(
    /95 t CO2e a year/,
  )
})

test.describe('@ai TPL-05: "Draft with AI" follows the template', () => {
  test.beforeEach(skipWithoutAi)

  /** A project whose template gains "Pilot plan", a proposal started, a drafting agent. */
  async function drafting(alice: Api) {
    const team = await aiTeam(alice, 'AI template')
    const template = await proposalTemplate(alice, team.project.slug)
    await setProposalTemplate(alice, team.project.slug, [
      ...template.sections
        .filter((section) => section.key !== 'cost')
        .map(({ key, title, hint }) => ({ key, title, hint })),
      { title: 'Pilot plan', hint: 'Where we try it first, and for how long.' },
    ])
    const key = await team.idea({ status: 'shortlisted' })
    const agent = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['draft_section'],
    })
    return { team, key, agent }
  }

  test('a removed or unknown section is refused before any run starts', async ({ api }) => {
    const alice = await api('alice')
    const { team, key, agent } = await drafting(alice)
    try {
      for (const sectionKey of ['cost', 'budget']) {
        const response = await requestRun(
          team.owner,
          key,
          'draft_section',
          agent.agent.id,
          sectionKey,
        )
        expect(response.status(), sectionKey).toBe(422)
        expect(await response.json()).toMatchObject({ code: 'unknown_section' })
      }
    } finally {
      await retireAgents(alice, [agent])
      await team.dispose()
    }
  })

  test('a draft for a section the project added becomes its suggestion', async ({ api }) => {
    const alice = await api('alice')
    const { team, key, agent } = await drafting(alice)
    try {
      const run = await askAgent(team.owner, key, 'draft_section', agent.agent.id, 'pilot_plan')
      expect(run.section_key).toBe('pilot_plan')
      const done = await waitRun(team.owner, key, run.id)
      expect(done.status).toBe('succeeded')
      const suggestions = await team.owner.suggestions(key)
      expect(suggestions.items.map((item) => item.section_key)).toContain('pilot_plan')
    } finally {
      await retireAgents(alice, [agent])
      await team.dispose()
    }
  })
})
