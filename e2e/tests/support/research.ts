import type { components } from '../../../frontend/src/api/generated/schema'
import { createTeamProject, type Api, type Person, type Project, type ProjectRole } from './api'

/**
 * Phase 8 (contract-phase8): per-project proposal templates and the research step,
 * arranged through the real API as a project admin would (session, CSRF). Specs that
 * change a template or a step use a project of their own (`researchTeam`), so they run
 * side by side and never touch the demo story.
 */

type Schemas = components['schemas']
export type ResearchStep = Schemas['ResearchStep']
export type ResearchSettings = Schemas['ResearchSettings']
export type IdeaResearch = Schemas['IdeaResearch']
export type ProposalTemplate = Schemas['ProposalTemplate']
export type TemplateSectionIn = Schemas['TemplateSectionIn']
export type SimilarIdeas = Schemas['SimilarIdeas']

/** The default checklist the settings offer (`DEFAULT_RESEARCH_CHECKLIST`). */
export const CHECKLIST = {
  elsewhere: 'Not already being done elsewhere',
  consulted: 'Departments or teams consulted',
  privacy: 'Data protection considered',
} as const
export const REQUIRED_ITEMS = [CHECKLIST.elsewhere, CHECKLIST.consulted]

/** The built-in eight (titles as the template has them). */
export const DEFAULT_SECTIONS = [
  'Summary',
  'Problem',
  'Solution',
  'Market & users',
  'Cost & effort',
  'Benefits / revenue',
  'Risks',
  'Next steps / the ask',
] as const

export function researchSettings(api: Api, slug: string): Promise<ResearchSettings> {
  return api.get(`/projects/${slug}/research`)
}

/**
 * Sets the project's research step. Turning it on with no checklist yet uses the
 * default three items (as the settings page offers them); otherwise the checklist
 * stays as it is.
 */
export async function setResearchStep(
  api: Api,
  slug: string,
  step: ResearchStep,
): Promise<ResearchSettings> {
  const current = await researchSettings(api, slug)
  const items =
    step === 'off'
      ? []
      : current.items.length > 0
        ? current.items.map(({ id, title, hint, required }) => ({ id, title, hint, required }))
        : current.default_items
  return api.send('PUT', `/projects/${slug}/research`, { step, items })
}

export function ideaResearch(api: Api, key: string): Promise<IdeaResearch> {
  return api.get(`/ideas/${key}/research`)
}

/** Answers the item with this title (the idea's owner or an admin). */
export async function answerItem(
  api: Api,
  key: string,
  title: string,
  answer: string,
): Promise<IdeaResearch> {
  const research = await ideaResearch(api, key)
  const item = research.items.find((candidate) => candidate.title === title)
  if (!item) throw new Error(`No research item "${title}" on ${key}`)
  return api.send('PUT', `/ideas/${key}/research/items/${item.item_id}`, { answer })
}

/** Answers every required item, so the idea may move past Research. */
export async function answerRequired(api: Api, key: string): Promise<IdeaResearch> {
  let research = await ideaResearch(api, key)
  for (const item of research.items) {
    if (item.required && !item.answer) {
      research = await api.send('PUT', `/ideas/${key}/research/items/${item.item_id}`, {
        answer: `${item.title}: checked (e2e).`,
      })
    }
  }
  return research
}

export function proposalTemplate(api: Api, slug: string): Promise<ProposalTemplate> {
  return api.get(`/projects/${slug}/proposal-template`)
}

export function setProposalTemplate(
  api: Api,
  slug: string,
  sections: TemplateSectionIn[],
): Promise<ProposalTemplate> {
  return api.send('PUT', `/projects/${slug}/proposal-template`, { sections })
}

export function similarIdeas(api: Api, key: string): Promise<SimilarIdeas> {
  return api.get(`/ideas/${key}/similar-ideas`)
}

/**
 * A fresh private project (Alice its admin) with the research step at `step` (the
 * default checklist) and these members.
 */
export async function researchTeam(
  alice: Api,
  name: string,
  step: ResearchStep,
  members: Partial<Record<Person, ProjectRole>>,
): Promise<Project> {
  const project = await createTeamProject(alice, name, members)
  if (step !== 'off') await setResearchStep(alice, project.slug, step)
  return alice.project(project.slug)
}
