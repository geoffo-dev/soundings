import { describe, expect, it } from 'vitest'

import type { IdeaDetail, IdeaEvaluator, IdeaPermissions } from '@/api/types'

import { primaryAction } from './primary-action'

const ME = 'me'
const NONE: IdeaPermissions = {
  can_assign_owner: false,
  can_change_status: false,
  can_close_evaluation: false,
  can_comment: false,
  can_delete: false,
  can_edit: false,
  can_evaluate: false,
  can_invite_evaluators: false,
  can_release_owner: false,
  can_remove_evaluators: false,
  can_volunteer: false,
  can_vote: false,
  can_answer_research: false,
  invite_blocked_by_research: false,
  can_assign_researcher: false,
  can_assign_outside_researcher: false,
  can_hand_back_research: false,
  can_view_project: true,
}
const OWNER_PERMISSIONS: IdeaPermissions = {
  ...NONE,
  can_change_status: true,
  can_close_evaluation: true,
  can_invite_evaluators: true,
  can_remove_evaluators: true,
  can_release_owner: true,
}

const person = (id: string) => ({ id, display_name: id, avatar_url: null, initials: 'XX' })
const evaluator = (id: string, state: IdeaEvaluator['state']): IdeaEvaluator => ({
  user: person(id),
  invited_at: '2026-09-20T10:00:00Z',
  is_ai: false,
  state,
  submitted_at: state === 'submitted' ? '2026-09-21T10:00:00Z' : null,
})

function idea(patch: Partial<IdeaDetail> = {}): IdeaDetail {
  const evaluators = patch.evaluators ?? []
  return {
    id: 'idea',
    key: 'CUST-1',
    number: 1,
    title: 'Idea',
    summary: 'Summary',
    description_md: '',
    project: { id: 'p', key: 'CUST', name: 'Customer Innovation', slug: 'customer-innovation' },
    status: 'evaluating',
    resolution: null,
    status_label: 'Evaluating',
    owner: person(ME),
    submitted_by: null,
    held_for: null,
    via_public_form: false,
    tags: [],
    created_at: '2026-09-01T10:00:00Z',
    last_activity_at: '2026-09-21T10:00:00Z',
    evaluation_due_at: null,
    evaluation_closed_at: null,
    evaluation_open: true,
    evaluators,
    evaluator_progress: {
      total: evaluators.length,
      submitted: evaluators.filter((e) => e.state === 'submitted').length,
    },
    score: null,
    score_hidden: false,
    high_disagreement: false,
    aggregate: null,
    comment_count: 0,
    vote_count: 0,
    has_voted: false,
    watching: true,
    permissions: OWNER_PERMISSIONS,
    research: null,
    researcher: null,
    research_due_at: null,
    ...patch,
  }
}

describe('primaryAction', () => {
  it('asks a pending evaluator to evaluate, whatever else they may do', () => {
    const pending = idea({
      evaluators: [evaluator(ME, 'invited'), evaluator('bob', 'submitted')],
      permissions: { ...OWNER_PERMISSIONS, can_evaluate: true },
    })
    expect(primaryAction(pending, ME)).toEqual({ kind: 'evaluate', label: 'Evaluate' })
    const draft = idea({
      evaluators: [evaluator(ME, 'draft')],
      permissions: { ...NONE, can_evaluate: true },
    })
    expect(primaryAction(draft, ME)?.label).toBe('Continue evaluation')
  })

  it('does not ask to evaluate once submitted or when evaluation is closed', () => {
    const submitted = idea({
      owner: person('bob'),
      evaluators: [evaluator(ME, 'submitted')],
      permissions: { ...NONE, can_evaluate: true },
    })
    expect(primaryAction(submitted, ME)).toBeNull()
    const closed = idea({
      owner: person('bob'),
      evaluators: [evaluator(ME, 'invited')],
      permissions: { ...NONE, can_evaluate: false },
    })
    expect(primaryAction(closed, ME)).toBeNull()
  })

  it('offers ownership of an unowned idea', () => {
    expect(
      primaryAction(idea({ owner: null, permissions: { ...NONE, can_assign_owner: true } }), ME),
    ).toEqual({ kind: 'assign-owner', label: 'Assign owner' })
    expect(
      primaryAction(idea({ owner: null, permissions: { ...NONE, can_volunteer: true } }), ME),
    ).toEqual({ kind: 'volunteer', label: 'I’ll own this' })
  })

  it('guides the owner: invite, then close evaluation, then decide', () => {
    expect(primaryAction(idea(), ME)?.kind).toBe('invite')
    // While evaluation is open, closing it is the owner's next step (all in or not).
    const waiting = idea({
      evaluators: [evaluator('bob', 'submitted'), evaluator('cy', 'invited')],
    })
    expect(primaryAction(waiting, ME)?.kind).toBe('close-evaluation')
    const allIn = idea({
      evaluators: [evaluator('bob', 'submitted'), evaluator('cy', 'submitted')],
    })
    expect(primaryAction(allIn, ME)?.kind).toBe('close-evaluation')
    const closed = idea({
      evaluators: allIn.evaluators,
      evaluation_open: false,
      evaluation_closed_at: '2026-09-25T10:00:00Z',
    })
    expect(primaryAction(closed, ME)?.kind).toBe('change-status')
  })

  it('moves on to the proposal once the idea is Shortlisted or in Proposal', () => {
    const evaluators = [evaluator('bob', 'submitted'), evaluator('cy', 'submitted')]
    const shortlisted = idea({ evaluators, status: 'shortlisted', status_label: 'Shortlisted' })
    // Close evaluation stays in the sidebar from here.
    expect(primaryAction(shortlisted, ME, { exists: false, canCreate: true })).toEqual({
      kind: 'start-proposal',
      label: 'Start proposal',
    })
    // The proposal tab not loaded yet, or a proposal already started: open it.
    expect(primaryAction(shortlisted, ME)?.kind).toBe('open-proposal')
    expect(primaryAction(shortlisted, ME, { exists: true, canCreate: false })?.kind).toBe(
      'open-proposal',
    )
    const proposal = idea({ evaluators, status: 'proposal', status_label: 'Proposal' })
    expect(primaryAction(proposal, ME, { exists: true, canCreate: false })?.kind).toBe(
      'open-proposal',
    )
    // Not for people who don't run the idea.
    expect(primaryAction({ ...proposal, permissions: NONE }, ME)).toBeNull()
  })

  it('has nothing for viewers or closed ideas', () => {
    expect(primaryAction(idea({ owner: person('bob'), permissions: NONE }), ME)).toBeNull()
    expect(
      primaryAction(idea({ status: 'closed', resolution: 'accepted', evaluation_open: false }), ME),
    ).toBeNull()
  })
})

describe('primaryAction with a research step (Phase 8)', () => {
  const open = { answered: 1, total: 3, required_open: 1 }
  const done = { answered: 3, total: 3, required_open: 0 }
  const answerer = { ...OWNER_PERMISSIONS, can_answer_research: true }

  it('starts, then finishes research before evaluation, then starts evaluation', () => {
    const fresh = idea({ status: 'new', research: open, permissions: answerer })
    expect(primaryAction(fresh, ME, undefined, 'before_evaluation')).toEqual({
      kind: 'start-research',
      label: 'Start research',
    })
    const researching = idea({ status: 'research', research: open, permissions: answerer })
    expect(primaryAction(researching, ME, undefined, 'before_evaluation')).toEqual({
      kind: 'finish-research',
      label: 'Finish research',
    })
    const finished = idea({ status: 'research', research: done, permissions: answerer })
    expect(primaryAction(finished, ME, undefined, 'before_evaluation')).toEqual({
      kind: 'start-evaluation',
      label: 'Start evaluation',
    })
    // A complete checklist on New lets the usual first step through.
    const ready = idea({ status: 'new', research: done, permissions: answerer })
    expect(primaryAction(ready, ME, undefined, 'before_evaluation')?.kind).toBe('invite')
  })

  it('before the proposal: research a shortlisted idea, then start the proposal', () => {
    const proposal = { exists: false, canCreate: true }
    const shortlisted = idea({ status: 'shortlisted', research: open, permissions: answerer })
    expect(primaryAction(shortlisted, ME, proposal, 'before_proposal')?.kind).toBe('start-research')
    const finished = idea({ status: 'research', research: done, permissions: answerer })
    expect(primaryAction(finished, ME, proposal, 'before_proposal')?.kind).toBe('start-proposal')
    // Readers of an idea in Research get no primary action.
    const reader = idea({ status: 'research', research: open, permissions: NONE })
    expect(primaryAction(reader, ME, proposal, 'before_proposal')).toBeNull()
  })
})
