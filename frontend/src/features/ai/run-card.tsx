import { Ban, Check, ChevronDown, CircleAlert, CircleCheck, Clock, RotateCw, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import { useCancelAiRun } from '@/api/ai'
import type { AiRun, AiRunEvent } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/relative-time'
import { Spinner } from '@/components/ui/spinner'
import { formatTime } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import {
  elapsed,
  elapsedWords,
  isActiveRun,
  runStatusLabel,
  runTitle,
  STATUS_COPY,
  timeLeft,
} from './ai-copy'
import { runDomId } from './dom-ids'
import { useRunProgress } from './use-run-progress'

/** Steps shown before "Show all N steps" folds the rest (a long run's history). */
const VISIBLE_STEPS = 8

/** A clock that ticks every second while `on` (the elapsed time of an active run). */
function useTicker(on: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!on) return
    const tick = () => setNow(Date.now())
    const frame = window.requestAnimationFrame(tick)
    const timer = window.setInterval(tick, 1000)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearInterval(timer)
    }
  }, [on])
  return now
}

export interface RunCardProps {
  ideaKey: string
  run: AiRun
  /** What the result links to ("View the evaluation"); none while it can't be shown. */
  resultAction?: ReactNode
  /** Asking again after a failure, timeout or cancel ("Try again"), when allowed. */
  retry?: ReactNode
  /** Start with the steps folded (earlier runs): the header and outcome only. */
  collapsed?: boolean
  className?: string
}

/**
 * One AI run (contract-phase6 §3.15 "a calm run panel"): the agent and what it
 * is doing, who asked, the live steps (Soundings' own sentences from the event
 * stream, never the agent's words), the elapsed time and the deadline, and
 * Cancel; when it is over, the outcome: what it saved, or why it stopped.
 */
export function RunCard({
  ideaKey,
  run,
  resultAction,
  retry,
  collapsed = false,
  className,
}: RunCardProps) {
  const [open, setOpen] = useState(!collapsed)
  const { detail, mode } = useRunProgress(ideaKey, run, { enabled: open || isActiveRun(run) })
  // The stream may be ahead of the list (a status from an event), or behind it.
  const current = isActiveRun(run) ? { ...run, ...pickLive(detail) } : run
  const active = isActiveRun(current)
  const now = useTicker(active)
  const cancel = useCancelAiRun(ideaKey)
  const titleId = useId()
  const cardRef = useRef<HTMLElement>(null)
  // Cancel goes when the run ends: if focus was on it (now lost), keep it on the card.
  const [mountedActive] = useState(active)
  useEffect(() => {
    if (mountedActive && !active) focusWhenRendered(() => cardRef.current)
  }, [mountedActive, active])
  const stepsId = useId()
  const latest = detail.events.at(-1)
  const status = STATUS_COPY[current.status]
  const label = runStatusLabel(current)
  const requester = current.requested_by?.display_name ?? 'Someone'

  return (
    <article
      ref={cardRef}
      id={runDomId(run.id)}
      tabIndex={-1}
      aria-labelledby={titleId}
      className={cn(
        'flex scroll-mt-20 flex-col rounded-lg border bg-surface outline-offset-2',
        className,
      )}
    >
      <header className="flex items-start gap-3 px-4 pt-3 pb-2.5">
        <Avatar name={current.agent.display_name} isAgent size="md" decorative className="mt-0.5" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 id={titleId} className="min-w-0 font-medium text-primary">
              {runTitle(current)}{' '}
              <span className="font-normal text-muted">· {current.agent.display_name}</span>
            </h3>
            <AiBadge />
            <Badge variant={status.tone === 'neutral' ? 'neutral' : status.tone}>
              {active && !current.cancel_requested && current.status === 'running' && (
                <Spinner className="size-3" />
              )}
              {label}
            </Badge>
          </div>
          <p className="text-sm text-muted">
            Asked by {requester} <RelativeTime date={current.created_at} />
          </p>
        </div>
        {collapsed && (
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            aria-controls={stepsId}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? 'Hide steps' : 'Steps'}
            <ChevronDown
              className={cn('transition-transform duration-150', open && 'rotate-180')}
            />
          </Button>
        )}
      </header>

      {open && (
        <div id={stepsId} className="border-t border-subtle px-4 py-3">
          <RunSteps events={detail.events} active={active} />
          {mode === 'polling' && active && (
            <p className="mt-2 text-xs text-muted">
              Live updates aren’t available here: checking every few seconds.
            </p>
          )}
        </div>
      )}
      {/* Each new step is announced once (Soundings' own sentences). */}
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {active && latest ? latest.message : ''}
      </p>

      <footer className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-subtle px-4 py-2.5 text-sm">
        {active ? (
          <>
            <span className="text-secondary tabular-nums">
              <span aria-hidden="true">
                {elapsed(current.started_at ?? current.created_at, now)}
              </span>
              <span className="sr-only">
                Running for {elapsedWords(current.started_at ?? current.created_at, now)}
              </span>
            </span>
            <span className="text-muted">
              {current.status === 'queued'
                ? 'Waiting for a free worker'
                : current.deadline_at
                  ? `Stops by ${formatTime(current.deadline_at)}${timeLeft(current.deadline_at, now) ? ` · ${timeLeft(current.deadline_at, now) ?? ''}` : ''}`
                  : 'Starting'}
            </span>
            {current.can_cancel && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                disabled={current.cancel_requested}
                loading={cancel.isPending}
                onClick={() => cancel.mutate(current.id)}
                aria-label={`Cancel: ${runTitle(current)} by ${current.agent.display_name}`}
              >
                <X />
                {current.cancel_requested ? 'Cancelling…' : 'Cancel'}
              </Button>
            )}
          </>
        ) : (
          <Outcome run={current} resultAction={resultAction} retry={retry} />
        )}
      </footer>
    </article>
  )
}

/** The fields of the streamed copy that can be ahead of the list. */
function pickLive(detail: AiRun): Partial<AiRun> {
  return {
    status: detail.status,
    cancel_requested: detail.cancel_requested,
    started_at: detail.started_at ?? null,
    finished_at: detail.finished_at,
    ...(detail.deadline_at ? { deadline_at: detail.deadline_at } : {}),
    ...(detail.error ? { error: detail.error } : {}),
    can_cancel: detail.can_cancel,
  }
}

function Outcome({
  run,
  resultAction,
  retry,
}: {
  run: AiRun
  resultAction?: ReactNode
  retry?: ReactNode
}) {
  const finished = run.finished_at ? <RelativeTime date={run.finished_at} /> : null
  if (run.status === 'succeeded') {
    return (
      <>
        <span className="flex items-center gap-1.5 text-primary">
          <CircleCheck aria-hidden="true" className="size-4 text-success" />
          {run.kind === 'evaluate'
            ? 'Evaluation submitted'
            : run.kind === 'research'
              ? 'Research note saved'
              : 'Suggestion saved'}
        </span>
        {finished && <span className="text-muted">{finished}</span>}
        {resultAction && <span className="ml-auto">{resultAction}</span>}
      </>
    )
  }
  if (run.status === 'cancelled') {
    return (
      <>
        <span className="flex items-center gap-1.5 text-secondary">
          <Ban aria-hidden="true" className="size-4 text-muted" />
          Cancelled
        </span>
        {finished && <span className="text-muted">{finished}</span>}
        {retry && <span className="ml-auto">{retry}</span>}
      </>
    )
  }
  const TimedOut = run.status === 'timed_out'
  return (
    <>
      <span className="flex min-w-0 items-start gap-1.5 text-primary">
        {TimedOut ? (
          <Clock aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
        ) : (
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-danger" />
        )}
        {run.error?.message ??
          (TimedOut ? 'It didn’t finish in time.' : 'It stopped with an error.')}
      </span>
      {finished && <span className="text-muted">{finished}</span>}
      {retry && <span className="ml-auto">{retry}</span>}
    </>
  )
}

/** The run's steps, oldest first; the newest one is "now" while the run is active. */
export function RunSteps({ events, active }: { events: AiRunEvent[]; active: boolean }) {
  const [all, setAll] = useState(false)
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted">
        {active ? 'Waiting for the first step…' : 'No steps recorded.'}
      </p>
    )
  }
  const hidden = all ? 0 : Math.max(0, events.length - VISIBLE_STEPS)
  const shown = events.slice(hidden)
  return (
    <div className="flex flex-col gap-1.5">
      {hidden > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 self-start text-muted"
          onClick={() => setAll(true)}
        >
          Show all {events.length} steps
        </Button>
      )}
      <ol aria-label="Steps" className="flex flex-col gap-1">
        {shown.map((event, index) => {
          const last = index === shown.length - 1
          return (
            <li key={event.seq} className="flex items-start gap-2 text-sm">
              <StepIcon event={event} current={last && active} />
              <span
                className={cn(
                  'min-w-0 flex-1',
                  last ? 'text-primary' : 'text-secondary',
                  event.final && 'font-medium',
                )}
              >
                {event.message}
                {last && active && <span className="sr-only"> (now)</span>}
              </span>
              <time
                dateTime={event.created_at}
                className="shrink-0 text-xs text-muted tabular-nums"
              >
                {formatTime(event.created_at)}
              </time>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function StepIcon({ event, current }: { event: AiRunEvent; current: boolean }) {
  const box = 'mt-0.5 flex size-4 shrink-0 items-center justify-center'
  if (current) {
    return (
      <span className={cn(box, 'text-accent')} aria-hidden="true">
        <Spinner className="size-3.5" />
      </span>
    )
  }
  const icon =
    event.type === 'succeeded' ? (
      <CircleCheck className="size-4 text-success" />
    ) : event.type === 'failed' ? (
      <CircleAlert className="size-4 text-danger" />
    ) : event.type === 'timed_out' ? (
      <Clock className="size-4 text-warning" />
    ) : event.type === 'cancelled' || event.type === 'cancel_requested' ? (
      <Ban className="size-3.5 text-muted" />
    ) : event.type === 'retrying' ? (
      <RotateCw className="size-3.5 text-warning" />
    ) : (
      <Check className="size-3.5 text-muted" />
    )
  return (
    <span className={box} aria-hidden="true">
      {icon}
    </span>
  )
}
