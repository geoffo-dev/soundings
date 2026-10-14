/**
 * Days in a named time zone (IANA, e.g. "Europe/London"). Phase 10's call deadlines and
 * assessment due dates are days in the **instance's** time zone, "by the end of that day"
 * (contract-phase10 §3.2, UX review M6): the emails, reminders and the report count them
 * there, so the SPA picks, sends and shows them there too, whatever the browser's zone.
 *
 *   browserTimeZone()                    "Europe/Paris"
 *   validTimeZone(zone)                  the zone if Intl knows it, else undefined
 *   zonedParts(iso, zone)                { year, month, day, hour, minute }
 *   toZonedDateInput(iso, zone)          "2026-10-24" (a date input's value)
 *   endOfZonedDay("2026-10-24", zone)    the ISO moment of 23:59 that day in the zone
 */

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

const known = new Map<string, boolean>()

/** The zone when this browser's Intl knows it, else undefined (the caller falls back). */
export function validTimeZone(zone: string | null | undefined): string | undefined {
  if (!zone) return undefined
  let ok = known.get(zone)
  if (ok === undefined) {
    try {
      new Intl.DateTimeFormat('en', { timeZone: zone })
      ok = true
    } catch {
      ok = false
    }
    known.set(zone, ok)
  }
  return ok ? zone : undefined
}

export interface ZonedParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
}

const formatters = new Map<string, Intl.DateTimeFormat>()

function partsFormatter(zone: string): Intl.DateTimeFormat {
  let formatter = formatters.get(zone)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone: zone,
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      hourCycle: 'h23',
    })
    formatters.set(zone, formatter)
  }
  return formatter
}

/** The wall-clock date and time of a moment in `zone`. */
export function zonedParts(value: string | number | Date, zone: string): ZonedParts {
  const date = value instanceof Date ? value : new Date(value)
  const parts: Partial<Record<Intl.DateTimeFormatPartTypes, number>> = {}
  for (const part of partsFormatter(zone).formatToParts(date)) {
    if (part.type !== 'literal') parts[part.type] = Number(part.value)
  }
  return {
    year: parts.year ?? 1970,
    month: parts.month ?? 1,
    day: parts.day ?? 1,
    // Some engines say 24 for midnight even with h23.
    hour: (parts.hour ?? 0) % 24,
    minute: parts.minute ?? 0,
  }
}

const pad = (n: number) => String(n).padStart(2, '0')

/** The calendar day of a moment in `zone` as `YYYY-MM-DD`; '' for none or an invalid one. */
export function toZonedDateInput(iso: string | null | undefined, zone: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const { year, month, day } = zonedParts(date, zone)
  return `${year}-${pad(month)}-${pad(day)}`
}

/** Minutes `zone` is ahead of UTC at `utcMillis`. */
function offsetMinutes(utcMillis: number, zone: string): number {
  const p = zonedParts(utcMillis, zone)
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute)
  return Math.round((asUtc - Math.floor(utcMillis / 60_000) * 60_000) / 60_000)
}

/**
 * `YYYY-MM-DD` → 23:59 of that day in `zone`, as an ISO moment (UTC); null for '' or an
 * invalid day. DST-safe: the offset is read again at the result.
 */
export function endOfZonedDay(value: string, zone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const [, y, m, d] = match
  const year = Number(y)
  const month = Number(m)
  const day = Number(d)
  const wall = Date.UTC(year, month - 1, day, 23, 59)
  const check = new Date(wall)
  if (check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null
  let guess = wall - offsetMinutes(wall, zone) * 60_000
  // Across a DST change the offset at the answer can differ from the first guess.
  guess = wall - offsetMinutes(guess, zone) * 60_000
  return new Date(guess).toISOString()
}
