import type { AdminApiKeyFilters } from '@/api/api-keys'
import { keySearchTerm } from '@/api/api-keys'
import type { ApiKeyState } from '@/api/types'
import { searchEnum, searchString } from '@/lib/search-params'

export const KEY_STATES = ['active', 'expired', 'dormant'] as const satisfies readonly ApiKeyState[]

/** `/settings/all-api-keys?q=&state=&user_id=` (defaults dropped). */
export interface AdminKeysSearch {
  /** A key name, an owner, or a key's prefix (a whole key is cut to its prefix). */
  q?: string
  state?: ApiKeyState
  /** One person's or agent's keys (linked from their admin page and "Sign out everywhere"). */
  user_id?: string
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function validateAdminKeysSearch(search: Record<string, unknown>): AdminKeysSearch {
  const q = searchString(search.q, 100)
  const userId = typeof search.user_id === 'string' ? search.user_id : undefined
  return {
    // Never keep a whole key in the URL, even one typed into it by hand.
    q: q === undefined ? undefined : keySearchTerm(q),
    state: searchEnum(search.state, KEY_STATES),
    user_id: userId && UUID.test(userId) ? userId.toLowerCase() : undefined,
  }
}

export function toAdminKeyFilters(search: AdminKeysSearch): AdminApiKeyFilters {
  return { q: search.q, state: search.state, user_id: search.user_id }
}

export function hasAdminKeyFilters(search: AdminKeysSearch): boolean {
  return [search.q, search.state, search.user_id].some(Boolean)
}

export const STATE_LABELS: Record<ApiKeyState, { label: string; description: string }> = {
  active: { label: 'Active', description: 'Working now' },
  expired: { label: 'Expired', description: 'Past their expiry date' },
  dormant: { label: 'Dormant', description: 'The owner hasn’t signed in for 30 days' },
}
