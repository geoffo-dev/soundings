import { useQuery } from '@tanstack/react-query'
import { useRouteContext } from '@tanstack/react-router'

import { meQueryOptions } from '@/api/auth'
import type { CurrentUser } from '@/api/types'

/**
 * The signed-in user, inside the app shell (routes under `_app`, whose guard
 * guarantees a session). Use the API's `permissions` for what they may do —
 * `is_platform_admin` is only for platform-level actions such as "New project".
 */
export function useCurrentUser(): CurrentUser {
  const { user } = useRouteContext({ from: '/_app' })
  const { data } = useQuery(meQueryOptions())
  return data ?? user
}
