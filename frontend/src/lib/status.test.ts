import { describe, expect, it } from 'vitest'

import {
  crossesGate,
  gatedStatuses,
  gateStatus,
  lifecycle,
  publicStatus,
  showsResearchProgress,
  statusBeforeResearch,
} from '@/lib/status'

describe('the research step (contract-phase8 §3.2, §3.5)', () => {
  it('puts Research where the step says, and nowhere while off', () => {
    expect(lifecycle('off')).toEqual(['new', 'evaluating', 'shortlisted', 'proposal', 'closed'])
    expect(lifecycle('before_evaluation')).toEqual([
      'new',
      'research',
      'evaluating',
      'shortlisted',
      'proposal',
      'closed',
    ])
    expect(lifecycle('before_proposal')).toEqual([
      'new',
      'evaluating',
      'shortlisted',
      'research',
      'proposal',
      'closed',
    ])
  })

  it('knows the statuses around Research', () => {
    expect(gateStatus('off')).toBeNull()
    expect(gateStatus('before_evaluation')).toBe('evaluating')
    expect(gateStatus('before_proposal')).toBe('proposal')
    expect(statusBeforeResearch('before_evaluation')).toBe('new')
    expect(statusBeforeResearch('before_proposal')).toBe('shortlisted')
    expect(gatedStatuses('before_evaluation')).toEqual(['evaluating', 'shortlisted', 'proposal'])
    expect(gatedStatuses('before_proposal')).toEqual(['proposal'])
    expect(gatedStatuses('off')).toEqual([])
  })

  it('guards crossing into a status after Research, never back or to Closed', () => {
    expect(crossesGate('before_evaluation', 'research', 'evaluating')).toBe(true)
    expect(crossesGate('before_evaluation', 'new', 'shortlisted')).toBe(true)
    expect(crossesGate('before_evaluation', 'evaluating', 'shortlisted')).toBe(false)
    expect(crossesGate('before_evaluation', 'evaluating', 'new')).toBe(false)
    expect(crossesGate('before_evaluation', 'research', 'closed')).toBe(false)
    expect(crossesGate('before_proposal', 'shortlisted', 'proposal')).toBe(true)
    expect(crossesGate('before_proposal', 'new', 'evaluating')).toBe(false)
    expect(crossesGate('off', 'new', 'proposal')).toBe(false)
  })

  it('counts a reopened idea from the status it was closed from (unknown: New)', () => {
    expect(crossesGate('before_evaluation', 'closed', 'evaluating', 'shortlisted')).toBe(false)
    expect(crossesGate('before_evaluation', 'closed', 'evaluating', 'research')).toBe(true)
    expect(crossesGate('before_evaluation', 'closed', 'evaluating', null)).toBe(true)
  })

  it('shows progress for ideas in Research or right before it', () => {
    expect(showsResearchProgress('before_evaluation', 'new')).toBe(true)
    expect(showsResearchProgress('before_evaluation', 'research')).toBe(true)
    expect(showsResearchProgress('before_evaluation', 'evaluating')).toBe(false)
    expect(showsResearchProgress('before_proposal', 'new')).toBe(false)
    expect(showsResearchProgress('before_proposal', 'shortlisted')).toBe(true)
    expect(showsResearchProgress('off', 'new')).toBe(false)
  })

  it('reports Research to submitters as the status before it', () => {
    expect(publicStatus('before_evaluation', 'research')).toBe('new')
    expect(publicStatus('before_proposal', 'research')).toBe('shortlisted')
    expect(publicStatus('off', 'research')).toBe('new')
    expect(publicStatus('before_proposal', 'proposal')).toBe('proposal')
  })
})
