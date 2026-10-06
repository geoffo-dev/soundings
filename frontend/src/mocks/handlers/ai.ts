/**
 * Phase 6 AI assistance (contract-phase6 §2): Admin settings → AI agents
 * (platform admins, session only; check order 401 → 422 shape → 403 → 404 →
 * 422 business → 409), the idea's AI runs with their event stream (SSE), the
 * include-in-score toggle and research notes (401 → 404 → 403 → 422 → 409 →
 * 429). The pretend worker in `../ai.ts` runs what is requested here.
 */
import { HttpResponse } from 'msw'

import type { AiAgentProtocol, AiRunKind, ProposalSectionKey } from '@/api/types'
import {
  agentById,
  agentKeyName,
  agentKeyScopes,
  agentName,
  agentOut,
  agentPasses,
  agentSecretManifest,
  agentCardUrl,
  agentsForIdea,
  agentRef,
  AI_AGENTS_MAX,
  AI_KINDS,
  AI_PROTOCOLS,
  AI_REQUESTS_PER_HOUR,
  AI_SSE_RETRY_MS,
  AI_SSE_STREAMS_PER_USER,
  AI_TESTS_PER_MINUTE,
  aiPermissions,
  addRunEvent,
  cancelRun,
  canonicalPurposes,
  eventOut,
  eventsOf,
  includeBlockedReason,
  isActive,
  KUBERNETES_LABEL,
  mayAskAi,
  mayCancel,
  mayDeleteNote,
  outcomeSetting,
  researchNoteOut,
  runDetailOut,
  runOut,
  scheduleRun,
  settingsOut,
  subscribeRun,
  type MockAiAgent,
  type MockAiRun,
} from '@/mocks/ai'
import { recordAudit } from '@/mocks/access'
import {
  API_KEY_LOOKUP_LENGTH,
  API_KEY_PREFIX,
  API_KEY_SECRET_LENGTH,
  apiKeyOut,
  keyPrefix,
  liveKeys,
  MAX_KEY_PROJECTS,
  randomBase62,
  revokeKey,
  type MockApiKey,
} from '@/mocks/api-keys'
import { ID_KIND, newId, type MockDb, type MockIdea, type MockUser } from '@/mocks/db'
import {
  canViewIdea,
  directRole,
  effectiveRole,
  evaluationOpen,
  evaluationOut,
  findUser,
  invalidateIndexes,
  isPendingEvaluator,
} from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  noContent,
  notFound,
  queryEnum,
  queryLimit,
  readJson,
  route,
  stringField,
  tooManyAttempts,
  type RouteContext,
} from '@/mocks/http'
import { proposalOf, SECTION_KEYS } from '@/mocks/proposals'
import { sessionAuthMethod } from '@/mocks/session'

import { emit, ensureIdeaWritable, isUuid, uuidParam, viewIdea } from './common'

const HOUR = 3_600_000

/* ------------------------------------------------------------------ */
/* Body fields                                                         */
/* ------------------------------------------------------------------ */

function singleLine(value: string): boolean {
  return !Array.from(value).some((char) => {
    const code = char.charCodeAt(0)
    return code < 0x20 || code === 0x7f || code === 0x2028 || code === 0x2029
  })
}

function displayNameField(body: Record<string, unknown>, required: boolean): string | undefined {
  const name = stringField(body, 'display_name', { required, max: 80 })
  if (name !== undefined && !singleLine(name)) {
    failValidation([
      { loc: ['body', 'display_name'], msg: 'Must be a single line of text', type: 'value_error' },
    ])
  }
  return name
}

function labelField(body: Record<string, unknown>, field: 'namespace' | 'name'): string {
  const value = body[field]
  if (typeof value !== 'string' || !KUBERNETES_LABEL.test(value)) {
    failValidation([
      {
        loc: ['body', field],
        msg: 'Use lower-case letters, digits and hyphens (a Kubernetes name, at most 63)',
        type: 'string_pattern_mismatch',
      },
    ])
  }
  return value
}

function protocolField(body: Record<string, unknown>): AiAgentProtocol | undefined {
  const value = body.protocol
  if (value === undefined || value === null) return undefined
  if (!AI_PROTOCOLS.includes(value as AiAgentProtocol)) {
    failValidation([
      {
        loc: ['body', 'protocol'],
        msg: 'Input should be kagent_v0_10 or kagent_v1_0',
        type: 'enum',
      },
    ])
  }
  return value as AiAgentProtocol
}

function purposesField(body: Record<string, unknown>, required: boolean): AiRunKind[] | undefined {
  const value = body.purposes
  if ((value === undefined || value === null) && !required) return undefined
  const distinct = Array.isArray(value) ? [...new Set(value)] : null
  if (
    !distinct ||
    distinct.length < 1 ||
    distinct.length > 3 ||
    !distinct.every((kind) => AI_KINDS.includes(kind as AiRunKind))
  ) {
    failValidation([
      {
        loc: ['body', 'purposes'],
        msg: 'Choose 1 to 3 of evaluate, research, draft_section',
        type: 'value_error',
      },
    ])
  }
  return canonicalPurposes(distinct as AiRunKind[])
}

function projectIdsField(body: Record<string, unknown>, required: boolean): string[] | undefined {
  const value = body.project_ids
  if ((value === undefined || value === null) && !required) return undefined
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > MAX_KEY_PROJECTS ||
    !value.every(isUuid)
  ) {
    failValidation([
      {
        loc: ['body', 'project_ids'],
        msg: `Choose 1 to ${MAX_KEY_PROJECTS} projects`,
        type: 'value_error',
      },
    ])
  }
  return [...new Set(value.map((id) => id.toLowerCase()))]
}

function agentIdField(body: Record<string, unknown>): string {
  const value = body.agent_id
  if (!isUuid(value)) {
    failValidation([
      { loc: ['body', 'agent_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
    ])
  }
  return value.toLowerCase()
}

/* ------------------------------------------------------------------ */
/* Admin helpers                                                       */
/* ------------------------------------------------------------------ */

function requirePlatformAdmin(ctx: RouteContext): void {
  if (!ctx.user.is_platform_admin) forbidden('forbidden', 'Only platform admins can do this.')
}

function findAgent(ctx: RouteContext): MockAiAgent {
  const id = uuidParam(ctx, 'agentId')
  requirePlatformAdmin(ctx)
  const agent = agentById(ctx.db, id)
  if (!agent) notFound('AI agent not found.')
  return agent
}

function checkProjects(db: MockDb, ids: string[]): void {
  if (ids.every((id) => db.projects.some((p) => p.id === id))) return
  failValidation(
    [{ loc: ['body', 'project_ids'], msg: 'Unknown project', type: 'invalid_project' }],
    'invalid_project',
  )
}

/** A new key for the agent (shown once); the old one is revoked by the caller. */
function issueKey(
  db: MockDb,
  agent: MockAiAgent,
  admin: MockUser,
): { key: MockApiKey; secret: string } {
  const lookup = randomBase62(API_KEY_LOOKUP_LENGTH)
  const secret = `${API_KEY_PREFIX}${lookup}_${randomBase62(API_KEY_SECRET_LENGTH)}`
  const key: MockApiKey = {
    id: newId(db, ID_KIND.phase5),
    user_id: agent.user_id,
    name: agentKeyName(agent),
    lookup_id: lookup,
    scopes: agentKeyScopes(agent.purposes),
    project_ids: [...agent.project_ids],
    expires_at: null,
    created_at: new Date().toISOString(),
    created_by_id: admin.id,
    created_auth_method: sessionAuthMethod(),
    last_used_at: null,
    revoked_at: null,
    revoked_by_id: null,
  }
  db.apiKeys.push(key)
  recordAudit(
    db,
    admin,
    'api_key.create',
    { type: 'user', id: agent.user_id },
    {
      rule: 'platform.manage_agents',
      key_id: key.id,
      prefix: keyPrefix(key),
      scopes: key.scopes,
      restricted: true,
      project_ids: key.project_ids,
      expires_at: null,
    },
  )
  return { key, secret }
}

function addMembership(db: MockDb, agent: MockAiAgent, projectId: string, admin: MockUser): void {
  if (effectiveRole(db, projectId, agent.user_id) !== null) return
  db.members.push({
    project_id: projectId,
    user_id: agent.user_id,
    role: 'member',
    joined_at: new Date().toISOString(),
  })
  recordAudit(
    db,
    admin,
    'project.member_add',
    { type: 'user', id: agent.user_id },
    { rule: 'platform.manage_agents', role: 'member' },
    projectId,
  )
}

function cancelAgentRuns(
  db: MockDb,
  agent: MockAiAgent,
  admin: MockUser,
  which: (run: MockAiRun, idea: MockIdea | undefined) => boolean,
): void {
  for (const run of db.aiRuns) {
    if (run.agent_id !== agent.id || !isActive(run.status)) continue
    const idea = db.ideas.find((i) => i.id === run.idea_id)
    if (!which(run, idea)) continue
    cancelRun(db, run, admin)
    recordAudit(
      db,
      admin,
      'ai_run.cancel',
      { type: 'idea', id: run.idea_id },
      { rule: 'platform.manage_agents', run_id: run.id, agent_id: agent.id, status: run.status },
      idea?.project_id ?? null,
    )
  }
}

/** What the mock "kagent" answers at the card URL. */
function testAgent(db: MockDb, agent: MockAiAgent) {
  const url = agentCardUrl(db, agent)
  const started = performance.now()
  const duration = () => Math.max(8, Math.round(performance.now() - started) + 37)
  if (!agent.enabled || agent.name.endsWith('-down')) {
    return {
      ok: false,
      url,
      http_status: agent.name.endsWith('-down') ? 503 : null,
      duration_ms: agent.name.endsWith('-down') ? duration() : 5000,
      card: null,
      error_code: 'agent_unreachable' as const,
      error_message: agent.name.endsWith('-down')
        ? 'Couldn’t reach the agent. (HTTP 503)'
        : 'Couldn’t reach the agent.',
    }
  }
  if (agent.name.endsWith('-broken')) {
    return {
      ok: false,
      url,
      http_status: 200,
      duration_ms: duration(),
      card: null,
      error_code: 'agent_protocol_error' as const,
      error_message: 'The agent’s answer couldn’t be understood.',
    }
  }
  const label = (kind: AiRunKind) =>
    kind === 'evaluate'
      ? 'Evaluate an idea'
      : kind === 'research'
        ? 'Research an idea'
        : 'Draft a proposal section'
  return {
    ok: true,
    url,
    http_status: 200,
    duration_ms: duration(),
    card: {
      name: `${agent.namespace}__NS__${agent.name.replace(/-/g, '_')}`,
      description: agent.description || `${agentName(db, agent)} for Soundings`,
      protocol_versions: agent.protocol === 'kagent_v1_0' ? ['1.0'] : ['0.3', '1.0'],
      streaming: true,
      skills: agent.purposes.map((kind) => ({ id: `soundings-${kind}`, name: label(kind) })),
    },
    error_code: null,
    error_message: null,
  }
}

/* ------------------------------------------------------------------ */
/* Run helpers                                                         */
/* ------------------------------------------------------------------ */

function findRun(ctx: RouteContext, idea: MockIdea): MockAiRun {
  const id = uuidParam(ctx, 'runId')
  const run = ctx.db.aiRuns.find((r) => r.id === id && r.idea_id === idea.id)
  if (!run) notFound('AI run not found.')
  return run
}

function checkRequestRule(ctx: RouteContext, idea: MockIdea): void {
  if (!mayAskAi(ctx.db, idea, ctx.user)) {
    forbidden('forbidden', 'Only the idea’s owner and admins can ask an AI agent.')
  }
}

/** c10 for the named agent (an unknown agent is the same 409). */
function usableAgent(db: MockDb, idea: MockIdea, agentId: string, kind: AiRunKind): MockAiAgent {
  const agent = agentById(db, agentId)
  if (!db.aiSettings.enabled) conflict('ai_unavailable', 'AI assistance is off.')
  if (!agent || !agentPasses(db, agent, idea, kind)) {
    conflict('ai_unavailable', 'That agent can’t do this for this idea now.')
  }
  return agent
}

/** Idempotency, the per-person limit, then a new queued run and its job. */
function requestRun(
  ctx: RouteContext,
  idea: MockIdea,
  agent: MockAiAgent,
  kind: AiRunKind,
  sectionKey: ProposalSectionKey | null,
) {
  const { db, user } = ctx
  const active = db.aiRuns.find(
    (run) =>
      run.idea_id === idea.id &&
      run.agent_id === agent.id &&
      run.kind === kind &&
      run.section_key === sectionKey &&
      isActive(run.status),
  )
  if (active) return runOut(db, active, user)
  const now = Date.now()
  const recent = (db.aiRequests[user.id] ?? []).filter((at) => now - at < HOUR)
  if (recent.length >= AI_REQUESTS_PER_HOUR) {
    tooManyAttempts(
      ((recent[0] ?? now) + HOUR - now) / 1000,
      'You asked AI agents 20 times in the last hour. Try again later.',
    )
  }
  db.aiRequests[user.id] = [...recent, now]
  const run: MockAiRun = {
    id: newId(db, ID_KIND.phase5),
    idea_id: idea.id,
    agent_id: agent.id,
    kind,
    section_key: sectionKey,
    status: 'queued',
    requested_by_id: user.id,
    created_at: new Date(now).toISOString(),
    started_at: null,
    finished_at: null,
    timeout_seconds: db.aiSettings.run_timeout_seconds,
    cancel_requested_at: null,
    cancel_requested_by_id: null,
    error_code: null,
    error_message: null,
    evaluation_id: null,
    suggestion_id: null,
    activity_event_id: null,
    assigned_evaluator: false,
    outcome: outcomeSetting(),
    step: 0,
  }
  db.aiRuns.push(run)
  addRunEvent(db, run, 'queued')
  if (
    kind === 'evaluate' &&
    !db.assignments.some((a) => a.idea_id === idea.id && a.user_id === agent.user_id)
  ) {
    db.assignments.push({ idea_id: idea.id, user_id: agent.user_id, invited_at: run.created_at })
    run.assigned_evaluator = true
    emit(db, idea, 'evaluator_added', user.id, { evaluator_id: agent.user_id })
    recordAudit(
      db,
      user,
      'evaluator.add',
      { type: 'idea', id: idea.id },
      { rule: 'ai.request_evaluation', evaluator_id: agent.user_id },
      idea.project_id,
    )
    invalidateIndexes()
  }
  recordAudit(
    db,
    user,
    'ai_run.request',
    { type: 'idea', id: idea.id },
    {
      rule:
        kind === 'evaluate'
          ? 'ai.request_evaluation'
          : kind === 'research'
            ? 'ai.research'
            : 'ai.draft_section',
      run_id: run.id,
      agent_id: agent.id,
      kind,
      section_key: sectionKey,
    },
    idea.project_id,
  )
  scheduleRun(db, run)
  return created(runOut(db, run, user))
}

function ideaNoteEvent(ctx: RouteContext, idea: MockIdea) {
  const id = uuidParam(ctx, 'noteId')
  const event = ctx.db.events.find(
    (e) => e.id === id && e.idea_id === idea.id && e.type === 'ai_research_note',
  )
  if (!event) notFound('Research note not found.')
  return event
}

/** `Last-Event-ID` (header wins) or `?after=`: a non-negative integer, else 422. */
function afterParam(ctx: RouteContext): number {
  const raw = ctx.request.headers.get('Last-Event-ID') ?? ctx.url.searchParams.get('after')
  if (raw === null || raw === '') return 0
  if (!/^\d+$/.test(raw)) {
    failValidation([
      { loc: ['query', 'after'], msg: 'Input should be a valid integer', type: 'int_parsing' },
    ])
  }
  return Number(raw)
}

const encoder = new TextEncoder()

/** 201 with `Cache-Control: no-store` (the body holds a key, shown once). */
function noStore(body: unknown): Response {
  return HttpResponse.json(body as never, { status: 201, headers: { 'Cache-Control': 'no-store' } })
}

/* ------------------------------------------------------------------ */
/* Handlers                                                            */
/* ------------------------------------------------------------------ */

export const aiHandlers = [
  /* Admin settings → AI agents ---------------------------------------- */
  route('get', '/admin/ai-agents', (ctx) => {
    requirePlatformAdmin(ctx)
    const { db, user } = ctx
    return {
      items: [...db.aiAgents]
        .sort((a, b) => agentName(db, a).localeCompare(agentName(db, b)))
        .map((agent) => agentOut(db, agent)),
      settings: settingsOut(db),
      max_agents: AI_AGENTS_MAX,
      can_register: !user.is_break_glass && db.aiAgents.length < AI_AGENTS_MAX,
    }
  }),

  route('post', '/admin/ai-agents', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, [
      'display_name',
      'description',
      'namespace',
      'name',
      'protocol',
      'purposes',
      'project_ids',
    ])
    const displayName = displayNameField(body, true) ?? ''
    const description = stringField(body, 'description', { max: 500 }) ?? ''
    const namespace = labelField(body, 'namespace')
    const name = labelField(body, 'name')
    const protocol = protocolField(body)
    const purposes = purposesField(body, true) ?? []
    const projectIds = projectIdsField(body, true) ?? []
    requirePlatformAdmin(ctx)
    const { db, user } = ctx
    if (user.is_break_glass) {
      forbidden(
        'break_glass_account',
        'The break-glass account can’t register agents: it would create a key.',
      )
    }
    const allowed = db.aiSettings.agent_namespaces
    if (allowed.length > 0 && !allowed.includes(namespace)) {
      failValidation(
        [
          {
            loc: ['body', 'namespace'],
            msg: `Agents may run in ${allowed.join(', ')}`,
            type: 'namespace_not_allowed',
          },
        ],
        'namespace_not_allowed',
      )
    }
    checkProjects(db, projectIds)
    if (db.aiAgents.some((a) => a.namespace === namespace && a.name === name)) {
      conflict('agent_taken', 'An agent with that namespace and name is already registered.')
    }
    if (db.aiAgents.length >= AI_AGENTS_MAX) conflict('too_many_agents', 'Soundings has 50 agents.')
    const now = new Date().toISOString()
    const agentId = newId(db, ID_KIND.phase5)
    const userId = newId(db, ID_KIND.phase5)
    db.users.push({
      id: userId,
      display_name: displayName,
      email: `agent-${agentId}@soundings.invalid`,
      avatar_url: null,
      is_platform_admin: false,
      is_active: true,
      is_service_account: true,
      is_break_glass: false,
      created_at: now,
      last_seen_at: null,
    })
    const agent: MockAiAgent = {
      id: agentId,
      user_id: userId,
      description,
      namespace,
      name,
      protocol: protocol ?? db.aiSettings.default_protocol,
      purposes,
      project_ids: projectIds,
      enabled: true,
      created_at: now,
      updated_at: now,
      created_by_id: user.id,
    }
    db.aiAgents.push(agent)
    for (const projectId of projectIds) addMembership(db, agent, projectId, user)
    const { key, secret } = issueKey(db, agent, user)
    recordAudit(
      db,
      user,
      'ai_agent.register',
      { type: 'user', id: userId },
      {
        rule: 'platform.manage_agents',
        agent_id: agentId,
        namespace,
        name,
        protocol: agent.protocol,
        purposes,
        project_ids: projectIds,
      },
    )
    invalidateIndexes()
    return noStore({
      agent: agentOut(db, agent),
      key: { key: apiKeyOut(db, key), secret },
      secret_manifest: agentSecretManifest(namespace, name, secret),
    })
  }),

  route('get', '/admin/ai-agents/:agentId', (ctx) => agentOut(ctx.db, findAgent(ctx))),

  route('patch', '/admin/ai-agents/:agentId', async (ctx) => {
    uuidParam(ctx, 'agentId')
    const body = await readJson(ctx.request)
    const fields = ['display_name', 'description', 'protocol', 'purposes', 'project_ids', 'enabled']
    allowOnly(body, fields)
    const present = fields.filter((field) => field in body)
    if (present.length === 0) {
      failValidation([{ loc: ['body'], msg: 'Change at least one field', type: 'value_error' }])
    }
    const nulls = present.filter((field) => body[field] === null)
    if (nulls.length > 0) {
      failValidation(
        nulls.map((field) => ({
          loc: ['body', field],
          msg: 'Must not be null',
          type: 'value_error',
        })),
      )
    }
    const displayName = displayNameField(body, false)
    const description = stringField(body, 'description', { max: 500 })
    const protocol = protocolField(body)
    const purposes = purposesField(body, false)
    const projectIds = projectIdsField(body, false)
    const enabled = body.enabled
    if (enabled !== undefined && typeof enabled !== 'boolean') {
      failValidation([
        { loc: ['body', 'enabled'], msg: 'Input should be a boolean', type: 'bool_type' },
      ])
    }
    const agent = findAgent(ctx)
    const { db, user } = ctx
    if (projectIds) checkProjects(db, projectIds)
    const changed: string[] = []
    const account = findUser(db, agent.user_id)
    if (displayName !== undefined && account && displayName !== account.display_name) {
      account.display_name = displayName
      changed.push('display_name')
    }
    if (description !== undefined && description !== agent.description) {
      agent.description = description
      changed.push('description')
    }
    if (protocol && protocol !== agent.protocol) {
      agent.protocol = protocol
      changed.push('protocol')
    }
    const key = liveKeys(db, agent.user_id)[0]
    if (purposes && purposes.join() !== agent.purposes.join()) {
      const dropped = agent.purposes.filter((kind) => !purposes.includes(kind))
      agent.purposes = purposes
      if (key) key.scopes = agentKeyScopes(purposes)
      cancelAgentRuns(db, agent, user, (run) => dropped.includes(run.kind))
      changed.push('purposes')
    }
    if (projectIds && [...projectIds].sort().join() !== [...agent.project_ids].sort().join()) {
      const dropped = agent.project_ids.filter((id) => !projectIds.includes(id))
      for (const id of projectIds)
        if (!agent.project_ids.includes(id)) addMembership(db, agent, id, user)
      for (const id of dropped) {
        if (directRole(db, id, agent.user_id) === null) continue
        db.members = db.members.filter((m) => !(m.project_id === id && m.user_id === agent.user_id))
        recordAudit(
          db,
          user,
          'project.member_remove',
          { type: 'user', id: agent.user_id },
          { rule: 'platform.manage_agents' },
          id,
        )
      }
      agent.project_ids = projectIds
      if (key) key.project_ids = [...projectIds]
      cancelAgentRuns(db, agent, user, (_run, idea) =>
        Boolean(idea && dropped.includes(idea.project_id)),
      )
      changed.push('project_ids')
    }
    if (typeof enabled === 'boolean' && enabled !== agent.enabled) {
      agent.enabled = enabled
      if (!enabled) {
        cancelAgentRuns(db, agent, user, () => true)
        for (const live of liveKeys(db, agent.user_id))
          revokeKey(db, live, user, 'platform.manage_agents')
      }
      changed.push('enabled')
    }
    if (changed.length > 0) {
      agent.updated_at = new Date().toISOString()
      recordAudit(
        db,
        user,
        'ai_agent.update',
        { type: 'user', id: agent.user_id },
        {
          rule: 'platform.manage_agents',
          agent_id: agent.id,
          changed,
          ...(changed.includes('enabled') ? { enabled: agent.enabled } : {}),
        },
      )
    }
    invalidateIndexes()
    return agentOut(db, agent)
  }),

  route('post', '/admin/ai-agents/:agentId/key', (ctx) => {
    uuidParam(ctx, 'agentId')
    requirePlatformAdmin(ctx)
    if (ctx.user.is_break_glass) {
      forbidden('break_glass_account', 'The break-glass account can’t create keys.')
    }
    const agent = findAgent(ctx)
    const { db, user } = ctx
    if (!findUser(db, agent.user_id)?.is_active) {
      conflict('ai_unavailable', 'Reactivate the agent’s service account first.')
    }
    const old = liveKeys(db, agent.user_id)
    const { key, secret } = issueKey(db, agent, user)
    for (const previous of old) revokeKey(db, previous, user, 'platform.manage_agents')
    return noStore({
      agent: agentOut(db, agent),
      key: { key: apiKeyOut(db, key), secret },
      secret_manifest: agentSecretManifest(agent.namespace, agent.name, secret),
      revoked_key_id: old[0]?.id ?? null,
    })
  }),

  route('post', '/admin/ai-agents/:agentId/test', (ctx) => {
    const agent = findAgent(ctx)
    const { db, user } = ctx
    const now = Date.now()
    const recent = (db.aiTests[user.id] ?? []).filter((at) => now - at < 60_000)
    if (recent.length >= AI_TESTS_PER_MINUTE) {
      tooManyAttempts(
        ((recent[0] ?? now) + 60_000 - now) / 1000,
        'Wait a minute before testing again.',
      )
    }
    db.aiTests[user.id] = [...recent, now]
    return testAgent(db, agent)
  }),

  /* Runs on an idea ------------------------------------------------------ */
  route('get', '/ideas/:idea/ai-runs', (ctx) => {
    const idea = viewIdea(ctx)
    const kinds = queryEnum(ctx.url, 'kind', AI_KINDS)
    const limit = queryLimit(ctx.url, 20, 50)
    const { db, user } = ctx
    const runs = db.aiRuns
      .filter((run) => run.idea_id === idea.id && (kinds.length === 0 || kinds.includes(run.kind)))
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
      .slice(0, limit)
    return {
      items: runs.map((run) => runOut(db, run, user)),
      ai_enabled: db.aiSettings.enabled,
      agents: agentsForIdea(db, idea).map((agent) => agentRef(db, agent)),
      permissions: aiPermissions(db, idea, user),
    }
  }),

  route('post', '/ideas/:idea/ai-runs/evaluation', async (ctx) => {
    const idea = viewIdea(ctx)
    checkRequestRule(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['agent_id'])
    const agentId = agentIdField(body)
    ensureIdeaWritable(ctx.db, idea)
    if (idea.status === 'closed') conflict('idea_closed', 'This idea is closed.')
    if (!evaluationOpen(idea)) conflict('evaluation_closed', 'Evaluation is closed.')
    const agent = usableAgent(ctx.db, idea, agentId, 'evaluate')
    return requestRun(ctx, idea, agent, 'evaluate', null)
  }),

  route('post', '/ideas/:idea/ai-runs/research', async (ctx) => {
    const idea = viewIdea(ctx)
    checkRequestRule(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['agent_id'])
    const agentId = agentIdField(body)
    ensureIdeaWritable(ctx.db, idea)
    if (idea.status === 'closed') conflict('idea_closed', 'This idea is closed.')
    const agent = usableAgent(ctx.db, idea, agentId, 'research')
    return requestRun(ctx, idea, agent, 'research', null)
  }),

  route('post', '/ideas/:idea/ai-runs/section-draft', async (ctx) => {
    const idea = viewIdea(ctx)
    checkRequestRule(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['agent_id', 'section_key'])
    const agentId = agentIdField(body)
    const sectionKey = body.section_key
    if (!SECTION_KEYS.includes(sectionKey as ProposalSectionKey)) {
      failValidation([
        {
          loc: ['body', 'section_key'],
          msg: `Input should be ${SECTION_KEYS.join(', ')}`,
          type: 'enum',
        },
      ])
    }
    if (!proposalOf(ctx.db, idea)) notFound('This idea has no proposal yet.')
    ensureIdeaWritable(ctx.db, idea)
    if (idea.status !== 'shortlisted' && idea.status !== 'proposal') {
      conflict(
        'proposal_not_available',
        'The proposal is read-only while the idea isn’t shortlisted.',
      )
    }
    const agent = usableAgent(ctx.db, idea, agentId, 'draft_section')
    return requestRun(ctx, idea, agent, 'draft_section', sectionKey as ProposalSectionKey)
  }),

  route('get', '/ideas/:idea/ai-runs/:runId', (ctx) => {
    const idea = viewIdea(ctx)
    return runDetailOut(ctx.db, findRun(ctx, idea), ctx.user)
  }),

  route('post', '/ideas/:idea/ai-runs/:runId/cancel', (ctx) => {
    const idea = viewIdea(ctx)
    const run = findRun(ctx, idea)
    const { db, user } = ctx
    if (!mayCancel(db, idea, user))
      forbidden('forbidden', 'Only the idea’s owner and admins can cancel.')
    if (!isActive(run.status)) conflict('ai_run_finished', 'This run has already ended.')
    const wasRequested = run.cancel_requested_at !== null
    const result = cancelRun(db, run, user)
    if (!wasRequested || result === 'cancelled') {
      recordAudit(
        db,
        user,
        'ai_run.cancel',
        { type: 'idea', id: idea.id },
        {
          rule: 'ai.cancel_run',
          run_id: run.id,
          agent_id: run.agent_id,
          ...(result === 'cancelled' ? { status: 'cancelled' } : {}),
        },
        idea.project_id,
      )
    }
    return runOut(db, run, user)
  }),

  route('get', '/ideas/:idea/ai-runs/:runId/events', (ctx) => {
    const idea = viewIdea(ctx)
    const run = findRun(ctx, idea)
    const after = afterParam(ctx)
    const { db, user } = ctx
    const open = db.aiStreams[user.id] ?? 0
    if (open >= AI_SSE_STREAMS_PER_USER) {
      tooManyAttempts(5, 'Too many open progress streams. Close a tab and try again.')
    }
    const pending = eventsOf(db, run).filter((event) => event.seq > after)
    if (!isActive(run.status) && pending.length === 0) return noContent()
    db.aiStreams[user.id] = open + 1
    let close = () => {
      // Replaced once the stream starts.
    }
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        let done = false
        const closed = () => done
        const write = (text: string) => {
          if (!done) controller.enqueue(encoder.encode(text))
        }
        const keepAlive = setInterval(() => {
          // Re-checks (every 30 s in the API): access gone → the stream ends, no final event.
          const current = db.ideas.find((i) => i.id === idea.id)
          if (!current || !canViewIdea(db, current, user)) close()
          else write(': keep-alive\n\n')
        }, 15_000)
        let unsubscribe = () => {
          // Replaced once subscribed.
        }
        close = () => {
          if (done) return
          done = true
          clearInterval(keepAlive)
          unsubscribe()
          db.aiStreams[user.id] = Math.max(0, (db.aiStreams[user.id] ?? 1) - 1)
          try {
            controller.close()
          } catch {
            // Already closed by the reader.
          }
        }
        write(`retry: ${AI_SSE_RETRY_MS}\n\n`)
        const send = (event: ReturnType<typeof eventOut>) => {
          write(`id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`)
          if (event.final) close()
        }
        for (const event of pending) send(eventOut(event))
        if (!closed()) unsubscribe = subscribeRun(db, run.id, send)
      },
      cancel() {
        close()
      },
    })
    return new Response(stream, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    })
  }),

  /* The include toggle and research notes ------------------------------ */
  route('put', '/ideas/:idea/evaluations/:evaluationId/include-in-aggregate', async (ctx) => {
    const idea = viewIdea(ctx)
    const id = uuidParam(ctx, 'evaluationId')
    const { db, user } = ctx
    const evaluation = db.evaluations.find((e) => e.id === id && e.idea_id === idea.id)
    // A draft, another idea's, or any while you owe your own: 404 (it holds scores).
    if (evaluation?.status !== 'submitted' || isPendingEvaluator(db, idea, user.id)) {
      notFound('Evaluation not found.')
    }
    if (includeBlockedReason(db, idea, user) === 'not_allowed') {
      forbidden('forbidden', 'Only the idea’s owner and admins can include AI evaluations.')
    }
    const body = await readJson(ctx.request)
    allowOnly(body, ['include'])
    if (typeof body.include !== 'boolean') {
      failValidation([
        { loc: ['body', 'include'], msg: 'Input should be a boolean', type: 'bool_type' },
      ])
    }
    if (!findUser(db, evaluation.evaluator_id)?.is_service_account) {
      conflict('not_ai_evaluation', 'Only AI evaluations can be left out of the score.')
    }
    ensureIdeaWritable(db, idea)
    if (evaluation.include_in_aggregate !== body.include) {
      evaluation.include_in_aggregate = body.include
      recordAudit(
        db,
        user,
        'evaluation.include_ai',
        { type: 'idea', id: idea.id },
        {
          rule: 'evaluation.include_ai',
          evaluation_id: evaluation.id,
          evaluator_id: evaluation.evaluator_id,
          include: body.include,
        },
        idea.project_id,
      )
    }
    return evaluationOut(db, evaluation)
  }),

  route('get', '/ideas/:idea/research-notes/:noteId', (ctx) => {
    const idea = viewIdea(ctx)
    return researchNoteOut(ctx.db, ideaNoteEvent(ctx, idea), ctx.user)
  }),

  route('delete', '/ideas/:idea/research-notes/:noteId', (ctx) => {
    const idea = viewIdea(ctx)
    const event = ideaNoteEvent(ctx, idea)
    const { db, user } = ctx
    if (!mayAskAi(db, idea, user))
      forbidden('forbidden', 'Only the idea’s owner and admins can delete notes.')
    ensureIdeaWritable(db, idea)
    if (!mayDeleteNote(db, idea, user)) forbidden()
    if (event.payload.deleted !== true) {
      event.payload = {
        run_id: event.payload.run_id,
        agent_id: event.payload.agent_id,
        body_md: '',
        sources: [],
        deleted: true,
      }
      recordAudit(
        db,
        user,
        'ai_note.delete',
        { type: 'idea', id: idea.id },
        {
          rule: 'ai.delete_note',
          note_id: event.id,
          run_id: event.payload.run_id,
          agent_id: event.payload.agent_id,
        },
        idea.project_id,
      )
    }
    return noContent()
  }),
]
