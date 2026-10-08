/**
 * Phase 6 AI assistance in the mock API (contract-phase6): registered kagent
 * agents with their service accounts and keys, AI runs and their progress
 * events, research notes (activity events of type `ai_research_note`) and the
 * rules (role matrix section J, c10). A pretend worker walks each new run
 * through the steps the real worker reports, really writing the agent's result
 * (an AI evaluation with rationale and sources, a research note, a proposal
 * suggestion) as the fake A2A agent does through MCP. The backend is the
 * authority; this follows its rules closely enough to build and test screens.
 *
 * Knobs (localStorage, then reload):
 *   soundings-mock-ai          `off`: features.ai is off (no run can start)
 *   soundings-mock-ai-outcome  how new runs end: `fail`, `timeout`, `no_result`,
 *                              `unreachable`, `slow` (works until cancelled) or
 *                              `queued` (never starts); unset: they succeed
 *   soundings-mock-ai-pace     ms per progress step (default 900; 5 under Node)
 */
import type {
  AiAgent,
  AiAgentProtocol,
  AiAgentRef,
  AiBlockedReason,
  AiPermissions,
  AiRun,
  AiRunDetail,
  AiRunError,
  AiRunEvent,
  AiRunEventType,
  AiRunKind,
  AiRunStatus,
  AiSettingsInEffect,
  Citation,
  ProposalSectionKey,
  ResearchNote,
} from '@/api/types'

import { recordAudit } from './access'
import { apiKeyOut, liveKeys, keyState, type MockApiKey } from './api-keys'
import { ID_KIND, newId, type MockDb, type MockEvent, type MockIdea, type MockUser } from './db'
import {
  activeCriteria,
  effectiveRole,
  evaluationOf,
  evaluationOpen,
  findUser,
  ideaKey,
  invalidateIndexes,
  isProjectAdmin,
  projectOf,
  rowsForIdea,
  userRef,
  userRefById,
} from './domain'
import { flushFanOut } from './notifications'
import { proposalOf, proposalOpenFor } from './proposals'
import { inviteBlocked } from './research'
import { activeSection } from './templates'

/* ------------------------------------------------------------------ */
/* Records (docs/erd.md: ai_agents, ai_agent_projects, ai_runs, …)    */
/* ------------------------------------------------------------------ */

export interface MockAiSettings {
  enabled: boolean
  kagent_url: string
  kagent_token_set: boolean
  default_protocol: AiAgentProtocol
  run_timeout_seconds: number
  max_concurrent_runs: number
  agent_namespaces: string[]
  mcp_url: string
}

export interface MockAiAgent {
  id: string
  /** Its service account (`users.is_service_account`); its display name is the agent's. */
  user_id: string
  description: string
  namespace: string
  name: string
  protocol: AiAgentProtocol
  /** Canonical order: evaluate, research, draft_section. */
  purposes: AiRunKind[]
  project_ids: string[]
  enabled: boolean
  created_at: string
  updated_at: string
  created_by_id: string | null
}

/** How the pretend worker ends a run (the outcome knob at request time). */
export type MockRunOutcome =
  'succeed' | 'fail' | 'timeout' | 'no_result' | 'unreachable' | 'slow' | 'queued'

export interface MockAiRun {
  id: string
  idea_id: string
  agent_id: string
  kind: AiRunKind
  section_key: ProposalSectionKey | null
  status: AiRunStatus
  requested_by_id: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  timeout_seconds: number
  cancel_requested_at: string | null
  cancel_requested_by_id: string | null
  error_code: AiRunError | null
  error_message: string | null
  evaluation_id: string | null
  suggestion_id: string | null
  activity_event_id: string | null
  /** "Ask AI to evaluate" assigned the agent (undone if the run ends without its evaluation). */
  assigned_evaluator: boolean
  /** Mock only: how the pretend worker ends it, and the step it is on. */
  outcome: MockRunOutcome
  step: number
}

export interface MockAiRunEvent {
  run_id: string
  seq: number
  type: AiRunEventType
  message: string
  created_at: string
}

/** A cited source as stored: http(s), plain ASCII (punycode host). */
export interface MockCitation {
  title: string
  url: string
}

/* ------------------------------------------------------------------ */
/* Fixed messages (backend app/schemas/ai.py)                          */
/* ------------------------------------------------------------------ */

export const AI_RUN_EVENT_MESSAGES: Partial<Record<AiRunEventType, string>> = {
  queued: 'Waiting to start',
  started: 'Sending the request to the agent',
  retrying: 'Couldn’t reach the agent; trying again',
  agent_accepted: 'The agent started',
  agent_working: 'The agent is working',
  cancel_requested: 'Cancelling',
  succeeded: 'Done',
  cancelled: 'Cancelled',
}

export const AI_TOOL_MESSAGES: Record<string, string> = {
  list_projects: 'Listed its projects',
  search_ideas: 'Searched ideas',
  get_idea: 'Read the idea',
  get_rubric: 'Read the rubric',
  get_proposal: 'Read the proposal',
  create_idea: 'Created an idea',
  add_comment: 'Commented',
  submit_evaluation: 'Saved its evaluation',
  propose_proposal_section: 'Suggested section text',
  add_research_note: 'Wrote the research note',
}

export const AI_RUN_ERROR_MESSAGES: Record<AiRunError, string> = {
  ai_disabled: 'AI assistance was turned off before this run started.',
  agent_unavailable: 'The agent isn’t available for this idea any more.',
  agent_unreachable: 'Couldn’t reach the agent.',
  agent_protocol_error: 'The agent’s answer couldn’t be understood.',
  agent_rejected: 'The agent declined the request.',
  agent_failed: 'The agent stopped with an error.',
  agent_needs_input: 'The agent asked for input, which a run can’t give.',
  no_result: 'The agent finished without saving a result.',
  timed_out: 'The agent didn’t finish in time.',
  queue_timeout: 'The run waited too long to start.',
  worker_lost: 'The worker running it stopped before it finished.',
  internal_error: 'Something went wrong on our side.',
}

export const RESULT_MESSAGES: Record<AiRunKind, string> = {
  evaluate: 'Evaluation submitted',
  research: 'Research note saved',
  draft_section: 'Suggestion saved',
}

export const AI_KINDS: readonly AiRunKind[] = ['evaluate', 'research', 'draft_section']
export const AI_PROTOCOLS: readonly AiAgentProtocol[] = ['kagent_v0_10', 'kagent_v1_0']
export const AI_AGENTS_MAX = 50
export const AI_RUN_EVENTS_MAX = 200
export const AI_REQUESTS_PER_HOUR = 20
export const AI_TESTS_PER_MINUTE = 10
export const AI_SSE_STREAMS_PER_USER = 5
export const AI_SSE_RETRY_MS = 3000
/** `^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$` (`KUBERNETES_LABEL_PATTERN`). */
export const KUBERNETES_LABEL = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/
export const RESEARCH_NOTE_MAX_LENGTH = 20_000

const ACTIVE: readonly AiRunStatus[] = ['queued', 'running']
export const isActive = (status: AiRunStatus) => ACTIVE.includes(status)
const FINAL_EVENTS: readonly AiRunEventType[] = ['succeeded', 'failed', 'cancelled', 'timed_out']

/** Canonical order, duplicates dropped (`canonical_purposes`). */
export function canonicalPurposes(purposes: readonly AiRunKind[]): AiRunKind[] {
  return AI_KINDS.filter((kind) => purposes.includes(kind))
}

/** `agent_key_scopes`: read + mcp always, evaluate to evaluate, write to research or draft. */
export function agentKeyScopes(purposes: readonly AiRunKind[]): MockApiKey['scopes'] {
  const scopes: MockApiKey['scopes'] = ['read']
  if (purposes.includes('research') || purposes.includes('draft_section')) scopes.push('write')
  if (purposes.includes('evaluate')) scopes.push('evaluate')
  scopes.push('mcp')
  return scopes
}

export const agentKeyName = (agent: Pick<MockAiAgent, 'namespace' | 'name'>) =>
  `kagent ${agent.namespace}/${agent.name}`.slice(0, 80)

/** `agent_secret_manifest`: the Secret kagent's RemoteMCPServer `headersFrom` reads. */
export function agentSecretManifest(namespace: string, name: string, secret: string): string {
  return [
    'apiVersion: v1',
    'kind: Secret',
    'metadata:',
    `  name: soundings-agent-${name}`,
    `  namespace: ${namespace}`,
    'type: Opaque',
    'stringData:',
    `  authorization: "Bearer ${secret}"`,
    '',
  ].join('\n')
}

/** `agent_a2a_url` / `agent_card_url`: built, never configured. */
export function agentA2aUrl(db: MockDb, agent: MockAiAgent): string {
  const base = db.aiSettings.kagent_url
  return agent.protocol === 'kagent_v1_0'
    ? `${base}/agents/${agent.namespace}/${agent.name}`
    : `${base}/api/a2a/${agent.namespace}/${agent.name}/`
}

export function agentCardUrl(db: MockDb, agent: MockAiAgent): string {
  const url = agentA2aUrl(db, agent)
  return `${url.endsWith('/') ? url : `${url}/`}.well-known/agent-card.json`
}

/* ------------------------------------------------------------------ */
/* Knobs                                                               */
/* ------------------------------------------------------------------ */

export const MOCK_AI_OUTCOME_STORAGE_KEY = 'soundings-mock-ai-outcome'
export const MOCK_AI_PACE_STORAGE_KEY = 'soundings-mock-ai-pace'

function setting(key: string): string | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(key)
  } catch {
    return null
  }
}

const OUTCOMES: readonly MockRunOutcome[] = [
  'succeed',
  'fail',
  'timeout',
  'no_result',
  'unreachable',
  'slow',
  'queued',
]

export function outcomeSetting(): MockRunOutcome {
  const value = setting(MOCK_AI_OUTCOME_STORAGE_KEY)
  return OUTCOMES.includes(value as MockRunOutcome) ? (value as MockRunOutcome) : 'succeed'
}

/** ms per step: the knob, else 900 in a browser and 5 under Node (tests). */
export function paceSetting(): number {
  const value = setting(MOCK_AI_PACE_STORAGE_KEY)
  if (value && /^\d+$/.test(value)) return Number(value)
  return typeof window === 'undefined' || /jsdom/i.test(navigator.userAgent) ? 5 : 900
}

/* ------------------------------------------------------------------ */
/* Agents                                                              */
/* ------------------------------------------------------------------ */

export function agentById(db: MockDb, id: string): MockAiAgent | undefined {
  return db.aiAgents.find((agent) => agent.id === id)
}

export function agentOfUser(db: MockDb, userId: string | null): MockAiAgent | undefined {
  return userId ? db.aiAgents.find((agent) => agent.user_id === userId) : undefined
}

export function agentName(db: MockDb, agent: MockAiAgent): string {
  return findUser(db, agent.user_id)?.display_name ?? 'AI agent'
}

/** Its key that works now: not revoked, not expired (agents' keys are never dormant). */
export function agentKey(db: MockDb, agent: MockAiAgent): MockApiKey | undefined {
  return liveKeys(db, agent.user_id).find((key) => keyState(db, key) === 'active')
}

export function agentRef(db: MockDb, agent: MockAiAgent): AiAgentRef {
  return {
    id: agent.id,
    display_name: agentName(db, agent),
    purposes: agent.purposes,
    user_id: agent.user_id,
  }
}

/**
 * c10 for one agent, kind and idea, except the instance switch: enabled, the
 * purpose, serving the project, its service account active with the member
 * role there, and a usable key.
 */
export function agentPasses(
  db: MockDb,
  agent: MockAiAgent,
  idea: MockIdea,
  kind: AiRunKind,
): boolean {
  const account = findUser(db, agent.user_id)
  return Boolean(
    agent.enabled &&
    agent.purposes.includes(kind) &&
    agent.project_ids.includes(idea.project_id) &&
    account?.is_active &&
    effectiveRole(db, idea.project_id, agent.user_id) === 'member' &&
    agentKey(db, agent),
  )
}

/** Agents passing c10 for some kind on this idea (`AiRunList.agents`), by name. */
export function agentsForIdea(db: MockDb, idea: MockIdea): MockAiAgent[] {
  if (!db.aiSettings.enabled) return []
  return db.aiAgents
    .filter((agent) => AI_KINDS.some((kind) => agentPasses(db, agent, idea, kind)))
    .sort((a, b) => agentName(db, a).localeCompare(agentName(db, b)))
}

export function agentOut(db: MockDb, agent: MockAiAgent): AiAgent {
  const key = agentKey(db, agent) ?? liveKeys(db, agent.user_id)[0]
  const account = findUser(db, agent.user_id)
  return {
    id: agent.id,
    display_name: agentName(db, agent),
    description: agent.description,
    namespace: agent.namespace,
    name: agent.name,
    protocol: agent.protocol,
    purposes: agent.purposes,
    enabled: agent.enabled,
    a2a_url: agentA2aUrl(db, agent),
    card_url: agentCardUrl(db, agent),
    projects: db.projects
      .filter((project) => agent.project_ids.includes(project.id))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((project) => ({
        id: project.id,
        key: project.key,
        name: project.name,
        slug: project.slug,
        role: effectiveRole(db, project.id, agent.user_id),
      })),
    key: key ? apiKeyOut(db, key) : null,
    service_account: account
      ? userRef(account)
      : { id: agent.user_id, display_name: 'AI agent', avatar_url: null, initials: 'AI' },
    active_run_count: db.aiRuns.filter((run) => run.agent_id === agent.id && isActive(run.status))
      .length,
    created_at: agent.created_at,
    updated_at: agent.updated_at,
    created_by: userRefById(db, agent.created_by_id),
  }
}

export function settingsOut(db: MockDb): AiSettingsInEffect {
  return { ...db.aiSettings, agent_namespaces: [...db.aiSettings.agent_namespaces] }
}

/* ------------------------------------------------------------------ */
/* Rules (role matrix section J)                                       */
/* ------------------------------------------------------------------ */

/** The owner (while member or admin) and project or platform admins. */
export function mayAskAi(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  if (user.is_service_account) return false
  const project = projectOf(db, idea)
  if (isProjectAdmin(db, project, user)) return true
  const role = effectiveRole(db, project.id, user.id)
  return idea.owner_id === user.id && (role === 'member' || role === 'admin')
}

function proposalOpen(db: MockDb, idea: MockIdea): boolean {
  return proposalOpenFor(db, idea)
}

/** Why an AI request of this kind is unavailable now (`AiBlockedReason`, in check order). */
export function blockedReason(
  db: MockDb,
  idea: MockIdea,
  user: MockUser,
  kind: AiRunKind,
): AiBlockedReason | null {
  if (!mayAskAi(db, idea, user)) return 'not_allowed'
  if (!db.aiSettings.enabled) return 'ai_off'
  if (projectOf(db, idea).archived_at !== null) return 'project_archived'
  if (idea.held_for) return 'awaiting_moderation'
  if (idea.status === 'closed') return 'idea_closed'
  if (kind === 'evaluate' && !evaluationOpen(idea)) return 'evaluation_closed'
  if (kind === 'draft_section') {
    if (!proposalOpen(db, idea)) return 'proposal_not_available'
    if (!proposalOf(db, idea)) return 'no_proposal'
  }
  if (!db.aiAgents.some((agent) => agentPasses(db, agent, idea, kind))) return 'no_agent'
  // Phase 8: "Ask AI to evaluate" is the first evaluator; the research gate guards it.
  if (kind === 'evaluate' && inviteBlocked(db, idea)) return 'research_incomplete'
  return null
}

/** `ai.cancel_run`: the owner and admins, archived projects included. */
export function mayCancel(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return mayAskAi(db, idea, user)
}

/** `evaluation.include_ai`: the owner and admins, while the idea is writable. */
export function includeBlockedReason(
  db: MockDb,
  idea: MockIdea,
  user: MockUser,
): AiBlockedReason | null {
  if (!mayAskAi(db, idea, user)) return 'not_allowed'
  if (projectOf(db, idea).archived_at !== null) return 'project_archived'
  if (idea.held_for) return 'awaiting_moderation'
  return null
}

export function aiPermissions(db: MockDb, idea: MockIdea, user: MockUser): AiPermissions {
  const evaluate = blockedReason(db, idea, user, 'evaluate')
  const research = blockedReason(db, idea, user, 'research')
  const draft = blockedReason(db, idea, user, 'draft_section')
  const include = includeBlockedReason(db, idea, user)
  return {
    can_request_evaluation: evaluate === null,
    request_evaluation_blocked_by: evaluate,
    can_research: research === null,
    research_blocked_by: research,
    can_draft_section: draft === null,
    draft_section_blocked_by: draft,
    can_cancel: mayCancel(db, idea, user),
    can_include_ai: include === null,
    include_ai_blocked_by: include,
  }
}

/** `ai.delete_note`: the idea's owner and project and platform admins (an idea write). */
export function mayDeleteNote(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return mayAskAi(db, idea, user) && projectOf(db, idea).archived_at === null && !idea.held_for
}

/* ------------------------------------------------------------------ */
/* Runs and events                                                     */
/* ------------------------------------------------------------------ */

export function eventsOf(db: MockDb, run: MockAiRun): MockAiRunEvent[] {
  return db.aiRunEvents.filter((event) => event.run_id === run.id).sort((a, b) => a.seq - b.seq)
}

export function eventOut(event: MockAiRunEvent): AiRunEvent {
  return {
    seq: event.seq,
    type: event.type,
    message: event.message,
    created_at: event.created_at,
    final: FINAL_EVENTS.includes(event.type),
  }
}

export function runOut(db: MockDb, run: MockAiRun, user: MockUser): AiRun {
  const idea = db.ideas.find((i) => i.id === run.idea_id)
  const agent = agentById(db, run.agent_id)
  const active = isActive(run.status)
  const events = eventsOf(db, run)
  return {
    id: run.id,
    idea_id: run.idea_id,
    kind: run.kind,
    section_key: run.section_key,
    status: run.status,
    agent: agent
      ? agentRef(db, agent)
      : { id: run.agent_id, display_name: 'AI agent', purposes: [], user_id: run.agent_id },
    requested_by: userRefById(db, run.requested_by_id),
    created_at: run.created_at,
    started_at: run.started_at,
    finished_at: run.finished_at,
    deadline_at:
      run.status === 'running' && run.started_at
        ? new Date(Date.parse(run.started_at) + run.timeout_seconds * 1000).toISOString()
        : null,
    cancel_requested: active && run.cancel_requested_at !== null,
    can_cancel: active && Boolean(idea && mayCancel(db, idea, user)),
    error:
      (run.status === 'failed' || run.status === 'timed_out') && run.error_code
        ? {
            code: run.error_code,
            message: run.error_message ?? AI_RUN_ERROR_MESSAGES[run.error_code],
          }
        : null,
    result: {
      evaluation_id: run.evaluation_id,
      note_id: run.activity_event_id,
      suggestion_id: run.suggestion_id,
    },
    event_count: events.at(-1)?.seq ?? 0,
  }
}

export function runDetailOut(db: MockDb, run: MockAiRun, user: MockUser): AiRunDetail {
  return { ...runOut(db, run, user), events: eventsOf(db, run).map(eventOut) }
}

type RunListener = (event: AiRunEvent) => void
const listeners = new WeakMap<MockDb, Map<string, Set<RunListener>>>()

/** New events of one run, as they are written (the SSE handler streams them). */
export function subscribeRun(db: MockDb, runId: string, listener: RunListener): () => void {
  let byRun = listeners.get(db)
  if (!byRun) {
    byRun = new Map()
    listeners.set(db, byRun)
  }
  const set = byRun.get(runId) ?? new Set()
  set.add(listener)
  byRun.set(runId, set)
  return () => {
    set.delete(listener)
  }
}

/** Adds an event (at most 200 per run, the final included) and tells the streams. */
export function addRunEvent(
  db: MockDb,
  run: MockAiRun,
  type: AiRunEventType,
  message?: string,
): void {
  const events = eventsOf(db, run)
  const final = FINAL_EVENTS.includes(type)
  if (!final && events.length >= AI_RUN_EVENTS_MAX - 1) return
  const event: MockAiRunEvent = {
    run_id: run.id,
    seq: (events.at(-1)?.seq ?? 0) + 1,
    type,
    message: message ?? AI_RUN_EVENT_MESSAGES[type] ?? type,
    created_at: new Date().toISOString(),
  }
  db.aiRunEvents.push(event)
  for (const listener of listeners.get(db)?.get(run.id) ?? []) listener(eventOut(event))
}

function hasResult(run: MockAiRun): boolean {
  return Boolean(run.evaluation_id ?? run.activity_event_id ?? run.suggestion_id)
}

/**
 * Ends a run (compare-and-set in the API): a recorded result succeeds unless a
 * cancel was asked for; an evaluate run that assigned the agent and ends
 * without its submitted evaluation takes the assignment back.
 */
export function finishRun(
  db: MockDb,
  run: MockAiRun,
  status: Exclude<AiRunStatus, 'queued' | 'running'>,
  error?: { code: AiRunError; message?: string },
): void {
  if (!isActive(run.status)) return
  let final = status
  if (status !== 'cancelled' && run.cancel_requested_at) final = 'cancelled'
  else if ((status === 'failed' || status === 'timed_out') && hasResult(run)) final = 'succeeded'
  run.status = final
  run.finished_at = new Date().toISOString()
  if (final === 'failed' || final === 'timed_out') {
    const code = error?.code ?? (final === 'timed_out' ? 'timed_out' : 'internal_error')
    run.error_code = code
    run.error_message = error?.message ?? AI_RUN_ERROR_MESSAGES[code]
  }
  const idea = db.ideas.find((i) => i.id === run.idea_id)
  const agent = agentById(db, run.agent_id)
  if (idea && agent && run.kind === 'evaluate' && run.assigned_evaluator) {
    const evaluation = evaluationOf(db, idea.id, agent.user_id)
    if (evaluation?.status !== 'submitted') {
      db.assignments = db.assignments.filter(
        (a) => !(a.idea_id === idea.id && a.user_id === agent.user_id),
      )
      if (evaluation) db.evaluations = db.evaluations.filter((e) => e !== evaluation)
      pushEvent(db, idea, 'evaluator_removed', null, { evaluator_id: agent.user_id })
      recordAudit(
        db,
        null,
        'evaluator.remove',
        { type: 'idea', id: idea.id },
        {
          rule: 'ai.request_evaluation',
          evaluator_id: agent.user_id,
          run_id: run.id,
          reason: 'ai_run_ended',
        },
        idea.project_id,
      )
    }
  }
  addRunEvent(
    db,
    run,
    final,
    final === 'failed' || final === 'timed_out' ? (run.error_message ?? undefined) : undefined,
  )
  invalidateIndexes()
  flushFanOut(db)
}

/** An activity event written outside a request (the worker), fanned out at once. */
function pushEvent(
  db: MockDb,
  idea: MockIdea,
  type: MockEvent['type'],
  actorId: string | null,
  payload: Record<string, unknown>,
): MockEvent {
  const at = new Date().toISOString()
  const event: MockEvent = {
    id: newId(db, ID_KIND.event),
    idea_id: idea.id,
    actor_id: actorId,
    type,
    payload,
    comment_id: null,
    created_at: at,
  }
  db.events.push(event)
  db.pendingEvents.push(event)
  idea.last_activity_at = at
  return event
}

/** Cancel: a queued run ends at once; a running one gets a request the worker acts on. */
export function cancelRun(db: MockDb, run: MockAiRun, actor: MockUser): 'cancelled' | 'requested' {
  if (run.status === 'queued') {
    run.cancel_requested_at = new Date().toISOString()
    run.cancel_requested_by_id = actor.id
    finishRun(db, run, 'cancelled')
    return 'cancelled'
  }
  if (run.cancel_requested_at === null) {
    run.cancel_requested_at = new Date().toISOString()
    run.cancel_requested_by_id = actor.id
    addRunEvent(db, run, 'cancel_requested')
  }
  scheduleRun(db, run, Math.min(paceSetting(), 600))
  return 'requested'
}

/* ------------------------------------------------------------------ */
/* The pretend worker                                                  */
/* ------------------------------------------------------------------ */

type Step =
  | { kind: 'start' }
  | { kind: 'event'; type: AiRunEventType }
  | { kind: 'tool'; tool: string }
  | { kind: 'write' }
  | { kind: 'succeed' }
  | { kind: 'fail'; code: AiRunError; message?: string }
  | { kind: 'wait' }

const READS: Record<AiRunKind, string[]> = {
  evaluate: ['get_rubric', 'get_idea'],
  research: ['get_idea'],
  draft_section: ['get_idea', 'get_proposal'],
}

function plan(run: MockAiRun): Step[] {
  const start: Step[] = [
    { kind: 'start' },
    { kind: 'event', type: 'agent_accepted' },
    { kind: 'event', type: 'agent_working' },
  ]
  const reads = READS[run.kind].map((tool): Step => ({ kind: 'tool', tool }))
  switch (run.outcome) {
    case 'queued':
      return []
    case 'unreachable':
      return [
        { kind: 'start' },
        { kind: 'event', type: 'retrying' },
        { kind: 'event', type: 'retrying' },
        {
          kind: 'fail',
          code: 'agent_unreachable',
          message: `${AI_RUN_ERROR_MESSAGES.agent_unreachable} (HTTP 503)`,
        },
      ]
    case 'fail':
      return [...start, reads[0] ?? { kind: 'wait' }, { kind: 'fail', code: 'agent_failed' }]
    case 'no_result':
      return [...start, ...reads, { kind: 'fail', code: 'no_result' }]
    case 'timeout':
    case 'slow':
      return [...start, reads[0] ?? { kind: 'wait' }, { kind: 'wait' }]
    case 'succeed':
      return [...start, ...reads, { kind: 'write' }, { kind: 'succeed' }]
  }
}

/** Runs the next step after `delay` ms (default: the pace knob). */
export function scheduleRun(db: MockDb, run: MockAiRun, delay = paceSetting()): void {
  if (run.outcome === 'queued' && run.status === 'queued') return
  setTimeout(() => step(db, run.id), delay)
}

function step(db: MockDb, runId: string): void {
  const run = db.aiRuns.find((r) => r.id === runId)
  if (!run || !isActive(run.status)) return
  const idea = db.ideas.find((i) => i.id === run.idea_id)
  const agent = agentById(db, run.agent_id)
  if (!idea || !agent) {
    finishRun(db, run, 'failed', { code: 'agent_unavailable' })
    return
  }
  if (run.cancel_requested_at) {
    finishRun(db, run, 'cancelled')
    return
  }
  if (run.status === 'running' && run.started_at) {
    const deadline = Date.parse(run.started_at) + run.timeout_seconds * 1000
    if (Date.now() >= deadline) {
      finishRun(db, run, 'timed_out', { code: 'timed_out' })
      return
    }
  }
  const steps = plan(run)
  const next = steps[Math.min(run.step, steps.length - 1)]
  if (!next) return
  if (next.kind !== 'wait') run.step += 1
  switch (next.kind) {
    case 'start':
      if (!db.aiSettings.enabled) {
        finishRun(db, run, 'failed', { code: 'ai_disabled' })
        return
      }
      if (!agentPasses(db, agent, idea, run.kind)) {
        finishRun(db, run, 'failed', { code: 'agent_unavailable' })
        return
      }
      run.status = 'running'
      run.started_at = new Date().toISOString()
      if (run.outcome === 'timeout') {
        run.timeout_seconds = Math.max(1, Math.ceil((paceSetting() * 6) / 1000))
      }
      addRunEvent(db, run, 'started')
      break
    case 'event':
      addRunEvent(db, run, next.type)
      break
    case 'tool':
      addRunEvent(db, run, 'tool_called', AI_TOOL_MESSAGES[next.tool])
      break
    case 'write': {
      const tool =
        run.kind === 'evaluate'
          ? 'submit_evaluation'
          : run.kind === 'research'
            ? 'add_research_note'
            : 'propose_proposal_section'
      const error = writeResult(db, run, idea, agent)
      addRunEvent(
        db,
        run,
        'tool_called',
        `${AI_TOOL_MESSAGES[tool] ?? tool}${error ? `: ${error}` : ''}`,
      )
      if (error) {
        finishRun(db, run, 'failed', { code: 'no_result' })
        return
      }
      addRunEvent(db, run, 'result_recorded', RESULT_MESSAGES[run.kind])
      invalidateIndexes()
      flushFanOut(db)
      break
    }
    case 'succeed':
      finishRun(db, run, hasResult(run) ? 'succeeded' : 'failed', { code: 'no_result' })
      return
    case 'fail':
      finishRun(db, run, 'failed', { code: next.code, message: next.message })
      return
    case 'wait':
      break
  }
  scheduleRun(db, run)
}

/** What the fake agent writes through MCP; an MCP error code when it can't. */
function writeResult(
  db: MockDb,
  run: MockAiRun,
  idea: MockIdea,
  agent: MockAiAgent,
): string | null {
  if (projectOf(db, idea).archived_at !== null) return 'project_archived'
  if (run.kind === 'evaluate') return writeEvaluation(db, run, idea, agent)
  if (run.kind === 'research') return writeNote(db, run, idea, agent)
  return writeSuggestion(db, run, idea, agent)
}

const SCORE_PATTERN = [4, 3, 4, 2, 3, 4, 3]

function writeEvaluation(
  db: MockDb,
  run: MockAiRun,
  idea: MockIdea,
  agent: MockAiAgent,
): string | null {
  if (!evaluationOpen(idea)) return 'evaluation_closed'
  if (!rowsForIdea(db.assignments, idea.id).some((a) => a.user_id === agent.user_id)) {
    return 'forbidden'
  }
  const key = ideaKey(db, idea)
  const criteria = activeCriteria(db, idea.project_id)
  const now = new Date().toISOString()
  const scores = criteria.map((criterion, index) => ({
    criterion_id: criterion.id,
    score: SCORE_PATTERN[index % SCORE_PATTERN.length] ?? 3,
    comment: `${criterion.name} for ${key}: ${
      criterion.inverted
        ? 'the effort looks moderate; most of it is integration work we have done before.'
        : 'the idea addresses a need customers raise often, with evidence from comparable products.'
    }`,
    sources: [
      {
        title: `${criterion.name}: industry benchmark`,
        url: `https://example.org/benchmarks/${criterion.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
      },
      {
        title: 'Customer research summary 2026',
        url: 'https://research.example.com/reports/customer-needs-2026',
      },
    ],
  }))
  let evaluation = evaluationOf(db, idea.id, agent.user_id)
  const changed =
    evaluation?.status === 'submitted' &&
    (evaluation.recommendation !== 'go' ||
      scores.some(
        (s) =>
          evaluation?.scores.find((old) => old.criterion_id === s.criterion_id)?.score !== s.score,
      ))
  if (!evaluation) {
    evaluation = {
      id: newId(db, ID_KIND.evaluation),
      idea_id: idea.id,
      evaluator_id: agent.user_id,
      status: 'draft',
      scores: [],
      recommendation: null,
      comment: '',
      submitted_at: null,
      edited_at: null,
      updated_at: now,
      // Left out of the aggregate until the owner includes it (contract-phase6 §3.7).
      include_in_aggregate: false,
    }
    db.evaluations.push(evaluation)
  }
  const first = evaluation.status !== 'submitted'
  evaluation.scores = scores
  evaluation.recommendation = 'go'
  evaluation.comment = `Worth pursuing: ${idea.title} has a clear benefit and manageable risk. Check the cited sources before relying on them.`
  evaluation.updated_at = now
  if (first) {
    evaluation.status = 'submitted'
    evaluation.submitted_at = now
    evaluation.include_in_aggregate = false
    pushEvent(db, idea, 'evaluation_submitted', agent.user_id, { evaluator_id: agent.user_id })
  } else {
    evaluation.edited_at = now
    if (changed) evaluation.include_in_aggregate = false
  }
  run.evaluation_id = evaluation.id
  return null
}

function writeNote(db: MockDb, run: MockAiRun, idea: MockIdea, agent: MockAiAgent): string | null {
  if (idea.status === 'closed') return 'idea_closed'
  const key = ideaKey(db, idea)
  const payload = {
    run_id: run.id,
    agent_id: agent.id,
    body_md: `## What we found\n\nThree comparable programmes suggest **${idea.title.toLowerCase()}** is feasible within a quarter [1][2].\n\n- Customers in two surveys asked for it unprompted [2]\n- The main risk is integration with existing systems [3]\n- Similar launches report a payback of 6–9 months\n\n## Open questions\n\n1. Which customer segment should pilot it?\n2. What does support need before launch?\n\n_Research for ${key}. Check the sources: they were found by an AI agent._`,
    sources: [
      {
        title: 'Comparable programmes: a 2026 review',
        url: 'https://example.org/reviews/programmes-2026',
      },
      {
        title: 'Customer survey, spring 2026',
        url: 'https://research.example.com/surveys/spring-2026',
      },
      {
        title: 'Integration risks in retail platforms',
        url: 'https://blog.example.net/integration-risks',
      },
    ],
  }
  const existing = run.activity_event_id
    ? db.events.find((e) => e.id === run.activity_event_id)
    : undefined
  if (existing) {
    existing.payload = payload
    return null
  }
  const event = pushEvent(db, idea, 'ai_research_note', agent.user_id, payload)
  run.activity_event_id = event.id
  return null
}

function writeSuggestion(
  db: MockDb,
  run: MockAiRun,
  idea: MockIdea,
  agent: MockAiAgent,
): string | null {
  if (!proposalOpen(db, idea)) return 'proposal_not_available'
  const proposal = proposalOf(db, idea)
  const sectionKey = run.section_key
  if (!proposal || !sectionKey) return 'not_found'
  const section = db.proposalSections.find(
    (s) => s.proposal_id === proposal.id && s.key === sectionKey,
  )
  const title = activeSection(db, idea.project_id, sectionKey)?.title ?? sectionKey
  const now = new Date().toISOString()
  // Its earlier pending suggestion for the section is replaced (contract-phase5 §3.4).
  for (const old of db.proposalSuggestions) {
    if (
      old.proposal_id === proposal.id &&
      old.section_key === sectionKey &&
      old.author_id === agent.user_id &&
      old.status === 'pending'
    ) {
      old.status = 'discarded'
      old.decided_at = now
      old.decided_by_id = agent.user_id
    }
  }
  const id = newId(db, ID_KIND.phase5)
  db.proposalSuggestions.push({
    id,
    proposal_id: proposal.id,
    section_key: sectionKey,
    author_id: agent.user_id,
    body_md: `${title} for ${idea.title}, drafted from the idea and the proposal so far:\n\n- **Main point:** what changes for customers, and how we will know it worked\n- **Evidence:** the figures in the idea's description and the evaluations' comments\n- **Next step:** a four-week pilot with one customer segment\n\nCheck the facts before you accept this text.`,
    base_version: section?.version ?? 1,
    source: 'ai',
    status: 'pending',
    created_at: now,
    decided_at: null,
    decided_by_id: null,
  })
  run.suggestion_id = id
  return null
}

/* ------------------------------------------------------------------ */
/* Research notes                                                      */
/* ------------------------------------------------------------------ */

/** The host as `Citation.host` shows it (ASCII: the URL parser gives punycode). */
export function citationOut(source: MockCitation): Citation {
  let host = ''
  try {
    host = new URL(source.url).hostname
  } catch {
    host = ''
  }
  return { title: source.title, url: source.url, host }
}

export function researchNoteOut(db: MockDb, event: MockEvent, user: MockUser): ResearchNote {
  const payload = event.payload
  const agentId = typeof payload.agent_id === 'string' ? payload.agent_id : null
  const agent = agentId ? agentById(db, agentId) : undefined
  const deleted = payload.deleted === true
  const idea = db.ideas.find((i) => i.id === event.idea_id)
  const sources = Array.isArray(payload.sources) ? (payload.sources as MockCitation[]) : []
  return {
    id: event.id,
    run_id: typeof payload.run_id === 'string' ? payload.run_id : null,
    agent: agent ? agentRef(db, agent) : null,
    body_md: deleted ? '' : typeof payload.body_md === 'string' ? payload.body_md : '',
    sources: deleted ? [] : sources.map(citationOut),
    deleted,
    can_delete: !deleted && Boolean(idea && mayDeleteNote(db, idea, user)),
  }
}
