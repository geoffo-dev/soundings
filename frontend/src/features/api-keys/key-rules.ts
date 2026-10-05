import type { ApiKeyScope } from '@/api/types'

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
    label: 'MCP',
    description:
      'Connect an MCP client, such as an AI assistant, at /mcp. On its own it can’t do anything: its tools also need Read, Write or Evaluate.',
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
    label: 'MCP client',
    scopes: ['read', 'mcp'],
    description: 'An AI assistant that searches and reads ideas for you.',
  },
  {
    value: 'evaluator',
    label: 'AI evaluator',
    scopes: ['read', 'evaluate', 'mcp'],
    description: 'An assistant that also submits your evaluations.',
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
