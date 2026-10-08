import type {
  DefaultChecklistItem,
  FieldError,
  RemovedResearchItem,
  ResearchChecklistItem,
  ResearchSettings,
  ResearchSettingsUpdate,
  ResearchStep,
} from '@/api/types'

import { moveItem } from './rubric'

/**
 * The research settings form (contract-phase8 §3.3): the step and, while it is on,
 * 1–10 checklist items (title 1–80, one line, unique ignoring case; hint up to 200;
 * Required on by default). One Save sends both. With the step off the checklist isn't
 * sent at all (`items` is ignored then, and kept as it is).
 */
export const MIN_ITEMS = 1
export const MAX_ITEMS = 10
export const ITEM_LIMITS = { title: 80, hint: 200 } as const

export interface ItemDraft {
  /** Stable React key (the item id, or a temporary one for new rows). */
  key: string
  /** The item's id; null for a new item. */
  id: string | null
  title: string
  hint: string
  required: boolean
}

export type ItemField = 'title' | 'hint'

export interface ChecklistErrors {
  rows: Record<string, Partial<Record<ItemField, string>>>
  form?: string
}

let nextKey = 0
const newKey = () => {
  nextKey += 1
  return `new-item-${nextKey}`
}

export function toItemDrafts(items: readonly ResearchChecklistItem[]): ItemDraft[] {
  return [...items]
    .sort((a, b) => a.position - b.position)
    .map((item) => ({
      key: item.id,
      id: item.id,
      title: item.title,
      hint: item.hint,
      required: item.required,
    }))
}

/** The default checklist as new rows (offered when the step is turned on with none). */
export function defaultItemDrafts(defaults: readonly DefaultChecklistItem[]): ItemDraft[] {
  return defaults.map((item) => ({ key: newKey(), id: null, ...item }))
}

export function emptyItem(): ItemDraft {
  return { key: newKey(), id: null, title: '', hint: '', required: true }
}

export function restoredItem(item: RemovedResearchItem): ItemDraft {
  return { key: item.id, id: item.id, title: item.title, hint: item.hint, required: item.required }
}

const LINE_BREAK = /[\r\n\u2028\u2029]/

export function validateChecklist(step: ResearchStep, drafts: readonly ItemDraft[]) {
  const errors: ChecklistErrors = { rows: {} }
  // While the step is off nothing is sent for the checklist.
  if (step === 'off') return errors
  const uses = new Map<string, number>()
  for (const draft of drafts) {
    const title = draft.title.trim().toLowerCase()
    if (title) uses.set(title, (uses.get(title) ?? 0) + 1)
  }
  for (const draft of drafts) {
    const row: Partial<Record<ItemField, string>> = {}
    const title = draft.title.trim()
    if (!title) row.title = 'Give the item a title.'
    else if (title.length > ITEM_LIMITS.title)
      row.title = `At most ${ITEM_LIMITS.title} characters.`
    else if (LINE_BREAK.test(title)) row.title = 'Keep it to one line.'
    else if ((uses.get(title.toLowerCase()) ?? 0) > 1) {
      row.title = `Another item is called “${title}”.`
    }
    const hint = draft.hint.trim()
    if (hint.length > ITEM_LIMITS.hint) {
      row.hint = `Keep it to one line (${ITEM_LIMITS.hint} characters).`
    } else if (LINE_BREAK.test(hint)) row.hint = 'Keep it to one line.'
    if (Object.keys(row).length > 0) errors.rows[draft.key] = row
  }
  if (drafts.length < MIN_ITEMS) errors.form = 'The checklist needs at least one item.'
  else if (drafts.length > MAX_ITEMS) errors.form = `The checklist has at most ${MAX_ITEMS} items.`
  return errors
}

export function hasChecklistErrors(errors: ChecklistErrors): boolean {
  return Boolean(errors.form) || Object.keys(errors.rows).length > 0
}

export function toResearchUpdate(
  step: ResearchStep,
  drafts: readonly ItemDraft[],
): ResearchSettingsUpdate {
  if (step === 'off') return { step, items: [] }
  return {
    step,
    items: drafts.map((draft) => ({
      ...(draft.id ? { id: draft.id } : {}),
      title: draft.title.trim(),
      hint: draft.hint.trim(),
      required: draft.required,
    })),
  }
}

/** True when saving would change something: the step, or (while on) the checklist. */
export function isResearchDirty(
  step: ResearchStep,
  drafts: readonly ItemDraft[],
  settings: ResearchSettings | undefined,
): boolean {
  if (!settings) return false
  if (step !== settings.step) return true
  if (step === 'off') return false
  return (
    JSON.stringify(toResearchUpdate(step, drafts)) !==
    JSON.stringify(toResearchUpdate(step, toItemDrafts(settings.items)))
  )
}

export const moveChecklistItem = moveItem<ItemDraft>

/** Maps a 422 from `replace_research_settings` (`loc: ["body", "items", 1, "title"]`). */
export function serverChecklistErrors(
  drafts: readonly ItemDraft[],
  problems: Pick<FieldError, 'loc' | 'msg'>[],
): ChecklistErrors {
  const result: ChecklistErrors = { rows: {} }
  for (const problem of problems) {
    const index = problem.loc[2]
    const draft = typeof index === 'number' ? drafts[index] : undefined
    const message = problem.msg || 'Check this value.'
    if (!draft || (problem.loc[3] !== 'title' && problem.loc[3] !== 'hint')) {
      result.form ??= message
      continue
    }
    const field: ItemField = problem.loc[3] === 'hint' ? 'hint' : 'title'
    result.rows[draft.key] = { ...result.rows[draft.key], [field]: message }
  }
  return result
}

/** "Answered on 4 ideas" for a removed item. */
export function removedItemNote(item: Pick<RemovedResearchItem, 'answer_count'>): string {
  const count = item.answer_count
  return `Answered on ${count} ${count === 1 ? 'idea' : 'ideas'}`
}
