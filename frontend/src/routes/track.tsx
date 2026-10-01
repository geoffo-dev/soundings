import { createFileRoute } from '@tanstack/react-router'

import { TrackPage } from '@/features/public/track-page'

/**
 * /track#<token> — the submitter's private tracking page (contract-phase4
 * §3.7). Public, no app shell. The token is read from the fragment (never sent
 * to the server in a URL) and posted in a JSON body; the fragment is kept so
 * the link can be bookmarked.
 */
export const Route = createFileRoute('/track')({
  head: () => ({
    meta: [{ title: 'Your idea · Soundings' }, { name: 'referrer', content: 'no-referrer' }],
  }),
  component: TrackPage,
})
