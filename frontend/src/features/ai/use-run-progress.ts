import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useState } from 'react'

import { runFinished, useAiRun } from '@/api/ai'
import { applyRunEvent, openRunStream } from '@/api/ai-stream'
import { queryKeys } from '@/api/keys'
import type { AiRun, AiRunDetail, AiRunEvent } from '@/api/types'

import { isActiveRun } from './ai-copy'

export type ProgressMode = 'stream' | 'polling' | 'idle'

/**
 * A run's events, live: while the run is active its event stream (SSE) feeds
 * the run's cache entry; where streaming fails it polls `get_ai_run` every
 * 2.5 s instead. When the run ends the run, its list and whatever its result
 * changed are refetched (`runFinished`). A finished run is read once.
 */
export function useRunProgress(
  ideaKey: string,
  run: AiRun,
  options: { enabled?: boolean } = {},
): { detail: AiRunDetail; mode: ProgressMode } {
  const queryClient = useQueryClient()
  const enabled = options.enabled ?? true
  const active = isActiveRun(run)
  const [fallback, setFallback] = useState(false)
  const query = useAiRun(ideaKey, run.id, {
    enabled: enabled && (!active || fallback),
    poll: active && fallback,
  })
  // Seeded from the list until the first event or fetch.
  const detail = query.data ?? { ...run, events: [] }
  const key = queryKeys.ai.run(ideaKey, run.id)

  const onEvent = useEffectEvent((event: AiRunEvent) => {
    queryClient.setQueryData<AiRunDetail>(key, (old) =>
      applyRunEvent(old ?? { ...run, events: [] }, event),
    )
    // The list carries the deadline once the run has started.
    if (event.type === 'started') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(ideaKey) })
    }
    if (event.final) runFinished(queryClient, ideaKey, run)
  })
  const lastSeen = useEffectEvent(
    () => queryClient.getQueryData<AiRunDetail>(key)?.events.at(-1)?.seq ?? 0,
  )

  useEffect(() => {
    if (!enabled || !active || fallback) return
    const stream = openRunStream({
      idea: ideaKey,
      runId: run.id,
      after: lastSeen(),
      onEvent,
      onFallback: () => setFallback(true),
    })
    return () => stream.close()
  }, [enabled, active, fallback, ideaKey, run.id])

  // Polling saw the end: refetch what the result changed, once.
  const polledFinal = Boolean(fallback && active && query.data && !isActiveRun(query.data))
  const finish = useEffectEvent(() => runFinished(queryClient, ideaKey, run))
  useEffect(() => {
    if (polledFinal) finish()
  }, [polledFinal])

  return { detail, mode: !active ? 'idle' : fallback ? 'polling' : 'stream' }
}
