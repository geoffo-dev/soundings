import { CircleAlert, CircleCheck, RotateCw, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

import type { AltchaState } from './use-altcha'

const HINT = 'No puzzle to solve: your browser does a quick check by itself.'

const COPY: Record<AltchaState, { text: string; hint?: string }> = {
  idle: { text: 'We check that you’re human when you start typing', hint: HINT },
  verifying: { text: 'Checking this browser…', hint: HINT },
  verified: { text: 'Verified you’re human' },
  error: { text: 'We couldn’t verify this browser', hint: 'Try again: it takes a few seconds.' },
}

/**
 * The ALTCHA proof of work's state in words (contract-phase4 §3.5, wireframe
 * 06): it solves itself in the background, so this is a calm status line, not
 * a control; only a failure offers Retry. Once verified it shrinks to one muted
 * line. Announced politely as it changes (the same status element throughout).
 */
export function HumanCheck({ state, onRetry }: { state: AltchaState; onRetry: () => void }) {
  const copy = COPY[state]
  const done = state === 'verified'
  return (
    <div
      data-state={state}
      className={cn(
        'flex items-center gap-3 rounded-lg border',
        done ? 'gap-2 border-transparent px-0 py-0' : 'px-3 py-2.5',
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
        <span className={done ? 'text-muted' : 'font-medium text-primary'}>{copy.text}</span>
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
