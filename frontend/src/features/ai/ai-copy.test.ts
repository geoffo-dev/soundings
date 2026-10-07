import { describe, expect, it } from 'vitest'

import type { AiRun } from '@/api/types'

import {
  elapsed,
  elapsedWords,
  purposeWords,
  runErrorWords,
  runLimitWords,
  runStatusLabel,
  runTitle,
  timeLeft,
} from './ai-copy'
import { partitionRuns } from './ai-runs-section'
import { outcomeWords } from './run-card'

function run(id: string, overrides: Partial<AiRun> = {}): AiRun {
  return {
    id,
    idea_id: 'i',
    kind: 'evaluate',
    section_key: null,
    status: 'succeeded',
    agent: { id: 'a1', display_name: 'Idea evaluator', purposes: ['evaluate'], user_id: 'u1' },
    requested_by: null,
    created_at: '2026-10-06T09:00:00Z',
    started_at: '2026-10-06T09:00:01Z',
    finished_at: '2026-10-06T09:01:00Z',
    deadline_at: null,
    cancel_requested: false,
    can_cancel: false,
    error: null,
    result: { evaluation_id: 'e1', note_id: null, suggestion_id: null },
    event_count: 0,
    ...overrides,
  }
}

describe('AI copy', () => {
  it('titles a run by what it does now, or did', () => {
    expect(runTitle({ kind: 'evaluate', section_key: null, status: 'running' })).toBe('Evaluating')
    expect(runTitle({ kind: 'evaluate', section_key: null, status: 'failed' })).toBe('Evaluation')
    expect(runTitle({ kind: 'draft_section', section_key: 'risks', status: 'queued' })).toBe(
      'Drafting Risks',
    )
    expect(runTitle({ kind: 'draft_section', section_key: 'risks', status: 'succeeded' })).toBe(
      'Draft of Risks',
    )
  })

  it('says “Cancelling” while a cancel request is pending', () => {
    expect(runStatusLabel({ status: 'running', cancel_requested: true })).toBe('Cancelling')
    expect(runStatusLabel({ status: 'cancelled', cancel_requested: false })).toBe('Cancelled')
    expect(runStatusLabel({ status: 'queued', cancel_requested: false })).toBe('Waiting')
  })

  it('counts the time a run has taken and has left', () => {
    const start = Date.parse('2026-10-06T09:00:00Z')
    expect(elapsed('2026-10-06T09:00:00Z', start + 84_000)).toBe('1:24')
    expect(elapsed('2026-10-06T09:00:00Z', start + 3_725_000)).toBe('1:02:05')
    expect(elapsedWords('2026-10-06T09:00:00Z', start + 61_000)).toBe('1 minute 1 second')
    expect(timeLeft('2026-10-06T09:05:00Z', start + 30_000)).toBe('5 min left')
    expect(timeLeft('2026-10-06T09:05:00Z', start + 290_000)).toBe('under a minute left')
    expect(timeLeft('2026-10-06T09:05:00Z', start + 400_000)).toBeNull()
    expect(timeLeft(null, start)).toBeNull()
    // Rounded, never up: a one-minute limit never reads "2 min left".
    expect(timeLeft('2026-10-06T09:01:00Z', start + 1_000)).toBe('under a minute left')
    expect(timeLeft('2026-10-06T09:05:00Z', start + 100_000)).toBe('3 min left')
  })

  it('states a timed-out run’s limit, from its deadline or when it ended', () => {
    expect(
      runLimitWords({
        started_at: '2026-10-06T09:00:00Z',
        deadline_at: '2026-10-06T09:05:00Z',
        finished_at: null,
      }),
    ).toBe('5 minutes')
    // Ended a few seconds after the deadline (cancelling): whole minutes, rounded down.
    expect(
      runLimitWords({
        started_at: '2026-10-06T09:00:00Z',
        deadline_at: null,
        finished_at: '2026-10-06T09:01:04Z',
      }),
    ).toBe('1 minute')
    expect(
      runErrorWords(
        run('t', {
          status: 'timed_out',
          error: { code: 'timed_out', message: 'x' },
          started_at: '2026-10-06T09:00:00Z',
          finished_at: '2026-10-06T09:05:03Z',
        }),
      ).what,
    ).toBe('The agent didn’t finish within 5 minutes.')
  })

  it('words stopped runs by code with a next step, and says whether an evaluation counts', () => {
    const failed = run('f', {
      status: 'failed',
      error: {
        code: 'agent_rejected',
        message: 'The agent declined the request. (state rejected)',
      },
    })
    expect(outcomeWords(failed)).toMatchObject({
      label: 'Failed',
      text: 'The agent turned the request down.',
    })
    expect(outcomeWords(failed).next).toMatch(/^Try again later/)
    expect(outcomeWords(run('s'), false).text).toBe('Evaluation submitted · not in the score yet')
    expect(outcomeWords(run('s'), true).text).toBe('Evaluation submitted · counted in the score')
    expect(outcomeWords(run('s')).text).toBe('Evaluation submitted')
    const cancelled = { status: 'cancelled' as const }
    expect(
      outcomeWords(
        run('c', {
          ...cancelled,
          result: { evaluation_id: null, note_id: null, suggestion_id: null },
        }),
      ).text,
    ).toBe('Cancelled: nothing was saved.')
    // Cancelled after it saved: the result stays, and the row says so.
    expect(outcomeWords(run('c', cancelled)).text).toBe('Cancelled · its evaluation was submitted')
  })

  it('shows working and stopped runs, one per agent and kind; the rest in History, drafts elsewhere', () => {
    const runs = [
      run('new-research', { kind: 'research' }),
      run('evaluating', { status: 'running' }),
      run('old-research', { kind: 'research' }),
      run('draft', { kind: 'draft_section', section_key: 'risks' }),
      run('old-evaluation', { status: 'failed' }),
      run('other-agent', {
        agent: { id: 'a2', display_name: 'Quick', purposes: ['evaluate'], user_id: 'u2' },
      }),
    ]
    const { latest, history } = partitionRuns(runs)
    // Finished runs did their job (their result is on the page): History.
    expect(latest.map((r) => r.id)).toEqual(['evaluating'])
    expect(history.map((r) => r.id)).toEqual([
      'new-research',
      'old-research',
      'old-evaluation',
      'other-agent',
    ])
    // A latest run that stopped short keeps its row (Try again); one watched finishing too.
    const stopped = partitionRuns([run('failed', { status: 'timed_out' }), run('ok')])
    expect(stopped.latest.map((r) => r.id)).toEqual(['failed'])
    const watched = partitionRuns([run('done')], (r) => r.id === 'done')
    expect(watched.latest.map((r) => r.id)).toEqual(['done'])
  })

  it('names an agent’s purposes in a sentence, in a fixed order', () => {
    expect(purposeWords(['research', 'evaluate'])).toBe('evaluation and research')
    expect(purposeWords(['draft_section', 'research', 'evaluate'])).toBe(
      'evaluation, research and proposal drafts',
    )
    expect(purposeWords(['unknown'])).toBe('')
  })
})
