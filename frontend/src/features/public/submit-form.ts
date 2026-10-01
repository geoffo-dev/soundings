import { isApiError } from '@/api/errors'
import type { PublicProject, PublicSubmissionCreate } from '@/api/types'

/**
 * The public form's fields, checks and request body (contract-phase4 §3.5).
 * Only title and summary are required; the honeypot (`website`) is sent as
 * typed (a person never sees or fills it).
 */

export interface PublicForm {
  title: string
  summary: string
  description: string
  name: string
  email: string
  wantsUpdates: boolean
  /** The honeypot's value (input `hp_ref`, sent as `website`). */
  honeypot: string
}

export const EMPTY_PUBLIC_FORM: PublicForm = {
  title: '',
  summary: '',
  description: '',
  name: '',
  email: '',
  wantsUpdates: false,
  honeypot: '',
}

export const PUBLIC_LIMITS = { title: 200, summary: 500, description: 10_000, name: 80, email: 254 }

export type PublicField = 'title' | 'summary' | 'description' | 'name' | 'email'
export type PublicErrors = Partial<Record<PublicField, string>>

/** In the order the fields appear (focus goes to the first error). */
export const PUBLIC_FIELDS: PublicField[] = ['title', 'summary', 'description', 'name', 'email']

// One plain address (the API's MailAddress), with a dot in the domain.
const EMAIL =
  /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/

export function isEmailAddress(value: string): boolean {
  const email = value.trim()
  return (
    email.length >= 3 &&
    email.length <= PUBLIC_LIMITS.email &&
    EMAIL.test(email) &&
    !email.toLowerCase().endsWith('.invalid')
  )
}

type FormRules = Pick<PublicProject, 'asks_for_email' | 'email_required'>

export function validatePublicForm(form: PublicForm, project: FormRules): PublicErrors {
  const errors: PublicErrors = {}
  const title = form.title.trim()
  if (!title) errors.title = 'Give your idea a short title.'
  else if (title.length > PUBLIC_LIMITS.title) {
    errors.title = `Use at most ${PUBLIC_LIMITS.title} characters.`
  }
  const summary = form.summary.trim()
  if (!summary) errors.summary = 'Say in a sentence or two what your idea is.'
  else if (summary.length > PUBLIC_LIMITS.summary) {
    errors.summary = `Use at most ${PUBLIC_LIMITS.summary} characters.`
  }
  if (form.description.length > PUBLIC_LIMITS.description) {
    errors.description = `Use at most ${PUBLIC_LIMITS.description.toLocaleString('en')} characters.`
  }
  if (form.name.trim().length > PUBLIC_LIMITS.name) {
    errors.name = `Use at most ${PUBLIC_LIMITS.name} characters.`
  }
  if (project.asks_for_email) {
    const email = form.email.trim()
    if (!email && project.email_required) {
      errors.email = 'Enter your email address: we send you a link to confirm your idea.'
    } else if (email && !isEmailAddress(email)) {
      errors.email = 'Enter an email address like name@example.com.'
    } else if (!email && form.wantsUpdates) {
      errors.email = 'Add your email address to get updates, or untick the box below.'
    }
  }
  return errors
}

/** The request body. Without email on the instance, neither address nor opt-in is sent. */
export function toSubmission(
  form: PublicForm,
  project: FormRules,
  altcha: string,
): PublicSubmissionCreate {
  const email = project.asks_for_email ? form.email.trim() : ''
  return {
    title: form.title.trim(),
    summary: form.summary.trim(),
    description_md: form.description.trim(),
    name: form.name.trim() || null,
    email: email || null,
    wants_updates: Boolean(email) && form.wantsUpdates,
    altcha,
    website: form.honeypot,
  }
}

/** "180/200 characters" once a field gets close to its limit (limits appear only when they matter). */
export function nearLimit(value: string, limit: number): string | undefined {
  return value.length >= limit * 0.8
    ? `${value.length.toLocaleString('en')}/${limit.toLocaleString('en')} characters`
    : undefined
}

/** What went wrong with a submission, for the form to show. */
export type SubmitProblem =
  | { kind: 'fields'; errors: PublicErrors }
  | { kind: 'rate_limited' }
  | { kind: 'challenge' }
  | { kind: 'unavailable' }
  | { kind: 'network' }
  | { kind: 'other' }

const SERVER_FIELDS: Record<string, PublicField> = {
  title: 'title',
  summary: 'summary',
  description_md: 'description',
  name: 'name',
  email: 'email',
  wants_updates: 'email',
}

export function submitProblem(error: unknown): SubmitProblem {
  if (!isApiError(error)) return { kind: 'other' }
  if (error.isNetworkError) return { kind: 'network' }
  if (error.status === 404) return { kind: 'unavailable' }
  if (error.status === 429) return { kind: 'rate_limited' }
  if (error.code === 'challenge_failed') return { kind: 'challenge' }
  if (error.code === 'email_required') {
    return {
      kind: 'fields',
      errors: { email: 'Enter your email address: we send you a link to confirm your idea.' },
    }
  }
  if (error.status === 422) {
    const errors: PublicErrors = {}
    for (const entry of error.problem?.errors ?? []) {
      const loc = entry.loc.map(String)
      const field = SERVER_FIELDS[loc.at(-1) ?? ''] ?? (loc.includes('altcha') ? null : undefined)
      if (field === null) return { kind: 'challenge' }
      if (field && !errors[field]) errors[field] = sentence(entry.msg)
    }
    if (Object.keys(errors).length > 0) return { kind: 'fields', errors }
  }
  return { kind: 'other' }
}

function sentence(message: string): string {
  const text = message.replace(/^Value error, /, '').trim()
  if (!text) return 'Check this field.'
  const capital = text.charAt(0).toUpperCase() + text.slice(1)
  return /[.!?]$/.test(capital) ? capital : `${capital}.`
}
