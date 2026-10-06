import { expect, type Locator, type Page, test } from '@playwright/test'

import type { components } from '../../../frontend/src/api/generated/schema'
import { FakeAgent } from '../../scripts/fake-agent'
import {
  Api,
  createTeamProject,
  type CurrentUser,
  type Person,
  type Project,
  uniqueSuffix,
} from './api'

/**
 * AI assistance in the e2e suite (Phase 6, contract-phase6): agents registered through
 * the admin API as an admin would, their keys handed to Soundings' fake kagent agent
 * (dev/fake-agent, e2e/scripts/fake-agent.ts) as an operator applies the Secret, runs
 * requested and watched through the real API, worker, A2A and `/mcp`.
 *
 * Every spec registers agents of its own (run-unique names; the name's suffix picks the
 * fake's behaviour: `-slow`, `-lingers`, `-fails`, `-blind-probe`, ...) for a project of
 * its own, so specs run side by side and the stack's own "Idea evaluator"
 * (soundings/idea-evaluator, Customer Innovation) is never touched. `aiTest` skips unless
 * AI assistance is on and the fake answers (`E2E_AI=1`, or `make demo DEMO_AI=1` with
 * E2E_FAKE_AGENT_URL / E2E_FAKE_AGENT_KEYS_DIR); tag AI specs `@ai` (CI's e2e-ai job
 * greps for it).
 */

type Schemas = components['schemas']
export type AiAgent = Schemas['AiAgent']
export type AiAgentList = Schemas['AiAgentList']
export type CreatedAiAgent = Schemas['CreatedAiAgent']
export type AiRun = Schemas['AiRun']
export type AiRunDetail = Schemas['AiRunDetail']
export type AiRunList = Schemas['AiRunList']
export type AiRunKind = Schemas['AiRunKind']
export type AiRunEvent = Schemas['AiRunEvent']
export type ResearchNote = Schemas['ResearchNote']
export type Evaluation = Schemas['Evaluation']
export type EvaluationList = Schemas['EvaluationList']

export const NAMESPACE = 'soundings'
export const FINAL = ['succeeded', 'failed', 'cancelled', 'timed_out']

/**
 * What the fake agent writes into an evaluation (its rationale, summary and sources):
 * never shown to a pending evaluator. Research notes (`…/fake-agent/research/…`, "Fake
 * research source") are not score data and may be.
 */
export const AGENT_TEXT = /fake-rationale|Fake source \d|example\.org\/fake-agent\/(?!research\/)/i

let available: Promise<string | null> | undefined

/** Why AI specs can't run here (null: they can): AI off, or no fake agent to talk to. */
export function aiUnavailable(baseURL: string): Promise<string | null> {
  available ??= (async () => {
    const fake = new FakeAgent()
    if (!(await fake.up())) return `no fake kagent agent at ${fake.url} (E2E_AI=1)`
    const alice = await Api.as(baseURL, 'alice')
    try {
      const agents = await alice.get<AiAgentList>('/admin/ai-agents')
      return agents.settings.enabled ? null : 'AI assistance is off (SOUNDINGS_AI_ENABLED)'
    } finally {
      await alice.dispose()
    }
  })()
  return available
}

/** Skips the calling test (or describe block) unless AI specs can run. */
export async function skipWithoutAi() {
  const reason = await aiUnavailable(test.info().project.use.baseURL ?? '')
  test.skip(reason !== null, reason ?? '')
}

export interface RegisteredAgent {
  agent: AiAgent
  /** The key shown once; already with the fake. */
  secret: string
  created: CreatedAiAgent
}

/** A run-unique agent name ending in the fake's behaviour suffix (`-slow`, ...). */
export function agentName(behaviour = ''): string {
  return `e2e-${uniqueSuffix()}${behaviour ? `-${behaviour}` : ''}`
}

/**
 * Registers an agent through the admin API (as `admin`, a platform admin) and gives its
 * key to the fake, like an operator applying the Secret registration showed.
 */
export async function registerAgent(
  admin: Api,
  options: {
    projectIds: string[]
    purposes?: AiRunKind[]
    name?: string
    displayName?: string
    protocol?: 'kagent_v0_10' | 'kagent_v1_0'
  },
): Promise<RegisteredAgent> {
  const name = options.name ?? agentName()
  const created = await admin.send<CreatedAiAgent>(
    'POST',
    '/admin/ai-agents',
    {
      display_name: options.displayName ?? 'Idea evaluator',
      description: 'An e2e agent (Soundings’ fake kagent agent).',
      namespace: NAMESPACE,
      name,
      purposes: options.purposes ?? ['evaluate', 'research', 'draft_section'],
      project_ids: options.projectIds,
      ...(options.protocol ? { protocol: options.protocol } : {}),
    },
    201,
  )
  new FakeAgent().giveKey(NAMESPACE, name, created.key.secret)
  return { agent: created.agent, secret: created.key.secret, created }
}

/** Disables the agents (their runs stop, their keys are revoked) and takes the keys back. */
export async function retireAgents(admin: Api, agents: RegisteredAgent[]) {
  const fake = new FakeAgent()
  for (const { agent } of agents) {
    await admin.raw('PATCH', `/admin/ai-agents/${agent.id}`, { enabled: false })
    fake.removeKey(agent.namespace, agent.name)
  }
}

const RUN_PATH: Record<AiRunKind, string> = {
  evaluate: 'evaluation',
  research: 'research',
  draft_section: 'section-draft',
}

/** Asks an agent (201 new run, 200 the active one). */
export function requestRun(
  api: Api,
  key: string,
  kind: AiRunKind,
  agentId: string,
  sectionKey?: string,
) {
  return api.raw('POST', `/ideas/${key}/ai-runs/${RUN_PATH[kind]}`, {
    agent_id: agentId,
    ...(sectionKey ? { section_key: sectionKey } : {}),
  })
}

export async function askAgent(
  api: Api,
  key: string,
  kind: AiRunKind,
  agentId: string,
  sectionKey?: string,
): Promise<AiRun> {
  const response = await requestRun(api, key, kind, agentId, sectionKey)
  const body = await response.text()
  expect(response.status(), body).toBe(201)
  return JSON.parse(body) as AiRun
}

export function run(api: Api, key: string, runId: string): Promise<AiRunDetail> {
  return api.get(`/ideas/${key}/ai-runs/${runId}`)
}

/** Polls `get_ai_run` until the run is over (or `until` says so). */
export async function waitRun(
  api: Api,
  key: string,
  runId: string,
  until: (run: AiRunDetail) => boolean = (r) => FINAL.includes(r.status),
  timeoutMs = 60_000,
): Promise<AiRunDetail> {
  const deadline = Date.now() + timeoutMs
  let last: AiRunDetail | undefined
  while (Date.now() < deadline) {
    last = await run(api, key, runId)
    if (until(last)) return last
    await new Promise((done) => setTimeout(done, 300))
  }
  throw new Error(`run ${runId} still ${last?.status ?? 'unknown'} after ${timeoutMs} ms`)
}

/** The run's event stream as `api`'s person, read to its end (the server closes it after
 * the final event), parsed: what EventSource would deliver. */
export async function readEvents(
  api: Api,
  key: string,
  runId: string,
  lastEventId?: number,
): Promise<{ status: number; raw: string; events: AiRunEvent[]; contentType: string }> {
  const response = await api.context.get(`/api/v1/ideas/${key}/ai-runs/${runId}/events`, {
    headers: {
      Accept: 'text/event-stream',
      ...(lastEventId !== undefined ? { 'Last-Event-ID': String(lastEventId) } : {}),
    },
    timeout: 120_000,
  })
  const raw = await response.text()
  const events = raw
    .split('\n')
    .filter((line) => line.startsWith('data: '))
    .map((line) => JSON.parse(line.slice('data: '.length)) as AiRunEvent)
  return {
    status: response.status(),
    raw,
    events,
    contentType: response.headers()['content-type'] ?? '',
  }
}

export interface AiTeam {
  project: Project
  /**
   * The ideas' owner: a member created for this team, signed in (dev login). Runs are
   * asked as the owner, since each person may ask for 20 runs an hour (contract §3.3):
   * one person asking for every spec would run out.
   */
  owner: Api
  /** One idea per call of `idea()`: owned by `owner`, evaluating, with evaluators. */
  idea(options?: {
    title?: string
    submitted?: Person[]
    pending?: Person[]
    status?: 'evaluating' | 'shortlisted'
  }): Promise<string>
  /** Signs the owner's client out (the `api` fixture's clients go by themselves). */
  dispose(): Promise<void>
}

/** A new person (dev login), created by a platform admin, signed in. */
export async function newPerson(admin: Api, first: string): Promise<Api> {
  const run = uniqueSuffix()
  const user = await admin.createUser({
    email: `${first.toLowerCase()}.${run}@example.com`,
    display_name: `${first} ${run.slice(-4).toUpperCase()}`,
  })
  return Api.asUser(admin.baseURL, { ...user, auth_method: 'dev_login' } as unknown as CurrentUser)
}

/** Signs `page`'s context in as any user (e.g. a team's owner) with the dev login. */
export async function signInAs(page: Page, user: { id: string }) {
  const response = await page.request.post('/api/v1/auth/dev/login', {
    data: { user_id: user.id },
  })
  expect(response.status()).toBe(200)
}

/**
 * A private project of the spec's own: Alice (platform admin) its admin, a new person
 * owning its ideas (`owner`, a member), Bob and Carol members who score, Farah a member
 * who hasn't yet, Kenji a member.
 */
export async function aiTeam(alice: Api, name = 'AI'): Promise<AiTeam> {
  const project = await createTeamProject(alice, name, {
    bob: 'member',
    carol: 'member',
    farah: 'member',
    kenji: 'member',
  })
  const owner = await newPerson(alice, 'Olivia')
  await alice.addMemberUser(project.slug, owner.me)
  const people = new Map<Person, Api>()
  const as = async (person: Person) => {
    let client = people.get(person)
    if (!client) {
      client = await Api.as(alice.baseURL, person)
      people.set(person, client)
    }
    return client
  }
  return {
    project,
    owner,
    dispose: () => owner.dispose(),
    async idea(options = {}) {
      const submitted = options.submitted ?? ['bob', 'carol']
      const pending = options.pending ?? ['farah']
      const created = await alice.createIdea(project.slug, {
        title: options.title ?? `An idea for the agents ${uniqueSuffix()}`,
        summary: 'Customers book a slot and collect their order from a locker by the door.',
      })
      await alice.setOwnerUser(created.key, owner.me)
      if (options.status === 'shortlisted') {
        // Ready for a proposal (c7): shortlisted, the proposal started.
        await alice.changeStatus(created.key, 'shortlisted')
        await owner.startProposal(created.key)
        return created.key
      }
      await alice.changeStatus(created.key, 'evaluating')
      if (submitted.length + pending.length > 0) {
        await alice.invite(created.key, [...submitted, ...pending])
      }
      for (const [index, person] of submitted.entries()) {
        const score = index % 2 === 0 ? 4 : 2
        await (
          await as(person)
        ).evaluate(
          created.key,
          { Value: score, Feasibility: score, Effort: 3, 'Strategic fit': score, Risk: 3 },
          { recommendation: score >= 3 ? 'go' : 'maybe' },
        )
      }
      for (const client of people.values()) await client.dispose()
      people.clear()
      return created.key
    },
  }
}

/**
 * The run's steps on the idea page. A run is one quiet row (its current step, or how it
 * ended); who asked and every step are behind its "Steps" button, opened here.
 */
export async function runSteps(card: Locator): Promise<Locator> {
  const toggle = card.getByRole('button', { name: 'Steps' })
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
  return card.getByRole('list', { name: 'Steps' })
}
