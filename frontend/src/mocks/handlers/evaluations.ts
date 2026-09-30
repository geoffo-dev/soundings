import type { Recommendation } from '@/api/types'

import { ID_KIND, newId, type MockScore } from '@/mocks/db'
import {
  activeCriteria,
  evaluationOf,
  evaluationOpen,
  evaluationOut,
  isAssigned,
  isPendingEvaluator,
  myEvaluation,
  projectOf,
  rowsForIdea,
} from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  failValidation,
  forbidden,
  json,
  readJson,
  route,
  type FieldIssue,
} from '@/mocks/http'

import { emit, ensureIdeaWritable, standing, viewIdea } from '@/mocks/handlers/common'

const RECOMMENDATIONS: Recommendation[] = ['go', 'maybe', 'no']

export const evaluationHandlers = [
  route('get', '/ideas/:idea/evaluations', (ctx) => {
    const idea = viewIdea(ctx)
    if (isPendingEvaluator(ctx.db, idea, ctx.user.id)) return { items: [], score_hidden: true }
    const items = rowsForIdea(ctx.db.evaluations, idea.id)
      .filter((e) => e.status === 'submitted')
      .sort((a, b) => (a.submitted_at ?? '').localeCompare(b.submitted_at ?? ''))
      .map((e) => evaluationOut(ctx.db, e))
    return { items, score_hidden: false }
  }),

  route('get', '/ideas/:idea/evaluations/me', (ctx) =>
    json(myEvaluation(ctx.db, viewIdea(ctx), ctx.user)),
  ),

  route('put', '/ideas/:idea/evaluations/me', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['scores', 'recommendation', 'comment', 'submit'])
    const rawScores = body.scores ?? []
    if (!Array.isArray(rawScores)) {
      failValidation([
        { loc: ['body', 'scores'], msg: 'Input should be a valid list', type: 'list_type' },
      ])
    }
    const scores: MockScore[] = rawScores.map((raw: unknown, index) => {
      const item = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
      const score = item.score ?? null
      if (
        score !== null &&
        (!Number.isInteger(score) || (score as number) < 1 || (score as number) > 5)
      ) {
        failValidation([
          {
            loc: ['body', 'scores', index, 'score'],
            msg: 'Scores are 1 to 5',
            type: 'less_than_equal',
          },
        ])
      }
      if (typeof item.criterion_id !== 'string') {
        failValidation([
          {
            loc: ['body', 'scores', index, 'criterion_id'],
            msg: 'Field required',
            type: 'missing',
          },
        ])
      }
      const comment = typeof item.comment === 'string' ? item.comment.trim() : ''
      if (comment.length > 1000) {
        failValidation([
          {
            loc: ['body', 'scores', index, 'comment'],
            msg: 'At most 1000 characters',
            type: 'string_too_long',
          },
        ])
      }
      return {
        criterion_id: item.criterion_id.toLowerCase(),
        score: score as number | null,
        comment,
      }
    })
    const recommendation = (body.recommendation ?? null) as Recommendation | null
    if (recommendation !== null && !RECOMMENDATIONS.includes(recommendation)) {
      failValidation([
        {
          loc: ['body', 'recommendation'],
          msg: "Input should be 'go', 'maybe' or 'no'",
          type: 'enum',
        },
      ])
    }
    const comment = typeof body.comment === 'string' ? body.comment.trim() : ''
    if (comment.length > 4000) {
      failValidation([
        { loc: ['body', 'comment'], msg: 'At most 4000 characters', type: 'string_too_long' },
      ])
    }
    const submit = body.submit === true

    const idea = viewIdea(ctx)
    const who = standing(ctx.db, projectOf(ctx.db, idea), ctx.user, idea)
    if (!isAssigned(ctx.db, idea.id, ctx.user.id) || !who.memberish) {
      forbidden('forbidden', 'You are not an evaluator of this idea.')
    }
    const criteria = activeCriteria(ctx.db, idea.project_id)
    for (const [index, score] of scores.entries()) {
      if (!criteria.some((c) => c.id === score.criterion_id)) {
        failValidation(
          [
            {
              loc: ['body', 'scores', index, 'criterion_id'],
              msg: 'Not in the active rubric',
              type: 'unknown_criterion',
            },
          ],
          'unknown_criterion',
        )
      }
    }
    if (submit) {
      const gaps: FieldIssue[] = criteria
        .filter((c) => !scores.some((s) => s.criterion_id === c.id && s.score !== null))
        .map((c) => ({ loc: ['body', 'scores', c.id], msg: `Score ${c.name}`, type: 'missing' }))
      if (!recommendation) {
        gaps.push({
          loc: ['body', 'recommendation'],
          msg: 'Choose a recommendation',
          type: 'missing',
        })
      }
      if (gaps.length) failValidation(gaps, 'evaluation_incomplete')
    }
    ensureIdeaWritable(ctx.db, idea)
    if (!evaluationOpen(idea)) conflict('evaluation_closed')
    const now = new Date().toISOString()
    let evaluation = evaluationOf(ctx.db, idea.id, ctx.user.id)
    if (evaluation?.status === 'submitted' && !submit) conflict('evaluation_already_submitted')
    if (!evaluation) {
      evaluation = {
        id: newId(ctx.db, ID_KIND.evaluation),
        idea_id: idea.id,
        evaluator_id: ctx.user.id,
        status: 'draft',
        scores: [],
        recommendation: null,
        comment: '',
        submitted_at: null,
        edited_at: null,
        updated_at: now,
        include_in_aggregate: true,
      }
      ctx.db.evaluations.push(evaluation)
    }
    const wasSubmitted = evaluation.status === 'submitted'
    evaluation.scores = scores
    evaluation.recommendation = recommendation
    evaluation.comment = comment
    evaluation.updated_at = now
    if (submit) {
      if (wasSubmitted) evaluation.edited_at = now
      else {
        evaluation.status = 'submitted'
        evaluation.submitted_at = now
        emit(ctx.db, idea, 'evaluation_submitted', ctx.user.id, { evaluator_id: ctx.user.id })
      }
    }
    return myEvaluation(ctx.db, idea, ctx.user)
  }),
]
