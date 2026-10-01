/**
 * The one place dates are formatted. Everything is locale-aware (Intl, the
 * browser's language) and takes an optional `now` so it is easy to test.
 *
 *   formatRelative(iso)      "5 minutes ago", "yesterday", then "12 Sept"
 *   formatRelative(iso, { style: 'narrow' })   "5m ago" (dense tables)
 *   formatDate(iso)          "Fri 3 Oct" (+ year when not this year)
 *   formatDateTime(iso)      "Friday, 3 October 2026 at 15:20" (tooltips, title attributes)
 *   formatTime(iso)          "15:20" today, else "12 Sept" (e.g. "Draft saved 15:20")
 *   dueDate(iso)             { label: "Due tomorrow" | "Overdue 2 days" | …, tone }
 *
 * UI code renders times with <RelativeTime> (components/ui/relative-time.tsx),
 * which adds the absolute date as a tooltip and keeps itself up to date.
 */

export type DateInput = string | number | Date

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

let cachedLocale: { raw: string; locale: string | undefined } | undefined

/**
 * The browser's language as a valid BCP 47 tag, or undefined (Intl's default).
 * Some environments report tags Intl rejects (e.g. "en-US@posix").
 */
export function currentLocale(): string | undefined {
  if (typeof navigator === 'undefined') return undefined
  const raw = navigator.language
  if (cachedLocale?.raw === raw) return cachedLocale.locale
  let locale: string | undefined
  try {
    locale = Intl.getCanonicalLocales(raw)[0]
  } catch {
    try {
      locale = Intl.getCanonicalLocales(raw.split(/[@.]/)[0] ?? '')[0]
    } catch {
      locale = undefined
    }
  }
  cachedLocale = { raw, locale }
  return locale
}

function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value)
}

/** Whole calendar days from `from` to `to` in local time (DST-safe). */
export function calendarDaysBetween(from: DateInput, to: DateInput): number {
  const a = toDate(from)
  const b = toDate(to)
  const startA = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())
  const startB = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate())
  return Math.round((startB - startA) / DAY)
}

export interface FormatOptions {
  now?: DateInput
  locale?: string
}

/** "Fri 3 Oct" — with the year when it isn't the current year. */
export function formatDate(
  value: DateInput,
  { now = Date.now(), locale = currentLocale() }: FormatOptions = {},
) {
  const date = toDate(value)
  const sameYear = date.getFullYear() === toDate(now).getFullYear()
  return new Intl.DateTimeFormat(locale, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  }).format(date)
}

/** "3 Oct" / "3 Oct 2025" — compact, no weekday (lists). */
export function formatShortDate(
  value: DateInput,
  { now = Date.now(), locale = currentLocale() }: FormatOptions = {},
) {
  const date = toDate(value)
  const sameYear = date.getFullYear() === toDate(now).getFullYear()
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  }).format(date)
}

/** Full date and time for tooltips and `title` attributes. */
export function formatDateTime(
  value: DateInput,
  { locale = currentLocale() }: Pick<FormatOptions, 'locale'> = {},
) {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeStyle: 'short' }).format(
    toDate(value),
  )
}

/**
 * "10:42" today, "28 Sept" on any other day (e.g. "Draft saved 10:42"): a bare time
 * from two days ago would read as today.
 */
export function formatTime(
  value: DateInput,
  { now = Date.now(), locale = currentLocale() }: FormatOptions = {},
) {
  if (calendarDaysBetween(value, now) !== 0) return formatShortDate(value, { now, locale })
  return new Intl.DateTimeFormat(locale, { timeStyle: 'short' }).format(toDate(value))
}

export interface RelativeOptions extends FormatOptions {
  /** `long` "5 minutes ago" · `short` "5 min. ago" · `narrow` "5m ago". */
  style?: Intl.RelativeTimeFormatStyle
  /** After this many days switch to a date ("12 Sept"). Default 7. */
  maxDays?: number
}

/**
 * Relative time for recent moments, a short date for older ones. Future
 * times work too ("in 3 days").
 */
export function formatRelative(
  value: DateInput,
  { now = Date.now(), locale = currentLocale(), style = 'long', maxDays = 7 }: RelativeOptions = {},
): string {
  const date = toDate(value)
  const nowDate = toDate(now)
  const diff = date.getTime() - nowDate.getTime()
  const abs = Math.abs(diff)
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style })
  if (abs < 45_000) {
    const moment = rtf.format(0, 'second')
    // "Sent just now", not "Sent now" (a bare "now" reads oddly for the past). A few
    // seconds ahead is the server's clock, not the future.
    return diff < 5_000 && moment === 'now' ? 'just now' : moment
  }
  if (abs < HOUR) return rtf.format(Math.round(diff / MINUTE), 'minute')
  if (abs < DAY && calendarDaysBetween(nowDate, date) === 0)
    return rtf.format(Math.round(diff / HOUR), 'hour')
  if (abs < 20 * HOUR) return rtf.format(Math.round(diff / HOUR), 'hour')
  const days = calendarDaysBetween(nowDate, date)
  if (Math.abs(days) <= maxDays) return rtf.format(days, 'day')
  return formatShortDate(date, { now: nowDate, locale })
}

export type DueTone = 'overdue' | 'soon' | 'later' | 'none'

export interface DueDate {
  /** "Due tomorrow", "Due Fri 3 Oct", "Overdue 2 days", "No due date". */
  label: string
  tone: DueTone
  overdue: boolean
  /** Absolute date and time for a tooltip; null without a due date. */
  full: string | null
}

/** Due-date wording for evaluations (My work, idea sidebar, evaluate sheet). */
export function dueDate(
  value: DateInput | null | undefined,
  { now = Date.now(), locale = currentLocale() }: FormatOptions = {},
): DueDate {
  if (value === null || value === undefined) {
    return { label: 'No due date', tone: 'none', overdue: false, full: null }
  }
  const date = toDate(value)
  const nowDate = toDate(now)
  const full = formatDateTime(date, { locale })
  const days = calendarDaysBetween(nowDate, date)
  if (date.getTime() < nowDate.getTime()) {
    const late = -days
    const label =
      late <= 0
        ? `Overdue since ${new Intl.DateTimeFormat(locale, { timeStyle: 'short' }).format(date)}`
        : `Overdue ${late} ${late === 1 ? 'day' : 'days'}`
    return { label, tone: 'overdue', overdue: true, full }
  }
  if (days === 0) return { label: 'Due today', tone: 'soon', overdue: false, full }
  if (days === 1) return { label: 'Due tomorrow', tone: 'soon', overdue: false, full }
  return {
    label: `Due ${formatDate(date, { now: nowDate, locale })}`,
    tone: 'later',
    overdue: false,
    full,
  }
}
