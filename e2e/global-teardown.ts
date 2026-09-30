import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

/** Stops the local stack, unless it was given (E2E_BASE_URL) or should stay (E2E_KEEP_STACK=1). */
export default function globalTeardown() {
  if (process.env.E2E_BASE_URL || process.env.E2E_KEEP_STACK === '1') return
  execFileSync(join(here, 'scripts', 'stop-stack.sh'), { stdio: 'inherit' })
}
