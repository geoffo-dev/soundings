/**
 * The fake kagent agent (dev/fake-agent) for the AI end-to-end tests (Phase 6) and the
 * shell.
 *
 * With E2E_AI=1 the local stack (start-stack.sh) runs it on
 * http://127.0.0.1:$E2E_FAKE_AGENT_PORT (8183) as the API's kagent controller and, after
 * every seed, registers E2E_AI_AGENT ("Idea evaluator", soundings/idea-evaluator, all
 * three purposes, Customer Innovation) with its key already handed over. It serves every
 * agent that has a key file `<namespace>.<name>` in E2E_FAKE_AGENT_KEYS_DIR (default
 * e2e/.stack/fake-agent-keys); what an agent does depends on its name's suffix
 * (dev/fake-agent/README.md: -slow, -lingers, -fails, -silent, -asks, -rejects,
 * -blind-probe, -strays, -late, -no-cancel, -unavailable, -drops).
 *
 * In a spec, after registering an agent (its key is shown once):
 *
 *   import { FakeAgent } from '../scripts/fake-agent.ts'
 *   const fake = new FakeAgent()
 *   fake.giveKey('soundings', 'idea-evaluator-slow', created.key.secret)   // "the operator"
 *   // ... request a run, cancel it ...
 *   const seen = await fake.waitFor(runId, (run) => run.cancel_requests > 0)
 *   seen.a2a_requests, seen.tool_calls, seen.blind, seen.strays, seen.late, seen.final_state
 *
 * Keys are written to files only (mode 600), never logged. Against an E2E_BASE_URL app
 * set E2E_FAKE_AGENT_URL and E2E_FAKE_AGENT_KEYS_DIR to its fake agent's.
 *
 * From a shell (Node 22.18+ runs TypeScript as is; 22.12-22.17 need
 * --experimental-strip-types):
 *
 *   node e2e/scripts/fake-agent.ts observations <run_id>   # what it saw of a run (JSON)
 *   node e2e/scripts/fake-agent.ts list | clear | url
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const LABEL = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/

/** The fake's base URL: E2E_FAKE_AGENT_URL, else http://127.0.0.1:$E2E_FAKE_AGENT_PORT (8183). */
export function fakeAgentUrl(): string {
  const url =
    process.env.E2E_FAKE_AGENT_URL ?? `http://127.0.0.1:${process.env.E2E_FAKE_AGENT_PORT ?? 8183}`
  return url.replace(/\/$/, '')
}

/**
 * Where the fake reads agents' keys: E2E_FAKE_AGENT_KEYS_DIR (a relative path is the
 * repository's, e.g. `dev/.fake-agent-keys` for `make demo DEMO_AI=1`, whatever directory
 * Playwright runs in), else <E2E_STATE_DIR>/fake-agent-keys.
 */
export function fakeAgentKeysDir(): string {
  if (process.env.E2E_FAKE_AGENT_KEYS_DIR) {
    const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
    return resolve(repo, process.env.E2E_FAKE_AGENT_KEYS_DIR)
  }
  const state =
    process.env.E2E_STATE_DIR ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '.stack')
  return join(state, 'fake-agent-keys')
}

/** One A2A request the fake received for a run (never a header's value). */
export interface FakeA2aRequest {
  at: string
  agent: string
  layout: 'kagent_v0_10' | 'kagent_v1_0' | 'byo'
  method: string | null
  a2a_version: string | null
  x_user_id: string | null
  authorization: 'none' | 'bearer' | 'other'
  cookie: boolean
  accept: string | null
  history_length: number | null
  task_id: string | null
  message_id: string | null
  context_id_sent: boolean
  configuration: string[] | null
}

/** What the fake saw and did in one run (dev/fake-agent/fake_agent/observations.py). */
export interface FakeRun {
  run_id: string
  agent?: string
  behaviour?: string
  kind?: 'evaluate' | 'research' | 'draft_section'
  idea?: string
  section_key?: string | null
  task_id?: string
  context_id?: string | null
  message_id?: string | null
  /** The run's message must carry no URL and no API key. */
  message_checks?: { has_url: boolean; has_api_key: boolean }
  a2a_requests: FakeA2aRequest[]
  tool_calls: { at: string; tool: string; error_code: string | null; phase: string }[]
  /** -blind-probe: what get_idea and search_ideas showed before and after its work. */
  blind: Record<string, unknown>[]
  /** -strays: the error code (or the listed projects/ideas) per attempt. */
  strays: Record<string, string | null>
  /** -late: its write after the run ended. */
  late: { at: string; tool: string; error_code: string | null } | null
  cancel_requests: number
  final_state: string | null
}

export class FakeAgent {
  readonly url: string
  readonly keysDir: string

  constructor(url = fakeAgentUrl(), keysDir = fakeAgentKeysDir()) {
    this.url = url
    this.keysDir = keysDir
  }

  /** Hand an agent its key, as an operator applies the Secret registration shows. */
  giveKey(namespace: string, name: string, key: string): void {
    if (!LABEL.test(namespace) || !LABEL.test(name)) throw new Error('not a Kubernetes name')
    if (!/^sdg_[A-Za-z0-9_]{8,}$/.test(key)) throw new Error('not a Soundings API key')
    mkdirSync(this.keysDir, { recursive: true, mode: 0o700 })
    writeFileSync(join(this.keysDir, `${namespace}.${name}`), `Bearer ${key}\n`, { mode: 0o600 })
  }

  /** Take the key away again: the agent then answers 404, like a deleted Agent. */
  removeKey(namespace: string, name: string): void {
    rmSync(join(this.keysDir, `${namespace}.${name}`), { force: true })
  }

  async observations(runId: string): Promise<FakeRun | null> {
    const response = await fetch(`${this.url}/_fake/observations/${encodeURIComponent(runId)}`)
    if (response.status === 404) return null
    if (!response.ok) throw new Error(`fake agent: ${response.status}`)
    return (await response.json()) as FakeRun
  }

  async all(): Promise<FakeRun[]> {
    const response = await fetch(`${this.url}/_fake/observations`)
    if (!response.ok) throw new Error(`fake agent: ${response.status}`)
    return ((await response.json()) as { runs: FakeRun[] }).runs
  }

  /** Poll until the run's observations satisfy `ready` (default: the fake saw it). */
  async waitFor(
    runId: string,
    ready: (run: FakeRun) => boolean = () => true,
    timeoutMs = 30_000,
  ): Promise<FakeRun> {
    const deadline = Date.now() + timeoutMs
    let last: FakeRun | null = null
    while (Date.now() < deadline) {
      last = await this.observations(runId)
      if (last && ready(last)) return last
      await new Promise((done) => setTimeout(done, 250))
    }
    throw new Error(`fake agent: run ${runId} not as expected: ${JSON.stringify(last)}`)
  }

  async clear(): Promise<void> {
    const response = await fetch(`${this.url}/_fake/observations`, { method: 'DELETE' })
    if (!response.ok) throw new Error(`fake agent: ${response.status}`)
  }

  async up(): Promise<boolean> {
    try {
      return (await fetch(`${this.url}/healthz`)).ok
    } catch {
      return false
    }
  }
}

const USAGE = `usage: node e2e/scripts/fake-agent.ts <command>
  observations <run_id>   what the fake saw of a run (JSON)
  list                    every run it saw: run id, agent, kind, final state
  clear                   forget them
  url                     its base URL`

async function main(argv: string[]): Promise<void> {
  const [command, ...args] = argv
  const fake = new FakeAgent()
  switch (command) {
    case 'observations': {
      if (!args[0]) throw new Error(USAGE)
      console.log(JSON.stringify(await fake.observations(args[0]), null, 2))
      return
    }
    case 'list':
      for (const run of await fake.all()) {
        console.log(
          `${run.run_id}  ${run.agent ?? '-'}  ${run.kind ?? '-'}  ${run.final_state ?? '-'}`,
        )
      }
      return
    case 'clear':
      return fake.clear()
    case 'url':
      console.log(fake.url)
      return
    default:
      throw new Error(USAGE)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  })
}
