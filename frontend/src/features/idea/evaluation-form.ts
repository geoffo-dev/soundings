/**
 * The evaluate sheet's form model, kept free of React so the rules are easy
 * to test: one entry per active rubric criterion (score 1–5 and an optional
 * comment), the overall recommendation and an optional overall comment.
 *
 * Drafts may leave anything out; submitting needs every active criterion
 * scored and a recommendation (contract §3.6, 422 `evaluation_incomplete`).
 */
import { isApiError } from '@/api/errors'
import type { MyEvaluation, MyEvaluationIn, Recommendation, RubricCriterion } from '@/api/types'

export type Score = 1 | 2 | 3 | 4 | 5

export const SCORES: readonly Score[] = [1, 2, 3, 4, 5]
export const RECOMMENDATIONS: readonly Recommendation[] = ['go', 'maybe', 'no']

/** Server limits (mirrored so the fields stop at the limit instead of failing). */
export const COMMENT_LIMITS = { criterion: 1000, overall: 4000 } as const

export interface CriterionEntry {
  score: Score | null
  comment: string
}

export interface EvaluationForm {
  /** By criterion id. Only active criteria are kept. */
  criteria: Record<string, CriterionEntry>
  recommendation: Recommendation | null
  comment: string
}

export interface FormErrors {
  /** Criterion ids that still need a score. */
  criteria: string[]
  recommendation: boolean
}

export const NO_ERRORS: FormErrors = { criteria: [], recommendation: false }

export function hasErrors(errors: FormErrors): boolean {
  return errors.criteria.length > 0 || errors.recommendation
}

function toScore(value: number | null | undefined): Score | null {
  return typeof value === 'number' && SCORES.includes(value as Score) ? (value as Score) : null
}

/** The form for the active rubric, filled from what you saved before (if anything). */
export function formFromEvaluation(
  rubric: readonly RubricCriterion[],
  saved: MyEvaluation | null | undefined,
): EvaluationForm {
  const criteria: Record<string, CriterionEntry> = {}
  for (const criterion of rubric) {
    const previous = saved?.scores.find((score) => score.criterion_id === criterion.id)
    criteria[criterion.id] = { score: toScore(previous?.score), comment: previous?.comment ?? '' }
  }
  return {
    criteria,
    recommendation: saved?.recommendation ?? null,
    comment: saved?.comment ?? '',
  }
}

/** The PUT body: every active criterion in rubric order (unscored ones as `null` in a draft). */
export function formToBody(
  rubric: readonly RubricCriterion[],
  form: EvaluationForm,
  submit: boolean,
): MyEvaluationIn {
  return {
    scores: rubric.map((criterion) => {
      const entry = form.criteria[criterion.id]
      return {
        criterion_id: criterion.id,
        score: entry?.score ?? null,
        comment: entry?.comment.trim() ?? '',
      }
    }),
    recommendation: form.recommendation,
    comment: form.comment.trim(),
    submit,
  }
}

/** How many active criteria have a score. */
export function scoredCount(rubric: readonly RubricCriterion[], form: EvaluationForm): number {
  return rubric.filter((criterion) => form.criteria[criterion.id]?.score != null).length
}

/** What is still missing before you can submit, in rubric order. */
export function missingForSubmit(
  rubric: readonly RubricCriterion[],
  form: EvaluationForm,
): FormErrors {
  return {
    criteria: rubric
      .filter((criterion) => form.criteria[criterion.id]?.score == null)
      .map((criterion) => criterion.id),
    recommendation: form.recommendation === null,
  }
}

/** Errors that are no longer true once the user fixed them (keeps the others visible). */
export function remainingErrors(
  errors: FormErrors,
  rubric: readonly RubricCriterion[],
  form: EvaluationForm,
): FormErrors {
  const missing = missingForSubmit(rubric, form)
  return {
    criteria: errors.criteria.filter((id) => missing.criteria.includes(id)),
    recommendation: errors.recommendation && missing.recommendation,
  }
}

/** True when two forms would save the same thing (comments compared trimmed). */
export function sameForm(a: EvaluationForm, b: EvaluationForm): boolean {
  if (a.recommendation !== b.recommendation || a.comment.trim() !== b.comment.trim()) return false
  const ids = new Set([...Object.keys(a.criteria), ...Object.keys(b.criteria)])
  for (const id of ids) {
    const x = a.criteria[id]
    const y = b.criteria[id]
    if ((x?.score ?? null) !== (y?.score ?? null)) return false
    if ((x?.comment.trim() ?? '') !== (y?.comment.trim() ?? '')) return false
  }
  return true
}

/**
 * The gaps named by a 422 `evaluation_incomplete` (one `errors[]` entry per
 * gap: `["body", "scores", "<criterion id>"]` or `["body", "recommendation"]`).
 * Null when the error is something else.
 */
export function incompleteErrors(
  error: unknown,
  rubric: readonly RubricCriterion[],
): FormErrors | null {
  if (!isApiError(error) || error.code !== 'evaluation_incomplete') return null
  const ids = new Set(rubric.map((criterion) => criterion.id))
  const criteria: string[] = []
  let recommendation = false
  for (const entry of error.problem?.errors ?? []) {
    const loc = entry.loc
    if (loc[1] === 'recommendation') recommendation = true
    else if (loc[1] === 'scores') {
      const id = String(loc[2] ?? '').toLowerCase()
      if (ids.has(id)) criteria.push(id)
    }
  }
  // Keep rubric order so focus goes to the first gap on the page.
  return {
    criteria: rubric.map((c) => c.id).filter((id) => criteria.includes(id)),
    recommendation,
  }
}

/** "Value and Effort need a score" — for the live region and the footer. */
export function describeMissing(rubric: readonly RubricCriterion[], errors: FormErrors): string {
  const names = rubric.filter((c) => errors.criteria.includes(c.id)).map((c) => c.name)
  const parts: string[] = []
  if (names.length === 1) parts.push(`${names[0] ?? ''} needs a score`)
  else if (names.length > 1) parts.push(`${names.length} criteria need a score`)
  // The field itself says "Choose Go, Maybe or No": name what's missing instead.
  if (errors.recommendation) parts.push('the overall recommendation is missing')
  const text = parts.join(', and ')
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : ''
}

const DEFAULT_GUIDANCE: Record<Score, string> = {
  1: 'Very weak — clear problems',
  2: 'Weak — more concerns than strengths',
  3: 'Adequate — no strong case either way',
  4: 'Strong — a convincing case',
  5: 'Exceptional — among the best we have seen',
}

/** For inverted criteria (Effort, Risk) a high score is bad, so "strong" would mislead. */
const DEFAULT_INVERTED_GUIDANCE: Record<Score, string> = {
  1: 'Very low',
  2: 'Low',
  3: 'Moderate',
  4: 'High',
  5: 'Very high',
}

/**
 * The hint for each score, "4 · A useful benefit…". Rubrics often describe
 * only 1, 3 and 5; the scores between say so ("Between 3 and 5") instead of
 * borrowing generic text that may contradict the rubric.
 */
export function guidanceFor(
  criterion: Pick<RubricCriterion, 'guidance' | 'inverted'>,
): Record<Score, string> {
  const given = new Map<Score, string>()
  for (const score of SCORES) {
    const text = criterion.guidance[String(score)]?.trim()
    if (text) given.set(score, text)
  }
  const fallback = criterion.inverted ? DEFAULT_INVERTED_GUIDANCE : DEFAULT_GUIDANCE
  const out = {} as Record<Score, string>
  for (const score of SCORES) {
    const text = given.get(score)
    if (text) {
      out[score] = `${score} · ${text}`
      continue
    }
    const lower = SCORES.filter((s) => s < score && given.has(s)).at(-1)
    const higher = SCORES.find((s) => s > score && given.has(s))
    out[score] =
      lower !== undefined && higher !== undefined
        ? `${score} · Between ${lower} and ${higher}`
        : `${score} · ${fallback[score]}`
  }
  return out
}

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  go: 'Go',
  maybe: 'Maybe',
  no: 'No',
}

export const RECOMMENDATION_HINTS: Record<Recommendation, string> = {
  go: 'Take it forward',
  maybe: 'Promising, but needs more work',
  no: 'Don’t pursue this now',
}
