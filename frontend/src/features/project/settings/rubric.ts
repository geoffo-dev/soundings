import type { FieldError, RubricCriterion, RubricUpdate } from '@/api/types'

/**
 * The rubric editor's form model and rules (contract §3.1): 3–6 criteria with
 * unique names (case-insensitive), weights 0.01–10 in steps of 0.01, one-line
 * descriptions, optional guidance per score. Saving replaces the whole rubric.
 */
export const MIN_CRITERIA = 3
export const MAX_CRITERIA = 6
export const LIMITS = { name: 40, description: 200, guidance: 200 } as const
/** The guidance the editor asks for; other scores' hints are kept as they are. */
export const GUIDANCE_SCORES = ['1', '3', '5'] as const
export type GuidanceScore = '1' | '2' | '3' | '4' | '5'

export interface CriterionDraft {
  /** Stable React key (the id, or a temporary one for new rows). */
  key: string
  /** Existing criterion to update; null adds a new one. */
  id: string | null
  name: string
  description: string
  /** As typed, so "1." or "" can be corrected in place. */
  weight: string
  inverted: boolean
  guidance: Partial<Record<GuidanceScore, string>>
}

export type CriterionField = 'name' | 'description' | 'weight' | `guidance.${GuidanceScore}`
export type RowErrors = Partial<Record<CriterionField, string>>

export interface RubricErrors {
  rows: Record<string, RowErrors>
  /** About the rubric as a whole (too few or too many criteria). */
  form?: string
}

let nextKey = 0
const newKey = () => `new-${++nextKey}`

export function toDrafts(rubric: RubricCriterion[]): CriterionDraft[] {
  return [...rubric]
    .sort((a, b) => a.position - b.position)
    .map((criterion) => ({
      key: criterion.id,
      id: criterion.id,
      name: criterion.name,
      description: criterion.description,
      weight: formatWeight(criterion.weight),
      inverted: criterion.inverted,
      guidance: { ...criterion.guidance },
    }))
}

export function emptyCriterion(): CriterionDraft {
  return {
    key: newKey(),
    id: null,
    name: '',
    description: '',
    weight: '1',
    inverted: false,
    guidance: {},
  }
}

export function formatWeight(weight: number): string {
  return String(Math.round(weight * 100) / 100)
}

/** 0.01–10, at most two decimals; null if the text isn't a valid weight. */
export function parseWeight(text: string): number | null {
  const trimmed = text.trim().replace(',', '.')
  if (!/^\d+(\.\d{1,2})?$|^\.\d{1,2}$/.test(trimmed)) return null
  const value = Number(trimmed)
  return value >= 0.01 && value <= 10 ? value : null
}

export function validateRubric(drafts: CriterionDraft[]): RubricErrors {
  const rows: Record<string, RowErrors> = {}
  // Names are unique ignoring case; both rows of a clash are marked, so the one you edit shows it.
  const uses = new Map<string, number>()
  for (const draft of drafts) {
    const name = draft.name.trim().toLowerCase()
    if (name) uses.set(name, (uses.get(name) ?? 0) + 1)
  }
  for (const draft of drafts) {
    const errors: RowErrors = {}
    const name = draft.name.trim()
    if (!name) errors.name = 'Give the criterion a name.'
    else if (name.length > LIMITS.name) errors.name = `At most ${LIMITS.name} characters.`
    else if ((uses.get(name.toLowerCase()) ?? 0) > 1) {
      errors.name = `Another criterion is called “${name}”.`
    }
    if (draft.description.trim().length > LIMITS.description) {
      errors.description = `Keep it to one line (${LIMITS.description} characters).`
    }
    if (parseWeight(draft.weight) === null) {
      errors.weight = 'Use a number from 0.01 to 10.'
    }
    for (const score of Object.keys(draft.guidance) as GuidanceScore[]) {
      if ((draft.guidance[score] ?? '').trim().length > LIMITS.guidance) {
        errors[`guidance.${score}`] = `At most ${LIMITS.guidance} characters.`
      }
    }
    if (Object.keys(errors).length > 0) rows[draft.key] = errors
  }
  const form =
    drafts.length < MIN_CRITERIA
      ? `A rubric needs at least ${MIN_CRITERIA} criteria.`
      : drafts.length > MAX_CRITERIA
        ? `A rubric has at most ${MAX_CRITERIA} criteria.`
        : undefined
  return { rows, form }
}

export function hasErrors(errors: RubricErrors): boolean {
  return Boolean(errors.form) || Object.keys(errors.rows).length > 0
}

/** The request body; call only when `validateRubric` found nothing. */
export function toRubricUpdate(drafts: CriterionDraft[]): RubricUpdate {
  return {
    criteria: drafts.map((draft) => {
      const guidance: Partial<Record<GuidanceScore, string>> = {}
      for (const [score, text] of Object.entries(draft.guidance)) {
        const trimmed = text.trim()
        if (trimmed) guidance[score as GuidanceScore] = trimmed
      }
      return {
        id: draft.id,
        name: draft.name.trim(),
        description: draft.description.trim(),
        weight: parseWeight(draft.weight) ?? 1,
        inverted: draft.inverted,
        guidance,
      }
    }),
  }
}

/** True when saving would change something (order included). */
export function isRubricDirty(drafts: CriterionDraft[], rubric: RubricCriterion[]): boolean {
  const saved = JSON.stringify(toRubricUpdate(toDrafts(rubric)))
  return JSON.stringify(toRubricUpdate(drafts)) !== saved
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || to < 0 || to >= items.length) return items
  const next = [...items]
  const [item] = next.splice(from, 1)
  if (item !== undefined) next.splice(to, 0, item)
  return next
}

/**
 * Maps a 422 from `replace_rubric` (`loc: ["body", "criteria", 2, "name"]`)
 * onto the rows, so server-side errors show next to the right field.
 */
export function serverRubricErrors(
  drafts: CriterionDraft[],
  problemErrors: Pick<FieldError, 'loc' | 'msg'>[],
): RubricErrors {
  const result: RubricErrors = { rows: {} }
  for (const entry of problemErrors) {
    const loc = entry.loc
    const message = entry.msg === '' ? 'Check this value.' : entry.msg
    const index = loc[2]
    const field = loc[3]
    const draft = typeof index === 'number' ? drafts[index] : undefined
    if (!draft) {
      result.form ??= message
      continue
    }
    const key: CriterionField =
      field === 'guidance' && loc[4] !== undefined
        ? (`guidance.${String(loc[4])}` as CriterionField)
        : field === 'description' || field === 'weight'
          ? field
          : 'name'
    result.rows[draft.key] = { ...result.rows[draft.key], [key]: message }
  }
  return result
}

/** Each criterion's share of the aggregate in whole percent (empty while any weight is invalid). */
export function weightShares(drafts: CriterionDraft[]): Map<string, number> {
  const weights = drafts.map((draft) => parseWeight(draft.weight))
  if (weights.some((weight) => weight === null)) return new Map()
  const total = weights.reduce<number>((sum, weight) => sum + (weight ?? 0), 0)
  return new Map(
    drafts.map((draft, index) => [draft.key, Math.round(((weights[index] ?? 0) / total) * 100)]),
  )
}
