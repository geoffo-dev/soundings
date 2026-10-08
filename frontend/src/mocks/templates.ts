/**
 * Phase 8 per-project proposal templates in the mock API (contract-phase8 §2):
 * 1–12 sections per project, each with a stable key, a title and a hint; a
 * removed section that anything refers to is archived (its text kept, hidden),
 * otherwise deleted. Records mirror `proposal_template_sections`. The backend is
 * the authority.
 */
import type { ProposalTemplate, ProposalTemplateSection, RemovedTemplateSection } from '@/api/types'

import type { MockDb } from './db'

export interface MockTemplateSection {
  id: string
  project_id: string
  key: string
  title: string
  hint: string
  position: number
  archived_at: string | null
}

export const MIN_TEMPLATE_SECTIONS = 1
export const MAX_TEMPLATE_SECTIONS = 12
export const TEMPLATE_TITLE_MAX_LENGTH = 60
export const TEMPLATE_HINT_MAX_LENGTH = 200
export const SECTION_KEY_PATTERN = /^[a-z][a-z0-9_]{0,39}$/

/** The built-in eight (SPEC section 2): every project starts from these. */
export const DEFAULT_TEMPLATE: readonly { key: string; title: string; hint: string }[] = [
  {
    key: 'summary',
    title: 'Summary',
    hint: 'The idea in a few sentences: what we would do and why it matters.',
  },
  { key: 'problem', title: 'Problem', hint: 'Who has this problem, and how do we know?' },
  {
    key: 'solution',
    title: 'Solution',
    hint: 'Describe what we would build or change, and how it solves the problem.',
  },
  {
    key: 'market',
    title: 'Market & users',
    hint: 'Who would use or buy this, how many of them are there, and how do we reach them?',
  },
  {
    key: 'cost',
    title: 'Cost & effort',
    hint: 'What would it take: people, time, money and dependencies?',
  },
  {
    key: 'benefits',
    title: 'Benefits / revenue',
    hint: 'What do we gain: revenue, savings or other benefits, and how will we measure them?',
  },
  { key: 'risks', title: 'Risks', hint: 'What could go wrong, and how would we reduce it?' },
  {
    key: 'next_steps',
    title: 'Next steps / the ask',
    hint: 'What do you need, from whom, and by when?',
  },
]

/** Template rows for a new project (the backend's default eight). */
export function defaultTemplate(projectId: string, nextId: () => string): MockTemplateSection[] {
  return DEFAULT_TEMPLATE.map((section, position) => ({
    ...section,
    id: nextId(),
    project_id: projectId,
    position,
    archived_at: null,
  }))
}

/** The project's active sections, in order. */
export function activeSections(db: MockDb, projectId: string): MockTemplateSection[] {
  return db.templateSections
    .filter((s) => s.project_id === projectId && s.archived_at === null)
    .sort((a, b) => a.position - b.position)
}

export function activeSection(
  db: MockDb,
  projectId: string,
  key: string,
): MockTemplateSection | undefined {
  return db.templateSections.find(
    (s) => s.project_id === projectId && s.key === key && s.archived_at === null,
  )
}

/** Index of a key in the project's template (removed and unknown keys sort last). */
export function sectionOrder(db: MockDb, projectId: string): (key: string) => number {
  const keys = activeSections(db, projectId).map((s) => s.key)
  return (key) => {
    const index = keys.indexOf(key)
    return index < 0 ? keys.length : index
  }
}

/**
 * `section_key_for(title, taken)` (contract-phase8 §2.2): ASCII-folded, lower
 * case, other runs one `_`, trimmed, ≤ 36 characters, `s_` before a digit,
 * `section` when empty; `_2`, `_3`… while taken.
 */
export function sectionKeyFor(title: string, taken: ReadonlySet<string>): string {
  let base = title
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 36)
    .replace(/_+$/g, '')
  if (/^[0-9]/.test(base)) base = `s_${base}`
  if (!base) base = 'section'
  if (!taken.has(base)) return base
  for (let n = 2; ; n += 1) {
    const candidate = `${base}_${n}`
    if (!taken.has(candidate)) return candidate
  }
}

/** Proposals of the project with text in each section key (the removal warning's N). */
function proposalCounts(db: MockDb, projectId: string): Map<string, number> {
  const ideaIds = new Set(db.ideas.filter((i) => i.project_id === projectId).map((i) => i.id))
  const proposalIds = new Set(db.proposals.filter((p) => ideaIds.has(p.idea_id)).map((p) => p.id))
  const counts = new Map<string, number>()
  for (const row of db.proposalSections) {
    if (!proposalIds.has(row.proposal_id) || !row.body_md.trim()) continue
    counts.set(row.key, (counts.get(row.key) ?? 0) + 1)
  }
  return counts
}

/** Something refers to the key: text, a thread, a suggestion or an AI run (keep it archived). */
export function sectionInUse(db: MockDb, projectId: string, key: string): boolean {
  const ideaIds = new Set(db.ideas.filter((i) => i.project_id === projectId).map((i) => i.id))
  const proposalIds = new Set(db.proposals.filter((p) => ideaIds.has(p.idea_id)).map((p) => p.id))
  return (
    db.proposalSections.some(
      (s) => proposalIds.has(s.proposal_id) && s.key === key && s.body_md.trim() !== '',
    ) ||
    db.proposalThreads.some((t) => proposalIds.has(t.proposal_id) && t.section_key === key) ||
    db.proposalSuggestions.some((s) => proposalIds.has(s.proposal_id) && s.section_key === key) ||
    db.aiRuns.some((run) => ideaIds.has(run.idea_id) && run.section_key === key)
  )
}

export function templateOut(db: MockDb, projectId: string): ProposalTemplate {
  const counts = proposalCounts(db, projectId)
  const sections: ProposalTemplateSection[] = activeSections(db, projectId).map((s) => ({
    key: s.key,
    title: s.title,
    hint: s.hint,
    position: s.position,
    proposal_count: counts.get(s.key) ?? 0,
  }))
  const removed: RemovedTemplateSection[] = db.templateSections
    .filter((s) => s.project_id === projectId && s.archived_at !== null)
    .sort((a, b) => (b.archived_at ?? '').localeCompare(a.archived_at ?? ''))
    .map((s) => ({
      key: s.key,
      title: s.title,
      hint: s.hint,
      removed_at: s.archived_at ?? '',
      proposal_count: counts.get(s.key) ?? 0,
    }))
  return { sections, removed_sections: removed }
}

/** Every proposal of the project gets a (version 1, empty) row for each active section. */
export function fillMissingSections(db: MockDb, projectId: string): void {
  const sections = activeSections(db, projectId)
  const ideaIds = new Set(db.ideas.filter((i) => i.project_id === projectId).map((i) => i.id))
  for (const proposal of db.proposals) {
    if (!ideaIds.has(proposal.idea_id)) continue
    for (const section of sections) {
      const exists = db.proposalSections.some(
        (row) => row.proposal_id === proposal.id && row.key === section.key,
      )
      if (!exists) {
        db.proposalSections.push({
          proposal_id: proposal.id,
          key: section.key,
          body_md: '',
          version: 1,
          updated_at: proposal.created_at,
          updated_by_id: null,
        })
      }
    }
  }
}
