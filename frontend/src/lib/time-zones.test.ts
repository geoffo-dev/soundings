import { describe, expect, it } from 'vitest'

import { dueDate, formatDate } from './dates'
import { endOfZonedDay, toZonedDateInput, validTimeZone, zonedParts } from './time-zones'

describe('days in a named time zone (UX review M6)', () => {
  it('the end of a day in London is 23:59 there, in summer and in winter', () => {
    // BST (UTC+1) and GMT.
    expect(endOfZonedDay('2026-10-24', 'Europe/London')).toBe('2026-10-24T22:59:00.000Z')
    expect(endOfZonedDay('2026-12-01', 'Europe/London')).toBe('2026-12-01T23:59:00.000Z')
  })

  it('handles the days the clocks change, and zones ahead of and behind UTC', () => {
    // 25 Oct 2026: BST ends at 02:00; 23:59 that evening is GMT.
    expect(endOfZonedDay('2026-10-25', 'Europe/London')).toBe('2026-10-25T23:59:00.000Z')
    // 29 Mar 2026: BST starts at 01:00; 23:59 that evening is BST.
    expect(endOfZonedDay('2026-03-29', 'Europe/London')).toBe('2026-03-29T22:59:00.000Z')
    expect(endOfZonedDay('2026-10-24', 'Asia/Tokyo')).toBe('2026-10-24T14:59:00.000Z')
    expect(endOfZonedDay('2026-10-24', 'America/New_York')).toBe('2026-10-25T03:59:00.000Z')
    expect(endOfZonedDay('2026-10-24', 'UTC')).toBe('2026-10-24T23:59:00.000Z')
  })

  it('round-trips a picked day whatever zone the browser is in', () => {
    for (const zone of [
      'Europe/London',
      'Asia/Tokyo',
      'America/Los_Angeles',
      'Pacific/Kiritimati',
    ]) {
      const end = endOfZonedDay('2026-02-28', zone)
      expect(toZonedDateInput(end, zone)).toBe('2026-02-28')
      expect(zonedParts(end ?? '', zone)).toMatchObject({ hour: 23, minute: 59 })
    }
  })

  it('refuses days that do not exist, and empty values', () => {
    expect(endOfZonedDay('2026-02-30', 'Europe/London')).toBeNull()
    expect(endOfZonedDay('', 'Europe/London')).toBeNull()
    expect(toZonedDateInput(null, 'Europe/London')).toBe('')
    expect(toZonedDateInput('not a date', 'Europe/London')).toBe('')
  })

  it('knows a real zone from a made-up one', () => {
    expect(validTimeZone('Europe/London')).toBe('Europe/London')
    expect(validTimeZone('Mars/Olympus_Mons')).toBeUndefined()
    expect(validTimeZone(null)).toBeUndefined()
  })

  it('dates and due dates count the day in the zone given', () => {
    // 23:59 in London on Sat 24 Oct is Sun 25 Oct in Tokyo: in London's zone it stays the 24th.
    const due = '2026-10-24T22:59:00.000Z'
    expect(
      formatDate(due, { timeZone: 'Europe/London', now: '2026-10-01T00:00:00Z', locale: 'en-GB' }),
    ).toBe('Sat 24 Oct')
    expect(
      formatDate(due, { timeZone: 'Asia/Tokyo', now: '2026-10-01T00:00:00Z', locale: 'en-GB' }),
    ).toBe('Sun 25 Oct')
    // The morning of the due day in London: due today, not tomorrow.
    expect(
      dueDate(due, { timeZone: 'Europe/London', now: '2026-10-24T07:00:00Z', locale: 'en-GB' })
        .label,
    ).toBe('Due today')
    expect(
      dueDate(due, { timeZone: 'Europe/London', now: '2026-10-23T07:00:00Z', locale: 'en-GB' })
        .label,
    ).toBe('Due tomorrow')
  })
})
