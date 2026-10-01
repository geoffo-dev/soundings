import type { EmailStatus, EmailType } from '@/api/types'
import { searchList } from '@/lib/search-params'

/**
 * `/settings/email?status=failed,queued&type=digest` (defaults dropped; unknown
 * values ignored). With no `status`, the page opens on what needs attention
 * (contract-phase3 §3.10: failed emails when there are any, with the ones
 * still queued for another try); `status=all` shows everything.
 */
export interface EmailSearch {
  status?: (EmailStatus | 'all')[]
  type?: EmailType[]
}

export const EMAIL_STATUSES: EmailStatus[] = ['failed', 'queued', 'sending', 'sent', 'cancelled']

/** The types the outbox holds in Phase 3 (Phase 4's submitter emails come later). */
export const EMAIL_TYPES: EmailType[] = [
  'evaluator_invited',
  'evaluation_reminder',
  'owner_assigned',
  'evaluations_complete',
  'mention',
  'comment',
  'status_changed',
  'digest',
  'test',
]

export function validateEmailSearch(search: Record<string, unknown>): EmailSearch {
  const status = searchList(search.status, [...EMAIL_STATUSES, 'all'] as const)
  return {
    // "all" wins over anything else in the list.
    status: status?.includes('all') ? ['all'] : status,
    type: searchList(search.type, EMAIL_TYPES),
  }
}

/**
 * What the outbox opens on when the URL says nothing: failed emails, and the
 * queued ones with them (they are retrying, or waiting for a worker), when
 * anything failed or mail has waited too long (`stuck`); else everything.
 */
export function defaultStatuses(
  counts: { failed: number; queued: number },
  stuck: boolean,
): EmailStatus[] {
  if (counts.failed === 0 && !stuck) return []
  return [
    ...(counts.failed > 0 ? (['failed'] as const) : []),
    ...(counts.queued > 0 ? (['queued'] as const) : []),
  ]
}

/** The API's status filter: the URL's statuses, or the page's default when unset. */
export function effectiveStatuses(
  status: EmailSearch['status'],
  defaults: EmailStatus[],
): EmailStatus[] {
  if (!status) return defaults
  return status.filter((value): value is EmailStatus => value !== 'all')
}
