import { useNotificationPreferences } from '@/api/notifications'
import { formatDate } from '@/lib/dates'
import { browserTimeZone, endOfZonedDay, toZonedDateInput, validTimeZone } from '@/lib/time-zones'

/**
 * A call's deadline and assessment due date are days in the **instance's** time zone, by
 * the end of that day (contract-phase10 §3.2; UX review M6): emails, reminders and the
 * report count them there. The instance's zone comes with your notification preferences
 * (every signed-in person has them); until they load, or if this browser doesn't know
 * the zone, the browser's own is used.
 */
export interface CallZone {
  timeZone: string
  /** The browser is elsewhere: say which zone a day is in. */
  differs: boolean
  /** "2026-10-24" for a picker from a stored moment ('' for none). */
  toInput: (iso: string | null | undefined) => string
  /** A picked day → the end of it in the instance's zone (null for none). */
  fromInput: (value: string) => string | null
  /** "Sat 24 Oct", the day in the instance's zone. */
  format: (iso: string) => string
  /** " (Europe/London)" when the browser is in another zone, else "". */
  suffix: string
  /** The picker's `min`: today in the zone, or the day already set when earlier. */
  pickerMin: (current: string) => string
}

export function callZone(zone: string | null | undefined): CallZone {
  const browser = browserTimeZone()
  const timeZone = validTimeZone(zone) ?? browser
  const differs = timeZone !== browser
  return {
    timeZone,
    differs,
    toInput: (iso) => toZonedDateInput(iso, timeZone),
    fromInput: (value) => (value ? endOfZonedDay(value, timeZone) : null),
    format: (iso) => formatDate(iso, { timeZone }),
    suffix: differs ? ` (${timeZone})` : '',
    pickerMin: (current) => {
      const today = toZonedDateInput(new Date().toISOString(), timeZone)
      return current && current < today ? current : today
    },
  }
}

export function useCallZone(): CallZone {
  const preferences = useNotificationPreferences()
  return callZone(preferences.data?.timezone)
}
