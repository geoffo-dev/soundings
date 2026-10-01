/**
 * Phase 4 fixtures (contract-phase4): proposals, public submissions and
 * branding. Deterministic, relative to `db.now`. Useful places:
 *
 * - **CUST-3** "Subscription boxes" (Proposal, owner Alice): a proposal with
 *   five of eight sections written and margin threads (open, resolved, one
 *   with a deleted comment). **TOOL-4** (Proposal, owner Bob; Alice is a TOOL
 *   admin): a proposal with only its Summary. **CUST-4** and **CUST-8**
 *   (Shortlisted) and **GREEN-4** (Proposal) have none yet.
 * - Public form **on** for Customer Innovation (moderated) and Sustainability
 *   (moderated, email confirmation required); Sustainability has a project
 *   branding override (green primary colour).
 * - **GREEN-9** came in through the form and is visible (submitter "Jo Marsh",
 *   confirmed, wants updates; tracking token `TRACKING_TOKENS.jo`); **GREEN-10**
 *   and **GREEN-11** wait for moderation (Carol and Priya see them in the queue);
 *   **GREEN-12** waits for its submitter's email confirmation (nobody sees it;
 *   confirmation token `confirmationToken(SUBMISSIONS.unconfirmed)`).
 */
import type { ProposalSectionKey } from '@/api/types'

import type { MockDb, MockIdea, PROJECTS as ProjectsMap, USERS as UsersMap } from './db'
import { fixtureToken } from './public'
import { PROPOSAL_TEMPLATE } from './proposals'

type Users = typeof UsersMap
type UserKey = keyof Users

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** Tracking tokens of the fixture submissions (the `/track#<token>` links). */
export const TRACKING_TOKENS = {
  /** GREEN-9, visible, confirmed address, wants updates. */
  jo: fixtureToken('JoMarshGreen9'),
  /** GREEN-10, waiting for moderation, no address. */
  moderated: fixtureToken('WaitingForReviewGreen10'),
  /** GREEN-11, waiting for moderation, unconfirmed address. */
  unconfirmedModerated: fixtureToken('UnconfirmedGreen11'),
  /** GREEN-12, waiting for its submitter to confirm their address. */
  unconfirmed: fixtureToken('ConfirmFirstGreen12'),
} as const

/** Submission ids (for `confirmationToken(id)` and the tests). */
export const SUBMISSIONS = {
  jo: 'e0000000-0000-4000-8000-0000000f0001',
  moderated: 'e0000000-0000-4000-8000-0000000f0002',
  unconfirmedModerated: 'e0000000-0000-4000-8000-0000000f0003',
  unconfirmed: 'e0000000-0000-4000-8000-0000000f0004',
} as const

const CUST3_SECTIONS: Partial<Record<ProposalSectionKey, [string, UserKey, number]>> = {
  summary: [
    `A monthly curated box for existing customers, starting with **coffee and tea**. Subscribers get three products picked for them, free delivery and 10% off anything else they buy.

We expect it to lift repeat purchases and give us a predictable revenue line.`,
    'alice',
    3 * DAY,
  ],
  problem: [
    `Repeat purchase rate dropped **8%** year on year (Q2 retention report), and most repeat buyers order the same few products every month.

- They re-order by hand, which is easy to forget
- Competitors already offer subscriptions in coffee and tea
- We have no recurring revenue at all today`,
    'alice',
    2 * DAY,
  ],
  solution: [
    `### What we would build

1. A subscription product with a monthly or two-monthly box
2. A "pause or skip" page in the account area
3. A curation rota with two category buyers

We would reuse the existing checkout and payment provider; billing runs as a scheduled order.`,
    'alice',
    26 * HOUR,
  ],
  market: [
    `About **42,000** customers bought coffee or tea at least three times last year. If 5% subscribe, that is 2,100 boxes a month.

| Segment | Customers | Expected uptake |
|---|---|---|
| Coffee | 28,000 | 5% |
| Tea | 14,000 | 4% |`,
    'alice',
    20 * HOUR,
  ],
  cost: [
    `- Engineering: two developers for six weeks
- Curation: 0.5 FTE across two buyers
- Packaging: £1.20 per box at 2,000 boxes a month`,
    'priya',
    5 * HOUR,
  ],
}

interface ThreadSpec {
  idea: string
  section: ProposalSectionKey
  comments: [UserKey, string, number, boolean?][]
  resolvedBy?: [UserKey, number]
}

const THREADS: ThreadSpec[] = [
  {
    idea: 'CUST-3',
    section: 'summary',
    comments: [
      ['carol', 'Can we quantify the churn impact? A number here would help the ask.', 2 * DAY],
      [
        'alice',
        'Good point. I’ll add the retention model numbers once finance sends them.',
        40 * HOUR,
      ],
    ],
  },
  {
    idea: 'CUST-3',
    section: 'problem',
    comments: [['bob', 'Source for the 8%? Is it all categories or coffee only?', 70 * MINUTE]],
  },
  {
    idea: 'CUST-3',
    section: 'solution',
    comments: [
      ['priya', 'Do we need a separate warehouse slot for the boxes?', 30 * HOUR],
      ['dave', 'Removed: wrong thread.', 29 * HOUR, true],
      ['alice', 'No: they ship from the main line as scheduled orders.', 28 * HOUR],
    ],
    resolvedBy: ['alice', 27 * HOUR],
  },
  {
    idea: 'CUST-3',
    section: 'market',
    comments: [
      ['hannah', 'Tea uptake looks optimistic compared with last year’s sampler.', 6 * HOUR],
    ],
  },
]

export function seedPhase4(
  db: MockDb,
  ctx: { users: Users; projects: typeof ProjectsMap; nextId: (kind: number | string) => string },
): void {
  const { users, projects } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  const id = () => ctx.nextId('e')
  const project = (key: string) => db.projects.find((p) => p.key === key)
  const idea = (key: string): MockIdea => {
    const [projectKey = '', number = ''] = key.split('-')
    const found = db.ideas.find(
      (i) => i.project_id === project(projectKey)?.id && i.number === Number(number),
    )
    if (!found) throw new Error(`fixture idea ${key} missing`)
    return found
  }

  /* Proposals ---------------------------------------------------------- */
  const addProposal = (
    key: string,
    by: UserKey,
    ageMs: number,
    written: Partial<Record<ProposalSectionKey, [string, UserKey, number]>>,
  ) => {
    const target = idea(key)
    const proposalId = id()
    const createdAt = now - ageMs
    let updatedAt = createdAt
    for (const template of PROPOSAL_TEMPLATE) {
      const text = written[template.key]
      const at = text ? now - text[2] : createdAt
      updatedAt = Math.max(updatedAt, at)
      db.proposalSections.push({
        proposal_id: proposalId,
        key: template.key,
        body_md: text?.[0] ?? '',
        version: text ? 3 : 1,
        updated_at: iso(at),
        updated_by_id: text ? users[text[1]] : null,
      })
    }
    db.proposals.push({
      id: proposalId,
      idea_id: target.id,
      created_at: iso(createdAt),
      created_by_id: users[by],
      updated_at: iso(updatedAt),
    })
    return proposalId
  }

  const cust3 = addProposal('CUST-3', 'alice', 4 * DAY, CUST3_SECTIONS)
  addProposal('TOOL-4', 'bob', 2 * DAY, {
    summary: [
      'Let teams turn features on and off per environment without a deploy, with an audit trail.',
      'bob',
      2 * DAY,
    ],
  })

  for (const spec of THREADS) {
    const proposalId = spec.idea === 'CUST-3' ? cust3 : ''
    const threadId = id()
    const first = spec.comments[0]
    db.proposalThreads.push({
      id: threadId,
      proposal_id: proposalId,
      section_key: spec.section,
      created_at: iso(now - (first?.[2] ?? 0)),
      resolved_at: spec.resolvedBy ? iso(now - spec.resolvedBy[1]) : null,
      resolved_by_id: spec.resolvedBy ? users[spec.resolvedBy[0]] : null,
    })
    for (const [author, body, ago, deleted] of spec.comments) {
      db.proposalComments.push({
        id: id(),
        thread_id: threadId,
        author_id: users[author],
        body_md: deleted ? '' : body,
        created_at: iso(now - ago),
        deleted_at: deleted ? iso(now - ago + MINUTE) : null,
      })
    }
  }

  /* Public forms ------------------------------------------------------- */
  db.publicForms.push(
    {
      project_id: projects.cust,
      enabled: true,
      require_email_verification: false,
      moderation_required: true,
      intro_md:
        'Got an idea that would make buying, receiving or returning easier? Tell us. A real person on the Customer Innovation team reads every one.',
    },
    {
      project_id: projects.green,
      enabled: true,
      require_email_verification: true,
      moderation_required: true,
      intro_md:
        'Help us lower our footprint. Share an idea for the office, the warehouse or the supply chain.',
    },
  )

  db.brandingProfiles.push({
    project_id: projects.green,
    app_name: null,
    primary_color: '#2e7d4f',
    accent_color: null,
    font: null,
    email_footer: null,
    logo_asset_id: null,
    favicon_asset_id: null,
    updated_at: iso(now - 10 * DAY),
    updated_by_id: users.carol,
  })

  /* Public ideas (Sustainability) --------------------------------------- */
  const green = project('GREEN')
  if (!green) return
  const addPublicIdea = (spec: {
    submission: string
    token: string
    title: string
    summary: string
    description?: string
    heldFor: MockIdea['held_for']
    ageHours: number
    name: string | null
    email: string | null
    verified: boolean
    wantsUpdates: boolean
  }) => {
    const createdAt = now - spec.ageHours * HOUR
    const ideaId = id()
    db.ideas.push({
      id: ideaId,
      project_id: green.id,
      number: green.next_idea_number++,
      title: spec.title,
      summary: spec.summary,
      description_md: spec.description ?? '',
      status: 'new',
      resolution: null,
      owner_id: null,
      submitted_by: null,
      created_at: iso(createdAt),
      last_activity_at: iso(createdAt),
      evaluation_due_at: null,
      evaluation_closed_at: null,
      tag_ids: [],
      held_for: spec.heldFor,
    })
    db.events.push({
      id: id(),
      idea_id: ideaId,
      actor_id: null,
      type: 'idea_created',
      payload: {},
      comment_id: null,
      created_at: iso(createdAt),
    })
    db.publicSubmissions.push({
      id: spec.submission,
      idea_id: ideaId,
      name: spec.name,
      email: spec.email,
      email_verified_at: spec.verified ? iso(createdAt + 10 * MINUTE) : null,
      wants_updates: spec.wantsUpdates,
      tracking_token: spec.token,
      submitted_title: spec.title,
      submitted_summary: spec.summary,
      created_at: iso(createdAt),
      erased_at: null,
      erased_by_id: null,
      confirmation_sends: spec.email ? [iso(createdAt)] : [],
    })
  }

  addPublicIdea({
    submission: SUBMISSIONS.jo,
    token: TRACKING_TOKENS.jo,
    title: 'Refill station for cleaning products',
    summary: 'Replace single-use spray bottles in the office with a refill station.',
    description:
      'We throw away about 40 spray bottles a month. A refill station from our supplier costs less than a year of bottles.',
    heldFor: null,
    ageHours: 5 * 24,
    name: 'Jo Marsh',
    email: 'jo.marsh@example.org',
    verified: true,
    wantsUpdates: true,
  })
  addPublicIdea({
    submission: SUBMISSIONS.moderated,
    token: TRACKING_TOKENS.moderated,
    title: 'Plant a wildflower strip by the car park',
    summary: 'Turn the grass verge by the car park into a wildflower strip for pollinators.',
    heldFor: 'moderation',
    ageHours: 30,
    name: null,
    email: null,
    verified: false,
    wantsUpdates: false,
  })
  addPublicIdea({
    submission: SUBMISSIONS.unconfirmedModerated,
    token: TRACKING_TOKENS.unconfirmedModerated,
    title: 'Cheap watches!!! Visit my shop',
    summary: 'Best prices on watches, click the link in my profile.',
    heldFor: 'moderation',
    ageHours: 3,
    name: 'Deals',
    email: 'deals@example.net',
    verified: false,
    wantsUpdates: false,
  })
  addPublicIdea({
    submission: SUBMISSIONS.unconfirmed,
    token: TRACKING_TOKENS.unconfirmed,
    title: 'Switch the canteen to oat milk by default',
    summary: 'Offer oat milk as the default and dairy on request.',
    heldFor: 'email_verification',
    ageHours: 2,
    name: 'Sam',
    email: 'sam@example.org',
    verified: false,
    wantsUpdates: true,
  })
}
