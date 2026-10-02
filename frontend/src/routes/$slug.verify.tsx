import { createFileRoute } from '@tanstack/react-router'

import { VerifyPage } from '@/features/public/verify-page'

/**
 * /{slug}/verify#<token> — confirm a public submitter's email address in the
 * project's branding (contract-phase4 §3.7). Public, no app shell. The slug
 * isn't secret; the token stays in the fragment and is posted only when the
 * person clicks Confirm (mail scanners open links). /verify#<token> still works.
 */
export const Route = createFileRoute('/$slug/verify')({
  head: () => ({
    meta: [
      { title: 'Confirm your email address · Soundings' },
      { name: 'referrer', content: 'no-referrer' },
    ],
  }),
  component: VerifyRoute,
})

function VerifyRoute() {
  const { slug } = Route.useParams()
  return <VerifyPage slug={slug} />
}
