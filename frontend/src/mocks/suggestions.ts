/**
 * Phase 5 proposal suggestions in the mock API (contract-phase5 §3.4): the
 * whole proposed text of one section, from a person (REST or MCP) or an AI
 * agent's service account. Records mirror `proposal_suggestions`.
 */
import type {
  ProposalSectionKey,
  ProposalSuggestion,
  SuggestionSource,
  SuggestionStatus,
} from '@/api/types'

import type { MockDb } from './db'
import { userRefById } from './domain'
import { SECTION_KEYS, type MockProposal } from './proposals'

export interface MockSuggestion {
  id: string
  proposal_id: string
  section_key: ProposalSectionKey
  author_id: string | null
  body_md: string
  base_version: number
  source: SuggestionSource
  status: SuggestionStatus
  created_at: string
  decided_at: string | null
  decided_by_id: string | null
}

/** Pending suggestions per proposal (`MAX_PENDING_SUGGESTIONS`). */
export const MAX_PENDING_SUGGESTIONS = 50
export const SUGGESTION_MAX_LENGTH = 20_000

export function suggestionOut(db: MockDb, suggestion: MockSuggestion): ProposalSuggestion {
  const section = db.proposalSections.find(
    (s) => s.proposal_id === suggestion.proposal_id && s.key === suggestion.section_key,
  )
  return {
    id: suggestion.id,
    section_key: suggestion.section_key,
    author: userRefById(db, suggestion.author_id),
    body_md: suggestion.body_md,
    base_version: suggestion.base_version,
    section_changed: (section?.version ?? 0) > suggestion.base_version,
    source: suggestion.source,
    status: suggestion.status,
    created_at: suggestion.created_at,
    decided_at: suggestion.decided_at,
    decided_by: userRefById(db, suggestion.decided_by_id),
  }
}

/** Pending suggestions in template-section order, then oldest first. */
export function pendingSuggestions(db: MockDb, proposal: MockProposal): MockSuggestion[] {
  return db.proposalSuggestions
    .filter((s) => s.proposal_id === proposal.id && s.status === 'pending')
    .sort(
      (a, b) =>
        SECTION_KEYS.indexOf(a.section_key) - SECTION_KEYS.indexOf(b.section_key) ||
        a.created_at.localeCompare(b.created_at) ||
        a.id.localeCompare(b.id),
    )
}
