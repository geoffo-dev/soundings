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
