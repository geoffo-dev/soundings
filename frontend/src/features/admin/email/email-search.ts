import type { EmailStatus, EmailType } from '@/api/types'
import { searchList } from '@/lib/search-params'

/**
 * `/settings/email?status=failed,queued&type=digest` (defaults dropped; unknown
 * values ignored). With no `status`, the page opens on failed emails when
 * there are any (contract-phase3 §3.10); `status=all` shows everything.
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

/** The API's status filter: the URL's statuses, or failed when unset and there are failures. */
export function effectiveStatuses(
  status: EmailSearch['status'],
  failedCount: number,
): EmailStatus[] {
  if (!status) return failedCount > 0 ? ['failed'] : []
  return status.filter((value): value is EmailStatus => value !== 'all')
}
