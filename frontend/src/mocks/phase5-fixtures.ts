/**
 * Phase 5 fixtures (contract-phase5): API keys, proposal suggestions, an AI
 * agent's service account and the audit entries they leave. Deterministic,
 * relative to `db.now`. Useful places:
 *
 * - **Alice** has three keys: "Claude Desktop" (read, evaluate, mcp; Customer
 *   Innovation only; never expires), "Weekly report script" (read; expires in
 *   3 days: shown "in 3 days", in a warning tone) and "Old laptop" (read, write;
 *   expired 5 days ago).
 * - **Priya**, **Bob** and **Mateo Rossi** (a person who hasn't signed in for 41
 *   days: his key is `dormant`) have one each; the **Research agent**
 *   (`PHASE5_USERS.agent`, a service account) has the key Priya made for it.
 * - **CUST-3**'s proposal has four pending suggestions: two for Summary
 *   (Carol through MCP, the Research agent), one for Problem (Bob, written
 *   against an older version: "the section has changed") and one for
 *   Benefits / revenue (the Research agent).
 */
import type { ApiKeyScope, AuditAction, AuditTargetType, ProposalSectionKey } from '@/api/types'

import type { MockApiKey } from './api-keys'
import type { MockDb, PROJECTS as ProjectsMap, USERS as UsersMap } from './db'
import type { MockSuggestion } from './suggestions'

type Users = typeof UsersMap
type Projects = typeof ProjectsMap

/** As db.ts `mockId` (not imported: db.ts imports this module). */
const mockId = (kind: string, n: number) =>
  `${kind}0000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** Phase 5's extra accounts (not in `USERS`: they aren't sign-in fixtures). */
export const PHASE5_USERS = {
  /** An AI agent's service account (Phase 6 registers these; here it already exists). */
  agent: mockId('f', 1),
  /** A person who hasn't signed in for 41 days: his key is dormant. */
  mateo: mockId('f', 2),
} as const

/** Fixture key ids and prefixes (the tests revoke and look them up). */
export const API_KEYS = {
  claudeDesktop: mockId('f', 101),
  weeklyReport: mockId('f', 102),
  oldLaptop: mockId('f', 103),
  grafana: mockId('f', 104),
  jira: mockId('f', 105),
  spreadsheet: mockId('f', 106),
  agent: mockId('f', 107),
  bobRevoked: mockId('f', 108),
} as const

/** Pending suggestions on CUST-3. */
export const SUGGESTIONS = {
  carolSummary: mockId('f', 201),
  agentSummary: mockId('f', 202),
  bobProblem: mockId('f', 203),
  agentBenefits: mockId('f', 204),
} as const

export function seedPhase5(
  db: MockDb,
  ctx: { users: Users; projects: Projects; nextId: (kind: number | string) => string },
): void {
  const { users, projects } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()

  db.users.push(
    {
      id: PHASE5_USERS.agent,
      display_name: 'Research agent',
      email: 'research-agent@agents.soundings.invalid',
      avatar_url: null,
      is_platform_admin: false,
      is_active: true,
      is_service_account: true,
      is_break_glass: false,
      created_at: iso(now - 9 * DAY),
      last_seen_at: null,
    },
    {
      id: PHASE5_USERS.mateo,
      display_name: 'Mateo Rossi',
      email: 'mateo.rossi@example.com',
      avatar_url: null,
      is_platform_admin: false,
      is_active: true,
      is_service_account: false,
      is_break_glass: false,
      created_at: iso(now - 200 * DAY),
      last_seen_at: iso(now - 41 * DAY),
    },
  )

  // Mateo signed in with SSO before he stopped using Soundings.
  db.identities.push({
    id: ctx.nextId('a'),
    user_id: PHASE5_USERS.mateo,
    issuer: 'http://localhost:8080/realms/soundings',
    subject: 'f7e1c0de-5000-4000-8000-00000000mateo',
    linked_at: iso(now - 200 * DAY),
    last_login_at: iso(now - 41 * DAY),
  })

  /* API keys ----------------------------------------------------------- */
  const key = (
    id: string,
    owner: string,
    name: string,
    lookup: string,
    scopes: ApiKeyScope[],
    options: {
      projects?: string[]
      expiresIn?: number
      createdAgo: number
      usedAgo?: number
      by?: string
      revokedAgo?: number
    },
  ): MockApiKey => ({
    id,
    user_id: owner,
    name,
    lookup_id: lookup,
    scopes,
    project_ids: options.projects ?? null,
    expires_at: options.expiresIn === undefined ? null : iso(now + options.expiresIn),
    created_at: iso(now - options.createdAgo),
    created_by_id: options.by ?? owner,
    created_auth_method: 'sso',
    last_used_at: options.usedAgo === undefined ? null : iso(now - options.usedAgo),
    revoked_at: options.revokedAgo === undefined ? null : iso(now - options.revokedAgo),
    revoked_by_id: options.revokedAgo === undefined ? null : users.priya,
  })
  db.apiKeys.push(
    key(
      API_KEYS.claudeDesktop,
      users.alice,
      'Claude Desktop',
      'Cl4uDeD3sk7p',
      ['read', 'evaluate', 'mcp'],
      { projects: [projects.cust], createdAgo: 12 * DAY, usedAgo: 2 * HOUR },
    ),
    key(API_KEYS.weeklyReport, users.alice, 'Weekly report script', 'Wk1yRep0rt5x', ['read'], {
      expiresIn: 3 * DAY,
      createdAgo: 40 * DAY,
      usedAgo: 3 * DAY,
    }),
    key(API_KEYS.oldLaptop, users.alice, 'Old laptop', 'OldL4pt0pK3y', ['read', 'write'], {
      expiresIn: -5 * DAY,
      createdAgo: 95 * DAY,
      usedAgo: 20 * DAY,
    }),
    key(API_KEYS.grafana, users.priya, 'Grafana dashboard', 'Gr4f4n4Dash1', ['read'], {
      createdAgo: 60 * DAY,
      usedAgo: 30 * MINUTE,
    }),
    key(API_KEYS.jira, users.bob, 'Jira sync', 'J1r4SyncB0b2', ['read', 'write'], {
      projects: [projects.cust, projects.tool],
      expiresIn: 200 * DAY,
      createdAgo: 7 * DAY,
    }),
    key(API_KEYS.spreadsheet, PHASE5_USERS.mateo, 'Spreadsheet sync', 'Spr3adSh33t9', ['read'], {
      createdAgo: 80 * DAY,
      usedAgo: 41 * DAY,
    }),
    key(
      API_KEYS.agent,
      PHASE5_USERS.agent,
      'kagent research-agent',
      'R3s3archAg3n',
      ['read', 'write', 'evaluate', 'mcp'],
      { projects: [projects.cust], createdAgo: 9 * DAY, usedAgo: 4 * MINUTE, by: users.priya },
    ),
    key(API_KEYS.bobRevoked, users.bob, 'Old CI token', 'B0bC1T0ken01', ['read'], {
      createdAgo: 30 * DAY,
      usedAgo: 4 * DAY,
      revokedAgo: 3 * DAY,
    }),
  )

  /* Suggestions on CUST-3 ---------------------------------------------- */
  const cust3 = db.ideas.find((i) => i.project_id === projects.cust && i.number === 3)
  const proposal = cust3 && db.proposals.find((p) => p.idea_id === cust3.id)
  if (proposal) {
    const version = (section: ProposalSectionKey) =>
      db.proposalSections.find((s) => s.proposal_id === proposal.id && s.key === section)
        ?.version ?? 1
    const suggestion = (
      id: string,
      section: ProposalSectionKey,
      author: string,
      source: MockSuggestion['source'],
      ago: number,
      body: string,
      base = version(section),
    ): MockSuggestion => ({
      id,
      proposal_id: proposal.id,
      section_key: section,
      author_id: author,
      body_md: body,
      base_version: base,
      source,
      status: 'pending',
      created_at: iso(now - ago),
      decided_at: null,
      decided_by_id: null,
    })
    db.proposalSuggestions.push(
      suggestion(
        SUGGESTIONS.carolSummary,
        'summary',
        users.carol,
        'mcp',
        50 * MINUTE,
        `A monthly curated box for existing customers, starting with **coffee and tea**. Subscribers get three products picked for them, free delivery and 10% off anything else they buy.

Finance’s retention model expects it to lift repeat purchases by **6 points** in the first year and give us a predictable revenue line of about **£48,000 a month** at 2,000 boxes.`,
      ),
      suggestion(
        SUGGESTIONS.agentSummary,
        'summary',
        PHASE5_USERS.agent,
        'ai',
        10 * MINUTE,
        `A monthly coffee and tea box for repeat customers: three curated products, free delivery and 10% off other purchases.

It targets the 8% drop in repeat purchases and creates our first recurring revenue line.`,
      ),
      suggestion(
        SUGGESTIONS.bobProblem,
        'problem',
        users.bob,
        'api',
        DAY,
        `Repeat purchase rate dropped **8%** year on year across all categories (Q2 retention report; coffee alone dropped 11%), and most repeat buyers order the same few products every month.

- They re-order by hand, which is easy to forget
- Competitors already offer subscriptions in coffee and tea
- We have no recurring revenue at all today`,
        version('problem') - 1,
      ),
      suggestion(
        SUGGESTIONS.agentBenefits,
        'benefits',
        PHASE5_USERS.agent,
        'ai',
        12 * MINUTE,
        `- **Recurring revenue:** about £48,000 a month at 2,000 boxes (£24 average box)
- **Retention:** subscribers in comparable programmes buy 1.4 times as often
- **Planning:** a predictable monthly volume for the coffee and tea buyers

We would measure monthly active subscriptions, churn and the repeat purchase rate of subscribers against a matched group.`,
      ),
    )
  }

  /* Audit entries ------------------------------------------------------ */
  const entry = (
    ago: number,
    action: AuditAction,
    actor: string,
    target: [AuditTargetType, string] | null,
    details: Record<string, unknown>,
    projectId: string | null = null,
  ) => {
    db.audit.push({
      id: ctx.nextId('b'),
      created_at: iso(now - ago),
      actor_id: actor,
      action,
      target_type: target?.[0] ?? null,
      target_id: target?.[1] ?? null,
      project_id: projectId,
      details,
    })
  }
  const prefix = (lookup: string) => `sdg_${lookup}`
  const viaKey = (keyId: string) => ({ auth: 'api_key', api_key_id: keyId })
  entry(12 * DAY, 'api_key.create', users.alice, ['user', users.alice], {
    rule: 'api_key.manage_own',
    key_id: API_KEYS.claudeDesktop,
    prefix: prefix('Cl4uDeD3sk7p'),
    scopes: ['read', 'evaluate', 'mcp'],
    restricted: true,
    project_ids: [projects.cust],
    expires_at: null,
    auth_method: 'sso',
  })
  entry(9 * DAY, 'api_key.create', users.priya, ['user', PHASE5_USERS.agent], {
    rule: 'api_key.manage_any',
    key_id: API_KEYS.agent,
    prefix: prefix('R3s3archAg3n'),
    scopes: ['read', 'write', 'evaluate', 'mcp'],
    restricted: true,
    project_ids: [projects.cust],
    expires_at: null,
    auth_method: 'sso',
  })
  entry(7 * DAY, 'api_key.create', users.bob, ['user', users.bob], {
    rule: 'api_key.manage_own',
    key_id: API_KEYS.jira,
    prefix: prefix('J1r4SyncB0b2'),
    scopes: ['read', 'write'],
    restricted: true,
    project_ids: [projects.cust, projects.tool],
    expires_at: iso(now + 200 * DAY),
    auth_method: 'sso',
  })
  entry(3 * DAY, 'api_key.revoke', users.priya, ['user', users.bob], {
    rule: 'api_key.manage_any',
    key_id: API_KEYS.bobRevoked,
    prefix: prefix('B0bC1T0ken01'),
    auth_method: 'sso',
  })
  entry(26 * HOUR, 'mcp.call', users.bob, null, {
    tool: null,
    rule: 'mcp.connect',
    decision: 'deny',
    code: 'insufficient_scope',
    ...viaKey(API_KEYS.jira),
  })
  const idea = (number: number, project = projects.cust) =>
    db.ideas.find((i) => i.project_id === project && i.number === number)?.id ?? ''
  const call = (
    ago: number,
    actor: string,
    keyId: string,
    tool: string,
    rule: string,
    target: [AuditTargetType, string] | null,
    code: string | null = null,
    decision: 'allow' | 'deny' = 'allow',
    projectId: string | null = projects.cust,
  ) =>
    entry(
      ago,
      'mcp.call',
      actor,
      target,
      { tool, rule, decision, code, ...viaKey(keyId) },
      target ? projectId : null,
    )
  call(
    2 * HOUR + 4 * MINUTE,
    users.alice,
    API_KEYS.claudeDesktop,
    'search_ideas',
    'idea.view',
    null,
  )
  call(2 * HOUR + 3 * MINUTE, users.alice, API_KEYS.claudeDesktop, 'get_rubric', 'project.view', [
    'project',
    projects.cust,
  ])
  call(2 * HOUR + 2 * MINUTE, users.alice, API_KEYS.claudeDesktop, 'get_idea', 'idea.view', [
    'idea',
    idea(1),
  ])
  call(
    2 * HOUR + MINUTE,
    users.alice,
    API_KEYS.claudeDesktop,
    'get_idea',
    'idea.view',
    ['idea', idea(1, projects.tool)],
    'not_found',
    'deny',
    projects.tool,
  )
  call(
    2 * HOUR,
    users.alice,
    API_KEYS.claudeDesktop,
    'create_idea',
    'idea.create',
    ['project', projects.cust],
    'insufficient_scope',
    'deny',
  )
  call(13 * MINUTE, PHASE5_USERS.agent, API_KEYS.agent, 'get_proposal', 'proposal.view', [
    'idea',
    idea(3),
  ])
  call(
    12 * MINUTE,
    PHASE5_USERS.agent,
    API_KEYS.agent,
    'propose_proposal_section',
    'proposal.suggest_section',
    ['idea', idea(3)],
  )
  db.audit.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
}
