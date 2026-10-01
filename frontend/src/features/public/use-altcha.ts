import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchAltchaChallenge } from '@/api/public'
import type { AltchaChallenge } from '@/api/types'

export type AltchaState = 'idle' | 'verifying' | 'verified' | 'error'

export type AltchaSolver = (
  challenge: AltchaChallenge,
  signal: AbortSignal,
) => Promise<string | null>

/** The real solver, loaded with the form's first input (it brings the worker). */
const defaultSolver: AltchaSolver = async (challenge, signal) => {
  const { solveAltcha } = await import('./altcha-solver')
  return solveAltcha(challenge, signal)
}

/** A solution is refreshed when its challenge has less than this left. */
const EXPIRY_MARGIN_MS = 60_000

interface Solved {
  payload: string
  expiresAt: number
}

/** The solved payload while its challenge has time left. */
function freshPayload(solved: Solved | null, now = Date.now()): string | null {
  return solved && solved.expiresAt - now > EXPIRY_MARGIN_MS ? solved.payload : null
}

/**
 * The public form's proof of work (contract-phase4 §3.5): it starts on the
 * form's first input (`start`), or on submit (`getPayload`) if it hasn't, and
 * runs in workers, so typing never stutters. A payload is accepted once:
 * `discard` after every attempt that reached the server, and the next one is
 * solved in the background. An expired solution is solved again.
 */
export function useAltcha(slug: string, solver: AltchaSolver = defaultSolver) {
  const [state, setState] = useState<AltchaState>('idle')
  const solved = useRef<Solved | null>(null)
  const job = useRef<Promise<string | null> | null>(null)
  const controller = useRef<AbortController | null>(null)

  useEffect(
    () => () => {
      controller.current?.abort()
    },
    [],
  )

  const run = useCallback((): Promise<string | null> => {
    if (job.current) return job.current
    const abort = new AbortController()
    controller.current = abort
    setState('verifying')
    const promise = (async () => {
      try {
        const challenge = await fetchAltchaChallenge(slug, abort.signal)
        const payload = await solver(challenge, abort.signal)
        if (abort.signal.aborted) return null
        if (!payload) throw new Error('No solution')
        solved.current = { payload, expiresAt: challenge.parameters.expiresAt * 1000 }
        setState('verified')
        return payload
      } catch {
        if (!abort.signal.aborted) setState('error')
        solved.current = null
        return null
      } finally {
        if (controller.current === abort) job.current = null
      }
    })()
    job.current = promise
    return promise
  }, [slug, solver])

  /** Start solving now (the form's first input), unless it already is or has. */
  const start = useCallback(() => {
    if (!freshPayload(solved.current) && !job.current) void run()
  }, [run])

  /** A payload to send: the solved one, or wait for (or start) a solve. Null if it failed. */
  const getPayload = useCallback(async (): Promise<string | null> => {
    const payload = freshPayload(solved.current)
    if (payload) return payload
    solved.current = null
    return run()
  }, [run])

  /** The payload was sent (it can't be used again): solve the next one in the background. */
  const discard = useCallback(
    (options: { next?: boolean } = {}) => {
      solved.current = null
      if (options.next ?? true) void run()
      else setState('idle')
    },
    [run],
  )

  /** Stop solving (the form is gone). */
  const cancel = useCallback(() => {
    controller.current?.abort()
    job.current = null
    solved.current = null
    setState('idle')
  }, [])

  return { state, start, getPayload, discard, retry: run, cancel }
}
