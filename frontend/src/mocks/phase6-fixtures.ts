/**
 * Phase 6 fixtures (contract-phase6): registered kagent agents with their
 * service accounts, memberships and keys, AI runs with their progress events,
 * an AI evaluation with rationale and sources, a research note and the audit
 * entries they leave. Deterministic, relative to `db.now`. Useful places:
 *
 * - **Idea evaluator** (`soundings/idea-evaluator`, evaluate + research;
 *   Customer Innovation and Sustainability) and the **Research agent**
 *   (`soundings/research-agent`, research + draft_section; Customer Innovation;
 *   Phase 5's service account and key) are enabled. **Market scout**
 *   (`kagent-agents/market-scout`, A2A 1.0) is disabled: its key was revoked
 *   and a project admin made it a viewer in Internal Tools.
 * - **CUST-7** (owner Carol; Alice is a pending evaluator) has Idea evaluator's
 *   submitted AI evaluation, left out of the score, from a run Carol asked for.
 * - **CUST-4** (owner Alice) has a research note by the Research agent and an
 *   evaluate run that timed out (its evaluator assignment was taken back).
 * - **CUST-3**'s AI suggestion for Benefits came from a draft run.
 * - **CUST-2** (owner Alice; Bob and Carol submitted, Dave pending) has no AI
 *   runs yet: ask the AI to evaluate it.
 */
import type { AiRunEventType, AuditAction, AuditTargetType } from '@/api/types'

import type { MockAiAgent, MockAiRun, MockAiRunEvent, MockCitation } from './ai'
import type { MockDb, MockEventType, PROJECTS as ProjectsMap, USERS as UsersMap } from './db'
import { API_KEYS, PHASE5_USERS, SUGGESTIONS } from './phase5-fixtures'

type Users = typeof UsersMap
type Projects = typeof ProjectsMap

/** As db.ts `mockId` (not imported: db.ts imports this module). */
const mockId = (kind: string, n: number) =>
  `${kind}0000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** Phase 6's service accounts (the Research agent's is Phase 5's). */
export const PHASE6_USERS = {
  evaluator: mockId('f', 0x301),
  scout: mockId('f', 0x302),
  research: PHASE5_USERS.agent,
} as const

export const AGENTS = {
  evaluator: mockId('f', 0x311),
  research: mockId('f', 0x312),
  scout: mockId('f', 0x313),
} as const

export const PHASE6_KEYS = {
  evaluator: mockId('f', 0x321),
  scoutRevoked: mockId('f', 0x322),
} as const

export const RUNS = {
  cust7Evaluation: mockId('f', 0x331),
  cust4Research: mockId('f', 0x332),
  cust4TimedOut: mockId('f', 0x333),
  cust3Draft: mockId('f', 0x334),
} as const

/** The research note on CUST-4 (its activity item's id). */
export const RESEARCH_NOTE_ID = mockId('f', 0x341)

const RATIONALE: [string, MockCitation[]][] = [
  [
    'Customers already send video messages with gifts on other platforms; a branded version keeps that moment in our checkout. Value is real but limited to the gifting season.',
    [
      {
        title: 'Gifting trends report 2026',
        url: 'https://example.org/reports/gifting-trends-2026',
      },
      {
        title: 'Video messages in e-commerce (Munich study)',
        url: 'https://xn--mnchen-3ya.example/studien/video-geschenke',
      },
    ],
  ],
  [
    'Recording and hosting short videos is well understood; the open question is moderation of what people record.',
    [{ title: 'Hosting short video at scale', url: 'https://engineering.example.com/short-video' }],
  ],
  ['Two to three months for one team: recording, storage, moderation and the gift card page.', []],
  [
    'It fits the plan to grow gifting, though it doesn’t help the repeat-purchase goal.',
    [{ title: 'Strategy one-pager (public summary)', url: 'https://example.org/strategy-2026' }],
  ],
  [
    'Moderation and storage costs are the main risks; a cap on video length keeps both down.',
    [
      { title: 'Content moderation costs', url: 'https://example.net/moderation-costs' },
      { title: 'Retention policies for user video', url: 'https://example.org/video-retention' },
    ],
  ],
]

const RESEARCH_NOTE = `## Summary

Partner APIs for marketplace sellers are common among mid-sized retailers; most start with **stock and order sync** before pricing [1].

## What comparable programmes did

- Two retailers of our size launched a read-only API first and added writes after six months [1][2]
- Sellers asked most for webhooks on new orders, not polling [2]
- Rate limits and per-seller keys were the main support topics [3]

## Open questions for the team

1. Do we offer a sandbox from day one?
2. Who supports sellers' developers?

Read the [developer survey](https://research.example.com/surveys/marketplace-developers) for the raw answers.`

const RESEARCH_SOURCES: MockCitation[] = [
  {
    title: 'Marketplace partner APIs: a 2026 review',
    url: 'https://example.org/reviews/marketplace-apis-2026',
  },
  {
    title: 'What sellers want from retailer APIs (survey)',
    url: 'https://research.example.com/surveys/marketplace-developers',
  },
  {
    title: 'Running a public API: support lessons',
    url: 'https://blog.example.net/public-api-support',
  },
]

const STEP_MESSAGES: Partial<Record<AiRunEventType, string>> = {
  queued: 'Waiting to start',
  started: 'Sending the request to the agent',
  agent_accepted: 'The agent started',
  agent_working: 'The agent is working',
  succeeded: 'Done',
}

export function seedPhase6(
  db: MockDb,
  ctx: { users: Users; projects: Projects; nextId: (kind: number | string) => string },
): void {
  const { users, projects } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  const idea = (number: number, project = projects.cust) =>
    db.ideas.find((i) => i.project_id === project && i.number === number)

  /* Service accounts, memberships and keys ------------------------------ */
  const account = (id: string, name: string, createdAgo: number) => ({
    id,
    display_name: name,
    email: `agent-${id}@soundings.invalid`,
    avatar_url: null,
    is_platform_admin: false,
    is_active: true,
    is_service_account: true,
    is_break_glass: false,
    created_at: iso(now - createdAgo),
    last_seen_at: null,
  })
  db.users.push(
    account(PHASE6_USERS.evaluator, 'Idea evaluator', 6 * DAY),
    account(PHASE6_USERS.scout, 'Market scout', 20 * DAY),
  )
  const member = (projectId: string, userId: string, role: 'member' | 'viewer', ago: number) =>
    db.members.push({ project_id: projectId, user_id: userId, role, joined_at: iso(now - ago) })
  member(projects.cust, PHASE6_USERS.evaluator, 'member', 6 * DAY)
  member(projects.green, PHASE6_USERS.evaluator, 'member', 6 * DAY)
  member(projects.cust, PHASE6_USERS.research, 'member', 9 * DAY)
  member(projects.tool, PHASE6_USERS.scout, 'viewer', 20 * DAY)

  db.apiKeys.push(
    {
      id: PHASE6_KEYS.evaluator,
      user_id: PHASE6_USERS.evaluator,
      name: 'kagent soundings/idea-evaluator',
      lookup_id: 'Id3aEva1uat0',
      scopes: ['read', 'write', 'evaluate', 'mcp'],
      project_ids: [projects.cust, projects.green],
      expires_at: null,
      created_at: iso(now - 6 * DAY),
      created_by_id: users.priya,
      created_auth_method: 'sso',
      last_used_at: iso(now - 5 * HOUR + 2 * MINUTE),
      revoked_at: null,
      revoked_by_id: null,
    },
    {
      id: PHASE6_KEYS.scoutRevoked,
      user_id: PHASE6_USERS.scout,
      name: 'kagent kagent-agents/market-scout',
      lookup_id: 'MrktSc0ut7Kx',
      scopes: ['read', 'write', 'mcp'],
      project_ids: [projects.tool],
      expires_at: null,
      created_at: iso(now - 20 * DAY),
      created_by_id: users.priya,
      created_auth_method: 'sso',
      last_used_at: iso(now - 4 * DAY),
      revoked_at: iso(now - 3 * DAY),
      revoked_by_id: users.priya,
    },
  )
  // Phase 5's Research agent key now follows its agent: research + draft_section.
  const researchKey = db.apiKeys.find((key) => key.id === API_KEYS.agent)
  if (researchKey) {
    researchKey.name = 'kagent soundings/research-agent'
    researchKey.scopes = ['read', 'write', 'mcp']
  }

  /* Agents --------------------------------------------------------------- */
  const agent = (spec: Omit<MockAiAgent, 'updated_at'> & { updatedAgo?: number }): MockAiAgent => {
    const { updatedAgo, ...rest } = spec
    return {
      ...rest,
      updated_at: updatedAgo === undefined ? spec.created_at : iso(now - updatedAgo),
    }
  }
  db.aiAgents.push(
    agent({
      id: AGENTS.evaluator,
      user_id: PHASE6_USERS.evaluator,
      description: 'Scores ideas against the project rubric, citing a source for each criterion.',
      namespace: 'soundings',
      name: 'idea-evaluator',
      protocol: 'kagent_v0_10',
      purposes: ['evaluate', 'research'],
      project_ids: [projects.cust, projects.green],
      enabled: true,
      created_at: iso(now - 6 * DAY),
      created_by_id: users.priya,
    }),
    agent({
      id: AGENTS.research,
      user_id: PHASE6_USERS.research,
      description: 'Writes research notes and drafts proposal sections.',
      namespace: 'soundings',
      name: 'research-agent',
      protocol: 'kagent_v0_10',
      purposes: ['research', 'draft_section'],
      project_ids: [projects.cust],
      enabled: true,
      created_at: iso(now - 9 * DAY),
      created_by_id: users.priya,
      updatedAgo: 6 * DAY,
    }),
    agent({
      id: AGENTS.scout,
      user_id: PHASE6_USERS.scout,
      description: 'Looks for competing products (being replaced).',
      namespace: 'kagent-agents',
      name: 'market-scout',
      protocol: 'kagent_v1_0',
      purposes: ['research'],
      project_ids: [projects.tool],
      enabled: false,
      created_at: iso(now - 20 * DAY),
      created_by_id: users.priya,
      updatedAgo: 3 * DAY,
    }),
  )

  /* Runs, their events and their results -------------------------------- */
  const addEvents = (runId: string, start: number, steps: [AiRunEventType, string?][]) => {
    steps.forEach(([type, message], index) => {
      const event: MockAiRunEvent = {
        run_id: runId,
        seq: index + 1,
        type,
        message: message ?? STEP_MESSAGES[type] ?? type,
        created_at: iso(start + index * 4_000),
      }
      db.aiRunEvents.push(event)
    })
  }
  const run = (
    spec: Partial<MockAiRun> & Pick<MockAiRun, 'id' | 'idea_id' | 'agent_id' | 'kind'>,
  ) =>
    db.aiRuns.push({
      section_key: null,
      status: 'succeeded',
      requested_by_id: users.alice,
      created_at: iso(now),
      started_at: iso(now),
      finished_at: iso(now),
      timeout_seconds: 300,
      cancel_requested_at: null,
      cancel_requested_by_id: null,
      error_code: null,
      error_message: null,
      evaluation_id: null,
      suggestion_id: null,
      activity_event_id: null,
      assigned_evaluator: false,
      outcome: 'succeed',
      step: 0,
      ...spec,
    })
  const activity = (
    ideaId: string,
    type: MockEventType,
    actor: string | null,
    at: number,
    payload: Record<string, unknown>,
    id = ctx.nextId(7),
  ) => {
    db.events.push({
      id,
      idea_id: ideaId,
      actor_id: actor,
      type,
      payload,
      comment_id: null,
      created_at: iso(at),
    })
    return id
  }
  const audit = (
    ago: number,
    action: AuditAction,
    actor: string | null,
    target: [AuditTargetType, string],
    details: Record<string, unknown>,
    projectId: string | null = null,
  ) =>
    db.audit.push({
      id: ctx.nextId('b'),
      created_at: iso(now - ago),
      actor_id: actor,
      action,
      target_type: target[0],
      target_id: target[1],
      project_id: projectId,
      details: actor ? { ...details, auth_method: 'sso' } : details,
    })

  // CUST-7: Carol asked Idea evaluator; its evaluation is in, left out of the score.
  const cust7 = idea(7)
  if (cust7) {
    const start = now - 5 * HOUR
    const evaluationId = ctx.nextId(5)
    const criteria = db.criteria
      .filter((c) => c.project_id === cust7.project_id && !c.archived)
      .sort((a, b) => a.position - b.position)
    db.assignments.push({
      idea_id: cust7.id,
      user_id: PHASE6_USERS.evaluator,
      invited_at: iso(start),
    })
    db.evaluations.push({
      id: evaluationId,
      idea_id: cust7.id,
      evaluator_id: PHASE6_USERS.evaluator,
      status: 'submitted',
      scores: criteria.map((criterion, index) => ({
        criterion_id: criterion.id,
        score: [3, 4, 3, 3, 2][index] ?? 3,
        comment: RATIONALE[index]?.[0] ?? '',
        sources: RATIONALE[index]?.[1] ?? [],
      })),
      recommendation: 'maybe',
      comment:
        'A pleasant feature for the gifting season with modest reach. Worth a small pilot if moderation is solved first.',
      submitted_at: iso(start + 28_000),
      edited_at: null,
      updated_at: iso(start + 28_000),
      include_in_aggregate: false,
    })
    activity(cust7.id, 'evaluator_added', users.carol, start, {
      evaluator_id: PHASE6_USERS.evaluator,
    })
    activity(cust7.id, 'evaluation_submitted', PHASE6_USERS.evaluator, start + 28_000, {
      evaluator_id: PHASE6_USERS.evaluator,
    })
    run({
      id: RUNS.cust7Evaluation,
      idea_id: cust7.id,
      agent_id: AGENTS.evaluator,
      kind: 'evaluate',
      requested_by_id: users.carol,
      created_at: iso(start),
      started_at: iso(start + 4_000),
      finished_at: iso(start + 32_000),
      evaluation_id: evaluationId,
      assigned_evaluator: true,
    })
    addEvents(RUNS.cust7Evaluation, start, [
      ['queued'],
      ['started'],
      ['agent_accepted'],
      ['agent_working'],
      ['tool_called', 'Read the rubric'],
      ['tool_called', 'Read the idea'],
      ['tool_called', 'Saved its evaluation'],
      ['result_recorded', 'Evaluation submitted'],
      ['succeeded'],
    ])
    audit(
      5 * HOUR,
      'ai_run.request',
      users.carol,
      ['idea', cust7.id],
      {
        rule: 'ai.request_evaluation',
        run_id: RUNS.cust7Evaluation,
        agent_id: AGENTS.evaluator,
        kind: 'evaluate',
        section_key: null,
      },
      projects.cust,
    )
    audit(
      5 * HOUR,
      'evaluator.add',
      users.carol,
      ['idea', cust7.id],
      {
        rule: 'ai.request_evaluation',
        evaluator_id: PHASE6_USERS.evaluator,
      },
      projects.cust,
    )
  }

  // CUST-4: a research note from the Research agent, then an evaluate run that timed out.
  const cust4 = idea(4)
  if (cust4) {
    const researchStart = now - 2 * DAY
    activity(
      cust4.id,
      'ai_research_note',
      PHASE6_USERS.research,
      researchStart + 24_000,
      {
        run_id: RUNS.cust4Research,
        agent_id: AGENTS.research,
        body_md: RESEARCH_NOTE,
        sources: RESEARCH_SOURCES,
      },
      RESEARCH_NOTE_ID,
    )
    run({
      id: RUNS.cust4Research,
      idea_id: cust4.id,
      agent_id: AGENTS.research,
      kind: 'research',
      created_at: iso(researchStart),
      started_at: iso(researchStart + 4_000),
      finished_at: iso(researchStart + 28_000),
      activity_event_id: RESEARCH_NOTE_ID,
    })
    addEvents(RUNS.cust4Research, researchStart, [
      ['queued'],
      ['started'],
      ['agent_accepted'],
      ['agent_working'],
      ['tool_called', 'Read the idea'],
      ['tool_called', 'Wrote the research note'],
      ['result_recorded', 'Research note saved'],
      ['succeeded'],
    ])
    const timedOutStart = now - DAY
    activity(cust4.id, 'evaluator_added', users.alice, timedOutStart, {
      evaluator_id: PHASE6_USERS.evaluator,
    })
    activity(cust4.id, 'evaluator_removed', null, timedOutStart + 5 * MINUTE + 8_000, {
      evaluator_id: PHASE6_USERS.evaluator,
    })
    run({
      id: RUNS.cust4TimedOut,
      idea_id: cust4.id,
      agent_id: AGENTS.evaluator,
      kind: 'evaluate',
      status: 'timed_out',
      created_at: iso(timedOutStart),
      started_at: iso(timedOutStart + 4_000),
      finished_at: iso(timedOutStart + 5 * MINUTE + 4_000),
      error_code: 'timed_out',
      error_message: 'The agent didn’t finish in time.',
      assigned_evaluator: true,
    })
    addEvents(RUNS.cust4TimedOut, timedOutStart, [
      ['queued'],
      ['started'],
      ['agent_accepted'],
      ['agent_working'],
      ['tool_called', 'Read the rubric'],
    ])
    db.aiRunEvents.push({
      run_id: RUNS.cust4TimedOut,
      seq: 6,
      type: 'timed_out',
      message: 'The agent didn’t finish in time.',
      created_at: iso(timedOutStart + 5 * MINUTE + 4_000),
    })
    audit(
      2 * DAY,
      'ai_run.request',
      users.alice,
      ['idea', cust4.id],
      {
        rule: 'ai.research',
        run_id: RUNS.cust4Research,
        agent_id: AGENTS.research,
        kind: 'research',
        section_key: null,
      },
      projects.cust,
    )
    audit(
      DAY,
      'ai_run.request',
      users.alice,
      ['idea', cust4.id],
      {
        rule: 'ai.request_evaluation',
        run_id: RUNS.cust4TimedOut,
        agent_id: AGENTS.evaluator,
        kind: 'evaluate',
        section_key: null,
      },
      projects.cust,
    )
  }

  // CUST-3: the Research agent's Benefits suggestion came from a draft run.
  const cust3 = idea(3)
  const benefits = db.proposalSuggestions.find((s) => s.id === SUGGESTIONS.agentBenefits)
  if (cust3 && benefits) {
    const start = Date.parse(benefits.created_at) - 20_000
    run({
      id: RUNS.cust3Draft,
      idea_id: cust3.id,
      agent_id: AGENTS.research,
      kind: 'draft_section',
      section_key: 'benefits',
      created_at: iso(start),
      started_at: iso(start + 4_000),
      finished_at: iso(start + 24_000),
      suggestion_id: benefits.id,
    })
    addEvents(RUNS.cust3Draft, start, [
      ['queued'],
      ['started'],
      ['agent_accepted'],
      ['agent_working'],
      ['tool_called', 'Read the idea'],
      ['tool_called', 'Read the proposal'],
      ['tool_called', 'Suggested section text'],
      ['result_recorded', 'Suggestion saved'],
      ['succeeded'],
    ])
  }

  /* Admin audit ---------------------------------------------------------- */
  audit(6 * DAY, 'ai_agent.register', users.priya, ['user', PHASE6_USERS.evaluator], {
    rule: 'platform.manage_agents',
    agent_id: AGENTS.evaluator,
    namespace: 'soundings',
    name: 'idea-evaluator',
    protocol: 'kagent_v0_10',
    purposes: ['evaluate', 'research'],
    project_ids: [projects.cust, projects.green],
  })
  audit(6 * DAY, 'ai_agent.update', users.priya, ['user', PHASE6_USERS.research], {
    rule: 'platform.manage_agents',
    agent_id: AGENTS.research,
    changed: ['purposes'],
  })
  audit(3 * DAY, 'ai_agent.update', users.priya, ['user', PHASE6_USERS.scout], {
    rule: 'platform.manage_agents',
    agent_id: AGENTS.scout,
    changed: ['enabled'],
    enabled: false,
  })
  audit(3 * DAY, 'api_key.revoke', users.priya, ['user', PHASE6_USERS.scout], {
    rule: 'platform.manage_agents',
    key_id: PHASE6_KEYS.scoutRevoked,
    prefix: 'sdg_MrktSc0ut7Kx',
  })

  db.events.sort((a, b) => a.created_at.localeCompare(b.created_at))
  db.audit.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
}
