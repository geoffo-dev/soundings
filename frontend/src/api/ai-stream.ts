/**
 * Live progress of one AI run (contract-phase6 §3.6): an `EventSource` on
 * `GET /ideas/{idea}/ai-runs/{run_id}/events`, same origin with the session
 * cookie. Each message is an `AiRunEvent` (Soundings' fixed sentences: no agent
 * text, no score data); the browser reconnects with `Last-Event-ID` and the
 * server replays what was missed. After the event with `final: true` the stream
 * is closed here, so the browser doesn't reconnect.
 *
 * Where streaming doesn't work (no EventSource, a proxy that buffers, a 401 /
 * 404 / 429 / 204 answer, repeated errors) `onFallback` fires once and the
 * caller polls `get_ai_run` instead (`useAiRun(…, { poll: true })`).
 *
 * The one place the SPA talks to the API without `client.ts`: EventSource
 * can't go through fetch middleware. It sends nothing but the URL and cookies.
 */
import type { AiRunDetail, AiRunEvent, AiRunEventType, AiRunStatus } from '@/api/types'

const EVENT_TYPES: readonly AiRunEventType[] = [
  'queued',
  'started',
  'retrying',
  'agent_accepted',
  'agent_working',
  'tool_called',
  'result_recorded',
  'cancel_requested',
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
]

/** Consecutive errors (reconnects) before giving up on the stream. */
const MAX_ERRORS = 3

export function runEventsUrl(idea: string, runId: string, after = 0): string {
  const path = `/api/v1/ideas/${encodeURIComponent(idea)}/ai-runs/${encodeURIComponent(runId)}/events`
  return after > 0 ? `${path}?after=${after}` : path
}

/** A message's data as an `AiRunEvent`, or null when it isn't one (ignored). */
export function parseRunEvent(data: unknown): AiRunEvent | null {
  if (typeof data !== 'string' || data.length > 4096) return null
  let value: unknown
  try {
    value = JSON.parse(data)
  } catch {
    return null
  }
  if (typeof value !== 'object' || value === null) return null
  const event = value as Record<string, unknown>
  if (
    typeof event.seq !== 'number' ||
    !Number.isInteger(event.seq) ||
    event.seq < 1 ||
    typeof event.type !== 'string' ||
    !EVENT_TYPES.includes(event.type as AiRunEventType) ||
    typeof event.message !== 'string' ||
    typeof event.created_at !== 'string' ||
    typeof event.final !== 'boolean'
  ) {
    return null
  }
  return {
    seq: event.seq,
    type: event.type as AiRunEventType,
    message: event.message.slice(0, 300),
    created_at: event.created_at,
    final: event.final,
  }
}

const FINAL_STATUS: Partial<Record<AiRunEventType, AiRunStatus>> = {
  succeeded: 'succeeded',
  failed: 'failed',
  cancelled: 'cancelled',
  timed_out: 'timed_out',
}

/**
 * The run as the stream says it is now: the event added (once, in order) and
 * what it implies for the status, until the refetch after the final event
 * brings the whole run (error code, result).
 */
export function applyRunEvent(detail: AiRunDetail, event: AiRunEvent): AiRunDetail {
  if (detail.events.some((existing) => existing.seq === event.seq)) return detail
  const events = [...detail.events, event].sort((a, b) => a.seq - b.seq)
  const next: AiRunDetail = {
    ...detail,
    events,
    event_count: Math.max(detail.event_count, event.seq),
  }
  const final = FINAL_STATUS[event.type]
  if (final) {
    return {
      ...next,
      status: final,
      finished_at: event.created_at,
      deadline_at: null,
      can_cancel: false,
      cancel_requested: false,
      error:
        final === 'failed' || final === 'timed_out'
          ? (detail.error ?? {
              code: final === 'timed_out' ? 'timed_out' : 'internal_error',
              message: event.message,
            })
          : null,
    }
  }
  if (event.type === 'started' && detail.status === 'queued') {
    return { ...next, status: 'running', started_at: detail.started_at ?? event.created_at }
  }
  if (event.type === 'cancel_requested') return { ...next, cancel_requested: true }
  return next
}

export interface RunStreamOptions {
  idea: string
  runId: string
  /** Replay only events after this seq (what is already on screen). */
  after?: number
  onEvent: (event: AiRunEvent) => void
  /** Streaming isn't possible here: poll instead. Called at most once. */
  onFallback: () => void
  /** For tests: the EventSource implementation (default: the browser's). */
  EventSourceImpl?: typeof EventSource
}

export interface RunStream {
  close: () => void
}

export function openRunStream({
  idea,
  runId,
  after = 0,
  onEvent,
  onFallback,
  EventSourceImpl = typeof EventSource === 'undefined' ? undefined : EventSource,
}: RunStreamOptions): RunStream {
  let closed = false
  let fellBack = false
  const fallBack = () => {
    if (fellBack || closed) return
    fellBack = true
    onFallback()
  }
  if (!EventSourceImpl) {
    // jsdom, old browsers: poll from the start (after the caller's first render).
    queueMicrotask(fallBack)
    return { close: () => (closed = true) }
  }
  let source: EventSource
  try {
    source = new EventSourceImpl(runEventsUrl(idea, runId, after))
  } catch {
    queueMicrotask(fallBack)
    return { close: () => (closed = true) }
  }
  let errors = 0
  const close = () => {
    closed = true
    source.close()
  }
  source.onopen = () => {
    errors = 0
  }
  source.onmessage = (message: MessageEvent) => {
    errors = 0
    const event = parseRunEvent(message.data)
    if (!event || closed) return
    onEvent(event)
    // The run is over: don't let the browser reconnect (the server would answer 204).
    if (event.final) close()
  }
  source.onerror = () => {
    if (closed) return
    errors += 1
    // CLOSED: the server refused (401, 404, 429, 204) or the response wasn't a stream.
    if (source.readyState === EventSourceImpl.CLOSED || errors >= MAX_ERRORS) {
      source.close()
      fallBack()
      closed = true
    }
  }
  return { close }
}
