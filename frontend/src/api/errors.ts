import type { ValidationProblem } from '@/api/types'

/**
 * The API reports failures as RFC 9457 problem+json. Every non-2xx response is
 * turned into an ApiError, so UI code can rely on `status`, `code`, `title`.
 *
 * The body is the contract's `Problem` (or `ValidationProblem` with field `errors`,
 * `loc` + `msg`). Every field is optional: a proxy or gateway in front of the API
 * may answer with no body or a different one.
 */
export type ProblemDetails = Partial<ValidationProblem>

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly title: string
  readonly detail: string | undefined
  readonly problem: ProblemDetails | undefined
  /** From a 429's `Retry-After` header: seconds until trying again makes sense. */
  readonly retryAfterSeconds: number | undefined

  constructor(init: {
    status: number
    code: string
    title: string
    detail?: string
    problem?: ProblemDetails
    retryAfterSeconds?: number
  }) {
    super(init.detail ?? init.title)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.title = init.title
    this.detail = init.detail
    this.problem = init.problem
    this.retryAfterSeconds = init.retryAfterSeconds
  }

  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500
  }

  /** Network failure / no response. */
  get isNetworkError(): boolean {
    return this.status === 0
  }

  /**
   * Field errors of a 422 keyed by the last `loc` segment, e.g.
   * `{ title: 'Field required' }` — for inline form errors.
   */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const entry of this.problem?.errors ?? []) {
      const field = entry.loc.at(-1)
      if (field !== undefined && entry.msg && !(String(field) in out)) {
        out[String(field)] = entry.msg
      }
    }
    return out
  }
}

/** True for an ApiError with one of the given `code`s. */
export function hasErrorCode(error: unknown, ...codes: string[]): error is ApiError {
  return isApiError(error) && codes.includes(error.code)
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const str = (value: unknown): string | undefined => (typeof value === 'string' ? value : undefined)

/** Builds an ApiError from a failed response. Reads the body; call on a clone if you need it again. */
export async function toApiError(response: Response): Promise<ApiError> {
  let problem: ProblemDetails | undefined
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('json')) {
    try {
      const body: unknown = await response.json()
      if (isRecord(body)) problem = body
    } catch {
      problem = undefined
    }
  }
  const title = str(problem?.title) ?? (response.statusText || defaultTitle(response.status))
  return new ApiError({
    status: response.status,
    code: str(problem?.code) ?? codeFromType(problem?.type) ?? `http_${response.status}`,
    title,
    detail: str(problem?.detail),
    problem,
    retryAfterSeconds: parseRetryAfter(response.headers.get('retry-after')),
  })
}

/** `Retry-After` is either seconds or an HTTP date (RFC 9110 §10.2.3). */
export function parseRetryAfter(
  value: string | null,
  now: number = Date.now(),
): number | undefined {
  if (!value) return undefined
  const trimmed = value.trim()
  if (/^\d+$/.test(trimmed)) return Number(trimmed)
  const at = Date.parse(trimmed)
  return Number.isNaN(at) ? undefined : Math.max(0, Math.ceil((at - now) / 1000))
}

export function networkError(cause: unknown): ApiError {
  const error = new ApiError({
    status: 0,
    code: 'network_error',
    title: 'Can’t reach the server',
    detail: 'Check your connection and try again.',
  })
  error.cause = cause
  return error
}

/**
 * Friendly copy for the documented error codes (contract §4). The API's own
 * `detail` is used when a code has no entry here.
 */
const ERROR_COPY: Record<string, { title: string; description?: string }> = {
  forbidden: {
    title: 'You can’t do that here',
    description: 'Ask a project admin if you need to.',
  },
  csrf_failed: {
    title: 'Your session needs a refresh',
    description: 'Reload the page and try again.',
  },
  not_submitter: {
    title: 'Only the submitter or owner can edit this idea',
  },
  not_author: { title: 'You can only change your own comments' },
  volunteering_disabled: {
    title: 'Volunteering is turned off',
    description: 'A project admin assigns owners in this project.',
  },
  cannot_remove_self: {
    title: 'You can’t remove yourself',
    description: 'Submit your evaluation, or ask the owner to remove you.',
  },
  not_found: { title: 'This no longer exists', description: 'It may have been deleted.' },
  project_archived: {
    title: 'This project is archived',
    description: 'Archived projects are read-only.',
  },
  idea_not_new: {
    title: 'This idea is no longer new',
    description: 'Only its owner or an admin can edit it now.',
  },
  idea_closed: { title: 'This idea is closed', description: 'Reopen it to make changes.' },
  idea_has_owner: { title: 'Someone already owns this idea' },
  evaluation_closed: {
    title: 'Evaluation is closed',
    description: 'The owner can reopen evaluation if needed.',
  },
  evaluation_already_submitted: {
    title: 'Already submitted',
    description: 'Submitted evaluations can be edited but not turned back into drafts.',
  },
  evaluator_has_submitted: {
    title: 'This evaluator has already submitted',
    description: 'Submitted evaluations are kept.',
  },
  assignee_not_eligible: {
    title: 'That person can’t be assigned',
    description: 'Owners and evaluators need a member or admin role in the project.',
  },
  user_not_found: { title: 'We couldn’t find that person' },
  slug_taken: { title: 'That URL name is taken' },
  key_taken: { title: 'That idea key is taken' },
  already_member: { title: 'Already a member' },
  last_admin: {
    title: 'A project needs at least one admin',
    description: 'Make someone else an admin first, directly or through a group.',
  },
  evaluation_incomplete: {
    title: 'Some scores are missing',
    description: 'Score every criterion and choose a recommendation to submit.',
  },
  // Phase 2: sign-in and access (contract-phase2 §4.1)
  invalid_credentials: {
    title: 'That username and password don’t match',
    description: 'Check both and try again.',
  },
  account_disabled: {
    title: 'This account is deactivated',
    description: 'Another platform admin can reactivate it.',
  },
  too_many_attempts: {
    title: 'Too many attempts',
    description: 'Wait a few minutes, then try again.',
  },
  cannot_change_self: {
    title: 'You can’t change that for yourself',
    description: 'Ask another platform admin to deactivate you or remove your admin rights.',
  },
  email_taken: { title: 'Someone already has that email address' },
  external_id_taken: {
    title: 'Another person already has that external ID',
    description: 'Each external ID belongs to one person.',
  },
  group_name_taken: { title: 'A group with that name already exists' },
  already_granted: {
    title: 'That group already has a role here',
    description: 'Change its role in the list instead.',
  },
  group_not_found: {
    title: 'We couldn’t find that group',
    description: 'It may have been deleted.',
  },
  last_platform_admin: {
    title: 'Soundings needs a platform admin',
    description: 'Make someone else a platform admin first.',
  },
  // The server's detail says what (an agent is never a project admin; service and
  // break-glass accounts keep their email and platform-admin role).
  system_account: { title: 'System accounts can’t be changed like this' },
  // Phase 3: email and notifications (contract-phase3 §4)
  too_many_mentions: {
    title: 'Too many people mentioned',
    description: 'Mention at most 20 people in one comment.',
  },
  smtp_not_configured: {
    title: 'Email isn’t set up',
    description: 'Set smtp.host and smtp.from in the Helm values first.',
  },
  email_not_retryable: {
    title: 'This email can’t be retried',
    description: 'Only failed emails from the last few days can be sent again.',
  },
  // Phase 4: proposals (contract-phase4 §4)
  proposal_not_available: {
    title: 'The proposal is read-only now',
    description: 'Proposals can be edited while the idea is Shortlisted or in Proposal.',
  },
  proposal_exists: { title: 'This idea already has a proposal' },
  proposal_conflict: {
    title: 'Someone else changed this section',
    description: 'Compare their version with yours, then choose one.',
  },
  too_many_comments: {
    title: 'This proposal can’t take more comments',
    description: 'Resolve or delete some threads first.',
  },
  awaiting_moderation: {
    title: 'This idea is waiting for review',
    description: 'Approve it first to make changes.',
  },
  export_busy: {
    title: 'The PDF export is busy',
    description: 'Try again in a few seconds.',
  },
  // Phase 4: public submission, moderation and branding (contract-phase4 §4)
  public_submission_unavailable: {
    title: 'Public forms aren’t available for this project',
    description:
      'They are turned off for this Soundings instance, or the project’s address is reserved.',
  },
  not_awaiting_moderation: {
    title: 'This idea isn’t waiting for review any more',
    description: 'Someone may have approved or rejected it already.',
  },
  challenge_failed: {
    title: 'We couldn’t verify this browser',
    description: 'Try again.',
  },
  email_required: { title: 'This form needs your email address' },
  no_email: { title: 'There’s no email address for this idea' },
  already_verified: { title: 'This email address is already confirmed' },
  unsupported_media_type: {
    title: 'The form couldn’t be read',
    description: 'Reload the page and try again.',
  },
  content_too_large: { title: 'That is too large to send' },
  invalid_image: {
    title: 'That image can’t be used',
    description: 'Upload a PNG or SVG file.',
  },
  invalid_asset: {
    title: 'That image can’t be used here',
    description: 'Upload it again, then save.',
  },
  // Phase 5: API keys and proposal suggestions (contract-phase5 §5)
  insufficient_scope: {
    title: 'An API key can’t do that',
    description: 'Sign in to Soundings to do this yourself.',
  },
  break_glass_account: {
    title: 'The break-glass account can’t create API keys',
    description: 'Sign in with your own account to create one.',
  },
  too_many_api_keys: {
    title: 'You have 25 API keys',
    description: 'Revoke keys you no longer use, then create a new one.',
  },
  api_key_name_taken: {
    title: 'You already have a key with this name',
    description: 'Choose another name, or revoke the old key first.',
  },
  invalid_project: {
    title: 'You can’t restrict a key to that project',
    description: 'Choose projects you can open in Soundings.',
  },
  too_many_suggestions: {
    title: 'This proposal has 50 suggestions waiting',
    description: 'Accept or discard some of them first.',
  },
  suggestion_not_pending: {
    title: 'Someone already decided on this suggestion',
    description: 'It was accepted or discarded a moment ago.',
  },
  network_error: { title: 'Can’t reach the server', description: 'Check your connection.' },
}

/** Title and description to show for any thrown error (toasts, inline alerts). */
export function describeError(error: unknown): { title: string; description?: string } {
  if (!isApiError(error)) {
    return { title: 'Something went wrong', description: 'Please try again.' }
  }
  const copy = ERROR_COPY[error.code]
  if (copy) return { title: copy.title, description: copy.description ?? error.detail }
  // A server error's title is an HTTP reason ("Internal Server Error") and its detail
  // is meant for logs: say what it means for the person instead.
  if (error.status >= 500) {
    return {
      title: defaultTitle(error.status),
      description: 'Try again in a moment. If it keeps happening, let an admin know.',
    }
  }
  return { title: error.title, description: error.detail }
}

function codeFromType(type: string | undefined): string | undefined {
  if (!type || type === 'about:blank') return undefined
  return type.split('/').filter(Boolean).pop()
}

function defaultTitle(status: number): string {
  if (status === 401) return 'You need to sign in'
  if (status === 403) return 'You don’t have access to this'
  if (status === 404) return 'Not found'
  if (status === 409) return 'This was changed by someone else'
  if (status === 422) return 'Some fields need attention'
  if (status >= 500) return 'Something went wrong on our side'
  return 'Request failed'
}
