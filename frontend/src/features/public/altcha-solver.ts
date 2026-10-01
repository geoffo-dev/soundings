/**
 * The ALTCHA proof of work (contract-phase4 §3.5; research R1 §7), solved in
 * this browser with altcha@3's own solver and its PBKDF2 worker, bundled by
 * Vite as a same-origin worker file: no CDN, no `blob:` worker, no
 * WebAssembly (the worker uses WebCrypto), so it works offline and under the
 * app's Content Security Policy. Loaded lazily by the public form.
 *
 * The payload is exactly what the `<altcha-widget>` posts (base64 of
 * `{challenge: {parameters, signature}, solution}`), with the challenge's
 * signed `data` passed back unchanged; the API verifies it with Python
 * `altcha` 2.x.
 */
import { solveChallengeWorkers } from 'altcha/lib'
import Pbkdf2Worker from 'altcha/workers/pbkdf2?worker'

import type { AltchaChallenge } from '@/api/types'

/** Gives up after this long (a very slow phone): the form offers Retry. */
const SOLVE_TIMEOUT_MS = 90_000

export async function solveAltcha(
  challenge: AltchaChallenge,
  signal: AbortSignal,
): Promise<string | null> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal.addEventListener('abort', abort)
  try {
    const cores = typeof navigator === 'undefined' ? 2 : navigator.hardwareConcurrency || 2
    const solution = await solveChallengeWorkers({
      challenge,
      concurrency: Math.min(4, Math.max(1, cores)),
      controller,
      createWorker: () => new Pbkdf2Worker(),
      counterMode: 'uint32',
      timeout: SOLVE_TIMEOUT_MS,
    })
    if (!solution || signal.aborted) return null
    return btoa(
      JSON.stringify({
        challenge: { parameters: challenge.parameters, signature: challenge.signature },
        solution,
      }),
    )
  } finally {
    signal.removeEventListener('abort', abort)
  }
}
