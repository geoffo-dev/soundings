import { describe, expect, it } from 'vitest'

import type { BidDetail, BidMustHaveState } from '@/api/types'

import { rejectionSuggestion } from './must-haves'

const state = (
  text: string,
  result: BidMustHaveState['result'],
  aiNotMet = false,
): BidMustHaveState => ({
  must_have: { id: text, position: 0, text, kind: 'document', pricing: false },
  result,
  automatic: true,
  decided_by: null,
  decided_at: null,
  note: '',
  document_ids: [],
  restricted_document_count: 0,
  ai_findings: aiNotMet
    ? [
        {
          ai_assessment_id: 'a',
          agent: { id: 'x', display_name: 'Bid assessor', avatar_url: null, initials: 'BA' },
          finding: 'not_met',
          rationale: '',
          evidence: [],
          submitted_at: '2026-10-01T00:00:00Z',
        },
      ]
    : [],
})

describe('the first reason offered for Reject', () => {
  it('names what is missing, not met, and what the AI found not met', () => {
    const bid = {
      must_have_results: [
        state('Insurance certificate', 'missing', true),
        state('Signed form of tender', 'met'),
        state('ISO 27001', 'not_met'),
        state('Accepts our terms', 'unchecked', true),
      ],
    } as BidDetail
    expect(rejectionSuggestion(bid)).toBe(
      'Missing: Insurance certificate. Not met: ISO 27001. The AI found not met: Accepts our terms.',
    )
  })

  it('is empty when nothing is flagged', () => {
    expect(rejectionSuggestion({ must_have_results: [state('A', 'met')] } as BidDetail)).toBe('')
  })
})
