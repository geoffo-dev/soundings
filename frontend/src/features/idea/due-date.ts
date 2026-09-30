/**
 * The evaluation due date is a moment (`due_at`, ISO with offset) but people
 * pick a day. A picked day means "by the end of that day" in the user's time
 * zone, so an evaluation is never overdue on the morning it is due.
 */

const pad = (n: number) => String(n).padStart(2, '0')

/** Local calendar day of an ISO moment as `YYYY-MM-DD` (the date input's value); '' for none. */
export function toDateInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** `YYYY-MM-DD` → the end of that local day as ISO (UTC); null for '' or an invalid day. */
export function fromDateInput(value: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const [, y, m, d] = match
  const date = new Date(Number(y), Number(m) - 1, Number(d), 23, 59, 0, 0)
  if (date.getMonth() !== Number(m) - 1) return null
  return date.toISOString()
}

/** Today + `days` as a date input value (the project's default evaluation window). */
export function dateInputInDays(days: number, now: number = Date.now()): string {
  const date = new Date(now)
  date.setDate(date.getDate() + days)
  return toDateInput(date.toISOString())
}

/** Today's date input value (the picker's `min`). */
export function todayInput(now: number = Date.now()): string {
  return toDateInput(new Date(now).toISOString())
}
