/**
 * The API reports failures as RFC 9457 problem+json. Every non-2xx response is
 * turned into an ApiError, so UI code can rely on `status`, `code`, `title`.
 */
export interface ProblemDetails {
  type?: string
  title?: string
  status?: number
  detail?: string
  instance?: string
  /** Stable machine-readable error code, e.g. "evaluation_closed". */
  code?: string
  /** Field-level validation messages, if any. */
  errors?: { field?: string; loc?: (string | number)[]; message?: string; msg?: string }[]
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly title: string
  readonly detail: string | undefined
  readonly problem: ProblemDetails | undefined

  constructor(init: {
    status: number
    code: string
    title: string
    detail?: string
    problem?: ProblemDetails
  }) {
    super(init.detail ?? init.title)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.title = init.title
    this.detail = init.detail
    this.problem = init.problem
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
      const field = entry.field ?? entry.loc?.[entry.loc.length - 1]
      const message = entry.message ?? entry.msg
      if (field !== undefined && message && !(String(field) in out)) out[String(field)] = message
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
  })
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
    description: 'Make someone else an admin first.',
  },
  evaluation_incomplete: {
    title: 'Some scores are missing',
    description: 'Score every criterion and choose a recommendation to submit.',
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
