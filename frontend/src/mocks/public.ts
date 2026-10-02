/**
 * Phase 4 public submission in the mock API (contract-phase4 §3.5–3.9): the
 * per-project form settings, the submissions behind public ideas, tracking and
 * confirmation tokens, moderation and erasure. Records mirror the backend
 * tables (`public_submissions`, the `projects.public_*` columns); the mock keeps
 * tracking tokens in clear (the API stores only a hash and a sealed copy).
 */
import type {
  EmailVerified,
  IdeaSubmission,
  ModerationItem,
  PublicFormSettings,
  PublicProject,
  TrackedStatusChange,
  TrackedSubmission,
} from '@/api/types'

import { effectiveBranding } from './branding'
import type { MockDb, MockEvent, MockIdea, MockProject, MockUser } from './db'
import { ideaRef, isProjectAdmin, projectOf, rowsForIdea, statusLabel } from './domain'
import { maskEmail, queueEmail } from './notifications'

export interface MockPublicForm {
  project_id: string
  enabled: boolean
  require_email_verification: boolean
  moderation_required: boolean
  intro_md: string
}

export interface MockPublicSubmission {
  id: string
  idea_id: string
  name: string | null
  email: string | null
  email_verified_at: string | null
  wants_updates: boolean
  /** The mock keeps the token itself; null once erased. */
  tracking_token: string | null
  submitted_title: string | null
  submitted_summary: string | null
  created_at: string
  /** When a hold released it (approval, confirmation); unset: `created_at` once not held. */
  reached_team_at?: string | null
  erased_at: string | null
  erased_by_id: string | null
  /** When `submission_received` emails went out (first send and resends). */
  confirmation_sends: string[]
}

/** The app's own top-level paths (`RESERVED_SLUGS`): no public form at `/{slug}/submit`. */
export const RESERVED_SLUGS = new Set(
  // prettier-ignore
  [
    'admin', 'api', 'assets', 'branding', 'design', 'docs', 'favicon', 'healthz', 'ideas',
    'login', 'logout', 'mcp', 'me', 'metrics', 'notifications', 'projects', 'public',
    'readyz', 'search', 'settings', 'static', 'submit', 'track', 'unsubscribe', 'verify',
  ],
)

export const PUBLIC_BASE_URL = typeof window === 'undefined' ? 'http://localhost:5173' : ''
export const SUBMISSIONS_PER_IP_PER_HOUR = 10
export const CONFIRMATIONS_PER_DAY = 3
export const ALTCHA_EXPIRY_MS = 30 * 60_000
export const INTRO_MAX_LENGTH = 2_000
const DAY = 24 * 3_600_000

export function publicFormOf(db: MockDb, project: MockProject): MockPublicForm {
  let form = db.publicForms.find((f) => f.project_id === project.id)
  if (!form) {
    form = {
      project_id: project.id,
      enabled: false,
      require_email_verification: false,
      moderation_required: true,
      intro_md: '',
    }
    db.publicForms.push(form)
  }
  return form
}

/** c8 without the instance switch: the project could have a form at all. */
export function formAvailable(db: MockDb, project: MockProject): boolean {
  return (
    db.publicSubmissionEnabled && project.archived_at === null && !RESERVED_SLUGS.has(project.slug)
  )
}

/** c8: the form is on and available. */
export function formOpen(db: MockDb, project: MockProject): boolean {
  return formAvailable(db, project) && publicFormOf(db, project).enabled
}

export function formUrl(project: MockProject): string {
  const base = typeof window === 'undefined' ? PUBLIC_BASE_URL : window.location.origin
  return `${base}/${project.slug}/submit`
}

export function trackingUrl(token: string): string {
  const base = typeof window === 'undefined' ? PUBLIC_BASE_URL : window.location.origin
  return `${base}/track#${token}`
}

export function awaitingModeration(db: MockDb, project: MockProject): MockIdea[] {
  return db.ideas
    .filter((idea) => idea.project_id === project.id && idea.held_for === 'moderation')
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.number - b.number)
}

export function publicFormSettings(db: MockDb, project: MockProject): PublicFormSettings {
  const form = publicFormOf(db, project)
  return {
    available: formAvailable(db, project),
    email_available: db.email.configured,
    enabled: form.enabled,
    require_email_verification: form.require_email_verification,
    moderation_required: form.moderation_required,
    intro_md: form.intro_md,
    form_url: formUrl(project),
    awaiting_moderation: awaitingModeration(db, project).length,
  }
}

export function publicProject(db: MockDb, project: MockProject): PublicProject {
  const form = publicFormOf(db, project)
  return {
    slug: project.slug,
    name: project.name,
    intro_md: form.intro_md,
    asks_for_email: db.email.configured,
    email_required: form.require_email_verification && db.email.configured,
    moderated: form.moderation_required,
    branding: effectiveBranding(db, project.id),
  }
}

export function submissionOf(db: MockDb, idea: MockIdea): MockPublicSubmission | undefined {
  return db.publicSubmissions.find((s) => s.idea_id === idea.id)
}

export function submissionByToken(db: MockDb, token: string): MockPublicSubmission | undefined {
  if (!db.publicSubmissionEnabled) return undefined
  const submission = db.publicSubmissions.find((s) => s.tracking_token === token)
  if (submission?.erased_at !== null) return undefined
  return db.ideas.some((idea) => idea.id === submission.idea_id) ? submission : undefined
}

export function ideaSubmission(
  db: MockDb,
  idea: MockIdea,
  submission: MockPublicSubmission,
  user: MockUser,
): IdeaSubmission {
  const admin = isProjectAdmin(db, projectOf(db, idea), user)
  return {
    idea_id: idea.id,
    submitted_at: submission.created_at,
    held_for: idea.held_for === 'moderation' ? 'moderation' : null,
    name: submission.name,
    contact: admin
      ? {
          email: submission.email,
          email_verified: submission.email_verified_at !== null,
          wants_updates: submission.wants_updates,
        }
      : null,
    erased_at: submission.erased_at,
    permissions: {
      can_moderate:
        admin && idea.held_for === 'moderation' && projectOf(db, idea).archived_at === null,
      can_erase: admin && submission.erased_at === null,
    },
  }
}

export function moderationItem(db: MockDb, idea: MockIdea, user: MockUser): ModerationItem {
  const submission = submissionOf(db, idea)
  return {
    ...ideaRef(db, idea),
    summary: idea.summary,
    description_md: idea.description_md,
    submission: submission
      ? ideaSubmission(db, idea, submission, user)
      : {
          idea_id: idea.id,
          submitted_at: idea.created_at,
          held_for: 'moderation',
          name: null,
          contact: null,
          erased_at: null,
          permissions: { can_moderate: true, can_erase: false },
        },
  }
}

function history(
  db: MockDb,
  idea: MockIdea,
  submission: MockPublicSubmission,
): TrackedStatusChange[] {
  const project = projectOf(db, idea)
  return rowsForIdea(db.events, idea.id)
    .filter((event) => event.type === 'status_changed' && event.created_at >= submission.created_at)
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((event) => {
      const status = event.payload.to_status as MockIdea['status']
      const resolution = (event.payload.to_resolution ?? null) as MockIdea['resolution']
      return {
        status,
        resolution,
        status_label: statusLabel(project, { status, resolution }),
        at: event.created_at,
      }
    })
}

export function canResendConfirmation(db: MockDb, submission: MockPublicSubmission): boolean {
  if (!db.email.configured || !submission.email || submission.email_verified_at) return false
  return recentSends(submission) < CONFIRMATIONS_PER_DAY
}

export function recentSends(submission: MockPublicSubmission, now = Date.now()): number {
  return submission.confirmation_sends.filter((at) => now - Date.parse(at) < DAY).length
}

export function trackedSubmission(db: MockDb, submission: MockPublicSubmission): TrackedSubmission {
  const idea = db.ideas.find((i) => i.id === submission.idea_id)
  if (!idea) throw new Error('submission without an idea')
  const project = projectOf(db, idea)
  return {
    project: { slug: project.slug, name: project.name },
    title: submission.submitted_title ?? '',
    summary: submission.submitted_summary ?? '',
    submitted_at: submission.created_at,
    reached_team_at: idea.held_for ? null : (submission.reached_team_at ?? submission.created_at),
    held_for: idea.held_for ?? null,
    status: idea.status,
    resolution: idea.resolution,
    status_label: statusLabel(project, idea),
    history: history(db, idea, submission),
    email_hint: submission.email ? maskEmail(submission.email) : null,
    email_verified: submission.email_verified_at !== null,
    wants_updates: submission.wants_updates,
    can_resend_verification: canResendConfirmation(db, submission),
    branding: effectiveBranding(db, project.id),
  }
}

export function emailVerified(db: MockDb, submission: MockPublicSubmission): EmailVerified {
  const idea = db.ideas.find((i) => i.id === submission.idea_id)
  if (!idea) throw new Error('submission without an idea')
  const project = projectOf(db, idea)
  return {
    project: { slug: project.slug, name: project.name },
    title: submission.submitted_title ?? '',
    held_for: idea.held_for ?? null,
    branding: effectiveBranding(db, project.id),
  }
}

/* ------------------------------------------------------------------ */
/* Tokens                                                              */
/* ------------------------------------------------------------------ */

const TOKEN_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'

/** 43 base64url characters, like the API's 32 random bytes. */
export function newTrackingToken(): string {
  const bytes = new Uint8Array(43)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => TOKEN_ALPHABET[byte % 64]).join('')
}

/** A deterministic 43-character fixture token ("track" + name, padded). */
export function fixtureToken(name: string): string {
  return `track${name}`
    .replace(/[^A-Za-z0-9_-]/g, '')
    .padEnd(43, 'x')
    .slice(0, 43)
}

/**
 * The mock's confirmation-link token (`/verify#<token>`): `v1.<submission id>`.
 * The API signs it and it expires after 3 days; here `v1.expired` (or any
 * unknown id) is the "invalid or expired" case.
 */
export function confirmationToken(submissionId: string): string {
  return `v1.${submissionId}`
}

export function submissionByConfirmationToken(
  db: MockDb,
  token: string,
): MockPublicSubmission | undefined {
  if (!db.publicSubmissionEnabled || !token.startsWith('v1.')) return undefined
  const submission = db.publicSubmissions.find((s) => s.id === token.slice(3))
  if (submission?.erased_at !== null || !submission.email) return undefined
  return db.ideas.some((idea) => idea.id === submission.idea_id) ? submission : undefined
}

/* ------------------------------------------------------------------ */
/* Writes                                                              */
/* ------------------------------------------------------------------ */

/** Queues a `submission_received` email (the outbox row names the idea, §3.8). */
export function queueConfirmation(db: MockDb, submission: MockPublicSubmission): void {
  if (!db.email.configured || !submission.email) return
  // The per-address limit is silent: the submission still says the email was sent.
  const address = addressKey(submission.email)
  const sentToAddress = db.publicSubmissions
    .filter((s) => s.email && addressKey(s.email) === address)
    .reduce((count, s) => count + recentSends(s), 0)
  if (sentToAddress >= CONFIRMATIONS_PER_DAY) return
  const row = queueEmail(db, { type: 'submission_received', to_address: submission.email })
  row.idea_id = submission.idea_id
  submission.confirmation_sends.push(new Date().toISOString())
}

/** Lower-cased, `+tag` removed (`SUBMITTER_ADDRESS_KEY_SQL`). */
export function addressKey(email: string): string {
  const [local = '', domain = ''] = email.toLowerCase().split('@')
  return `${local.split('+')[0] ?? ''}@${domain}`
}

/** Erases the submitter's details (admin or self, §3.9); the idea stays. */
export function eraseSubmission(
  db: MockDb,
  submission: MockPublicSubmission,
  by: MockUser | null,
): void {
  if (submission.erased_at !== null) return
  submission.name = null
  submission.email = null
  submission.email_verified_at = null
  submission.wants_updates = false
  submission.tracking_token = null
  submission.submitted_title = null
  submission.submitted_summary = null
  submission.erased_at = new Date().toISOString()
  submission.erased_by_id = by?.id ?? null
  db.outbox = db.outbox.filter((row) => row.idea_id !== submission.idea_id)
}

/** Status emails to an opted-in, confirmed submitter (fan-out of `status_changed`, §3.8). */
export function queueSubmitterStatusEmail(db: MockDb, idea: MockIdea, event: MockEvent): void {
  if (event.type !== 'status_changed' || idea.held_for || !db.email.configured) return
  const submission = submissionOf(db, idea)
  if (
    !submission?.email ||
    !submission.wants_updates ||
    !submission.email_verified_at ||
    submission.erased_at
  ) {
    return
  }
  const row = queueEmail(db, { type: 'submission_status_changed', to_address: submission.email })
  row.idea_id = idea.id
}
