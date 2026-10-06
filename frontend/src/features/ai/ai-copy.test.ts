import { describe, expect, it } from 'vitest'

import { elapsed, elapsedWords, purposeWords, runStatusLabel, runTitle, timeLeft } from './ai-copy'

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
  })

  it('names an agent’s purposes in a sentence, in a fixed order', () => {
    expect(purposeWords(['research', 'evaluate'])).toBe('evaluation and research')
    expect(purposeWords(['draft_section', 'research', 'evaluate'])).toBe(
      'evaluation, research and proposal drafts',
    )
    expect(purposeWords(['unknown'])).toBe('')
  })
})
