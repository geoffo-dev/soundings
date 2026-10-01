import type { AuditFilters } from '@/api/admin'
import type { AuditTargetType } from '@/api/types'
import { searchList, searchString } from '@/lib/search-params'

import { actionsFor, AUDIT_CATEGORY_IDS, type AuditCategory } from './audit-categories'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const DATE = /^\d{4}-\d{2}-\d{2}$/
const TARGET_TYPES: AuditTargetType[] = ['user', 'project', 'idea', 'group']

/**
 * `/settings/audit?actor=<user id>&action=sign_ins,denied&project=<id>&from=2026-09-01&to=2026-09-30&target=user:<id>`
 * (defaults dropped; unknown values ignored). Dates are whole days in the
 * viewer's time zone, both inclusive.
 */
export interface AuditSearch {
  actor?: string
  action?: AuditCategory[]
  project?: string
  from?: string
  to?: string
  /** `<type>:<id>`: entries about one user, group, project or idea. */
  target?: string
}

function uuid(value: unknown): string | undefined {
  const text = searchString(value, 36)
  return text && UUID.test(text) ? text.toLowerCase() : undefined
}

function date(value: unknown): string | undefined {
  const text = searchString(value, 10)
  return text && DATE.test(text) && !Number.isNaN(Date.parse(`${text}T00:00:00`)) ? text : undefined
}

export function parseTarget(
  value: string | undefined,
): { type: AuditTargetType; id: string } | undefined {
  if (!value) return undefined
  const [type, id] = value.split(':')
  if (!TARGET_TYPES.includes(type as AuditTargetType) || !id || !UUID.test(id)) return undefined
  return { type: type as AuditTargetType, id: id.toLowerCase() }
}

export function validateAuditSearch(search: Record<string, unknown>): AuditSearch {
  const target = parseTarget(searchString(search.target, 60))
  return {
    actor: uuid(search.actor),
    action: searchList(search.action, AUDIT_CATEGORY_IDS),
    project: uuid(search.project),
    from: date(search.from),
    to: date(search.to),
    target: target ? `${target.type}:${target.id}` : undefined,
  }
}

/** Local midnight of `YYYY-MM-DD` plus `days`, as an ISO instant (UTC). */
export function localDayStart(day: string, days = 0): string {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days).toISOString()
}

/** The URL state as `list_audit_entries` filters (`until` exclusive: the day after "to"). */
export function toAuditFilters(search: AuditSearch): AuditFilters {
  const target = parseTarget(search.target)
  const actions = actionsFor(search.action)
  return {
    actor_id: search.actor,
    action: actions.length ? actions : undefined,
    project_id: search.project,
    target_type: target?.type,
    target_id: target?.id,
    since: search.from ? localDayStart(search.from) : undefined,
    until: search.to ? localDayStart(search.to, 1) : undefined,
  }
}

export function hasAuditFilters(search: AuditSearch): boolean {
  return (
    [search.actor, search.project, search.from, search.to, search.target].some(Boolean) ||
    Boolean(search.action?.length)
  )
}

/** `YYYY-MM-DD` of the viewer's local day `offset` days from `now`. */
export function localDay(now: number, offset = 0): string {
  const date = new Date(now)
  date.setDate(date.getDate() + offset)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Quick ranges in the "When" filter: the last N days, today included. */
export const DATE_PRESETS = [
  { label: 'Today', days: 1 },
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
] as const

/** The preset's `from` (open-ended: no `to`). */
export function presetFrom(days: number, now: number): string {
  return localDay(now, -(days - 1))
}

/** The preset a range is, if any (so the chip says "Last 7 days", not "From 25 Sept"). */
export function matchingPreset(
  from: string | undefined,
  to: string | undefined,
  now: number,
): (typeof DATE_PRESETS)[number] | undefined {
  if (!from || (to && to !== localDay(now))) return undefined
  return DATE_PRESETS.find((preset) => presetFrom(preset.days, now) === from)
}
