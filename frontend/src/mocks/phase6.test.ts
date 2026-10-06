import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import type { AiRun, AiRunEvent } from '@/api/types'
import { MOCK_AI_OUTCOME_STORAGE_KEY, MOCK_AI_PACE_STORAGE_KEY } from '@/mocks/ai'
import { getDb, PROJECTS, resetDb, USERS } from '@/mocks/db'
import { AGENTS, PHASE6_USERS, RESEARCH_NOTE_ID, RUNS } from '@/mocks/phase6-fixtures'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '2')
  localStorage.removeItem(MOCK_AI_OUTCOME_STORAGE_KEY)
})
afterEach(() => {
  server.resetHandlers()
  endSession()
})
afterAll(() => server.close())

async function signIn(userId: string) {
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('expected the request to fail')
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function waitForRun(
  idea: string,
  runId: string,
  done = (run: AiRun) => run.status !== 'queued' && run.status !== 'running',
) {
  for (let i = 0; i < 200; i++) {
    const { data } = await api.GET('/api/v1/ideas/{idea}/ai-runs/{run_id}', {
      params: { path: { idea, run_id: runId } },
    })
    if (data && done(data)) return data
    await sleep(5)
  }
  throw new Error('the run never finished')
}

function askEvaluation(idea: string, agentId: string = AGENTS.evaluator) {
  return api.POST('/api/v1/ideas/{idea}/ai-runs/evaluation', {
    params: { path: { idea } },
    body: { agent_id: agentId },
  })
}

/** Reads an SSE response to its end (the mock closes after the final event). */
async function readStream(path: string, headers: Record<string, string> = {}) {
  const response = await fetch(new URL(path, window.location.origin), {
    headers: { Accept: 'text/event-stream', ...headers },
  })
  const text = response.status === 200 ? await response.text() : ''
  const events = text
    .split('\n\n')
    .map((block) => block.split('\n').find((line) => line.startsWith('data: ')))
    .filter((line): line is string => Boolean(line))
    .map((line) => JSON.parse(line.slice('data: '.length)) as AiRunEvent)
  return { response, text, events }
}

const SCORE_LIKE =
  /"(score|scores|aggregate|overall|recommendation|rationale|sources|comment|mean)"/

describe('AI permissions on the idea (role matrix J, c10)', () => {
  it('lets the owner ask the evaluate and research agents of the project', async () => {
    await signIn(USERS.alice) // owner of CUST-2
    const { data } = await api.GET('/api/v1/ideas/{idea}/ai-runs', {
      params: { path: { idea: 'CUST-2' } },
    })
    expect(data?.ai_enabled).toBe(true)
    expect(data?.agents.map((agent) => agent.display_name)).toEqual([
      'Idea evaluator',
      'Research agent',
    ])
    expect(data?.permissions).toMatchObject({
      can_request_evaluation: true,
      can_research: true,
      can_draft_section: false,
      draft_section_blocked_by: 'proposal_not_available',
      can_include_ai: true,
    })
  })

  it('explains why members, closed evaluation and a switched-off instance can’t ask', async () => {
    await signIn(USERS.bob) // member of CUST, not the owner of CUST-2
    const member = await api.GET('/api/v1/ideas/{idea}/ai-runs', {
      params: { path: { idea: 'CUST-2' } },
    })
    expect(member.data?.permissions).toMatchObject({
      can_request_evaluation: false,
      request_evaluation_blocked_by: 'not_allowed',
      can_include_ai: false,
      include_ai_blocked_by: 'not_allowed',
    })
    const denied = await rejection(askEvaluation('CUST-2'))
    expect(denied).toMatchObject({ status: 403, code: 'forbidden' })

    await signIn(USERS.alice)
    const closed = await api.GET('/api/v1/ideas/{idea}/ai-runs', {
      params: { path: { idea: 'CUST-3' } }, // evaluation closed, in Proposal
    })
    expect(closed.data?.permissions.request_evaluation_blocked_by).toBe('evaluation_closed')
    expect(closed.data?.permissions.can_draft_section).toBe(true)

    getDb().aiSettings.enabled = false
    const off = await api.GET('/api/v1/ideas/{idea}/ai-runs', {
      params: { path: { idea: 'CUST-2' } },
    })
    expect(off.data).toMatchObject({ ai_enabled: false, agents: [] })
    expect(off.data?.permissions.research_blocked_by).toBe('ai_off')
    expect(await rejection(askEvaluation('CUST-2'))).toMatchObject({
      status: 409,
      code: 'ai_unavailable',
    })
  })

  it('refuses an agent that doesn’t pass c10 with the same 409, and hides private ideas', async () => {
    await signIn(USERS.alice)
    // The Research agent doesn't evaluate; Market scout is disabled.
    expect(await rejection(askEvaluation('CUST-2', AGENTS.research))).toMatchObject({
      status: 409,
      code: 'ai_unavailable',
    })
    expect(await rejection(askEvaluation('CUST-2', AGENTS.scout))).toMatchObject({
      code: 'ai_unavailable',
    })
    await signIn(USERS.ivan) // no roles: Internal Tools is private
    expect(
      await rejection(
        api.GET('/api/v1/ideas/{idea}/ai-runs', { params: { path: { idea: 'TOOL-1' } } }),
      ),
    ).toMatchObject({ status: 404 })
  })
})

describe('AI evaluation runs', () => {
  it('runs once per idea and agent (201, then 200 with the same run)', async () => {
    localStorage.setItem(MOCK_AI_OUTCOME_STORAGE_KEY, 'queued')
    await signIn(USERS.alice)
    const first = await askEvaluation('CUST-2')
    expect(first.response.status).toBe(201)
    const again = await askEvaluation('CUST-2')
    expect(again.response.status).toBe(200)
    expect(again.data?.id).toBe(first.data?.id)
    // The agent is an evaluator now (no notification: service accounts get none).
    const { data: idea } = await api.GET('/api/v1/ideas/{idea}', {
      params: { path: { idea: 'CUST-2' } },
    })
    expect(idea?.evaluators.find((e) => e.is_ai)).toMatchObject({
      state: 'invited',
      user: { display_name: 'Idea evaluator' },
    })
  })

  it('submits a cited AI evaluation that is left out of the score until included', async () => {
    await signIn(USERS.alice)
    const before = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'CUST-2' } } })
    const asked = await askEvaluation('CUST-2')
    const run = await waitForRun('CUST-2', asked.data?.id ?? '')
    expect(run.status).toBe('succeeded')
    expect(run.events.map((event) => event.message)).toEqual([
      'Waiting to start',
      'Sending the request to the agent',
      'The agent started',
      'The agent is working',
      'Read the rubric',
      'Read the idea',
      'Saved its evaluation',
      'Evaluation submitted',
      'Done',
    ])
    expect(run.events.at(-1)?.final).toBe(true)

    const { data: list } = await api.GET('/api/v1/ideas/{idea}/evaluations', {
      params: { path: { idea: 'CUST-2' } },
    })
    const ai = list?.items.find((item) => item.is_ai)
    expect(ai).toMatchObject({ id: run.result.evaluation_id, include_in_aggregate: false })
    expect(
      ai?.scores.every((score) => score.comment.length > 0 && score.sources.length === 2),
    ).toBe(true)
    expect(ai?.scores[0]?.sources[0]?.host).toBe('example.org')
    const after = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'CUST-2' } } })
    expect(after.data?.aggregate?.count).toBe(before.data?.aggregate?.count)
    expect(after.data?.score?.overall).toBe(before.data?.score?.overall)

    const include = await api.PUT(
      '/api/v1/ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate',
      {
        params: { path: { idea: 'CUST-2', evaluation_id: ai?.id ?? '' } },
        body: { include: true },
      },
    )
    expect(include.data?.include_in_aggregate).toBe(true)
    const included = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'CUST-2' } } })
    expect(included.data?.aggregate?.count).toBe((before.data?.aggregate?.count ?? 0) + 1)
    await api.PUT('/api/v1/ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate', {
      params: { path: { idea: 'CUST-2', evaluation_id: ai?.id ?? '' } },
      body: { include: false },
    })
    const excluded = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'CUST-2' } } })
    expect(excluded.data?.aggregate?.count).toBe(before.data?.aggregate?.count)
  })

  it('refuses the toggle on a person’s evaluation (409) and for pending evaluators (404)', async () => {
    await signIn(USERS.carol) // owner of CUST-7
    const { data } = await api.GET('/api/v1/ideas/{idea}/evaluations', {
      params: { path: { idea: 'CUST-7' } },
    })
    const person = data?.items.find((item) => !item.is_ai)
    expect(
      await rejection(
        api.PUT('/api/v1/ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate', {
          params: { path: { idea: 'CUST-7', evaluation_id: person?.id ?? '' } },
          body: { include: false },
        }),
      ),
    ).toMatchObject({ status: 409, code: 'not_ai_evaluation' })
    const ai = data?.items.find((item) => item.is_ai)
    await signIn(USERS.alice) // pending evaluator on CUST-7
    expect(
      await rejection(
        api.PUT('/api/v1/ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate', {
          params: { path: { idea: 'CUST-7', evaluation_id: ai?.id ?? '' } },
          body: { include: true },
        }),
      ),
    ).toMatchObject({ status: 404 })
  })

  it('takes the agent off the evaluators again when its run fails', async () => {
    localStorage.setItem(MOCK_AI_OUTCOME_STORAGE_KEY, 'fail')
    await signIn(USERS.alice)
    const asked = await askEvaluation('CUST-2')
    const run = await waitForRun('CUST-2', asked.data?.id ?? '')
    expect(run).toMatchObject({
      status: 'failed',
      error: { code: 'agent_failed', message: 'The agent stopped with an error.' },
    })
    const { data: idea } = await api.GET('/api/v1/ideas/{idea}', {
      params: { path: { idea: 'CUST-2' } },
    })
    expect(idea?.evaluators.some((e) => e.is_ai)).toBe(false)
    const { data: feed } = await api.GET('/api/v1/ideas/{idea}/activity', {
      params: { path: { idea: 'CUST-2' } },
    })
    // Newest first: the run ended without an evaluation and took the assignment back.
    expect(feed?.items[0]).toMatchObject({ type: 'evaluator_removed', actor: null })
  })

  it('cancels a queued run at once and a running one through a request', async () => {
    localStorage.setItem(MOCK_AI_OUTCOME_STORAGE_KEY, 'queued')
    await signIn(USERS.alice)
    const queued = await askEvaluation('CUST-2')
    const cancelled = await api.POST('/api/v1/ideas/{idea}/ai-runs/{run_id}/cancel', {
      params: { path: { idea: 'CUST-2', run_id: queued.data?.id ?? '' } },
    })
    expect(cancelled.data?.status).toBe('cancelled')
    expect(
      await rejection(
        api.POST('/api/v1/ideas/{idea}/ai-runs/{run_id}/cancel', {
          params: { path: { idea: 'CUST-2', run_id: queued.data?.id ?? '' } },
        }),
      ),
    ).toMatchObject({ status: 409, code: 'ai_run_finished' })

    localStorage.setItem(MOCK_AI_OUTCOME_STORAGE_KEY, 'slow')
    const slow = await api.POST('/api/v1/ideas/{idea}/ai-runs/research', {
      params: { path: { idea: 'CUST-2' } },
      body: { agent_id: AGENTS.research },
    })
    await waitForRun('CUST-2', slow.data?.id ?? '', (run) => run.status === 'running')
    const requested = await api.POST('/api/v1/ideas/{idea}/ai-runs/{run_id}/cancel', {
      params: { path: { idea: 'CUST-2', run_id: slow.data?.id ?? '' } },
    })
    expect(requested.data).toMatchObject({ status: 'running', cancel_requested: true })
    const ended = await waitForRun('CUST-2', slow.data?.id ?? '')
    expect(ended.status).toBe('cancelled')
    expect(ended.events.map((event) => event.type)).toContain('cancel_requested')
  })

  it('times out a run that doesn’t finish', async () => {
    localStorage.setItem(MOCK_AI_OUTCOME_STORAGE_KEY, 'timeout')
    localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '40')
    await signIn(USERS.alice)
    const asked = await askEvaluation('CUST-2')
    const run = await waitForRun('CUST-2', asked.data?.id ?? '')
    expect(run).toMatchObject({ status: 'timed_out', error: { code: 'timed_out' } })
  }, 10_000)
})

describe('blind safety (role matrix §3, contract §3.6)', () => {
  it('shows a pending evaluator the runs and their steps, never score data', async () => {
    await signIn(USERS.alice) // pending on CUST-7, where Idea evaluator has submitted
    const { data: list } = await api.GET('/api/v1/ideas/{idea}/ai-runs', {
      params: { path: { idea: 'CUST-7' } },
    })
    expect(list?.items.map((run) => run.id)).toEqual([RUNS.cust7Evaluation])
    expect(JSON.stringify(list)).not.toMatch(SCORE_LIKE)
    const detail = await api.GET('/api/v1/ideas/{idea}/ai-runs/{run_id}', {
      params: { path: { idea: 'CUST-7', run_id: RUNS.cust7Evaluation } },
    })
    const body = JSON.stringify(detail.data)
    expect(body).not.toMatch(SCORE_LIKE)
    // None of the agent's rationale or sources reach the run.
    expect(body).not.toMatch(/Customers already send video|example\.org/)
    const { data: evaluations } = await api.GET('/api/v1/ideas/{idea}/evaluations', {
      params: { path: { idea: 'CUST-7' } },
    })
    expect(evaluations).toEqual({ items: [], score_hidden: true })
  })

  it('streams only Soundings’ fixed sentences to a pending evaluator', async () => {
    localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '15')
    await signIn(USERS.carol)
    const asked = await askEvaluation('CUST-7')
    await signIn(USERS.alice)
    const stream = await readStream(`/api/v1/ideas/CUST-7/ai-runs/${asked.data?.id ?? ''}/events`)
    expect(stream.response.headers.get('content-type')).toMatch(/^text\/event-stream/)
    expect(stream.text.startsWith('retry: 3000')).toBe(true)
    expect(stream.events.at(-1)).toMatchObject({ type: 'succeeded', final: true })
    expect(stream.text).not.toMatch(SCORE_LIKE)
    expect(stream.text).not.toMatch(/benchmark|research\.example|Worth pursuing/)
  })
})

describe('the event stream (SSE)', () => {
  it('replays after Last-Event-ID, answers 204 once over, 401 signed out', async () => {
    await signIn(USERS.carol)
    const path = `/api/v1/ideas/CUST-7/ai-runs/${RUNS.cust7Evaluation}/events`
    const from5 = await readStream(path, { 'Last-Event-ID': '5' })
    expect(from5.events.map((event) => event.seq)).toEqual([6, 7, 8, 9])
    const done = await readStream(path, { 'Last-Event-ID': '9' })
    expect(done.response.status).toBe(204)
    const malformed = await readStream(`${path}?after=x`)
    expect(malformed.response.status).toBe(422)
    endSession()
    const signedOut = await readStream(path)
    expect(signedOut.response.status).toBe(401)
  })
})

describe('research notes and drafts', () => {
  it('writes a cited research note into the feed; the owner may delete it', async () => {
    await signIn(USERS.alice)
    const asked = await api.POST('/api/v1/ideas/{idea}/ai-runs/research', {
      params: { path: { idea: 'CUST-2' } },
      body: { agent_id: AGENTS.research },
    })
    const run = await waitForRun('CUST-2', asked.data?.id ?? '')
    expect(run.status).toBe('succeeded')
    const { data: feed } = await api.GET('/api/v1/ideas/{idea}/activity', {
      params: { path: { idea: 'CUST-2' } },
    })
    const note = feed?.items.find((item) => item.type === 'ai_research_note')
    expect(note).toMatchObject({
      actor: { id: PHASE6_USERS.research },
      note: { id: run.result.note_id, deleted: false, can_delete: true },
    })
    await api.DELETE('/api/v1/ideas/{idea}/research-notes/{note_id}', {
      params: { path: { idea: 'CUST-2', note_id: run.result.note_id ?? '' } },
    })
    const deleted = await api.GET('/api/v1/ideas/{idea}/research-notes/{note_id}', {
      params: { path: { idea: 'CUST-2', note_id: run.result.note_id ?? '' } },
    })
    expect(deleted.data).toMatchObject({ deleted: true, body_md: '', sources: [] })
  })

  it('lets only the owner and admins delete a note', async () => {
    await signIn(USERS.bob) // member of CUST
    const { data } = await api.GET('/api/v1/ideas/{idea}/research-notes/{note_id}', {
      params: { path: { idea: 'CUST-4', note_id: RESEARCH_NOTE_ID } },
    })
    expect(data).toMatchObject({ can_delete: false, deleted: false })
    expect(data?.sources.map((source) => source.host)).toEqual([
      'example.org',
      'research.example.com',
      'blog.example.net',
    ])
    expect(
      await rejection(
        api.DELETE('/api/v1/ideas/{idea}/research-notes/{note_id}', {
          params: { path: { idea: 'CUST-4', note_id: RESEARCH_NOTE_ID } },
        }),
      ),
    ).toMatchObject({ status: 403 })
  })

  it('drafts one proposal section as an AI suggestion', async () => {
    await signIn(USERS.alice)
    const asked = await api.POST('/api/v1/ideas/{idea}/ai-runs/section-draft', {
      params: { path: { idea: 'CUST-3' } },
      body: { agent_id: AGENTS.research, section_key: 'risks' },
    })
    const run = await waitForRun('CUST-3', asked.data?.id ?? '')
    expect(run).toMatchObject({ status: 'succeeded', section_key: 'risks' })
    const { data } = await api.GET('/api/v1/ideas/{idea}/proposal/suggestions', {
      params: { path: { idea: 'CUST-3' } },
    })
    expect(data?.items.find((s) => s.id === run.result.suggestion_id)).toMatchObject({
      section_key: 'risks',
      source: 'ai',
      author: { display_name: 'Research agent' },
    })
    // No proposal yet: 404.
    expect(
      await rejection(
        api.POST('/api/v1/ideas/{idea}/ai-runs/section-draft', {
          params: { path: { idea: 'CUST-4' } },
          body: { agent_id: AGENTS.research, section_key: 'risks' },
        }),
      ),
    ).toMatchObject({ status: 404 })
  })
})

describe('Admin settings → AI agents', () => {
  it('lists agents with their settings to platform admins only', async () => {
    await signIn(USERS.alice)
    expect(await rejection(api.GET('/api/v1/admin/ai-agents'))).toMatchObject({ status: 403 })
    await signIn(USERS.priya)
    const { data } = await api.GET('/api/v1/admin/ai-agents')
    expect(
      data?.items.map((agent) => [agent.display_name, agent.enabled, agent.key?.prefix]),
    ).toEqual([
      ['Idea evaluator', true, 'sdg_Id3aEva1uat0'],
      ['Market scout', false, undefined],
      ['Research agent', true, 'sdg_R3s3archAg3n'],
    ])
    expect(data?.items[0]?.a2a_url).toBe(
      'http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator/',
    )
    expect(data?.items[1]?.projects).toEqual([
      expect.objectContaining({ name: 'Internal Tools', role: 'viewer' }),
    ])
    expect(data?.settings).toMatchObject({ enabled: true, kagent_token_set: false })
  })

  it('registers an agent with its service account, membership and a key shown once', async () => {
    await signIn(USERS.priya)
    const { data, response } = await api.POST('/api/v1/admin/ai-agents', {
      body: {
        display_name: 'Market analyst',
        description: '',
        namespace: 'soundings',
        name: 'market-analyst',
        purposes: ['research', 'evaluate', 'research'],
        project_ids: [PROJECTS.cust],
      },
    })
    expect(response.status).toBe(201)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(data?.agent).toMatchObject({
      display_name: 'Market analyst',
      description: '',
      purposes: ['evaluate', 'research'],
      protocol: 'kagent_v0_10',
      projects: [{ name: 'Customer Innovation', role: 'member' }],
    })
    expect(data?.key.key.scopes).toEqual(['read', 'write', 'evaluate', 'mcp'])
    expect(data?.secret_manifest).toContain(`authorization: "Bearer ${data?.key.secret ?? ''}"`)
    expect(data?.secret_manifest).toContain('name: soundings-agent-market-analyst')
    const { data: list } = await api.GET('/api/v1/admin/ai-agents')
    expect(JSON.stringify(list)).not.toContain(data?.key.secret ?? 'secret')

    expect(
      await rejection(
        api.POST('/api/v1/admin/ai-agents', {
          body: {
            display_name: 'Again',
            description: '',
            namespace: 'soundings',
            name: 'market-analyst',
            purposes: ['research'],
            project_ids: [PROJECTS.cust],
          },
        }),
      ),
    ).toMatchObject({ status: 409, code: 'agent_taken' })
    expect(
      await rejection(
        api.POST('/api/v1/admin/ai-agents', {
          body: {
            display_name: 'Elsewhere',
            description: '',
            namespace: 'kagent',
            name: 'k8s-agent',
            purposes: ['research'],
            project_ids: [PROJECTS.cust],
          },
        }),
      ),
    ).toMatchObject({ status: 422, code: 'namespace_not_allowed' })
    expect(
      await rejection(
        api.POST('/api/v1/admin/ai-agents', {
          body: {
            display_name: 'Bad',
            description: '',
            namespace: 'soundings',
            name: 'Bad/../name',
            purposes: ['research'],
            project_ids: [PROJECTS.cust],
          },
        }),
      ),
    ).toMatchObject({ status: 422, code: 'validation_error' })
  })

  it('disables (key revoked), enables (still no key) and rotates a new key', async () => {
    await signIn(USERS.priya)
    const disabled = await api.PATCH('/api/v1/admin/ai-agents/{agent_id}', {
      params: { path: { agent_id: AGENTS.evaluator } },
      body: { enabled: false },
    })
    expect(disabled.data).toMatchObject({ enabled: false, key: null })
    const enabled = await api.PATCH('/api/v1/admin/ai-agents/{agent_id}', {
      params: { path: { agent_id: AGENTS.evaluator } },
      body: { enabled: true },
    })
    expect(enabled.data).toMatchObject({ enabled: true, key: null })
    const rotated = await api.POST('/api/v1/admin/ai-agents/{agent_id}/key', {
      params: { path: { agent_id: AGENTS.evaluator } },
    })
    expect(rotated.response.status).toBe(201)
    expect(rotated.data?.agent.key?.prefix).toBe(rotated.data?.key.key.prefix)
    expect(rotated.data?.secret_manifest).toContain(rotated.data?.key.secret ?? 'x')
  })

  it('tests the connection through the controller: a card, or why not', async () => {
    await signIn(USERS.priya)
    const ok = await api.POST('/api/v1/admin/ai-agents/{agent_id}/test', {
      params: { path: { agent_id: AGENTS.evaluator } },
    })
    expect(ok.data).toMatchObject({
      ok: true,
      url: 'http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator/.well-known/agent-card.json',
      card: { streaming: true, protocol_versions: ['0.3', '1.0'] },
    })
    const down = await api.POST('/api/v1/admin/ai-agents/{agent_id}/test', {
      params: { path: { agent_id: AGENTS.scout } },
    })
    expect(down.data).toMatchObject({ ok: false, error_code: 'agent_unreachable', card: null })
  })
})
