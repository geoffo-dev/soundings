import type {
  FieldError,
  ProposalTemplate,
  ProposalTemplateSection,
  ProposalTemplateUpdate,
  RemovedTemplateSection,
} from '@/api/types'

import { moveItem } from './rubric'

/**
 * The proposal template editor's form model (contract-phase8 §2.2): 1–12 sections,
 * titles 1–60 characters (one line, unique ignoring case), hints up to 200. Each
 * section keeps its key (never shown); a new one gets its key from the server.
 * Saving replaces the whole template.
 */
export const MIN_SECTIONS = 1
export const MAX_SECTIONS = 12
export const SECTION_LIMITS = { title: 60, hint: 200 } as const

export interface SectionDraft {
  /** Stable React key (the section key, or a temporary one for new rows). */
  id: string
  /** The section's key; null for a new section. */
  key: string | null
  title: string
  hint: string
  /** Proposals with text in this section (the removal warning's N). */
  proposalCount: number
}

export type SectionField = 'title' | 'hint'

export interface TemplateErrors {
  rows: Record<string, Partial<Record<SectionField, string>>>
  form?: string
}

let nextId = 0

export function toSectionDrafts(sections: readonly ProposalTemplateSection[]): SectionDraft[] {
  return [...sections]
    .sort((a, b) => a.position - b.position)
    .map((section) => ({
      id: section.key,
      key: section.key,
      title: section.title,
      hint: section.hint,
      proposalCount: section.proposal_count,
    }))
}

export function emptySection(): SectionDraft {
  nextId += 1
  return { id: `new-section-${nextId}`, key: null, title: '', hint: '', proposalCount: 0 }
}

/** A removed section put back in the form (Restore): its text comes back with it on Save. */
export function restoredSection(section: RemovedTemplateSection): SectionDraft {
  return {
    id: section.key,
    key: section.key,
    title: section.title,
    hint: section.hint,
    proposalCount: section.proposal_count,
  }
}

const LINE_BREAK = /[\r\n\u2028\u2029]/

export function validateTemplate(drafts: readonly SectionDraft[]): TemplateErrors {
  const rows: TemplateErrors['rows'] = {}
  const uses = new Map<string, number>()
  for (const draft of drafts) {
    const title = draft.title.trim().toLowerCase()
    if (title) uses.set(title, (uses.get(title) ?? 0) + 1)
  }
  for (const draft of drafts) {
    const errors: Partial<Record<SectionField, string>> = {}
    const title = draft.title.trim()
    if (!title) errors.title = 'Give the section a title.'
    else if (title.length > SECTION_LIMITS.title) {
      errors.title = `At most ${SECTION_LIMITS.title} characters.`
    } else if (LINE_BREAK.test(title)) errors.title = 'Keep it to one line.'
    else if ((uses.get(title.toLowerCase()) ?? 0) > 1) {
      errors.title = `Another section is called “${title}”.`
    }
    const hint = draft.hint.trim()
    if (hint.length > SECTION_LIMITS.hint) {
      errors.hint = `Keep it to one line (${SECTION_LIMITS.hint} characters).`
    } else if (LINE_BREAK.test(hint)) errors.hint = 'Keep it to one line.'
    if (Object.keys(errors).length > 0) rows[draft.id] = errors
  }
  const form =
    drafts.length < MIN_SECTIONS
      ? 'A proposal needs at least one section.'
      : drafts.length > MAX_SECTIONS
        ? `A proposal has at most ${MAX_SECTIONS} sections.`
        : undefined
  return { rows, form }
}

export function hasTemplateErrors(errors: TemplateErrors): boolean {
  return Boolean(errors.form) || Object.keys(errors.rows).length > 0
}

export function toTemplateUpdate(drafts: readonly SectionDraft[]): ProposalTemplateUpdate {
  return {
    sections: drafts.map((draft) => ({
      ...(draft.key ? { key: draft.key } : {}),
      title: draft.title.trim(),
      hint: draft.hint.trim(),
    })),
  }
}

/** True when saving would change something (order included). */
export function isTemplateDirty(
  drafts: readonly SectionDraft[],
  template: ProposalTemplate | undefined,
): boolean {
  if (!template) return false
  return (
    JSON.stringify(toTemplateUpdate(drafts)) !==
    JSON.stringify(toTemplateUpdate(toSectionDrafts(template.sections)))
  )
}

export const moveSection = moveItem<SectionDraft>

/** Maps a 422 from `replace_proposal_template` (`loc: ["body", "sections", 2, "title"]`). */
export function serverTemplateErrors(
  drafts: readonly SectionDraft[],
  problems: Pick<FieldError, 'loc' | 'msg'>[],
): TemplateErrors {
  const result: TemplateErrors = { rows: {} }
  for (const problem of problems) {
    const index = problem.loc[2]
    const field = problem.loc[3] === 'hint' ? 'hint' : 'title'
    const draft = typeof index === 'number' ? drafts[index] : undefined
    const message = problem.msg || 'Check this value.'
    if (!draft || problem.loc[3] === 'key') {
      result.form ??= message
      continue
    }
    result.rows[draft.id] = { ...result.rows[draft.id], [field]: message }
  }
  return result
}

/** "Text in 3 proposals", or why a removed section with no text was kept. */
export function removedSectionNote(section: Pick<RemovedTemplateSection, 'proposal_count'>) {
  const count = section.proposal_count
  if (count === 0) return 'Kept for its comments and suggestions'
  return `Text in ${count} ${count === 1 ? 'proposal' : 'proposals'}`
}
