import type { ApiKeyScope } from '@/api/types'
import { formatDate } from '@/lib/dates'

/**
 * The words and the small rules of API keys in the SPA (contract-phase5 §3.1,
 * §3.10): what each scope means, the presets, how ticking `write` or
 * `evaluate` includes `read`, and the expiry choices. The API enforces all of
 * it again; this only keeps the form honest.
 */

export const SCOPES: readonly ApiKeyScope[] = ['read', 'write', 'evaluate', 'mcp']

export const SCOPE_COPY: Record<ApiKeyScope, { label: string; description: string }> = {
  read: {
    label: 'Read',
    description: 'See projects, ideas, evaluations, scores and proposals, as you can.',
  },
  write: {
    label: 'Write',
    description:
      'Create and change ideas, comments, owners, evaluators, statuses and proposals. Deleting and moderating ideas still need you signed in.',
  },
  evaluate: {
    label: 'Evaluate',
    description: 'Save and submit your own evaluations, blind like in the app.',
  },
  mcp: {
    label: 'AI assistants (MCP)',
    description:
      'Lets an AI assistant, such as Claude, connect with this key. On its own it can’t do anything: the assistant also needs Read, Write or Evaluate.',
  },
}

/** Scopes that include `read` (their answers contain readable data). */
const INCLUDES_READ: readonly ApiKeyScope[] = ['write', 'evaluate']

/** Distinct scopes in canonical order, with `read` added to `write` and `evaluate`. */
export function canonicalScopes(scopes: Iterable<ApiKeyScope>): ApiKeyScope[] {
  const wanted = new Set(scopes)
  if (INCLUDES_READ.some((scope) => wanted.has(scope))) wanted.add('read')
  return SCOPES.filter((scope) => wanted.has(scope))
}

/** `read` is ticked and locked ("Included") while `write` or `evaluate` is ticked. */
export function readIsIncluded(scopes: readonly ApiKeyScope[]): boolean {
  return INCLUDES_READ.some((scope) => scopes.includes(scope))
}

/** Ticks or unticks one scope; `read` can't be unticked while it is included. */
export function toggleScope(
  scopes: readonly ApiKeyScope[],
  scope: ApiKeyScope,
  on: boolean,
): ApiKeyScope[] {
  if (scope === 'read' && !on && readIsIncluded(scopes)) return canonicalScopes(scopes)
  const next = new Set(scopes)
  if (on) next.add(scope)
  else next.delete(scope)
  return canonicalScopes(next)
}

/** An `mcp` key with nothing for its tools to use (allowed, but say so). */
export function mcpWithoutTools(scopes: readonly ApiKeyScope[]): boolean {
  return scopes.includes('mcp') && scopes.length === 1
}

export type ScopePreset = 'read' | 'mcp' | 'evaluator' | 'full'

export const SCOPE_PRESETS: readonly {
  value: ScopePreset
  label: string
  scopes: readonly ApiKeyScope[]
  description: string
}[] = [
  {
    value: 'read',
    label: 'Read only',
    scopes: ['read'],
    description: 'Scripts and reports that only look.',
  },
  {
    value: 'mcp',
    label: 'Read with an assistant',
    scopes: ['read', 'mcp'],
    description: 'An AI assistant that searches and reads ideas for you.',
  },
  {
    // Not SPEC §9's AI evaluator (a service account, left out of the aggregate): yours.
    value: 'evaluator',
    label: 'Evaluate with an assistant',
    scopes: ['read', 'evaluate', 'mcp'],
    description: 'An assistant that also submits evaluations as you: they count as yours.',
  },
  {
    value: 'full',
    label: 'Full access',
    scopes: ['read', 'write', 'evaluate', 'mcp'],
    description: 'Everything you can do, except what needs you signed in.',
  },
]

/** The preset these scopes are exactly, if any. */
export function presetOf(scopes: readonly ApiKeyScope[]): ScopePreset | null {
  const key = canonicalScopes(scopes).join(',')
  return SCOPE_PRESETS.find((preset) => preset.scopes.join(',') === key)?.value ?? null
}

/* ------------------------------------------------------------------ */
/* Expiry                                                              */
/* ------------------------------------------------------------------ */

export type ExpiryChoice = '30d' | '90d' | '1y' | 'never' | 'date'

export const EXPIRY_CHOICES: readonly { value: ExpiryChoice; label: string }[] = [
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '1y', label: '1 year' },
  { value: 'never', label: 'Never' },
  { value: 'date', label: 'Date' },
]

const DAY_MS = 86_400_000
const PRESET_DAYS: Record<'30d' | '90d' | '1y', number> = { '30d': 30, '90d': 90, '1y': 365 }

/** `YYYY-MM-DD` of a local date. */
export function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** The dates a custom expiry may take: tomorrow to a year from today (local days). */
export function expiryDateBounds(now = new Date()): { min: string; max: string } {
  const min = new Date(now)
  min.setDate(min.getDate() + 1)
  const max = new Date(now)
  max.setDate(max.getDate() + 365)
  return { min: isoDay(min), max: isoDay(max) }
}

/**
 * The `expires_at` to send: null for never, now + the preset's days, or the
 * end of the chosen local day. `undefined` when the date is missing or out of
 * bounds (the form says so).
 */
export function expiresAt(
  choice: ExpiryChoice,
  date: string,
  now = new Date(),
): string | null | undefined {
  if (choice === 'never') return null
  if (choice !== 'date') return new Date(now.getTime() + PRESET_DAYS[choice] * DAY_MS).toISOString()
  const { min, max } = expiryDateBounds(now)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date < min || date > max) return undefined
  const [year, month, day] = date.split('-').map(Number)
  const end = new Date(year ?? 0, (month ?? 1) - 1, day ?? 1, 23, 59, 0, 0)
  return Number.isNaN(end.getTime()) ? undefined : end.toISOString()
}

/* ------------------------------------------------------------------ */
/* What a key can do, in plain words (the create dialog, rows, the key) */
/* ------------------------------------------------------------------ */

/**
 * The scopes as short plain words for a list ("Read and evaluate"), with
 * `assistants` when AI assistants may use it too and `changes` when it can
 * change anything (write or evaluate: the riskier keys read stronger).
 */
export function accessLabel(scopes: readonly ApiKeyScope[]): {
  label: string
  assistants: boolean
  changes: boolean
} {
  const has = (scope: ApiKeyScope) => scopes.includes(scope)
  const write = has('write')
  const evaluate = has('evaluate')
  const label = !has('read')
    ? 'Nothing yet'
    : write && evaluate
      ? 'Read, change and evaluate'
      : write
        ? 'Read and change'
        : evaluate
          ? 'Read and evaluate'
          : 'Read only'
  return { label, assistants: has('mcp'), changes: write || evaluate }
}

/** What the key lets its holder do, completing "can …" ("read everything you can see"). */
export function abilitiesPhrase(scopes: readonly ApiKeyScope[]): string {
  const has = (scope: ApiKeyScope) => scopes.includes(scope)
  if (!has('read'))
    return has('mcp') ? 'connect an AI assistant, but do nothing else' : 'do nothing yet'
  const parts = ['read everything you can see']
  if (has('write')) parts.push('change ideas, comments and proposals')
  if (has('evaluate')) parts.push('submit your evaluations')
  const last = parts.pop() ?? ''
  const joined = parts.length
    ? `${parts.join(', ')}${parts.length > 1 ? ',' : ''} and ${last}`
    : last
  return has('mcp') ? `${joined}, also through AI assistants` : joined
}

/** Where: "in every project you can open", "only in Customer Innovation", "only in 3 projects". */
export function projectsPhrase(
  restricted: boolean,
  projects: readonly { name: string }[],
  none = 'in no project',
): string {
  if (!restricted) return 'in every project you can open'
  if (projects.length === 0) return none
  if (projects.length === 1) return `only in ${projects[0]?.name ?? ''}`
  if (projects.length === 2)
    return `only in ${projects[0]?.name ?? ''} and ${projects[1]?.name ?? ''}`
  return `only in ${String(projects.length)} projects`
}

/** Until when: "until you revoke it" or "until Wed 5 Nov or until you revoke it". */
export function untilPhrase(expiresAt: string | null | undefined, now = new Date()): string {
  if (expiresAt === undefined) return 'until the date you choose'
  if (expiresAt === null) return 'until you revoke it'
  return `until ${formatDate(expiresAt, { now })} or until you revoke it`
}

/**
 * The whole plain summary, e.g. "read everything you can see and submit your
 * evaluations, also through AI assistants, only in Customer Innovation, until
 * Wed 5 Nov or until you revoke it" (after "This key can" or "anyone who has
 * it can act as you:").
 */
export function accessSummary(
  key: {
    scopes: readonly ApiKeyScope[]
    restricted: boolean
    projects: readonly { name: string }[]
    expires_at: string | null | undefined
  },
  { now = new Date(), noProjects }: { now?: Date; noProjects?: string } = {},
): string {
  return `${abilitiesPhrase(key.scopes)}, ${projectsPhrase(key.restricted, key.projects, noProjects)}, ${untilPhrase(key.expires_at, now)}`
}

/** Within this long of its expiry a key's date turns into "in 2 days", in a warning tone. */
export const EXPIRY_WARNING_MS = 7 * DAY_MS

/** Whether an active key expires soon (within 7 days). */
export function expiresSoon(expiresAt: string | null, now = Date.now()): boolean {
  if (!expiresAt) return false
  const left = new Date(expiresAt).getTime() - now
  return left > 0 && left <= EXPIRY_WARNING_MS
}
