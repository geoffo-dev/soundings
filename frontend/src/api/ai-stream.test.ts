import { describe, expect, it, vi } from 'vitest'

import type { AiRunDetail, AiRunEvent } from '@/api/types'

import { applyRunEvent, openRunStream, parseRunEvent, runEventsUrl } from './ai-stream'

const event = (
  seq: number,
  type: AiRunEvent['type'],
  message = 'Step',
  final = false,
): AiRunEvent => ({
  seq,
  type,
  message,
  created_at: `2026-10-06T09:00:0${seq % 10}Z`,
  final,
})

const run: AiRunDetail = {
  id: 'run-1',
  idea_id: 'idea-1',
  kind: 'evaluate',
  section_key: null,
  status: 'queued',
  agent: { id: 'agent-1', display_name: 'Idea evaluator', purposes: ['evaluate'], user_id: 'u-1' },
  requested_by: null,
  created_at: '2026-10-06T09:00:00Z',
  started_at: null,
  finished_at: null,
  deadline_at: null,
  cancel_requested: false,
  can_cancel: true,
  error: null,
  result: { evaluation_id: null, note_id: null, suggestion_id: null },
  event_count: 0,
  events: [],
}

describe('runEventsUrl', () => {
  it('builds the one stream endpoint per run, replaying after a seq', () => {
    expect(runEventsUrl('CUST-2', 'r1')).toBe('/api/v1/ideas/CUST-2/ai-runs/r1/events')
    expect(runEventsUrl('CUST-2', 'r1', 4)).toBe('/api/v1/ideas/CUST-2/ai-runs/r1/events?after=4')
  })
})

describe('parseRunEvent', () => {
  it('accepts an AiRunEvent and ignores anything else', () => {
    expect(parseRunEvent(JSON.stringify(event(1, 'queued', 'Waiting to start')))).toMatchObject({
      seq: 1,
      type: 'queued',
    })
    expect(parseRunEvent('not json')).toBeNull()
    expect(parseRunEvent(JSON.stringify({ ...event(1, 'queued'), type: 'agent_said' }))).toBeNull()
    expect(parseRunEvent(JSON.stringify({ ...event(1, 'queued'), seq: 0 }))).toBeNull()
    expect(parseRunEvent(JSON.stringify({ ...event(1, 'queued'), final: 'yes' }))).toBeNull()
    expect(parseRunEvent(undefined)).toBeNull()
    expect(parseRunEvent('x'.repeat(5000))).toBeNull()
  })
})

describe('applyRunEvent', () => {
  it('adds each event once, in order, and follows the status', () => {
    let detail = applyRunEvent(run, event(2, 'started', 'Sending'))
    detail = applyRunEvent(detail, event(1, 'queued'))
    detail = applyRunEvent(detail, event(2, 'started', 'Sending'))
    expect(detail.events.map((e) => e.seq)).toEqual([1, 2])
    expect(detail.status).toBe('running')
    expect(detail.started_at).toBe(event(2, 'started').created_at)
    detail = applyRunEvent(detail, event(3, 'cancel_requested', 'Cancelling'))
    expect(detail.cancel_requested).toBe(true)
    detail = applyRunEvent(detail, event(4, 'cancelled', 'Cancelled', true))
    expect(detail).toMatchObject({ status: 'cancelled', can_cancel: false, event_count: 4 })
  })

  it('keeps the failure’s sentence until the refetch brings the code', () => {
    const failed = applyRunEvent(
      run,
      event(5, 'timed_out', 'The agent didn’t finish in time.', true),
    )
    expect(failed).toMatchObject({
      status: 'timed_out',
      error: { code: 'timed_out', message: 'The agent didn’t finish in time.' },
    })
  })
})

/** A stand-in EventSource the tests drive. */
class FakeEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  static last: FakeEventSource | null = null
  readyState = FakeEventSource.CONNECTING
  url: string
  onopen: (() => void) | null = null
  onmessage: ((message: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn(() => {
    this.readyState = FakeEventSource.CLOSED
  })
  constructor(url: string) {
    this.url = url
    FakeEventSource.last = this
  }
  emit(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
  fail(state: number) {
    this.readyState = state
    this.onerror?.()
  }
}

const Impl = FakeEventSource as unknown as typeof EventSource

describe('openRunStream', () => {
  it('passes events on and closes itself after the final one', () => {
    const onEvent = vi.fn()
    const onFallback = vi.fn()
    openRunStream({
      idea: 'CUST-2',
      runId: 'r1',
      after: 2,
      onEvent,
      onFallback,
      EventSourceImpl: Impl,
    })
    const source = FakeEventSource.last
    expect(source?.url).toBe('/api/v1/ideas/CUST-2/ai-runs/r1/events?after=2')
    source?.emit(event(3, 'tool_called', 'Read the idea'))
    source?.emit({ nonsense: true })
    source?.emit(event(4, 'succeeded', 'Done', true))
    expect(onEvent.mock.calls.map(([e]) => (e as AiRunEvent).seq)).toEqual([3, 4])
    expect(source?.close).toHaveBeenCalled()
    expect(onFallback).not.toHaveBeenCalled()
  })

  it('falls back to polling when the server refuses or the stream keeps failing', () => {
    const refused = vi.fn()
    openRunStream({
      idea: 'X-1',
      runId: 'r',
      onEvent: vi.fn(),
      onFallback: refused,
      EventSourceImpl: Impl,
    })
    FakeEventSource.last?.fail(FakeEventSource.CLOSED)
    expect(refused).toHaveBeenCalledTimes(1)

    const flaky = vi.fn()
    openRunStream({
      idea: 'X-1',
      runId: 'r',
      onEvent: vi.fn(),
      onFallback: flaky,
      EventSourceImpl: Impl,
    })
    const source = FakeEventSource.last
    source?.fail(FakeEventSource.CONNECTING)
    source?.fail(FakeEventSource.CONNECTING)
    expect(flaky).not.toHaveBeenCalled()
    source?.fail(FakeEventSource.CONNECTING)
    expect(flaky).toHaveBeenCalledTimes(1)
    expect(source?.close).toHaveBeenCalled()
  })

  it('polls straight away where there is no EventSource', async () => {
    const onFallback = vi.fn()
    openRunStream({
      idea: 'X-1',
      runId: 'r',
      onEvent: vi.fn(),
      onFallback,
      EventSourceImpl: undefined,
    })
    await Promise.resolve()
    expect(onFallback).toHaveBeenCalledTimes(1)
  })

  it('does nothing more once closed by its owner', () => {
    const onEvent = vi.fn()
    const onFallback = vi.fn()
    const stream = openRunStream({
      idea: 'X-1',
      runId: 'r',
      onEvent,
      onFallback,
      EventSourceImpl: Impl,
    })
    const source = FakeEventSource.last
    stream.close()
    source?.emit(event(1, 'queued'))
    source?.fail(FakeEventSource.CLOSED)
    expect(onEvent).not.toHaveBeenCalled()
    expect(onFallback).not.toHaveBeenCalled()
  })
})
