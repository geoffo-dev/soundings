import { createFileRoute } from '@tanstack/react-router'

import { TrackPage } from '@/features/public/track-page'
import { searchFlag } from '@/lib/search-params'

export interface TrackSearch {
  /** The message email's Reply button (`/track?reply=1#…`): straight to the reply box. */
  reply?: true
}

/**
 * /track#<token> — the submitter's private tracking page (contract-phase4
 * §3.7). Public, no app shell. The token is read from the fragment (never sent
 * to the server in a URL) and posted in a JSON body; the fragment is kept so
 * the link can be bookmarked. `?reply=1` holds nothing secret.
 */
export const Route = createFileRoute('/track')({
  validateSearch: (search: Record<string, unknown>): TrackSearch => ({
    reply: searchFlag(search.reply),
  }),
  head: () => ({
    meta: [{ title: 'Your idea · Soundings' }, { name: 'referrer', content: 'no-referrer' }],
  }),
  component: TrackRoute,
})

function TrackRoute() {
  const { reply } = Route.useSearch()
  return <TrackPage toReply={Boolean(reply)} />
}
