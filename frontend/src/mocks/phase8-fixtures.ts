/**
 * Phase 8 fixtures (contract-phase8 §3.14, adapted to the mock's data):
 *
 * - **Internal Tools** (`TOOL`, Alice is its admin): research step **Before
 *   evaluation**, the default checklist, and a custom proposal template: Summary,
 *   Problem, Solution, **Effort & rollout**, Risks, **The ask**. **TOOL-7**
 *   ("Service health dashboard", owner Bob, a member) is in Research with one
 *   required item open ("1/3"); **TOOL-10** ("Code owners linting", owner Farid) is in
 *   Research with every item answered. Every TOOL idea past Research has its required
 *   items answered by its owner; **TOOL-4** (Proposal) has most of the custom template
 *   written, so the editor and the exports show it and the research appendix. TOOL-5
 *   (New, before Research, nothing answered) shows no badge yet.
 * - **Sustainability** (`GREEN`, Carol is its admin, Alice a member): research step
 *   **Before proposal**, the default checklist, and a **Carbon impact** section after
 *   Benefits / revenue. **GREEN-3** (Shortlisted, the status before Research here) has
 *   one item answered; **GREEN-4** (Proposal, owner Emma, no proposal yet) has its
 *   checklist answered. No GREEN idea is in Research, so its step can be moved freely.
 * - **Customer Innovation**: the defaults, step off.
 */
import type { IdeaStatus } from '@/api/types'

import type { MockDb, MockIdea, PROJECTS as ProjectsMap, USERS as UsersMap } from './db'
import { DEFAULT_RESEARCH_CHECKLIST, type MockResearchItem } from './research'

type Users = typeof UsersMap
type Projects = typeof ProjectsMap

/** As db.ts `mockId` (not imported: db.ts imports this module). */
const mockId = (kind: string, n: number) =>
  `${kind}0000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** Checklist item ids (tests answer and clear them by id). */
export const RESEARCH_ITEMS = {
  toolElsewhere: mockId('0', 0x801),
  toolConsulted: mockId('0', 0x802),
  toolDataProtection: mockId('0', 0x803),
  greenElsewhere: mockId('0', 0x811),
  greenConsulted: mockId('0', 0x812),
  greenDataProtection: mockId('0', 0x813),
} as const

/** Realistic consultation records, in checklist order (elsewhere, consulted, data protection). */
const ANSWERS: Record<string, [string, string, string]> = {
  'TOOL-1': [
    'Searched Soundings and asked in #platform: Payments has a fixture generator for their own tests only.',
    'Data platform team (Ines), 12 Sep: happy to host it if we anonymise at source.',
    'Synthetic data only; checked with the privacy office, no personal data leaves production.',
  ],
  'TOOL-2': [
    'Nothing in Soundings; the CI vendor flags flaky tests but has no cross-repository view.',
    'Developer experience guild, 18 Sep: they want a weekly digest, not another dashboard.',
    'Only test names and timings.',
  ],
  'TOOL-3': [
    'Two teams have their own scripts (Checkout, Search); neither covers every service.',
    'Platform engineering (Marta), 2 Aug: they will maintain the base images.',
    '',
  ],
  'TOOL-4': [
    'Only Marketing toggles banners in the CMS; nothing for application code.',
    'Security (Raj), 21 Jul: fine if every change is audited and flags expire.',
    'No personal data in flag rules; targeting uses team names only.',
  ],
  'TOOL-8': [
    'Finance sends a quarterly spreadsheet per department, nothing per team.',
    'Finance (cloud cost lead), 29 Sep: they will share the tagging scheme.',
    '',
  ],
  'TOOL-10': [
    'Searched Soundings and the platform backlog: nobody enforces code owners today.',
    'Legal (contracts team), 3 Oct: fine if we keep the standard terms for the linter licence.',
    'The linter reads file paths only; no personal data.',
  ],
  'TOOL-11': [
    'Docs team writes release notes by hand for the public product only.',
    'Product managers (weekly sync), 25 Sep: they want a draft, never an automatic post.',
    '',
  ],
  'GREEN-4': [
    'Accounts payable already scans paper invoices; nobody sends them electronically.',
    'Finance (accounts payable), 14 Aug: supportive; the ERP supports e-invoicing.',
    'Invoices hold supplier contacts only; checked with the privacy office.',
  ],
}

export function seedPhase8(
  db: MockDb,
  ctx: { users: Users; projects: Projects; nextId: (kind: number | string) => string },
): void {
  const { users, projects, nextId } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  const project = (id: string) => {
    const found = db.projects.find((p) => p.id === id)
    if (!found) throw new Error('fixture project missing')
    return found
  }
  const idea = (key: string): MockIdea => {
    const [projectKey = '', number = ''] = key.split('-')
    const found = db.ideas.find(
      (i) =>
        db.projects.find((p) => p.id === i.project_id)?.key === projectKey &&
        i.number === Number(number),
    )
    if (!found) throw new Error(`fixture idea ${key} missing`)
    return found
  }

  /* Checklists ---------------------------------------------------------- */
  const checklist = (projectId: string, ids: readonly string[]): MockResearchItem[] =>
    DEFAULT_RESEARCH_CHECKLIST.map((item, position) => ({
      id: ids[position] ?? nextId('0'),
      project_id: projectId,
      title: item.title,
      hint: item.hint,
      required: item.required,
      position,
      archived_at: null,
    }))
  const toolItems = checklist(projects.tool, [
    RESEARCH_ITEMS.toolElsewhere,
    RESEARCH_ITEMS.toolConsulted,
    RESEARCH_ITEMS.toolDataProtection,
  ])
  const greenItems = checklist(projects.green, [
    RESEARCH_ITEMS.greenElsewhere,
    RESEARCH_ITEMS.greenConsulted,
    RESEARCH_ITEMS.greenDataProtection,
  ])
  db.researchItems.push(...toolItems, ...greenItems)
  project(projects.tool).research_step = 'before_evaluation'
  project(projects.green).research_step = 'before_proposal'

  const answer = (key: string, items: MockResearchItem[], which: number[], byOwner = true) => {
    const target = idea(key)
    const texts = ANSWERS[key]
    const author = byOwner ? (target.owner_id ?? users.alice) : users.alice
    const at = Date.parse(target.created_at) + 2 * HOUR
    for (const index of which) {
      const item = items[index]
      const text = texts?.[index]
      if (!item || !text) continue
      db.researchAnswers.push({
        idea_id: target.id,
        item_id: item.id,
        answer: text,
        answered_by_id: author,
        answered_at: iso(at + index * MINUTE),
        updated_by_id: author,
        updated_at: iso(at + index * MINUTE),
      })
    }
  }

  /* Internal Tools: ideas past Research were answered before they moved on */
  for (const key of ['TOOL-1', 'TOOL-2', 'TOOL-3', 'TOOL-4', 'TOOL-8', 'TOOL-11']) {
    answer(key, toolItems, [0, 1, 2])
  }

  const moveToResearch = (key: string, owner: string, hoursAgo: number) => {
    const target = idea(key)
    const at = now - hoursAgo * HOUR
    target.owner_id = owner
    db.watchers.add(`${target.id}:${owner}`)
    const push = (type: 'owner_changed' | 'status_changed', ms: number, payload: object) =>
      db.events.push({
        id: nextId(7),
        idea_id: target.id,
        actor_id: owner,
        type,
        payload: { ...payload },
        comment_id: null,
        created_at: iso(ms),
      })
    push('owner_changed', at - HOUR, { from_owner_id: null, to_owner_id: owner, volunteered: true })
    push('status_changed', at, {
      from_status: 'new' satisfies IdeaStatus,
      from_resolution: null,
      to_status: 'research' satisfies IdeaStatus,
      to_resolution: null,
    })
    target.status = 'research'
    target.last_activity_at = iso(at)
    return target
  }
  const tool7 = moveToResearch('TOOL-7', users.bob, 30)
  moveToResearch('TOOL-10', users.farid, 50)
  // TOOL-7: only "Not already being done elsewhere" so far (1/3, one required open).
  db.researchAnswers.push({
    idea_id: tool7.id,
    item_id: RESEARCH_ITEMS.toolElsewhere,
    answer:
      'Searched Soundings: the Office energy dashboard idea in Sustainability is similar in spirit, but for energy. Ops has Grafana boards per service, no overview.',
    answered_by_id: users.bob,
    answered_at: iso(now - 26 * HOUR),
    updated_by_id: users.bob,
    updated_at: iso(now - 26 * HOUR),
  })
  answer('TOOL-10', toolItems, [0, 1, 2])

  /* Internal Tools: the custom template --------------------------------- */
  const toolSections = db.templateSections.filter((s) => s.project_id === projects.tool)
  const keep = ['summary', 'problem', 'solution', 'risks']
  db.templateSections = db.templateSections.filter(
    (s) => s.project_id !== projects.tool || keep.includes(s.key),
  )
  const titled = (key: string, title: string, hint: string, position: number) => ({
    id: nextId('0'),
    project_id: projects.tool,
    key,
    title,
    hint,
    position,
    archived_at: null,
  })
  db.templateSections.push(
    titled(
      'effort_rollout',
      'Effort & rollout',
      'Who builds it, how long it takes, and how teams start using it.',
      3,
    ),
    titled('the_ask', 'The ask', 'What you need, from whom, and by when.', 5),
  )
  for (const section of toolSections) {
    const position = { summary: 0, problem: 1, solution: 2, risks: 4 }[section.key]
    if (position !== undefined) section.position = position
  }

  // TOOL-4's proposal follows the new template, most of it written.
  const tool4 = idea('TOOL-4')
  const proposal = db.proposals.find((p) => p.idea_id === tool4.id)
  if (proposal) {
    db.proposalSections = db.proposalSections.filter(
      (row) =>
        row.proposal_id !== proposal.id ||
        ['summary', 'problem', 'solution', 'risks'].includes(row.key),
    )
    const written: Record<string, string> = {
      problem:
        'Turning a feature on for one team means a deploy and a change ticket. Teams wait two days on average, and rollbacks need another deploy.',
      solution:
        'A small flag service with a web page: teams create a flag, choose environments and teams, and switch it without a deploy. Every change is audited.',
      effort_rollout:
        '- Two engineers for six weeks\n- Pilot with Checkout and Search\n- Then every team, with a short guide and office hours',
      risks:
        'Flags left behind: they expire after 90 days unless someone renews them. An outage of the flag service: clients keep the last known values.',
    }
    for (const [key, text] of Object.entries(written)) {
      const row = db.proposalSections.find((r) => r.proposal_id === proposal.id && r.key === key)
      const at = iso(now - DAY)
      if (row) Object.assign(row, { body_md: text, version: 2, updated_at: at })
      else {
        db.proposalSections.push({
          proposal_id: proposal.id,
          key,
          body_md: text,
          version: 2,
          updated_at: at,
          updated_by_id: users.bob,
        })
      }
    }
    for (const row of db.proposalSections) {
      if (row.proposal_id === proposal.id && row.key !== 'summary' && written[row.key]) {
        row.updated_by_id = users.bob
      }
    }
    db.proposalSections.push({
      proposal_id: proposal.id,
      key: 'the_ask',
      body_md: '',
      version: 1,
      updated_at: proposal.created_at,
      updated_by_id: null,
    })
  }

  /* Sustainability: Carbon impact after Benefits / revenue -------------- */
  for (const section of db.templateSections) {
    if (section.project_id === projects.green && section.position >= 6) section.position += 1
  }
  db.templateSections.push({
    id: nextId('0'),
    project_id: projects.green,
    key: 'carbon_impact',
    title: 'Carbon impact',
    hint: 'How much CO₂e this saves or adds a year, and how we will measure it.',
    position: 6,
    archived_at: null,
  })
  answer('GREEN-4', greenItems, [0, 1, 2])
  // GREEN-3 (Shortlisted, the status before Research here): one item answered so far.
  db.researchAnswers.push({
    idea_id: idea('GREEN-3').id,
    item_id: RESEARCH_ITEMS.greenElsewhere,
    answer:
      'Facilities looked at solar in 2023 for the head office only; the warehouse roof was never assessed.',
    answered_by_id: users.carol,
    answered_at: iso(now - 3 * DAY),
    updated_by_id: users.carol,
    updated_at: iso(now - 3 * DAY),
  })

  db.events.sort((a, b) => a.created_at.localeCompare(b.created_at))
}
