import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

/** Waits until `${url}/readyz` answers 200 (the app is up and the database reachable). */
async function waitUntilReady(url: string, seconds: number) {
  const deadline = Date.now() + seconds * 1000
  for (;;) {
    try {
      if ((await fetch(`${url}/readyz`)).ok) return
    } catch {
      // not listening yet
    }
    if (Date.now() > deadline) throw new Error(`The app at ${url} is not ready (/readyz).`)
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
}

export default async function globalSetup() {
  const external = process.env.E2E_BASE_URL
  if (external) {
    await waitUntilReady(external.replace(/\/$/, ''), 180)
    return
  }
  // Starts (or reseeds) the local stack; see scripts/start-stack.sh.
  execFileSync(join(here, 'scripts', 'start-stack.sh'), { stdio: 'inherit' })
  await waitUntilReady(`http://localhost:${process.env.E2E_PORT ?? 8100}`, 60)
}
