/**
 * In-memory database for the MSW mock API. Deterministic: the same options
 * always produce the same users, projects, ideas, evaluations, comments and
 * activity (timestamps are relative to `now`). Handlers mutate it; reloading
 * the page starts fresh.
 *
 *   getDb()            the current database (created on first use)
 *   resetDb(options)   replace it, e.g. in tests: resetDb({ now: FIXED_NOW })
 *
 * Records mirror the backend tables (docs/erd.md), not the API shapes:
 * domain.ts turns them into API responses for a given viewer.
 */
import type {
  AuditAction,
  AuditTargetType,
  EmailStatus,
  EmailType,
  GroupSyncMode,
  HoldReason,
  IdeaStatus,
  NotificationMode,
  NotificationType,
  ProjectRole,
  ProjectVisibility,
  Recommendation,
  ResearchStep,
  Resolution,
  StatusLabels,
} from '@/api/types'

import { seedAccess } from './access-fixtures'
import type { MockApiKey } from './api-keys'
import type { MockBrandAsset, MockBrandingProfile } from './branding'
import { seedNotifications } from './notification-fixtures'
import { seedPhase4 } from './phase4-fixtures'
import { seedPhase5 } from './phase5-fixtures'
import type {
  MockProposal,
  MockProposalComment,
  MockProposalSection,
  MockProposalThread,
} from './proposals'
import type { MockPublicForm, MockPublicSubmission } from './public'
import type { MockSuggestion } from './suggestions'
import type { MockAiAgent, MockAiRun, MockAiRunEvent, MockAiSettings, MockCitation } from './ai'
import { seedPhase6 } from './phase6-fixtures'
import { seedPhase8 } from './phase8-fixtures'
import { seedPhase8b } from './phase8b-fixtures'
import type { MockResearchAnswer, MockResearchItem } from './research'
import { defaultTemplate, type MockTemplateSection } from './templates'

export interface MockUser {
  id: string
  display_name: string
  email: string
  avatar_url: string | null
  is_platform_admin: boolean
  is_active: boolean
  is_service_account: boolean
  /** The break-glass admin (contract-phase2 §3.8): never in pickers, roles or groups. */
  is_break_glass: boolean
  created_at: string
  last_seen_at: string | null
}

/* Phase 2: sign-in and access (docs/api/contract-phase2.md, docs/erd.md) */

export interface MockIdentity {
  id: string
  user_id: string
  issuer: string
  subject: string
  linked_at: string
  last_login_at: string | null
}

export interface MockExternalId {
  user_id: string
  kind: string
  value: string
}

export interface MockGroup {
  id: string
  name: string
  description: string
  sync_mode: GroupSyncMode
  /** Normalised, de-duplicated, sorted (contract §3.5). */
  idp_values: string[]
  created_at: string
  updated_at: string
}

export interface MockGroupMember {
  group_id: string
  user_id: string
  manual: boolean
  synced: boolean
  joined_at: string
}

export interface MockGroupGrant {
  project_id: string
  group_id: string
  role: ProjectRole
  granted_at: string
}

export interface MockAuditEntry {
  id: string
  created_at: string
  actor_id: string | null
  action: AuditAction
  target_type: AuditTargetType | null
  target_id: string | null
  project_id: string | null
  details: Record<string, unknown>
}

export interface MockProject {
  id: string
  slug: string
  key: string
  name: string
  description: string
  visibility: ProjectVisibility
  allow_volunteer_owners: boolean
  default_evaluation_days: number
  archived_at: string | null
  created_at: string
  /** Overrides only (the API resolves them against the defaults). */
  status_labels: Partial<StatusLabels>
  next_idea_number: number
  /** Phase 8 (contract-phase8 §3.2): where the optional Research stage sits, if anywhere. */
  research_step: ResearchStep
}

export interface MockMember {
  project_id: string
  user_id: string
  role: ProjectRole
  joined_at: string
}

export interface MockCriterion {
  id: string
  project_id: string
  name: string
  description: string
  weight: number
  inverted: boolean
  guidance: Record<string, string>
  position: number
  archived: boolean
}

export interface MockIdea {
  id: string
  project_id: string
  number: number
  title: string
  summary: string
  description_md: string
  status: IdeaStatus
  resolution: Resolution | null
  owner_id: string | null
  submitted_by: string | null
  created_at: string
  last_activity_at: string
  evaluation_due_at: string | null
  evaluation_closed_at: string | null
  /** Tag ids. */
  tag_ids: string[]
  /**
   * Phase 4 (contract-phase4 §3.6): a public idea waiting for its submitter's
   * confirmation or for moderation. Held ideas are in no list or count.
   */
  held_for?: HoldReason | null
  /**
   * Phase 8b (contract-phase8b §3.1): the idea's researcher (null = nobody: the
   * owner does the research), when they were asked, and the research due date.
   */
  researcher_id?: string | null
  research_assigned_at?: string | null
  research_due_at?: string | null
}

export interface MockTag {
  id: string
  project_id: string
  name: string
}

export interface MockAssignment {
  idea_id: string
  user_id: string
  invited_at: string
}

export interface MockScore {
  criterion_id: string
  score: number | null
  comment: string
  /** Phase 6: an AI evaluator's cited sources (people never cite). */
  sources?: MockCitation[]
}

export interface MockEvaluation {
  id: string
  idea_id: string
  evaluator_id: string
  status: 'draft' | 'submitted'
  scores: MockScore[]
  recommendation: Recommendation | null
  comment: string
  submitted_at: string | null
  edited_at: string | null
  updated_at: string
  include_in_aggregate: boolean
}

export interface MockComment {
  id: string
  idea_id: string
  author_id: string
  body_md: string
  created_at: string
  edited_at: string | null
  deleted_at: string | null
}

export type MockEventType =
  | 'idea_created'
  | 'idea_edited'
  | 'status_changed'
  | 'owner_changed'
  | 'evaluator_added'
  | 'evaluator_removed'
  | 'evaluation_submitted'
  | 'evaluation_closed'
  | 'evaluation_reopened'
  | 'due_date_changed'
  | 'comment'
  /** Phase 6: an AI research note (payload: run_id, agent_id, body_md, sources, deleted). */
  | 'ai_research_note'
  /** Phase 8b: payload from_researcher_id, to_researcher_id, handed_back. */
  | 'researcher_changed'
  /** Phase 8b: payload from_due_at, to_due_at. */
  | 'research_due_date_changed'

export interface MockEvent {
  id: string
  idea_id: string
  actor_id: string | null
  type: MockEventType
  payload: Record<string, unknown>
  comment_id: string | null
  created_at: string
}

/* Phase 3: email and notifications (docs/api/contract-phase3.md, docs/erd.md) */

export interface MockNotification {
  id: string
  user_id: string
  type: NotificationType
  idea_id: string
  actor_id: string | null
  comment_id: string | null
  /** Per type: `due_at`, `days_before`, `evaluator_count`, `from_status`… (never scores). */
  payload: Record<string, unknown>
  dedupe_key: string
  email_mode: NotificationMode
  email_id: string | null
  created_at: string
  read_at: string | null
}

export interface MockOutboxEmail {
  id: string
  type: EmailType
  status: EmailStatus
  recipient_user_id: string | null
  to_address: string | null
  requested_by_id: string | null
  attempts: number
  max_attempts: number
  next_attempt_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  sent_at: string | null
  /** Phase 4: the idea a submitter email is about (required for those, contract-phase4 §3.8). */
  idea_id?: string | null
}

/** The mock instance's email settings (knob `soundings-mock-email`: unset, `off`, `failing`). */
export interface MockEmailSettings {
  configured: boolean
  /** Every send attempt fails with "connection refused" (SMTP down). */
  failing: boolean
}

export interface MockDb {
  now: number
  users: MockUser[]
  projects: MockProject[]
  members: MockMember[]
  criteria: MockCriterion[]
  tags: MockTag[]
  ideas: MockIdea[]
  assignments: MockAssignment[]
  evaluations: MockEvaluation[]
  comments: MockComment[]
  events: MockEvent[]
  /** `${ideaId}:${userId}` */
  votes: Set<string>
  /** `${ideaId}:${userId}` */
  watchers: Set<string>
  identities: MockIdentity[]
  externalIds: MockExternalId[]
  groups: MockGroup[]
  groupMembers: MockGroupMember[]
  groupGrants: MockGroupGrant[]
  /** Oldest first (the viewer sorts newest first). */
  audit: MockAuditEntry[]
  /** Active sessions per user id (Admin → Users shows the count). */
  sessions: Record<string, number>
  /** Failed break-glass attempts (ms timestamps) for the mock throttle. */
  breakGlassFailures: number[]
  /** Phase 3: every user's inbox, newest last. */
  notifications: MockNotification[]
  /** Phase 3: email preferences that differ from the defaults, per user id. */
  notificationPrefs: Record<string, Partial<Record<NotificationType, NotificationMode>>>
  /** Phase 3: the transactional outbox (content isn't stored, as in the API). */
  outbox: MockOutboxEmail[]
  email: MockEmailSettings
  /** Events emitted by the request being handled: fanned out after its last write (http.ts). */
  pendingEvents: MockEvent[]
  /* Phase 4 (contract-phase4; records in proposals.ts, public.ts, branding.ts) */
  proposals: MockProposal[]
  proposalSections: MockProposalSection[]
  proposalThreads: MockProposalThread[]
  proposalComments: MockProposalComment[]
  /** Export times (ms) per user id, for the 10-a-minute limit. */
  proposalExports: Record<string, number[]>
  /** `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` (knob `soundings-mock-public` = `off`). */
  publicSubmissionEnabled: boolean
  publicForms: MockPublicForm[]
  publicSubmissions: MockPublicSubmission[]
  /** ALTCHA challenges already used (replay protection). */
  altchaUsed: Set<string>
  /** Public submission attempts (ms) from "this browser" (the mock's one client address). */
  publicAttempts: number[]
  brandingProfiles: MockBrandingProfile[]
  brandAssets: MockBrandAsset[]
  /* Phase 5 (contract-phase5; records in api-keys.ts, suggestions.ts) */
  apiKeys: MockApiKey[]
  proposalSuggestions: MockSuggestion[]
  /* Phase 6 (contract-phase6; records in ai.ts) */
  aiSettings: MockAiSettings
  aiAgents: MockAiAgent[]
  aiRuns: MockAiRun[]
  aiRunEvents: MockAiRunEvent[]
  /** Run requests (ms) per user id, for the 20-an-hour limit. */
  aiRequests: Record<string, number[]>
  /** Test connections (ms) per admin, for the 10-a-minute limit. */
  aiTests: Record<string, number[]>
  /** Open event streams per user id (5 at most). */
  aiStreams: Record<string, number>
  /* Phase 8 (contract-phase8; records in templates.ts, research.ts) */
  templateSections: MockTemplateSection[]
  researchItems: MockResearchItem[]
  researchAnswers: MockResearchAnswer[]
  /** Monotonic counter for new ids. */
  seq: number
}

export interface DbOptions {
  /** Reference time for all fixture timestamps (ms). Default: Date.now(). */
  now?: number
  /** `large` adds 10,000 ideas to Customer Innovation for performance checks. */
  dataset?: 'default' | 'large'
  /** Email settings: `off` = SMTP not configured, `failing` = the server is down. */
  email?: 'default' | 'off' | 'failing'
  /** Phase 4: `off` = the instance switch for public submission is off. */
  publicSubmission?: 'default' | 'off'
  /** Phase 6: `off` = `features.ai` is off (runs can't start). */
  ai?: 'default' | 'off'
  /**
   * Phase 8b: `private` makes every fixture project private, so a person without a
   * role (Ivan, Internal Tools' guest researcher) has no projects at all.
   */
  projects?: 'default' | 'private'
}

/* ------------------------------------------------------------------ */
/* Ids, time and randomness                                            */
/* ------------------------------------------------------------------ */

/** Deterministic UUIDs: the first hex digit names the kind (1 user, 2 project, 3 idea, …). */
export function mockId(kind: number | string, n: number): string {
  return `${kind}0000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`
}

export const ID_KIND = {
  user: 1,
  project: 2,
  idea: 3,
  criterion: 4,
  evaluation: 5,
  comment: 6,
  event: 7,
  tag: 8,
  group: 9,
  identity: 'a',
  audit: 'b',
  notification: 'c',
  outbox: 'd',
  /** Phase 4: proposals, sections' threads and comments, submissions, branding assets. */
  phase4: 'e',
  /** Phase 5: API keys, proposal suggestions, the agent and other Phase 5 people. */
  phase5: 'f',
  /** Phase 6 fixtures use `f` too, numbered from 0x300 (phase6-fixtures.ts). */
  /** Phase 8: template sections, checklist items. */
  phase8: '0',
} as const

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** Seeded PRNG (mulberry32) so fixtures never change between runs. */
function prng(seed: number) {
  let a = seed >>> 0
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  return {
    next,
    int: (min: number, max: number) => min + Math.floor(next() * (max - min + 1)),
    pick: <T>(items: readonly T[]): T => items[Math.floor(next() * items.length)] as T,
    chance: (p: number) => next() < p,
  }
}

/* ------------------------------------------------------------------ */
/* Fixture data                                                        */
/* ------------------------------------------------------------------ */

/** Handy names for the fixture users (tests and the user switcher use them). */
export const USERS = {
  priya: mockId(ID_KIND.user, 1),
  alice: mockId(ID_KIND.user, 2),
  bob: mockId(ID_KIND.user, 3),
  carol: mockId(ID_KIND.user, 4),
  dave: mockId(ID_KIND.user, 5),
  emma: mockId(ID_KIND.user, 6),
  farid: mockId(ID_KIND.user, 7),
  grace: mockId(ID_KIND.user, 8),
  hannah: mockId(ID_KIND.user, 9),
  ivan: mockId(ID_KIND.user, 10),
  jonas: mockId(ID_KIND.user, 11),
  /** Phase 2: in CUST and TOOL only through groups. */
  kofi: mockId(ID_KIND.user, 12),
  /** Phase 2: pre-created by an admin, never signed in; TOOL through a manual group membership. */
  lena: mockId(ID_KIND.user, 13),
  /** Phase 2: the break-glass admin (`break-glass@soundings.invalid`). */
  breakGlass: mockId(ID_KIND.user, 14),
} as const

export type FixtureUser = keyof typeof USERS

/** The reserved address of the break-glass account (contract-phase2 §3.8). */
export const BREAK_GLASS_EMAIL = 'break-glass@soundings.invalid'

const USER_ROWS: [FixtureUser, string, string, boolean, boolean][] = [
  // key, display name, email, platform admin, active
  ['priya', 'Priya Natarajan', 'priya.natarajan@example.com', true, true],
  ['alice', 'Alice Anders', 'alice.anders@example.com', false, true],
  ['bob', 'Bob Chen', 'bob.chen@example.com', false, true],
  ['carol', 'Carol Díaz', 'carol.diaz@example.com', false, true],
  ['dave', 'Dave Okafor', 'dave.okafor@example.com', false, true],
  ['emma', 'Emma Lindqvist', 'emma.lindqvist@example.com', false, true],
  ['farid', 'Farid Haddad', 'farid.haddad@example.com', false, true],
  ['grace', 'Grace Kim', 'grace.kim@example.com', false, true],
  ['hannah', 'Hannah Weber', 'hannah.weber@example.com', false, true],
  ['ivan', 'Ivan Petrov', 'ivan.petrov@example.com', false, true],
  ['jonas', 'Jonas Berg', 'jonas.berg@example.com', false, false],
  ['kofi', 'Kofi Boateng', 'kofi.boateng@example.com', false, true],
  ['lena', 'Lena Novak', 'lena.novak@example.com', false, true],
  ['breakGlass', 'Break-glass admin', BREAK_GLASS_EMAIL, true, true],
]

/** Days since the account was created, and hours since it was last seen (null: never). */
const USER_TIMES: Record<FixtureUser, [number, number | null]> = {
  priya: [420, 1],
  alice: [410, 0.2],
  bob: [405, 2],
  carol: [400, 26],
  dave: [395, 75],
  emma: [390, 120],
  farid: [380, 6],
  grace: [370, 50],
  hannah: [360, 290],
  ivan: [30, 22],
  jonas: [500, 4900],
  kofi: [21, 3],
  lena: [5, null],
  breakGlass: [430, 10_300],
}

export const PROJECTS = {
  cust: mockId(ID_KIND.project, 1),
  tool: mockId(ID_KIND.project, 2),
  green: mockId(ID_KIND.project, 3),
} as const

type ProjectKey = keyof typeof PROJECTS

const PROJECT_ROWS: {
  key: ProjectKey
  slug: string
  ideaKey: string
  name: string
  description: string
  visibility: ProjectVisibility
  allowVolunteers: boolean
  labels?: Partial<StatusLabels>
  members: [FixtureUser, ProjectRole][]
}[] = [
  {
    key: 'cust',
    slug: 'customer-innovation',
    ideaKey: 'CUST',
    name: 'Customer Innovation',
    description: 'Ideas that make buying, receiving and returning easier for our customers.',
    visibility: 'internal',
    allowVolunteers: true,
    members: [
      ['priya', 'admin'],
      ['alice', 'member'],
      ['bob', 'member'],
      ['carol', 'member'],
      ['dave', 'member'],
      ['emma', 'viewer'],
      ['farid', 'member'],
      ['hannah', 'member'],
    ],
  },
  {
    key: 'tool',
    slug: 'internal-tools',
    ideaKey: 'TOOL',
    name: 'Internal Tools',
    description: 'Developer experience and internal platforms.',
    visibility: 'private',
    allowVolunteers: true,
    members: [
      ['alice', 'admin'],
      ['bob', 'member'],
      ['dave', 'member'],
      ['farid', 'member'],
      ['grace', 'viewer'],
    ],
  },
  {
    key: 'green',
    slug: 'sustainability',
    ideaKey: 'GREEN',
    name: 'Sustainability',
    description: 'Lower our footprint in the office, the warehouse and the supply chain.',
    visibility: 'internal',
    allowVolunteers: false,
    labels: { new: 'Triage', accepted: 'Adopted' },
    members: [
      ['carol', 'admin'],
      ['alice', 'member'],
      ['emma', 'member'],
      ['grace', 'member'],
    ],
  },
]

const DEFAULT_RUBRIC: Omit<MockCriterion, 'id' | 'project_id' | 'position' | 'archived'>[] = [
  {
    name: 'Value',
    description: 'How much this would benefit customers or the organisation.',
    weight: 1,
    inverted: false,
    guidance: {
      '1': 'Little or no clear benefit.',
      '3': 'A useful benefit for some users or teams.',
      '5': 'A major benefit for many customers or the whole organisation.',
    },
  },
  {
    name: 'Feasibility',
    description: 'How confident we are that we could build and run it.',
    weight: 1,
    inverted: false,
    guidance: {
      '1': 'Unproven, with major unknowns or dependencies.',
      '3': 'Achievable, with some unknowns to resolve first.',
      '5': 'Straightforward with the skills and technology we have.',
    },
  },
  {
    name: 'Effort',
    description: 'How much time, money and people it would take (higher = more effort).',
    weight: 1,
    inverted: true,
    guidance: {
      '1': 'A few days for a small team.',
      '3': 'A few months for one team.',
      '5': 'A major programme across several teams.',
    },
  },
  {
    name: 'Strategic fit',
    description: 'How well it supports our strategy and current priorities.',
    weight: 1,
    inverted: false,
    guidance: {
      '1': 'Unrelated to our strategy.',
      '3': 'Supports a secondary goal.',
      '5': 'Directly advances a top priority.',
    },
  },
  {
    name: 'Risk',
    description: 'How much could go wrong: delivery, legal, security or reputation.',
    weight: 1,
    inverted: true,
    guidance: {
      '1': 'Low risk and easy to undo.',
      '3': 'Some risks, and we know how to manage them.',
      '5': 'Serious risks that are hard to mitigate.',
    },
  },
]

/** Rubric criteria for a new project (the backend's default_rubric_criteria). */
export function defaultRubric(projectId: string, nextId: () => string): MockCriterion[] {
  return DEFAULT_RUBRIC.map((criterion, position) => ({
    ...criterion,
    guidance: { ...criterion.guidance },
    id: nextId(),
    project_id: projectId,
    position,
    archived: false,
  }))
}

/**
 * How an idea's evaluation looks in the fixtures. `scores` are per evaluator in
 * rubric order (Value, Feasibility, Effort*, Strategic fit, Risk*); `null` = the
 * evaluator hasn't submitted (`draft: true` = has a saved draft).
 */
interface EvaluatorSpec {
  user: FixtureUser
  scores?: [number, number, number, number, number]
  rec?: Recommendation
  comment?: string
  draft?: boolean
  ageDays?: number
}

interface IdeaSpec {
  title: string
  summary: string
  description?: string
  status: IdeaStatus
  resolution?: Resolution
  owner?: FixtureUser
  by: FixtureUser
  tags?: string[]
  /** Days since creation. */
  age: number
  /** Hours since the idea's last event (default: most of its age, less for closed ideas). */
  activeHoursAgo?: number
  /** Due date in days from now (negative = overdue). */
  dueIn?: number | null
  evaluators?: EvaluatorSpec[]
  evaluationClosed?: boolean
  comments?: [FixtureUser, string, number][]
  votes?: FixtureUser[]
}

const RETURNS_DESCRIPTION = `Today customers have to print a returns label, which many can't do at home.

**Proposal:** show a QR code in the returns flow that the carrier scans at the drop-off point.

- Works with the carrier's existing label API
- No printer needed
- We can track drop-off in real time

Open questions: which carriers support QR drop-off in all regions?`

const IDEA_SPECS: Record<ProjectKey, IdeaSpec[]> = {
  cust: [
    {
      title: 'Self-serve returns portal',
      summary:
        'Let customers start a return, pick a refund method and track it without calling us.',
      description: RETURNS_DESCRIPTION,
      status: 'evaluating',
      owner: 'bob',
      by: 'hannah',
      tags: ['returns', 'self-service'],
      age: 12,
      dueIn: 1,
      evaluators: [
        { user: 'carol', scores: [4, 4, 3, 4, 2], rec: 'go', comment: 'Solid and cheap to run.' },
        {
          user: 'dave',
          scores: [5, 3, 4, 4, 3],
          rec: 'maybe',
          comment: 'Carrier API limits need checking.',
        },
        { user: 'alice' },
      ],
      comments: [
        ['carol', 'Have we checked the carrier API limits for peak season?', 30],
        ['bob', 'Good point — asking the carrier team this week.', 20],
      ],
      votes: ['carol', 'dave', 'hannah', 'farid'],
    },
    {
      title: 'Print-free returns with a QR code',
      summary: 'Customers show a QR code at the drop-off point instead of printing a label.',
      description: RETURNS_DESCRIPTION,
      status: 'evaluating',
      owner: 'alice',
      by: 'alice',
      tags: ['logistics', 'returns'],
      age: 9,
      dueIn: 4,
      evaluators: [
        {
          user: 'bob',
          scores: [4, 4, 2, 4, 2],
          rec: 'go',
          comment: 'Customers ask for this a lot.',
        },
        {
          user: 'carol',
          scores: [4, 2, 5, 3, 5],
          rec: 'maybe',
          comment: 'Carrier integration is the risk.',
        },
        { user: 'dave' },
      ],
      comments: [['dave', 'I can take a look at this on Thursday.', 26]],
      votes: ['bob', 'carol'],
    },
    {
      title: 'Subscription boxes for repeat buyers',
      summary: 'A monthly box of consumables for customers who reorder the same items.',
      status: 'proposal',
      owner: 'alice',
      by: 'farid',
      tags: ['growth', 'subscriptions'],
      age: 60,
      dueIn: -20,
      evaluationClosed: true,
      evaluators: [
        { user: 'bob', scores: [5, 4, 3, 5, 2], rec: 'go' },
        { user: 'carol', scores: [4, 4, 3, 5, 2], rec: 'go' },
        { user: 'dave', scores: [5, 5, 2, 4, 3], rec: 'go' },
        { user: 'farid', scores: [4, 4, 3, 4, 2], rec: 'go' },
        { user: 'hannah', scores: [5, 4, 3, 5, 2], rec: 'maybe' },
      ],
      votes: ['bob', 'carol', 'dave', 'farid', 'hannah', 'priya'],
    },
    {
      title: 'Partner API for marketplace sellers',
      summary: 'Open a documented API so marketplace sellers can sync stock and orders.',
      status: 'shortlisted',
      owner: 'alice',
      by: 'dave',
      tags: ['api', 'partners'],
      age: 35,
      dueIn: -10,
      evaluators: [
        { user: 'bob', scores: [5, 4, 2, 5, 2], rec: 'go' },
        { user: 'carol', scores: [4, 2, 5, 4, 4], rec: 'maybe', comment: 'Big build.' },
        { user: 'dave', scores: [5, 5, 3, 5, 2], rec: 'go' },
        { user: 'hannah', scores: [4, 4, 3, 4, 3], rec: 'go' },
      ],
      votes: ['dave', 'hannah', 'farid'],
    },
    {
      title: 'Loyalty tiers for B2B customers',
      summary: 'Volume-based tiers with better delivery terms for our largest business buyers.',
      status: 'new',
      owner: 'alice',
      by: 'alice',
      tags: ['b2b', 'loyalty'],
      age: 1,
      activeHoursAgo: 0.1,
    },
    {
      title: 'Live chat handover to specialists',
      summary: 'Route chats to a product specialist when the bot can’t answer.',
      status: 'new',
      by: 'hannah',
      tags: ['support'],
      age: 2,
    },
    {
      title: 'Gift cards with personal video messages',
      summary: 'Buyers record a short video that plays when the gift card is opened.',
      status: 'evaluating',
      owner: 'carol',
      by: 'carol',
      tags: ['gifting'],
      age: 16,
      dueIn: -2,
      evaluators: [
        { user: 'bob', scores: [3, 3, 3, 2, 3], rec: 'maybe' },
        { user: 'alice' },
        { user: 'farid', scores: [1, 4, 2, 2, 2], rec: 'no', comment: 'Nice, but niche.' },
      ],
      comments: [['carol', 'Moved this to evaluation — due end of the week.', 90]],
    },
    {
      title: 'Delivery time slots at checkout',
      summary: 'Let customers choose a two-hour delivery window when they order.',
      status: 'shortlisted',
      owner: 'dave',
      by: 'bob',
      tags: ['checkout', 'logistics'],
      age: 40,
      evaluators: [
        { user: 'alice', scores: [4, 3, 4, 4, 3], rec: 'go' },
        { user: 'carol', scores: [4, 3, 3, 4, 2], rec: 'go' },
        { user: 'hannah', scores: [5, 3, 4, 3, 3], rec: 'maybe' },
      ],
    },
    {
      title: 'Carbon-neutral shipping option',
      summary: 'Offset delivery emissions for customers who choose it at checkout.',
      status: 'closed',
      resolution: 'accepted',
      owner: 'alice',
      by: 'carol',
      tags: ['checkout', 'sustainability'],
      age: 120,
      evaluators: [
        { user: 'bob', scores: [4, 5, 2, 4, 1], rec: 'go' },
        { user: 'dave', scores: [4, 4, 2, 5, 2], rec: 'go' },
      ],
    },
    {
      title: 'Buy online, pick up in store',
      summary: 'Collect online orders from any store within two hours.',
      status: 'closed',
      resolution: 'accepted',
      owner: 'farid',
      by: 'farid',
      tags: ['stores'],
      age: 150,
    },
    {
      title: 'Social login for checkout',
      summary: 'Sign in with a social account to check out faster.',
      status: 'closed',
      resolution: 'rejected',
      owner: 'bob',
      by: 'emma',
      tags: ['checkout'],
      age: 100,
    },
    {
      title: 'AR preview for furniture',
      summary: 'Place furniture in your room with your phone’s camera before buying.',
      status: 'closed',
      resolution: 'parked',
      owner: 'alice',
      by: 'hannah',
      tags: ['mobile'],
      age: 90,
    },
    {
      title: 'Proactive delay notifications by SMS',
      summary: 'Text customers as soon as we know a parcel will be late, with a new estimate.',
      status: 'evaluating',
      owner: 'hannah',
      by: 'hannah',
      tags: ['logistics', 'support'],
      age: 8,
      dueIn: 6,
      evaluators: [
        { user: 'alice', scores: [4, 5, 2, 4, 1], rec: 'go', comment: 'Quick win.' },
        { user: 'bob', draft: true },
        { user: 'farid', scores: [4, 4, 2, 3, 2], rec: 'go' },
      ],
    },
    {
      title: 'Customer community forum',
      summary: 'A moderated space where customers help each other with products.',
      status: 'new',
      by: 'emma',
      tags: ['community', 'support'],
      age: 3,
    },
    {
      title: 'Price-drop alerts on wishlists',
      summary: 'Email customers when an item on their wishlist gets cheaper.',
      status: 'evaluating',
      owner: 'farid',
      by: 'farid',
      tags: ['growth'],
      age: 11,
      dueIn: 9,
      evaluators: [{ user: 'dave', scores: [3, 5, 1, 3, 1], rec: 'go' }, { user: 'hannah' }],
    },
    {
      title: 'Warranty registration by photo',
      summary: 'Register a warranty by photographing the receipt.',
      status: 'new',
      by: 'dave',
      tags: ['self-service'],
      age: 5,
    },
    {
      title: 'One-click reorder from order history',
      summary: 'Reorder a previous basket in one click from the order history page.',
      status: 'shortlisted',
      owner: 'bob',
      by: 'carol',
      tags: ['checkout', 'growth'],
      age: 30,
      evaluators: [
        { user: 'alice', scores: [4, 5, 1, 4, 1], rec: 'go' },
        { user: 'dave', scores: [4, 5, 2, 3, 1], rec: 'go' },
        { user: 'farid', scores: [3, 5, 1, 3, 1], rec: 'go' },
      ],
    },
    {
      title: 'Accessibility audit of the storefront',
      summary: 'Commission an external WCAG 2.2 AA audit and fix what it finds.',
      status: 'evaluating',
      owner: 'carol',
      by: 'emma',
      tags: ['accessibility'],
      age: 14,
      dueIn: 3,
    },
    {
      title: 'Voice search in the mobile app',
      summary: 'Search the catalogue by speaking to the app.',
      status: 'closed',
      resolution: 'parked',
      owner: 'dave',
      by: 'bob',
      tags: ['mobile'],
      age: 200,
    },
    {
      title: 'Referral credits for small businesses',
      summary: 'Give business customers store credit when they refer another business.',
      status: 'new',
      by: 'bob',
      tags: ['b2b', 'growth'],
      age: 0.2,
    },
  ],
  tool: [
    {
      title: 'Shared test data service',
      summary: 'One service that hands out realistic, anonymised test data to every team.',
      status: 'evaluating',
      owner: 'dave',
      by: 'dave',
      tags: ['testing', 'platform'],
      age: 10,
      dueIn: 3,
      evaluators: [
        { user: 'bob', scores: [4, 3, 3, 4, 2], rec: 'go' },
        { user: 'alice', draft: true },
        { user: 'farid', scores: [5, 3, 4, 4, 2], rec: 'go' },
      ],
    },
    {
      title: 'Flaky test dashboard',
      summary: 'Track flaky tests across repositories and flag the worst offenders weekly.',
      status: 'evaluating',
      owner: 'alice',
      by: 'bob',
      tags: ['ci', 'testing'],
      age: 20,
      dueIn: -1,
      evaluators: [
        { user: 'bob', scores: [4, 4, 2, 4, 1], rec: 'go' },
        { user: 'dave', scores: [4, 4, 3, 3, 2], rec: 'go' },
        { user: 'farid', scores: [3, 4, 2, 4, 1], rec: 'maybe' },
      ],
    },
    {
      title: 'One-command local environment',
      summary: 'Start every service and its dependencies locally with a single command.',
      status: 'shortlisted',
      owner: 'farid',
      by: 'farid',
      tags: ['developer-experience'],
      age: 45,
      evaluators: [
        { user: 'alice', scores: [5, 3, 4, 4, 2], rec: 'go' },
        { user: 'bob', scores: [5, 4, 3, 5, 2], rec: 'go' },
      ],
    },
    {
      title: 'Self-service feature flags',
      summary: 'Teams create and roll out feature flags without a ticket.',
      status: 'proposal',
      owner: 'bob',
      by: 'alice',
      tags: ['platform'],
      age: 70,
      evaluators: [
        { user: 'alice', scores: [4, 4, 2, 4, 2], rec: 'go' },
        { user: 'dave', scores: [5, 4, 3, 4, 2], rec: 'go' },
        { user: 'farid', scores: [4, 5, 2, 4, 1], rec: 'go' },
      ],
    },
    {
      title: 'Incident timeline bot for chat',
      summary: 'A bot that records who did what during an incident and drafts the timeline.',
      status: 'new',
      by: 'farid',
      tags: ['incidents'],
      age: 1.5,
    },
    {
      title: 'Automated dependency updates',
      summary: 'Open update pull requests automatically and merge the safe ones.',
      status: 'closed',
      resolution: 'accepted',
      owner: 'alice',
      by: 'dave',
      tags: ['ci'],
      age: 130,
    },
    {
      title: 'Service health dashboard',
      summary: 'Show each team the health of its services, updated live.',
      status: 'new',
      by: 'grace',
      tags: ['platform', 'incidents'],
      age: 4,
    },
    {
      title: 'Cost dashboard per team',
      summary: 'Show each team what its cloud resources cost, updated daily.',
      status: 'evaluating',
      owner: 'bob',
      by: 'bob',
      tags: ['cost'],
      age: 7,
      dueIn: null,
      evaluators: [{ user: 'alice', scores: [4, 4, 2, 4, 2], rec: 'go' }, { user: 'dave' }],
    },
    {
      title: 'Unified on-call schedule',
      summary: 'One on-call rota across teams instead of five spreadsheets.',
      status: 'closed',
      resolution: 'rejected',
      owner: 'dave',
      by: 'dave',
      tags: ['incidents'],
      age: 110,
    },
    {
      title: 'Code owners linting',
      summary: 'Fail CI when a changed path has no code owner.',
      status: 'new',
      by: 'bob',
      tags: ['ci'],
      age: 6,
    },
    {
      title: 'Release notes generator',
      summary: 'Draft release notes from merged pull requests and their labels.',
      status: 'shortlisted',
      owner: 'alice',
      by: 'farid',
      tags: ['developer-experience'],
      age: 25,
      evaluators: [
        { user: 'bob', scores: [3, 5, 1, 3, 1], rec: 'go' },
        { user: 'dave', scores: [3, 5, 2, 2, 1], rec: 'maybe' },
      ],
    },
    {
      title: 'Replace the wiki search',
      summary: 'Nobody can find anything in the wiki; try a better search engine.',
      status: 'closed',
      resolution: 'parked',
      owner: 'farid',
      by: 'grace',
      tags: ['knowledge'],
      age: 160,
    },
  ],
  green: [
    {
      title: 'Reusable packaging pilot',
      summary: 'Ship orders in returnable boxes in one region and measure the return rate.',
      status: 'evaluating',
      owner: 'carol',
      by: 'emma',
      tags: ['packaging'],
      age: 13,
      dueIn: 5,
      evaluators: [
        { user: 'emma', scores: [5, 3, 4, 5, 3], rec: 'go' },
        { user: 'grace', scores: [4, 2, 4, 4, 4], rec: 'maybe' },
      ],
    },
    {
      title: 'Bike-to-work scheme',
      summary: 'Help staff buy bikes through salary sacrifice.',
      status: 'closed',
      resolution: 'accepted',
      owner: 'grace',
      by: 'grace',
      tags: ['commuting'],
      age: 180,
    },
    {
      title: 'Solar panels on the warehouse roof',
      summary: 'Generate a third of the warehouse’s electricity on site.',
      status: 'shortlisted',
      owner: 'carol',
      by: 'carol',
      tags: ['energy'],
      age: 50,
      evaluators: [
        { user: 'alice', scores: [4, 4, 4, 5, 2], rec: 'go' },
        { user: 'emma', scores: [5, 3, 5, 5, 3], rec: 'go' },
        { user: 'grace', scores: [4, 4, 4, 4, 2], rec: 'go' },
      ],
    },
    {
      title: 'Paperless invoicing',
      summary: 'Send and receive every invoice electronically.',
      status: 'proposal',
      owner: 'emma',
      by: 'emma',
      tags: ['paper'],
      age: 80,
    },
    {
      title: 'Office energy dashboard',
      summary: 'Show live energy use per floor on screens by the lifts.',
      status: 'new',
      by: 'grace',
      tags: ['energy'],
      age: 2.5,
    },
    {
      title: 'Repair café for staff',
      summary: 'A monthly session where volunteers fix colleagues’ broken gadgets.',
      status: 'new',
      by: 'emma',
      tags: ['community'],
      age: 8,
    },
    {
      title: 'Green supplier scorecard',
      summary: 'Rate suppliers on emissions and prefer the better ones in tenders.',
      status: 'evaluating',
      owner: 'emma',
      by: 'carol',
      tags: ['procurement'],
      age: 15,
      dueIn: null,
      evaluators: [{ user: 'alice' }, { user: 'grace', scores: [4, 3, 3, 4, 2], rec: 'go' }],
    },
    {
      title: 'Meat-free Mondays in the canteen',
      summary: 'Serve only vegetarian dishes on Mondays.',
      status: 'closed',
      resolution: 'rejected',
      owner: 'carol',
      by: 'emma',
      tags: ['food'],
      age: 140,
    },
  ],
}

const LARGE_WORDS = {
  verbs: ['Automate', 'Simplify', 'Rethink', 'Speed up', 'Personalise', 'Measure', 'Streamline'],
  things: [
    'returns',
    'onboarding',
    'invoicing',
    'delivery tracking',
    'checkout',
    'product search',
    'order history',
    'support tickets',
    'wishlists',
    'gift wrapping',
    'store pickup',
    'loyalty points',
  ],
  for: ['for B2B buyers', 'on mobile', 'in stores', 'for new customers', 'at peak season', ''],
  tags: ['growth', 'checkout', 'logistics', 'support', 'mobile', 'returns', 'b2b', 'stores'],
}

/* ------------------------------------------------------------------ */
/* Builder                                                             */
/* ------------------------------------------------------------------ */

export function createDb({
  now = Date.now(),
  dataset = 'default',
  email = 'default',
  publicSubmission = 'default',
  ai = 'default',
  projects = 'default',
}: DbOptions = {}): MockDb {
  const rand = prng(20260930)
  const iso = (ms: number) => new Date(ms).toISOString()
  // 17:00 local, `days` calendar days from today: a date due in 1 day reads "Due
  // tomorrow" at any time of day (now + 27 h was two days away after 21:00).
  const daysAhead = (days: number) => {
    const date = new Date(now)
    date.setDate(date.getDate() + days)
    return date.setHours(17, 0, 0, 0)
  }
  const counters: Record<string, number> = {}
  const nextId = (kind: number | string) => {
    counters[kind] = (counters[kind] ?? 0) + 1
    return mockId(kind, counters[kind])
  }

  const db: MockDb = {
    now,
    users: [],
    projects: [],
    members: [],
    criteria: [],
    tags: [],
    ideas: [],
    assignments: [],
    evaluations: [],
    comments: [],
    events: [],
    votes: new Set(),
    watchers: new Set(),
    identities: [],
    externalIds: [],
    groups: [],
    groupMembers: [],
    groupGrants: [],
    audit: [],
    sessions: {},
    breakGlassFailures: [],
    notifications: [],
    notificationPrefs: {},
    outbox: [],
    email: { configured: email !== 'off', failing: email === 'failing' },
    pendingEvents: [],
    proposals: [],
    proposalSections: [],
    proposalThreads: [],
    proposalComments: [],
    proposalExports: {},
    publicSubmissionEnabled: publicSubmission !== 'off',
    publicForms: [],
    publicSubmissions: [],
    altchaUsed: new Set(),
    publicAttempts: [],
    brandingProfiles: [],
    brandAssets: [],
    apiKeys: [],
    proposalSuggestions: [],
    aiSettings: {
      enabled: ai !== 'off',
      kagent_url: 'http://kagent-controller.kagent:8083',
      kagent_token_set: false,
      default_protocol: 'kagent_v0_10',
      run_timeout_seconds: 300,
      max_concurrent_runs: 4,
      agent_namespaces: ['soundings', 'kagent-agents'],
      mcp_url: 'http://soundings.soundings.svc.cluster.local:8000/mcp',
    },
    aiAgents: [],
    aiRuns: [],
    aiRunEvents: [],
    aiRequests: {},
    aiTests: {},
    aiStreams: {},
    templateSections: [],
    researchItems: [],
    researchAnswers: [],
    seq: 1_000_000,
  }

  for (const [key, name, email, admin, active] of USER_ROWS) {
    const [createdDays, seenHours] = USER_TIMES[key]
    db.users.push({
      id: USERS[key],
      display_name: name,
      email,
      avatar_url: null,
      is_platform_admin: admin,
      is_active: active,
      is_service_account: false,
      is_break_glass: key === 'breakGlass',
      created_at: iso(now - createdDays * DAY),
      last_seen_at: seenHours === null ? null : iso(now - seenHours * HOUR),
    })
  }

  for (const [index, row] of PROJECT_ROWS.entries()) {
    const projectId = PROJECTS[row.key]
    db.projects.push({
      id: projectId,
      slug: row.slug,
      key: row.ideaKey,
      name: row.name,
      description: row.description,
      visibility: row.visibility,
      allow_volunteer_owners: row.allowVolunteers,
      default_evaluation_days: 7,
      archived_at: null,
      created_at: iso(now - (400 - index * 30) * DAY),
      status_labels: row.labels ?? {},
      next_idea_number: 1,
      research_step: 'off',
    })
    db.templateSections.push(...defaultTemplate(projectId, () => nextId(ID_KIND.phase8)))
    for (const [user, role] of row.members) {
      db.members.push({
        project_id: projectId,
        user_id: USERS[user],
        role,
        joined_at: iso(now - (380 - index * 30) * DAY),
      })
    }
    db.criteria.push(...defaultRubric(projectId, () => nextId(ID_KIND.criterion)))
  }

  const tagId = (projectId: string, name: string) => {
    const existing = db.tags.find(
      (tag) => tag.project_id === projectId && tag.name.toLowerCase() === name.toLowerCase(),
    )
    if (existing) return existing.id
    const tag = { id: nextId(ID_KIND.tag), project_id: projectId, name }
    db.tags.push(tag)
    return tag.id
  }

  const event = (
    ideaId: string,
    type: MockEventType,
    actor: string | null,
    at: number,
    payload: Record<string, unknown> = {},
    commentId: string | null = null,
  ) => {
    db.events.push({
      id: nextId(ID_KIND.event),
      idea_id: ideaId,
      actor_id: actor,
      type,
      payload,
      comment_id: commentId,
      created_at: iso(at),
    })
  }

  const addIdea = (projectKey: ProjectKey, spec: IdeaSpec, detailedEvents: boolean) => {
    const project = db.projects.find((p) => p.id === PROJECTS[projectKey])
    if (!project) throw new Error('fixture project missing')
    const criteria = db.criteria.filter((c) => c.project_id === project.id)
    const id = nextId(ID_KIND.idea)
    const createdAt = now - spec.age * DAY
    const by = USERS[spec.by]
    const owner = spec.owner ? USERS[spec.owner] : null
    const number = project.next_idea_number++
    const idea: MockIdea = {
      id,
      project_id: project.id,
      number,
      title: spec.title,
      summary: spec.summary,
      description_md: spec.description ?? '',
      status: spec.status,
      resolution: spec.status === 'closed' ? (spec.resolution ?? 'parked') : null,
      owner_id: owner,
      submitted_by: by,
      created_at: iso(createdAt),
      last_activity_at: iso(createdAt),
      evaluation_due_at: null,
      evaluation_closed_at: null,
      tag_ids: (spec.tags ?? []).map((name) => tagId(project.id, name)),
    }
    db.ideas.push(idea)
    // This idea's events are appended from here on (keeps the 10k build linear).
    const firstEvent = db.events.length
    db.watchers.add(`${id}:${by}`)
    let t = createdAt
    // Spread the idea's events evenly between creation and its last activity,
    // so timestamps are always in the past and last_activity_at matches them.
    const evaluatorCount = spec.evaluators?.length ?? 0
    const steps =
      (owner ? 1 : 0) +
      (spec.status !== 'new' ? 1 : 0) +
      (evaluatorCount > 0 ? 1 + evaluatorCount : 0) +
      (spec.evaluationClosed || spec.status === 'closed' ? 1 : 0) +
      (spec.status !== 'new' && spec.status !== 'evaluating' ? 1 : 0)
    const end =
      spec.activeHoursAgo !== undefined
        ? now - spec.activeHoursAgo * HOUR
        : createdAt + (now - createdAt) * (spec.status === 'closed' ? 0.6 : 0.9)
    const increment = steps > 0 ? Math.max(end - createdAt, 0) / steps : 0
    const step = () => (t += increment)
    if (detailedEvents) event(id, 'idea_created', by, createdAt)
    if (owner) {
      step()
      if (detailedEvents) {
        event(id, 'owner_changed', owner, t, {
          from_owner_id: null,
          to_owner_id: owner,
          // The submitter owning their own idea took it on themselves too.
          volunteered: true,
        })
      }
      db.watchers.add(`${id}:${owner}`)
    }
    if (spec.status !== 'new') {
      step()
      if (detailedEvents) {
        event(id, 'status_changed', owner ?? by, t, {
          from_status: 'new',
          from_resolution: null,
          to_status: 'evaluating',
          to_resolution: null,
        })
      }
    }
    const evaluators = spec.evaluators ?? []
    if (evaluators.length > 0) {
      step()
      const invitedAt = t
      idea.evaluation_due_at =
        spec.dueIn === undefined
          ? iso(invitedAt + 7 * DAY)
          : spec.dueIn === null
            ? null
            : iso(spec.dueIn < 0 ? now + spec.dueIn * DAY : daysAhead(spec.dueIn))
      for (const evaluator of evaluators) {
        const userId = USERS[evaluator.user]
        db.assignments.push({ idea_id: id, user_id: userId, invited_at: iso(invitedAt) })
        db.watchers.add(`${id}:${userId}`)
        if (detailedEvents) {
          event(id, 'evaluator_added', owner ?? by, invitedAt, { evaluator_id: userId })
        }
      }
      for (const evaluator of evaluators) {
        const userId = USERS[evaluator.user]
        if (evaluator.scores) {
          step()
          db.evaluations.push({
            id: nextId(ID_KIND.evaluation),
            idea_id: id,
            evaluator_id: userId,
            status: 'submitted',
            scores: criteria.map((criterion, i) => ({
              criterion_id: criterion.id,
              score: evaluator.scores?.[i] ?? 3,
              comment: '',
            })),
            recommendation: evaluator.rec ?? 'maybe',
            comment: evaluator.comment ?? '',
            submitted_at: iso(t),
            edited_at: null,
            updated_at: iso(t),
            include_in_aggregate: true,
          })
          if (detailedEvents) event(id, 'evaluation_submitted', userId, t, { evaluator_id: userId })
        } else if (evaluator.draft) {
          db.evaluations.push({
            id: nextId(ID_KIND.evaluation),
            idea_id: id,
            evaluator_id: userId,
            status: 'draft',
            scores: criteria.slice(0, 2).map((criterion) => ({
              criterion_id: criterion.id,
              score: 4,
              comment: '',
            })),
            recommendation: null,
            comment: '',
            submitted_at: null,
            edited_at: null,
            updated_at: iso(t),
            include_in_aggregate: true,
          })
        }
      }
    }
    if (spec.evaluationClosed || spec.status === 'closed') {
      step()
      if (spec.evaluationClosed) {
        idea.evaluation_closed_at = iso(t)
        if (detailedEvents) event(id, 'evaluation_closed', owner ?? by, t)
      }
    }
    if (spec.status !== 'new' && spec.status !== 'evaluating') {
      step()
      if (detailedEvents) {
        event(id, 'status_changed', owner ?? by, t, {
          from_status: 'evaluating',
          from_resolution: null,
          to_status: spec.status,
          to_resolution: idea.resolution,
        })
      }
    }
    for (const [author, body, minutesAgo] of spec.comments ?? []) {
      const at = Math.max(now - minutesAgo * 60_000, t)
      const commentId = nextId(ID_KIND.comment)
      db.comments.push({
        id: commentId,
        idea_id: id,
        author_id: USERS[author],
        body_md: body,
        created_at: iso(at),
        edited_at: null,
        deleted_at: null,
      })
      db.watchers.add(`${id}:${USERS[author]}`)
      event(id, 'comment', USERS[author], at, {}, commentId)
    }
    for (const voter of spec.votes ?? []) db.votes.add(`${id}:${USERS[voter]}`)
    const last = db.events
      .slice(firstEvent)
      .reduce((max, e) => Math.max(max, Date.parse(e.created_at)), Math.max(createdAt, t))
    idea.last_activity_at = iso(last)
  }

  for (const projectKey of Object.keys(IDEA_SPECS) as ProjectKey[]) {
    for (const spec of IDEA_SPECS[projectKey]) addIdea(projectKey, spec, true)
  }

  if (dataset === 'large') {
    const members = PROJECT_ROWS[0]?.members.filter(([, role]) => role !== 'viewer') ?? []
    const statuses: IdeaStatus[] = ['new', 'evaluating', 'shortlisted', 'proposal', 'closed']
    for (let i = 0; i < 10_000; i++) {
      const status = rand.pick(statuses)
      const evaluatorCount = status === 'new' ? 0 : rand.int(0, 4)
      const people = [...members].sort(() => rand.next() - 0.5)
      const scored = status !== 'evaluating' || rand.chance(0.6)
      const spec: IdeaSpec = {
        title:
          `${rand.pick(LARGE_WORDS.verbs)} ${rand.pick(LARGE_WORDS.things)} ${rand.pick(LARGE_WORDS.for)}`.trim(),
        summary: 'Generated for performance checks (mock dataset "large").',
        status,
        resolution: status === 'closed' ? rand.pick(['accepted', 'rejected', 'parked']) : undefined,
        owner: status === 'new' && rand.chance(0.5) ? undefined : people[0]?.[0],
        by: people[1]?.[0] ?? 'bob',
        tags: [rand.pick(LARGE_WORDS.tags)],
        age: rand.int(1, 700) + rand.next(),
        dueIn: status === 'evaluating' ? rand.int(-5, 10) : undefined,
        evaluators: people.slice(0, evaluatorCount).map(([user]) => ({
          user,
          scores: scored
            ? [rand.int(1, 5), rand.int(1, 5), rand.int(1, 5), rand.int(1, 5), rand.int(1, 5)]
            : undefined,
          rec: rand.pick(['go', 'maybe', 'no'] as const),
        })),
      }
      addIdea('cust', spec, false)
    }
  }

  // Events are stored newest-last per insertion; keep them sorted by time.
  db.events.sort((a, b) => a.created_at.localeCompare(b.created_at))
  seedAccess(db, { users: USERS, projects: PROJECTS, nextId })
  seedNotifications(db, { users: USERS, nextId })
  seedPhase4(db, { users: USERS, projects: PROJECTS, nextId })
  seedPhase5(db, { users: USERS, projects: PROJECTS, nextId })
  seedPhase6(db, { users: USERS, projects: PROJECTS, nextId })
  seedPhase8(db, { users: USERS, projects: PROJECTS, nextId })
  seedPhase8b(db, { users: USERS, projects: PROJECTS, nextId })
  if (projects === 'private') for (const project of db.projects) project.visibility = 'private'
  return db
}

/* ------------------------------------------------------------------ */
/* Singleton                                                           */
/* ------------------------------------------------------------------ */

let current: MockDb | null = null

export function getDb(): MockDb {
  current ??= createDb({
    dataset: readDatasetPreference(),
    email: readEmailPreference(),
    publicSubmission: readPublicPreference(),
    ai: readAiPreference(),
    projects: readProjectsPreference(),
  })
  return current
}

export function resetDb(options?: DbOptions): MockDb {
  current = createDb(options)
  return current
}

export const MOCK_DATASET_STORAGE_KEY = 'soundings-mock-dataset'

function readDatasetPreference(): 'default' | 'large' {
  try {
    return typeof localStorage !== 'undefined' &&
      localStorage.getItem(MOCK_DATASET_STORAGE_KEY) === 'large'
      ? 'large'
      : 'default'
  } catch {
    return 'default'
  }
}

/** `localStorage['soundings-mock-email']`: `off` (SMTP not configured) or `failing` (SMTP down). */
export const MOCK_EMAIL_STORAGE_KEY = 'soundings-mock-email'

function readEmailPreference(): 'default' | 'off' | 'failing' {
  try {
    const value =
      typeof localStorage === 'undefined' ? null : localStorage.getItem(MOCK_EMAIL_STORAGE_KEY)
    return value === 'off' || value === 'failing' ? value : 'default'
  } catch {
    return 'default'
  }
}

/** `localStorage['soundings-mock-public']`: `off` turns public submission off for the instance. */
export const MOCK_PUBLIC_STORAGE_KEY = 'soundings-mock-public'

function readPublicPreference(): 'default' | 'off' {
  try {
    return typeof localStorage !== 'undefined' &&
      localStorage.getItem(MOCK_PUBLIC_STORAGE_KEY) === 'off'
      ? 'off'
      : 'default'
  } catch {
    return 'default'
  }
}

/** `localStorage['soundings-mock-ai']`: `off` turns AI assistance off for the instance. */
export const MOCK_AI_STORAGE_KEY = 'soundings-mock-ai'

function readAiPreference(): 'default' | 'off' {
  try {
    return typeof localStorage !== 'undefined' &&
      localStorage.getItem(MOCK_AI_STORAGE_KEY) === 'off'
      ? 'off'
      : 'default'
  } catch {
    return 'default'
  }
}

/**
 * `localStorage['soundings-mock-projects']`: `private` makes every project private,
 * so Ivan (Internal Tools' guest researcher, no roles) has no projects at all.
 */
export const MOCK_PROJECTS_STORAGE_KEY = 'soundings-mock-projects'

function readProjectsPreference(): 'default' | 'private' {
  try {
    return typeof localStorage !== 'undefined' &&
      localStorage.getItem(MOCK_PROJECTS_STORAGE_KEY) === 'private'
      ? 'private'
      : 'default'
  } catch {
    return 'default'
  }
}

/** A fresh id of the given kind for rows created by handlers. */
export function newId(db: MockDb, kind: number | string): string {
  db.seq += 1
  return mockId(kind, db.seq)
}
