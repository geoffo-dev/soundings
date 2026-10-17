/**
 * Phase 11 fixtures (contract-phase11 §15, adapted to the mock's people): messages
 * between the team and people who sent ideas through Sustainability's public form.
 *
 * - **GREEN-13** "Reusable delivery crates with a deposit" (owner **Grace**, a member:
 *   she holds `public.message_submitter` as its owner): sent by Sam Okafor, whose
 *   address is confirmed, so team messages are emailed too. A conversation of four:
 *   Grace asked, Sam replied, Carol (the project's admin) asked again and Sam replied
 *   40 minutes ago; Grace and Carol have "The submitter replied" (the latest unread).
 *   **Alice**, a member who doesn't own it, sees no Messages section at all; Emma
 *   neither. Tracking link `PHASE11_TOKENS.sam`.
 * - **GREEN-14** "Bike repair stand by the entrance" (no owner): Ana Ruiz's address is
 *   not confirmed, so messages reach her tracking page only. Carol wrote yesterday;
 *   no reply yet (the tracking page has the reply box). `PHASE11_TOKENS.ana`.
 * - **GREEN-15** "Swap shelf for office supplies" (owner Grace): the submitter's details
 *   were erased, and the conversation with them: the panel says there is no one to
 *   write to.
 * - **GREEN-10** (Phase 4, held for moderation, no address): Carol asked before
 *   approving and the submitter answered (the queue says "They replied"; held ideas
 *   notify nobody).
 * - **GREEN-9** (Phase 4, Jo Marsh): the team hasn't written, so the tracking page has
 *   no Messages section.
 */
import type { MockDb, MockIdea, PROJECTS as ProjectsMap, USERS as UsersMap } from './db'
import { fixtureToken } from './public'
import { TRACKING_TOKENS } from './phase4-fixtures'
import type { MockSubmissionMessage } from './submitter-messages'

type Users = typeof UsersMap
type Projects = typeof ProjectsMap

const MINUTE = 60_000
const HOUR = 60 * MINUTE

/** Tracking tokens of the Phase 11 submissions (`/track#<token>`). */
export const PHASE11_TOKENS = {
  /** GREEN-13: confirmed address, a conversation of four. */
  sam: fixtureToken('SamOkaforGreen13'),
  /** GREEN-14: unconfirmed address, one team message, no reply yet. */
  ana: fixtureToken('AnaRuizGreen14'),
  /** GREEN-10 (Phase 4): held for moderation, asked before approving. */
  moderated: TRACKING_TOKENS.moderated,
} as const

export const PHASE11_SUBMISSIONS = {
  sam: 'e0000000-0000-4000-8000-0000000f0011',
  ana: 'e0000000-0000-4000-8000-0000000f0012',
  erased: 'e0000000-0000-4000-8000-0000000f0013',
} as const

export function seedPhase11(
  db: MockDb,
  ctx: { users: Users; projects: Projects; nextId: (kind: number | string) => string },
): void {
  const { users, nextId } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  const green = db.projects.find((p) => p.key === 'GREEN')
  if (!green) return

  const sentEmail = (
    type: 'submission_link' | 'submission_message',
    to: string,
    ideaId: string,
    at: number,
  ) => {
    db.outbox.push({
      id: nextId('d'),
      type,
      status: 'sent',
      recipient_user_id: null,
      to_address: to,
      requested_by_id: null,
      attempts: 1,
      max_attempts: 12,
      next_attempt_at: null,
      last_error: null,
      created_at: iso(at),
      updated_at: iso(at + MINUTE),
      sent_at: iso(at + MINUTE),
      idea_id: ideaId,
    })
  }

  const addIdea = (spec: {
    submission: string
    token: string | null
    title: string
    summary: string
    description: string
    owner: string | null
    ageHours: number
    name: string | null
    email: string | null
    verified: boolean
    wantsUpdates: boolean
    erasedHoursAgo?: number
  }): MockIdea => {
    const createdAt = now - spec.ageHours * HOUR
    const idea: MockIdea = {
      id: nextId(3),
      project_id: green.id,
      number: green.next_idea_number++,
      title: spec.title,
      summary: spec.summary,
      description_md: spec.description,
      status: 'new',
      resolution: null,
      owner_id: spec.owner,
      submitted_by: null,
      created_at: iso(createdAt),
      last_activity_at: iso(createdAt + 2 * HOUR),
      evaluation_due_at: null,
      evaluation_closed_at: null,
      tag_ids: [],
      held_for: null,
    }
    db.ideas.push(idea)
    db.events.push({
      id: nextId(7),
      idea_id: idea.id,
      actor_id: null,
      type: 'idea_created',
      payload: {},
      comment_id: null,
      created_at: iso(createdAt),
    })
    const erased = spec.erasedHoursAgo !== undefined
    db.publicSubmissions.push({
      id: spec.submission,
      idea_id: idea.id,
      name: erased ? null : spec.name,
      email: erased ? null : spec.email,
      email_verified_at: !erased && spec.verified ? iso(createdAt + 10 * MINUTE) : null,
      wants_updates: !erased && spec.wantsUpdates,
      tracking_token: erased ? null : spec.token,
      submitted_title: erased ? null : spec.title,
      submitted_summary: erased ? null : spec.summary,
      created_at: iso(createdAt),
      reached_team_at: iso(createdAt),
      erased_at: erased ? iso(now - (spec.erasedHoursAgo ?? 0) * HOUR) : null,
      erased_by_id: erased ? users.carol : null,
      confirmation_sends: spec.email && !erased ? [iso(createdAt)] : [],
    })
    if (!erased && spec.email && spec.verified) {
      // The tracking link went out when the address was confirmed (D1).
      sentEmail('submission_link', spec.email, idea.id, createdAt + 11 * MINUTE)
    }
    return idea
  }

  const message = (
    submission: string,
    idea: MockIdea,
    direction: MockSubmissionMessage['direction'],
    author: string | null,
    minutesAgo: number,
    body: string,
    emailTo: string | null = null,
  ): MockSubmissionMessage => {
    const at = now - minutesAgo * MINUTE
    const row: MockSubmissionMessage = {
      id: nextId('e'),
      submission_id: submission,
      direction,
      author_id: direction === 'team' ? author : null,
      body,
      emailed: direction === 'team' && emailTo !== null,
      created_at: iso(at),
    }
    db.submissionMessages.push(row)
    if (direction === 'team') {
      if (emailTo) sentEmail('submission_message', emailTo, idea.id, at)
      db.audit.push({
        id: nextId('b'),
        created_at: iso(at),
        actor_id: author,
        action: 'submission.message',
        target_type: 'idea',
        target_id: idea.id,
        project_id: idea.project_id,
        details: {
          rule: 'public.message_submitter',
          message_id: row.id,
          emailed: row.emailed,
          auth_method: 'sso',
        },
      })
    }
    return row
  }

  const replied = (to: string, idea: MockIdea, reply: MockSubmissionMessage, read: boolean) => {
    const at = Date.parse(reply.created_at)
    db.notifications.push({
      id: nextId('c'),
      user_id: to,
      type: 'submitter_replied',
      idea_id: idea.id,
      actor_id: null,
      comment_id: null,
      payload: { message_id: reply.id },
      dedupe_key: `submitter_replied:${reply.id}`,
      email_mode: 'immediate',
      email_id: null,
      created_at: iso(at),
      read_at: read ? iso(at + 20 * MINUTE) : null,
    })
  }

  /* GREEN-13: a conversation of four, emailed (confirmed address) ---------- */
  const sam = 'sam.okafor@example.org'
  const crates = addIdea({
    submission: PHASE11_SUBMISSIONS.sam,
    token: PHASE11_TOKENS.sam,
    title: 'Reusable delivery crates with a deposit',
    summary:
      'Deliver to our sites in sturdy crates that go back on the next run, with a small deposit.',
    description:
      'Most deliveries come in cardboard that goes straight into the recycling. A crate with a deposit comes back on the next delivery.',
    owner: users.grace,
    ageHours: 3 * 24,
    name: 'Sam Okafor',
    email: sam,
    verified: true,
    wantsUpdates: true,
  })
  message(
    PHASE11_SUBMISSIONS.sam,
    crates,
    'team',
    users.grace,
    2 * 24 * 60,
    'Thanks, Sam! Which of our sites did you have in mind?\nWe’d like to try it in two first.',
    sam,
  )
  const first = message(
    PHASE11_SUBMISSIONS.sam,
    crates,
    'submitter',
    null,
    2 * 24 * 60 - 90,
    'The two warehouses in the north see the most deliveries.\nHappy to help with the trial: see https://example.org/crates for the crates we use at home.',
  )
  message(
    PHASE11_SUBMISSIONS.sam,
    crates,
    'team',
    users.carol,
    5 * 60,
    'Great, thank you. Roughly how many crates a week would each warehouse need?',
    sam,
  )
  const latest = message(
    PHASE11_SUBMISSIONS.sam,
    crates,
    'submitter',
    null,
    40,
    'About 300 a week at each, a bit more before Christmas.',
  )
  replied(users.grace, crates, first, true)
  replied(users.grace, crates, latest, false)
  replied(users.carol, crates, latest, false)

  /* GREEN-14: tracking page only (the address isn't confirmed) ------------ */
  const bikes = addIdea({
    submission: PHASE11_SUBMISSIONS.ana,
    token: PHASE11_TOKENS.ana,
    title: 'Bike repair stand by the entrance',
    summary: 'A stand with a pump and basic tools, so people who cycle in can fix a puncture.',
    description: '',
    owner: null,
    ageHours: 2 * 24,
    name: 'Ana Ruiz',
    email: 'ana.ruiz@example.org',
    verified: false,
    wantsUpdates: false,
  })
  message(
    PHASE11_SUBMISSIONS.ana,
    bikes,
    'team',
    users.carol,
    20 * 60,
    'Hello Ana, thanks for this. Would the stand be for staff only, or for visitors too?',
  )

  /* GREEN-15: the submitter's details (and the conversation) erased ------- */
  addIdea({
    submission: PHASE11_SUBMISSIONS.erased,
    token: null,
    title: 'Swap shelf for office supplies',
    summary: 'A shelf where people leave the stationery they don’t need and take what they do.',
    description: '',
    owner: users.grace,
    ageHours: 6 * 24,
    name: 'Lee',
    email: 'lee@example.org',
    verified: true,
    wantsUpdates: false,
    erasedHoursAgo: 30,
  })

  /* GREEN-10 (Phase 4): asked before approving; held, so nobody is notified */
  const held = db.publicSubmissions.find((s) => s.tracking_token === TRACKING_TOKENS.moderated)
  const heldIdea = held && db.ideas.find((i) => i.id === held.idea_id)
  if (held && heldIdea) {
    message(
      held.id,
      heldIdea,
      'team',
      users.carol,
      3 * 60,
      'Before we share this: is the verge by the car park ours, or the council’s?',
    )
    message(held.id, heldIdea, 'submitter', null, 70, 'It’s ours: it’s inside the fence.')
  }
}
