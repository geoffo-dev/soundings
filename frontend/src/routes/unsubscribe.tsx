import { createFileRoute } from '@tanstack/react-router'

import { UnsubscribePage } from '@/features/notifications/unsubscribe-page'
import { searchString } from '@/lib/search-params'

export interface UnsubscribeSearch {
  /** The signed token from the email's link (contract-phase3 §3.5). */
  token?: string
}

/**
 * /unsubscribe?token=… — public (no sign-in), outside the app shell like
 * /login. The API's own unsubscribe URL redirects browsers here.
 */
export const Route = createFileRoute('/unsubscribe')({
  validateSearch: (search: Record<string, unknown>): UnsubscribeSearch => ({
    token: searchString(search.token, 600),
  }),
  head: () => ({
    meta: [{ title: 'Unsubscribe · Soundings' }, { name: 'referrer', content: 'no-referrer' }],
  }),
  component: UnsubscribeRoute,
})

function UnsubscribeRoute() {
  const { token } = Route.useSearch()
  return <UnsubscribePage token={token} />
}
