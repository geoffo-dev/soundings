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
  runErrorWords,
  runStatusLabel,
  runTitle,
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

/** Focus is nowhere: on `<body>`, or on an element that has gone. */
function focusLost(): boolean {
  const active = document.activeElement
  return !active || active === document.body || !active.isConnected
}

export interface RunCardProps {
  ideaKey: string
  run: AiRun
  /** What the result links to ("View the evaluation"); none while it can't be shown. */
  resultAction?: ReactNode
  /** Asking again after a failure, timeout or cancel ("Try again"), when allowed. */
  retry?: ReactNode
  /**
   * After "Evaluation submitted": whether it counts yet (an AI evaluation is left out
   * of the score until the owner includes it). Undefined when the viewer can't know.
   */
  counted?: boolean
  className?: string
}

/**
 * One AI run as one quiet row (contract-phase6 §3.15): the agent and what it does,
 * then a single line. While it works: the current step (Soundings' own sentence
 * from the event stream, never the agent's words), the time it has taken and has
 * left, and Cancel. When it is over: the outcome, what it saved or why it stopped
 * with the next step. Who asked and every step are behind "Steps".
 *
 * Focus stays where the person put it. When a run ends, its Cancel goes: only if
 * focus was in this row and is now lost does it move to the row; either way the
 * outcome is announced.
 */
export function RunCard({ ideaKey, run, resultAction, retry, counted, className }: RunCardProps) {
  const [open, setOpen] = useState(false)
  const { detail, mode } = useRunProgress(ideaKey, run, { enabled: open || isActiveRun(run) })
  // The stream may be ahead of the list (a status from an event), or behind it.
  const current = isActiveRun(run) ? { ...run, ...pickLive(detail) } : run
  const active = isActiveRun(current)
  const now = useTicker(active)
  const cancel = useCancelAiRun(ideaKey)
  const titleId = useId()
  const stepsId = useId()
  const cardRef = useRef<HTMLElement>(null)

  // Seen ending here: its outcome is announced (a row that loads finished says nothing).
  const [wasActive, setWasActive] = useState(active)
  const [endedHere, setEndedHere] = useState(false)
  if (wasActive !== active) {
    setWasActive(active)
    if (wasActive && !active) setEndedHere(true)
  }
  // Whether focus is (or was last, before it got lost) inside this row.
  const focusInside = useRef(false)
  useEffect(() => {
    if (!endedHere) return
    // Its Cancel just went. Focus moves only if it was here and fell to <body>.
    if (focusInside.current && focusLost()) {
      focusWhenRendered(() => cardRef.current, { force: true })
    }
  }, [endedHere])

  const latest = detail.events.at(-1)
  const requester = current.requested_by?.display_name ?? 'Someone'
  const agentName = current.agent.display_name
  const title = runTitle(current)
  const cancelling = current.cancel_requested
  const outcome = active ? null : outcomeWords(current, counted)

  return (
    <article
      ref={cardRef}
      id={runDomId(run.id)}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-run-status={current.status}
      onFocus={() => {
        focusInside.current = true
      }}
      onBlur={(event) => {
        // Focus moved somewhere else on purpose; a removed element blurs to nothing.
        const next = event.relatedTarget
        if (next instanceof Node && !event.currentTarget.contains(next)) {
          focusInside.current = false
        }
      }}
      className={cn('flex scroll-mt-20 flex-col outline-offset-2', className)}
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3">
        <Avatar
          name={agentName}
          isAgent
          agentBadge={false}
          size="sm"
          decorative
          className="mt-0.5"
        />
        <div className="flex min-w-0 flex-1 basis-56 flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 id={titleId} className="min-w-0 text-sm font-medium text-primary">
              {title} <span className="font-normal text-muted">· {agentName}</span>
            </h3>
            <AiBadge />
            {active && (
              <Badge variant={current.status === 'running' && !cancelling ? 'info' : 'neutral'}>
                {!cancelling && current.status === 'running' && <Spinner className="size-3" />}
                {runStatusLabel(current)}
              </Badge>
            )}
          </div>
          {active ? (
            <ActiveLine run={current} latest={latest} now={now} />
          ) : (
            outcome && <OutcomeLine run={current} outcome={outcome} />
          )}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {active
            ? current.can_cancel && (
                <Button
                  variant="ghost"
                  size="sm"
                  // Stays focusable while it cancels (aria-disabled), so focus isn't lost.
                  loading={cancel.isPending || cancelling}
                  onClick={() => cancel.mutate(current.id)}
                  aria-label={`Cancel: ${title} by ${agentName}`}
                >
                  {!cancel.isPending && !cancelling && <X />}
                  Cancel
                </Button>
              )
            : (retry ?? resultAction)}
          <Button
            variant="ghost"
            size="sm"
            className="text-muted"
            aria-expanded={open}
            aria-controls={stepsId}
            onClick={() => setOpen((value) => !value)}
          >
            Steps
            <ChevronDown
              className={cn('transition-transform duration-150', open && 'rotate-180')}
            />
          </Button>
        </div>
      </div>

      {open && (
        <div id={stepsId} className="flex flex-col gap-2 border-t border-subtle px-4 py-3 sm:pl-13">
          <p className="text-xs text-muted">
            Asked by {requester} <RelativeTime date={current.created_at} />
            {active && current.deadline_at && <> · stops by {formatTime(current.deadline_at)}</>}
          </p>
          <RunSteps events={detail.events} active={active} />
          {mode === 'polling' && active && (
            <p className="text-xs text-muted">
              Live updates aren’t available here: checking every few seconds.
            </p>
          )}
        </div>
      )}
      {/* Each new step is announced once, then how it ended (Soundings' own sentences). */}
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {active
          ? (latest?.message ?? '')
          : endedHere && outcome
            ? `${title} by ${agentName}: ${outcome.text}${outcome.next ? ` ${outcome.next}` : ''}`
            : ''}
      </p>
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

/** "Reading the rubric · 0:42 · 4 min left" while it works. */
function ActiveLine({
  run,
  latest,
  now,
}: {
  run: AiRun
  latest: AiRunEvent | undefined
  now: number
}) {
  const since = run.started_at ?? run.created_at
  const left = run.status === 'running' ? timeLeft(run.deadline_at, now) : null
  const step =
    run.status === 'queued' ? 'Waiting for a free worker' : (latest?.message ?? 'Starting')
  return (
    <p className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-sm text-secondary">
      <span className="min-w-0">{step}</span>
      <span aria-hidden="true" className="text-muted">
        ·
      </span>
      <span className="text-muted tabular-nums">
        <span aria-hidden="true">{elapsed(since, now)}</span>
        <span className="sr-only">running for {elapsedWords(since, now)}</span>
      </span>
      {left && (
        <>
          <span aria-hidden="true" className="text-muted">
            ·
          </span>
          <span className="text-muted">{left}</span>
        </>
      )}
    </p>
  )
}

interface Outcome {
  tone: 'success' | 'neutral' | 'warning' | 'danger'
  /** "Failed", "Timed out": read before the text, shown as the icon. */
  label: string
  text: string
  next?: string
}

/** How a finished run ended, in a sentence (and the next step when it stopped short). */
export function outcomeWords(run: AiRun, counted?: boolean): Outcome {
  if (run.status === 'succeeded') {
    const text =
      run.kind === 'evaluate'
        ? counted === false
          ? 'Evaluation submitted · not in the score yet'
          : counted
            ? 'Evaluation submitted · counted in the score'
            : 'Evaluation submitted'
        : run.kind === 'research'
          ? 'Research note saved'
          : 'Suggestion saved'
    return { tone: 'success', label: 'Done', text }
  }
  if (run.status === 'cancelled') {
    // A cancel that lands after the agent saved its result keeps it (contract-phase6 §3.4).
    const kept = run.result.evaluation_id
      ? 'its evaluation was submitted'
      : run.result.note_id
        ? 'its research note was saved'
        : run.result.suggestion_id
          ? 'its suggestion was saved'
          : null
    return {
      tone: 'neutral',
      label: 'Cancelled',
      text: kept ? `Cancelled · ${kept}` : 'Cancelled: nothing was saved.',
    }
  }
  const { what, next } = runErrorWords(run)
  return run.status === 'timed_out'
    ? { tone: 'warning', label: 'Timed out', text: what, next }
    : { tone: 'danger', label: 'Failed', text: what, next }
}

function OutcomeLine({ run, outcome }: { run: AiRun; outcome: Outcome }) {
  const Icon =
    outcome.tone === 'success'
      ? CircleCheck
      : outcome.tone === 'neutral'
        ? Ban
        : outcome.tone === 'warning'
          ? Clock
          : CircleAlert
  return (
    <p className="flex min-w-0 items-start gap-1.5 text-sm text-secondary">
      <Icon
        aria-hidden="true"
        className={cn(
          'mt-0.5 size-3.5 shrink-0',
          outcome.tone === 'success' && 'text-success',
          outcome.tone === 'neutral' && 'text-muted',
          outcome.tone === 'warning' && 'text-warning',
          outcome.tone === 'danger' && 'text-danger',
        )}
      />
      <span className="min-w-0">
        <span className="sr-only">{outcome.label}: </span>
        <span
          className={cn(outcome.tone !== 'success' && outcome.tone !== 'neutral' && 'text-primary')}
        >
          {outcome.text}
        </span>
        {outcome.next && <span className="text-muted"> {outcome.next}</span>}
        {run.finished_at && (
          <span className="text-muted">
            {' '}
            · <RelativeTime date={run.finished_at} />
          </span>
        )}
      </span>
    </p>
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
          // A time only where it moved on: several steps in the same minute share one.
          const time = formatTime(event.created_at)
          const previous = shown[index - 1]
          const sameTime = previous !== undefined && formatTime(previous.created_at) === time
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
                className={cn('shrink-0 text-xs text-muted tabular-nums', sameTime && 'invisible')}
              >
                {time}
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
