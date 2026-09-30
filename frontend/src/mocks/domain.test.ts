import { beforeEach, describe, expect, it } from 'vitest'

import { createDb, ID_KIND, mockId, USERS, type MockDb, type MockIdea } from '@/mocks/db'
import {
  board,
  computeAggregate,
  findIdea,
  findProjectBySlug,
  findUser,
  ideaDetail,
  ideaPermissions,
  ideaSummary,
  isPendingEvaluator,
  queryProjectIdeas,
  round1,
} from '@/mocks/domain'

let db: MockDb

beforeEach(() => {
  db = createDb({ now: Date.parse('2026-09-30T12:00:00Z') })
})

function user(id: string) {
  const found = findUser(db, id)
  if (!found) throw new Error(`no user ${id}`)
  return found
}

function idea(key: string): MockIdea {
  const found = findIdea(db, key)
  if (!found) throw new Error(`no idea ${key}`)
  return found
}

/** A project with the contract's worked-example rubric: Value (w2), Effort (w1, inverted). */
function workedExample(scores: [value: number, effort: number][]) {
  const project = findProjectBySlug(db, 'customer-innovation')
  if (!project) throw new Error('fixture project missing')
  const value = mockId(ID_KIND.criterion, 900)
  const effort = mockId(ID_KIND.criterion, 901)
  for (const criterion of db.criteria)
    if (criterion.project_id === project.id) criterion.archived = true
  db.criteria.push(
    {
      id: value,
      project_id: project.id,
      name: 'Value',
      description: '',
      weight: 2,
      inverted: false,
      guidance: {},
      position: 0,
      archived: false,
    },
    {
      id: effort,
      project_id: project.id,
      name: 'Effort',
      description: '',
      weight: 1,
      inverted: true,
      guidance: {},
      position: 1,
      archived: false,
    },
  )
  const target = idea('CUST-6') // "Live chat handover": no evaluators in the fixtures
  const evaluators = [USERS.bob, USERS.carol, USERS.dave]
  scores.forEach(([v, e], index) => {
    const evaluator = evaluators[index] ?? USERS.farid
    db.assignments.push({
      idea_id: target.id,
      user_id: evaluator,
      invited_at: '2026-09-01T00:00:00Z',
    })
    db.evaluations.push({
      id: mockId(ID_KIND.evaluation, 900 + index),
      idea_id: target.id,
      evaluator_id: evaluator,
      status: 'submitted',
      scores: [
        { criterion_id: value, score: v, comment: '' },
        { criterion_id: effort, score: e, comment: '' },
      ],
      recommendation: 'go',
      comment: '',
      submitted_at: `2026-09-0${index + 2}T00:00:00Z`,
      edited_at: null,
      updated_at: '2026-09-02T00:00:00Z',
      include_in_aggregate: true,
    })
  })
  return { target, value, effort }
}

describe('aggregate (contract §3.8)', () => {
  it('matches the worked example', () => {
    const { target, value, effort } = workedExample([
      [4, 2],
      [5, 4],
      [2, 3],
    ])
    const aggregate = computeAggregate(db, target)
    expect(aggregate?.overall).toBe(3.4)
    expect(aggregate?.count).toBe(3)
    expect(aggregate?.high_disagreement).toBe(true)
    expect(aggregate?.recommendations).toEqual({ go: 3, maybe: 0, no: 0 })
    const byId = new Map(aggregate?.criteria.map((c) => [c.criterion_id, c]))
    expect(byId.get(value)).toMatchObject({
      mean: 3.7,
      min: 2,
      max: 5,
      spread: 3,
      count: 3,
      inverted: false,
    })
    // Raw scores are reported for inverted criteria; the overall uses 6 − s.
    expect(byId.get(effort)).toMatchObject({ mean: 3, min: 2, max: 4, spread: 2, inverted: true })
  })

  it('flags disagreement only for a spread of 2 or more with at least two scores', () => {
    expect(computeAggregate(db, workedExample([[4, 3]]).target)?.high_disagreement).toBe(false)
    db = createDb()
    expect(
      computeAggregate(
        db,
        workedExample([
          [4, 3],
          [3, 3],
        ]).target,
      )?.high_disagreement,
    ).toBe(false)
  })

  it('ignores drafts, and has no aggregate without submissions', () => {
    const target = idea('CUST-5') // new, no evaluators
    expect(computeAggregate(db, target)).toBeNull()
    const draftOnly = idea('CUST-13')
    const before = computeAggregate(db, draftOnly)
    expect(before?.count).toBe(2) // Bob's draft is not counted
  })

  it('rounds half up to one decimal', () => {
    expect(round1(3.45)).toBe(3.5)
    expect(round1(3.444)).toBe(3.4)
    expect(round1(2.25)).toBe(2.3)
    expect(round1(4)).toBe(4)
  })
})

describe('blind evaluation (role matrix §3)', () => {
  // CUST-1: Carol and Dave submitted; Alice is assigned with no draft.
  // TOOL-1: Bob and Farid submitted; Alice has a draft.
  it('hides every score field from a pending evaluator without a draft', () => {
    const alice = user(USERS.alice)
    const target = idea('CUST-1')
    expect(isPendingEvaluator(db, target, alice.id)).toBe(true)
    const summary = ideaSummary(db, target, alice)
    expect(summary).toMatchObject({ score: null, score_hidden: true, high_disagreement: false })
    const detail = ideaDetail(db, target, alice)
    expect(detail.aggregate).toBeNull()
    expect(detail.score_hidden).toBe(true)
  })

  it('hides scores from a pending evaluator with a draft, and keeps drafts private', () => {
    const alice = user(USERS.alice)
    const target = idea('TOOL-1')
    expect(ideaSummary(db, target, alice)).toMatchObject({ score: null, score_hidden: true })
    const own = ideaDetail(db, target, alice).evaluators.find((e) => e.user.id === alice.id)
    expect(own?.state).toBe('draft')
    // Everyone else sees Alice as "invited", never "draft".
    const bob = user(USERS.bob)
    const seenByBob = ideaDetail(db, target, bob).evaluators.find((e) => e.user.id === alice.id)
    expect(seenByBob?.state).toBe('invited')
    expect(ideaDetail(db, target, bob).evaluator_progress).toEqual({ submitted: 2, total: 3 })
  })

  it('shows scores to everyone else with view access', () => {
    const target = idea('CUST-1')
    for (const viewer of [
      USERS.bob,
      USERS.priya,
      USERS.emma /* viewer */,
      USERS.ivan /* internal non-member */,
    ]) {
      const summary = ideaSummary(db, target, user(viewer))
      expect(summary.score_hidden).toBe(false)
      expect(summary.score?.count).toBe(2)
    }
  })

  it('applies to project admins who are pending evaluators', () => {
    const target = idea('CUST-8') // no pending admin in fixtures: make Priya (admin) pending
    db.assignments.push({
      idea_id: target.id,
      user_id: USERS.priya,
      invited_at: '2026-09-01T00:00:00Z',
    })
    const detail = ideaDetail(db, target, user(USERS.priya))
    expect(detail.score_hidden).toBe(true)
    expect(detail.aggregate).toBeNull()
    expect(detail.permissions.can_remove_evaluators).toBe(true) // but not themselves (handler)
  })

  it('sorts hidden ideas as unscored and excludes them from the disagreement filter', () => {
    const alice = user(USERS.alice)
    const project = findProjectBySlug(db, 'customer-innovation')
    if (!project) throw new Error('missing')
    const byScore = queryProjectIdeas(db, project, alice, { sort: '-score' })
    const hiddenIndex = byScore.findIndex((i) => i.id === idea('CUST-7').id)
    const scored = byScore.filter((i) => ideaSummary(db, i, alice).score !== null)
    expect(hiddenIndex).toBeGreaterThanOrEqual(scored.length)
    // CUST-7 has a spread of 2 on Value but Alice is pending: never matches.
    const flagged = queryProjectIdeas(db, project, alice, { high_disagreement: true })
    expect(flagged.map((i) => i.id)).not.toContain(idea('CUST-7').id)
    const flaggedForBob = queryProjectIdeas(db, project, user(USERS.bob), {
      high_disagreement: true,
    })
    expect(flaggedForBob.length).toBeGreaterThan(0)
  })

  it('masks board cards too', () => {
    const alice = user(USERS.alice)
    const project = findProjectBySlug(db, 'customer-innovation')
    if (!project) throw new Error('missing')
    const cards = board(db, project, alice, {}, 50).columns.flatMap((c) => c.items)
    const card = cards.find((c) => c.key === 'CUST-1')
    expect(card).toMatchObject({ score: null, score_hidden: true, high_disagreement: false })
  })

  it('reveals everything once the evaluator submits', () => {
    const alice = user(USERS.alice)
    const target = idea('TOOL-1')
    const draft = db.evaluations.find((e) => e.idea_id === target.id && e.evaluator_id === alice.id)
    if (!draft) throw new Error('fixture draft missing')
    draft.status = 'submitted'
    draft.scores = db.criteria
      .filter((c) => c.project_id === target.project_id && !c.archived)
      .map((c) => ({ criterion_id: c.id, score: 3, comment: '' }))
    draft.recommendation = 'maybe'
    const detail = ideaDetail(db, target, alice)
    expect(detail.score_hidden).toBe(false)
    expect(detail.aggregate?.count).toBe(3)
  })
})

describe('permissions booleans', () => {
  it('follow the role matrix for owners, members and viewers', () => {
    const target = idea('CUST-2') // owned by Alice, evaluating
    expect(ideaPermissions(db, target, user(USERS.alice))).toMatchObject({
      can_change_status: true,
      can_invite_evaluators: true,
      can_assign_owner: false,
      can_release_owner: true,
      can_delete: false,
    })
    expect(ideaPermissions(db, target, user(USERS.bob))).toMatchObject({
      can_change_status: false,
      can_comment: true,
      can_vote: true,
      can_evaluate: true,
    })
    expect(ideaPermissions(db, target, user(USERS.emma))).toMatchObject({
      can_comment: false,
      can_vote: false,
      can_edit: false,
    })
    expect(ideaPermissions(db, target, user(USERS.priya))).toMatchObject({
      can_assign_owner: true,
      can_delete: true,
    })
  })

  it('turn every write off in an archived project', () => {
    const target = idea('CUST-2')
    const project = findProjectBySlug(db, 'customer-innovation')
    if (!project) throw new Error('missing')
    project.archived_at = '2026-09-01T00:00:00Z'
    expect(Object.values(ideaPermissions(db, target, user(USERS.priya))).some(Boolean)).toBe(false)
  })

  it('respect "allow volunteer owners"', () => {
    const unowned = idea('GREEN-5') // Sustainability: volunteering disabled
    expect(ideaPermissions(db, unowned, user(USERS.alice)).can_volunteer).toBe(false)
    expect(ideaPermissions(db, unowned, user(USERS.carol)).can_volunteer).toBe(true) // admin
    expect(ideaPermissions(db, idea('CUST-6'), user(USERS.alice)).can_volunteer).toBe(true)
  })
})

describe('large dataset', () => {
  it('adds 10,000 ideas and still sorts by score quickly', () => {
    const large = createDb({ dataset: 'large' })
    const project = findProjectBySlug(large, 'customer-innovation')
    if (!project) throw new Error('missing')
    expect(large.ideas.filter((i) => i.project_id === project.id).length).toBeGreaterThan(10_000)
    const started = performance.now()
    const alice = findUser(large, USERS.alice)
    if (!alice) throw new Error('missing')
    queryProjectIdeas(large, project, alice, { sort: '-score' })
    expect(performance.now() - started).toBeLessThan(2000)
  })
})
