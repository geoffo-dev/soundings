/**
 * The public form, tracking and confirmation links (contract-phase4 §2
 * "Public submission", §3.5–3.7). No session: the project's setting (c8) or
 * the token in the body (c9) is the authority, and nothing private leaves.
 *
 * Mock simplifications: one client address (this browser), so the per-IP
 * limit counts every attempt; ALTCHA payloads aren't verified, only checked
 * for replay (the signature inside a JSON payload, else the payload itself) —
 * a payload containing `invalid` fails, to exercise `challenge_failed`.
 */
import type { HoldReason } from '@/api/types'
import { recordAudit } from '@/mocks/access'
import { ID_KIND, newId, type MockDb, type MockProject } from '@/mocks/db'
import { findProjectBySlug } from '@/mocks/domain'
import {
  accepted,
  allowOnly,
  conflict,
  created,
  fail,
  failValidation,
  noContent,
  notFound,
  publicRoute,
  readJson,
  stringField,
  tooManyAttempts,
  type PublicRouteContext,
} from '@/mocks/http'
import {
  ALTCHA_EXPIRY_MS,
  CONFIRMATIONS_PER_DAY,
  emailVerified,
  eraseSubmission,
  formOpen,
  newTrackingToken,
  publicFormOf,
  publicProject,
  queueConfirmation,
  recentSends,
  submissionByConfirmationToken,
  submissionByToken,
  SUBMISSIONS_PER_IP_PER_HOUR,
  trackedSubmission,
  trackingUrl,
  type MockPublicSubmission,
} from '@/mocks/public'

const HOUR = 3_600_000
const TRACKING_TOKEN = /^[A-Za-z0-9_-]{43}$/
const VERIFICATION_TOKEN = /^[A-Za-z0-9_.-]{16,512}$/
const EMAIL = /^[^\s@<>()",;:]+@[^\s@<>()",;:]+\.[^\s@<>()",;:]+$/

/** 415 unless the body is declared as JSON (contract-phase4 §1). */
function requireJson(ctx: PublicRouteContext): void {
  const type = ctx.request.headers.get('Content-Type') ?? ''
  if (!/^application\/json\s*(;|$)/i.test(type)) {
    fail(415, 'unsupported_media_type', 'Send the body as application/json.')
  }
}

/** The form's project, or the same 404 for every reason (c8). */
function openForm(ctx: PublicRouteContext): MockProject {
  const slug = typeof ctx.params.slug === 'string' ? decodeURIComponent(ctx.params.slug) : ''
  const project = findProjectBySlug(ctx.db, slug)
  if (!project || !formOpen(ctx.db, project)) notFound('This form isn’t available.')
  return project
}

function tokenField(body: Record<string, unknown>, pattern: RegExp): string {
  const token = body.token
  if (typeof token !== 'string' || !pattern.test(token)) {
    failValidation([
      {
        loc: ['body', 'token'],
        msg: 'String should match pattern',
        type: 'string_pattern_mismatch',
      },
    ])
  }
  return token
}

async function tracked(ctx: PublicRouteContext, fields: string[] = ['token']) {
  requireJson(ctx)
  const body = await readJson(ctx.request)
  allowOnly(body, fields)
  const token = tokenField(body, TRACKING_TOKEN)
  const submission = submissionByToken(ctx.db, token)
  if (!submission) notFound('We can’t find this submission. It may have been removed.')
  return { body, submission }
}

function holdFor(db: MockDb, project: MockProject): HoldReason | null {
  const form = publicFormOf(db, project)
  if (form.require_email_verification && db.email.configured) return 'email_verification'
  return form.moderation_required ? 'moderation' : null
}

/** The replay key of an ALTCHA payload, or null when it is unusable. */
function altchaKey(payload: string): string | null {
  if (payload.toLowerCase().includes('invalid')) return null
  try {
    const decoded = JSON.parse(atob(payload)) as { signature?: unknown }
    if (typeof decoded.signature === 'string') return decoded.signature
  } catch {
    // Not base64 JSON: the payload itself is the key.
  }
  return payload
}

function randomHex(bytes: number): string {
  const data = new Uint8Array(bytes)
  crypto.getRandomValues(data)
  return Array.from(data, (b) => b.toString(16).padStart(2, '0')).join('')
}

export const publicHandlers = [
  publicRoute('get', '/public/projects/:slug', (ctx) => publicProject(ctx.db, openForm(ctx))),

  publicRoute('get', '/public/projects/:slug/altcha', (ctx) => {
    const project = openForm(ctx)
    return {
      parameters: {
        algorithm: 'PBKDF2/SHA-256',
        cost: 1000,
        keyLength: 32,
        keyPrefix: '00',
        nonce: randomHex(16),
        salt: randomHex(16),
        expiresAt: Math.floor((Date.now() + ALTCHA_EXPIRY_MS) / 1000),
        data: { project: project.slug },
      },
      signature: randomHex(32),
    }
  }),

  publicRoute('post', '/public/projects/:slug/submissions', async (ctx) => {
    requireJson(ctx)
    const body = await readJson(ctx.request)
    allowOnly(body, [
      'title',
      'summary',
      'description_md',
      'name',
      'email',
      'wants_updates',
      'altcha',
      'website',
    ])
    const title = stringField(body, 'title', { required: true, max: 200 }) ?? ''
    if (/[\r\n]/.test(title)) {
      failValidation([{ loc: ['body', 'title'], msg: 'One line only', type: 'value_error' }])
    }
    const summary = stringField(body, 'summary', { required: true, max: 500 }) ?? ''
    const description = stringField(body, 'description_md', { max: 10_000 }) ?? ''
    const name = stringField(body, 'name', { max: 80 }) ?? ''
    let email: string | null = stringField(body, 'email', { max: 254 }) ?? ''
    if (!email) email = null
    if (email && (!EMAIL.test(email) || email.toLowerCase().endsWith('.invalid'))) {
      failValidation([
        { loc: ['body', 'email'], msg: 'Enter a valid email address', type: 'value_error' },
      ])
    }
    let wantsUpdates = body.wants_updates === true
    if (wantsUpdates && !email) {
      failValidation([
        { loc: ['body'], msg: 'wants_updates needs an email address', type: 'value_error' },
      ])
    }
    const altcha = stringField(body, 'altcha', { required: true, max: 4096 }) ?? ''
    const website = typeof body.website === 'string' ? body.website : ''

    const project = openForm(ctx)
    const now = Date.now()
    // Per-IP limit: every attempt counts (honeypot hits and failed challenges too).
    ctx.db.publicAttempts = ctx.db.publicAttempts.filter((at) => now - at < HOUR)
    if (ctx.db.publicAttempts.length >= SUBMISSIONS_PER_IP_PER_HOUR) {
      tooManyAttempts(
        (HOUR - (now - (ctx.db.publicAttempts[0] ?? now))) / 1000,
        'You’ve sent several ideas in a short time. Try again in a few minutes.',
      )
    }
    ctx.db.publicAttempts.push(now)
    const asksForEmail = ctx.db.email.configured
    if (!asksForEmail) {
      email = null
      wantsUpdates = false
    }
    const form = publicFormOf(ctx.db, project)
    if (form.require_email_verification && asksForEmail && !email) {
      failValidation(
        [{ loc: ['body', 'email'], msg: 'This form needs your email address', type: 'missing' }],
        'email_required',
      )
    }
    const key = altchaKey(altcha)
    if (!key || ctx.db.altchaUsed.has(key)) {
      failValidation(
        [{ loc: ['body', 'altcha'], msg: 'We couldn’t verify this browser', type: 'value_error' }],
        'challenge_failed',
      )
    }
    ctx.db.altchaUsed.add(key)
    const heldFor = holdFor(ctx.db, project)
    // Honeypot: a normal-looking receipt, nothing stored.
    if (website) {
      const token = newTrackingToken()
      return created({
        tracking_token: token,
        tracking_url: trackingUrl(token),
        held_for: heldFor,
        email_sent: Boolean(email && asksForEmail),
      })
    }
    const at = new Date(now).toISOString()
    const ideaId = newId(ctx.db, ID_KIND.idea)
    ctx.db.ideas.push({
      id: ideaId,
      project_id: project.id,
      number: project.next_idea_number++,
      title,
      summary,
      description_md: description,
      status: 'new',
      resolution: null,
      owner_id: null,
      submitted_by: null,
      created_at: at,
      last_activity_at: at,
      evaluation_due_at: null,
      evaluation_closed_at: null,
      tag_ids: [],
      held_for: heldFor,
    })
    ctx.db.events.push({
      id: newId(ctx.db, ID_KIND.event),
      idea_id: ideaId,
      actor_id: null,
      type: 'idea_created',
      payload: {},
      comment_id: null,
      created_at: at,
    })
    const token = newTrackingToken()
    const submission: MockPublicSubmission = {
      id: newId(ctx.db, ID_KIND.phase4),
      idea_id: ideaId,
      name: name || null,
      email,
      email_verified_at: null,
      wants_updates: wantsUpdates,
      tracking_token: token,
      submitted_title: title,
      submitted_summary: summary,
      created_at: at,
      erased_at: null,
      erased_by_id: null,
      confirmation_sends: [],
    }
    ctx.db.publicSubmissions.push(submission)
    queueConfirmation(ctx.db, submission)
    return created({
      tracking_token: token,
      tracking_url: trackingUrl(token),
      held_for: heldFor,
      email_sent: Boolean(email && asksForEmail),
    })
  }),

  publicRoute('post', '/public/track', async (ctx) => {
    const { submission } = await tracked(ctx)
    return trackedSubmission(ctx.db, submission)
  }),

  publicRoute('put', '/public/track/updates', async (ctx) => {
    const { body, submission } = await tracked(ctx, ['token', 'wants_updates'])
    if (typeof body.wants_updates !== 'boolean') {
      failValidation([
        {
          loc: ['body', 'wants_updates'],
          msg: 'Input should be a valid boolean',
          type: 'bool_type',
        },
      ])
    }
    if (body.wants_updates && !submission.email) {
      conflict('no_email', 'There is no email address on file for this idea.')
    }
    submission.wants_updates = body.wants_updates
    return trackedSubmission(ctx.db, submission)
  }),

  publicRoute('post', '/public/track/verification-email', async (ctx) => {
    const { submission } = await tracked(ctx)
    if (!submission.email) conflict('no_email', 'There is no email address on file for this idea.')
    if (submission.email_verified_at) conflict('already_verified', 'This address is confirmed.')
    if (!ctx.db.email.configured) conflict('smtp_not_configured', 'Email isn’t set up.')
    if (recentSends(submission) >= CONFIRMATIONS_PER_DAY) {
      const oldest = Math.min(...submission.confirmation_sends.map((s) => Date.parse(s)))
      tooManyAttempts(
        (oldest + 24 * HOUR - Date.now()) / 1000,
        'We’ve sent this email 3 times today.',
      )
    }
    queueConfirmation(ctx.db, submission)
    return accepted(trackedSubmission(ctx.db, submission))
  }),

  publicRoute('post', '/public/track/erase', async (ctx) => {
    const { submission } = await tracked(ctx)
    eraseSubmission(ctx.db, submission, null)
    const idea = ctx.db.ideas.find((i) => i.id === submission.idea_id)
    recordAudit(
      ctx.db,
      null,
      'submission.erase',
      { type: 'idea', id: submission.idea_id },
      { reason: 'submitter' },
      idea?.project_id ?? null,
    )
    return noContent()
  }),

  publicRoute('post', '/public/verify-email', async (ctx) => {
    requireJson(ctx)
    const body = await readJson(ctx.request)
    allowOnly(body, ['token'])
    const token = tokenField(body, VERIFICATION_TOKEN)
    const submission = submissionByConfirmationToken(ctx.db, token)
    if (!submission) notFound('This link has expired or isn’t valid.')
    if (!submission.email_verified_at) {
      submission.email_verified_at = new Date().toISOString()
      const idea = ctx.db.ideas.find((i) => i.id === submission.idea_id)
      if (idea?.held_for === 'email_verification') {
        const project = ctx.db.projects.find((p) => p.id === idea.project_id)
        idea.held_for =
          project && publicFormOf(ctx.db, project).moderation_required ? 'moderation' : null
        idea.last_activity_at = new Date().toISOString()
        if (!idea.held_for) submission.reached_team_at = idea.last_activity_at
      }
    }
    return emailVerified(ctx.db, submission)
  }),
]
