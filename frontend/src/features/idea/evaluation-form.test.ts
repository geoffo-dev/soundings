import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'
import type { MyEvaluation, RubricCriterion } from '@/api/types'

import {
  describeMissing,
  formFromEvaluation,
  formToBody,
  guidanceFor,
  hasErrors,
  incompleteErrors,
  missingForSubmit,
  NO_ERRORS,
  remainingErrors,
  sameForm,
  scoredCount,
  type EvaluationForm,
} from './evaluation-form'

const criterion = (
  id: string,
  name: string,
  extra: Partial<RubricCriterion> = {},
): RubricCriterion => ({
  id,
  name,
  description: `${name} description`,
  weight: 1,
  inverted: false,
  guidance: {},
  position: 0,
  ...extra,
})

const RUBRIC = [
  criterion('c-value', 'Value', { position: 0 }),
  criterion('c-effort', 'Effort', { position: 1, inverted: true }),
  criterion('c-fit', 'Strategic fit', { position: 2 }),
]

const saved = (patch: Partial<MyEvaluation> = {}): MyEvaluation => ({
  idea_id: 'idea',
  state: 'draft',
  editable: true,
  due_at: null,
  submitted_at: null,
  updated_at: '2026-09-30T10:42:00Z',
  recommendation: null,
  comment: '',
  scores: [],
  ...patch,
})

const filled = (): EvaluationForm => ({
  criteria: {
    'c-value': { score: 4, comment: '' },
    'c-effort': { score: 2, comment: ' cheap ' },
    'c-fit': { score: 5, comment: '' },
  },
  recommendation: 'go',
  comment: '  Ship it  ',
})

describe('formFromEvaluation', () => {
  it('starts empty for every active criterion when nothing was saved', () => {
    const form = formFromEvaluation(RUBRIC, null)
    expect(Object.keys(form.criteria)).toEqual(['c-value', 'c-effort', 'c-fit'])
    expect(Object.values(form.criteria).every((entry) => entry.score === null)).toBe(true)
    expect(form.recommendation).toBeNull()
    expect(scoredCount(RUBRIC, form)).toBe(0)
  })

  it('restores a saved draft and ignores scores for criteria no longer in the rubric', () => {
    const form = formFromEvaluation(
      RUBRIC,
      saved({
        recommendation: 'maybe',
        comment: 'Needs data',
        scores: [
          { criterion_id: 'c-value', score: 3, comment: 'ok' },
          { criterion_id: 'c-archived', score: 5, comment: '' },
          { criterion_id: 'c-fit', score: null, comment: 'unsure' },
        ],
      }),
    )
    expect(form.criteria['c-value']).toEqual({ score: 3, comment: 'ok' })
    expect(form.criteria['c-fit']).toEqual({ score: null, comment: 'unsure' })
    expect(form.criteria).not.toHaveProperty('c-archived')
    expect(form.recommendation).toBe('maybe')
    expect(scoredCount(RUBRIC, form)).toBe(1)
  })
})

describe('formToBody', () => {
  it('sends every active criterion in rubric order, unscored ones as null, comments trimmed', () => {
    const form = formFromEvaluation(RUBRIC, null)
    form.criteria['c-effort'] = { score: 2, comment: '  cheap  ' }
    expect(formToBody(RUBRIC, form, false)).toEqual({
      scores: [
        { criterion_id: 'c-value', score: null, comment: '' },
        { criterion_id: 'c-effort', score: 2, comment: 'cheap' },
        { criterion_id: 'c-fit', score: null, comment: '' },
      ],
      recommendation: null,
      comment: '',
      submit: false,
    })
  })

  it('marks a submission', () => {
    const body = formToBody(RUBRIC, filled(), true)
    expect(body.submit).toBe(true)
    expect(body.comment).toBe('Ship it')
    expect(body.recommendation).toBe('go')
  })
})

describe('submit validation', () => {
  it('needs a score for every criterion and a recommendation', () => {
    const missing = missingForSubmit(RUBRIC, formFromEvaluation(RUBRIC, null))
    expect(missing).toEqual({ criteria: ['c-value', 'c-effort', 'c-fit'], recommendation: true })
    expect(hasErrors(missing)).toBe(true)
    expect(describeMissing(RUBRIC, missing)).toBe(
      '3 criteria need a score, and the overall recommendation is missing',
    )
  })

  it('names a single gap', () => {
    const form = filled()
    form.criteria['c-effort'] = { score: null, comment: '' }
    const missing = missingForSubmit(RUBRIC, form)
    expect(missing).toEqual({ criteria: ['c-effort'], recommendation: false })
    expect(describeMissing(RUBRIC, missing)).toBe('Effort needs a score')
  })

  it('passes a complete form', () => {
    expect(missingForSubmit(RUBRIC, filled())).toEqual(NO_ERRORS)
    expect(hasErrors(missingForSubmit(RUBRIC, filled()))).toBe(false)
  })

  it('clears errors as they are fixed, keeping the rest', () => {
    const empty = formFromEvaluation(RUBRIC, null)
    const errors = missingForSubmit(RUBRIC, empty)
    const next: EvaluationForm = {
      ...empty,
      criteria: { ...empty.criteria, 'c-value': { score: 4, comment: '' } },
    }
    expect(remainingErrors(errors, RUBRIC, next)).toEqual({
      criteria: ['c-effort', 'c-fit'],
      recommendation: true,
    })
    // Errors that weren't shown are never added by typing.
    expect(remainingErrors(NO_ERRORS, RUBRIC, next)).toEqual(NO_ERRORS)
  })

  it('reads the gaps of a 422 evaluation_incomplete, in rubric order', () => {
    const error = new ApiError({
      status: 422,
      code: 'evaluation_incomplete',
      title: 'Unprocessable Content',
      problem: {
        code: 'evaluation_incomplete',
        errors: [
          { loc: ['body', 'recommendation'], msg: 'Choose a recommendation.', type: 'missing' },
          { loc: ['body', 'scores', 'C-FIT'], msg: 'Score this criterion.', type: 'missing' },
          { loc: ['body', 'scores', 'c-value'], msg: 'Score this criterion.', type: 'missing' },
          { loc: ['body', 'scores', 'unknown'], msg: 'Score this criterion.', type: 'missing' },
        ],
      },
    })
    expect(incompleteErrors(error, RUBRIC)).toEqual({
      criteria: ['c-value', 'c-fit'],
      recommendation: true,
    })
  })

  it('ignores other errors', () => {
    const conflict = new ApiError({ status: 409, code: 'evaluation_closed', title: 'Conflict' })
    expect(incompleteErrors(conflict, RUBRIC)).toBeNull()
    expect(incompleteErrors(new Error('boom'), RUBRIC)).toBeNull()
  })
})

describe('sameForm', () => {
  it('compares scores, recommendation and trimmed comments', () => {
    const a = filled()
    const b = filled()
    b.comment = 'Ship it'
    b.criteria['c-effort'] = { score: 2, comment: 'cheap' }
    expect(sameForm(a, b)).toBe(true)
    b.criteria['c-fit'] = { score: 4, comment: '' }
    expect(sameForm(a, b)).toBe(false)
    expect(sameForm(filled(), { ...filled(), recommendation: 'no' })).toBe(false)
  })
})

describe('guidanceFor', () => {
  it('uses the rubric text and says which scores lie in between', () => {
    const guidance = guidanceFor({
      guidance: { '1': 'Little benefit.', '3': 'Useful.', '5': 'Major benefit.' },
      inverted: false,
    })
    expect(guidance[1]).toBe('1 · Little benefit.')
    expect(guidance[2]).toBe('2 · Between 1 and 3')
    expect(guidance[4]).toBe('4 · Between 3 and 5')
    expect(guidance[5]).toBe('5 · Major benefit.')
  })

  it('falls back to neutral wording, without "strong" for inverted criteria', () => {
    expect(guidanceFor({ guidance: {}, inverted: false })[4]).toBe('4 · Strong — a convincing case')
    expect(guidanceFor({ guidance: {}, inverted: true })[4]).toBe('4 · High')
  })
})
