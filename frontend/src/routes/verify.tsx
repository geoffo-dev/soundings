import { createFileRoute } from '@tanstack/react-router'

import { VerifyPage } from '@/features/public/verify-page'

/**
 * /verify#<token> — confirm a public submitter's email address
 * (contract-phase4 §3.7). Public, no app shell. Nothing is posted on load (mail
 * scanners open links); the token is sent only when the person clicks Confirm.
 */
export const Route = createFileRoute('/verify')({
  head: () => ({
    meta: [
      { title: 'Confirm your email address · Soundings' },
      { name: 'referrer', content: 'no-referrer' },
    ],
  }),
  component: VerifyPage,
})
