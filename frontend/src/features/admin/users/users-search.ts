import type { AdminUserFilters } from '@/api/admin'
import { searchEnum, searchFlag, searchString } from '@/lib/search-params'

export const USER_STATUSES = ['active', 'deactivated'] as const
export type UserStatusFilter = (typeof USER_STATUSES)[number]

/** `/settings/users?q=&status=active|deactivated&admins=1&unlinked=1` (defaults dropped). */
export interface UsersSearch {
  q?: string
  status?: UserStatusFilter
  /** Platform admins only. */
  admins?: true
  /** Never linked to SSO (pre-created, not signed in yet). */
  unlinked?: true
}

export function validateUsersSearch(search: Record<string, unknown>): UsersSearch {
  return {
    q: searchString(search.q, 100),
    status: searchEnum(search.status, USER_STATUSES),
    admins: searchFlag(search.admins),
    unlinked: searchFlag(search.unlinked),
  }
}

/** The URL state as `list_admin_users` filters. */
export function toUserFilters(search: UsersSearch): AdminUserFilters {
  return {
    q: search.q,
    active: search.status === undefined ? undefined : search.status === 'active',
    platform_admin: search.admins,
    has_identity: search.unlinked ? false : undefined,
  }
}

export function hasUserFilters(search: UsersSearch): boolean {
  return [search.q, search.status, search.admins, search.unlinked].some(Boolean)
}
