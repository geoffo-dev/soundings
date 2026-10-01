import { CircleAlert, CircleCheck, RotateCw, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

import type { AltchaState } from './use-altcha'

const COPY: Record<AltchaState, { text: string; hint?: string }> = {
  idle: {
    text: 'We check that you’re human when you start typing',
    hint: 'No puzzle: your browser does a little work, here, even offline.',
  },
  verifying: {
    text: 'Checking this browser…',
    hint: 'No puzzle: your browser does a little work, here, even offline.',
  },
  verified: { text: 'Verified you’re human' },
  error: { text: 'We couldn’t verify this browser', hint: 'Try again: it takes a few seconds.' },
}

/**
 * The ALTCHA proof of work's state in words (contract-phase4 §3.5, wireframe
 * 06): it solves itself in the background, so this is a calm status line, not
 * a control; only a failure offers Retry. Announced politely as it changes.
 */
export function HumanCheck({ state, onRetry }: { state: AltchaState; onRetry: () => void }) {
  const copy = COPY[state]
  return (
    <div
      data-state={state}
      className={cn(
        'flex items-center gap-3 rounded-lg border px-3 py-2.5',
        state === 'error' && 'border-danger/40 bg-danger-subtle',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'flex size-5 shrink-0 items-center justify-center [&_svg]:size-4',
          state === 'verified' ? 'text-success' : state === 'error' ? 'text-danger' : 'text-muted',
        )}
      >
        {state === 'verifying' ? (
          <Spinner />
        ) : state === 'verified' ? (
          <CircleCheck />
        ) : state === 'error' ? (
          <CircleAlert />
        ) : (
          <ShieldCheck />
        )}
      </span>
      <p role="status" className="flex min-w-0 flex-1 flex-col text-sm">
        <span className="font-medium text-primary">{copy.text}</span>
        {copy.hint && <span className="text-muted">{copy.hint}</span>}
      </p>
      {state === 'error' && (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          Retry
        </Button>
      )}
    </div>
  )
}
