import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  calendarDaysBetween,
  currentLocale,
  dueDate,
  formatDate,
  formatRelative,
  formatShortDate,
  formatTime,
} from '@/lib/dates'

// Local-time fixture: Wednesday 30 September 2026, 12:00.
const NOW = new Date(2026, 8, 30, 12, 0, 0)
const at = (days: number, hours = 0, minutes = 0) =>
  new Date(2026, 8, 30 + days, 12 + hours, minutes).toISOString()
const en = { now: NOW, locale: 'en-GB' }

afterEach(() => vi.restoreAllMocks())

describe('formatRelative', () => {
  it('uses words for recent moments', () => {
    expect(formatRelative(at(0, 0, 0), en)).toBe('just now')
    expect(formatRelative(at(0, 0, -5), en)).toBe('5 minutes ago')
    expect(formatRelative(at(0, -3), en)).toBe('3 hours ago')
    expect(formatRelative(at(-1, -2), en)).toBe('yesterday')
    expect(formatRelative(at(-3), en)).toBe('3 days ago')
    expect(formatRelative(at(2), en)).toBe('in 2 days')
  })

  it('switches to a date after a week', () => {
    expect(formatRelative(at(-12), en)).toBe('18 Sept')
    expect(formatRelative(new Date(2025, 2, 12).toISOString(), en)).toBe('12 Mar 2025')
  })

  it('has a compact style for dense rows', () => {
    expect(formatRelative(at(0, 0, -5), { ...en, style: 'narrow' })).toMatch(/^5\s?m(in)?\.? ago$/)
  })
})

describe('dueDate', () => {
  it('describes upcoming due dates', () => {
    expect(dueDate(at(0, 3), en)).toMatchObject({
      label: 'Due today',
      tone: 'soon',
      overdue: false,
    })
    expect(dueDate(at(1), en)).toMatchObject({ label: 'Due tomorrow', tone: 'soon' })
    expect(dueDate(at(3), en)).toMatchObject({ label: 'Due Sat 3 Oct', tone: 'later' })
  })

  it('counts overdue days', () => {
    expect(dueDate(at(-2), en)).toMatchObject({
      label: 'Overdue 2 days',
      tone: 'overdue',
      overdue: true,
    })
    expect(dueDate(at(-1), en).label).toBe('Overdue 1 day')
    expect(dueDate(at(0, -2), en).label).toBe('Overdue since 10:00')
  })

  it('handles a missing due date', () => {
    expect(dueDate(null, en)).toEqual({
      label: 'No due date',
      tone: 'none',
      overdue: false,
      full: null,
    })
  })
})

describe('formatDate', () => {
  it('adds the year only when it differs', () => {
    expect(formatDate(at(3), en)).toBe('Sat 3 Oct')
    expect(formatDate(new Date(2027, 0, 5).toISOString(), en)).toMatch(/^Tue,? 5 Jan 2027$/)
    expect(formatShortDate(at(3), en)).toBe('3 Oct')
  })

  it('follows the locale', () => {
    expect(formatDate(at(3), { now: NOW, locale: 'en-US' })).toBe('Sat, Oct 3')
    expect(formatDate(at(3), { now: NOW, locale: 'de' })).toBe('Sa., 3. Okt.')
  })
})

describe('formatTime', () => {
  it('gives the time today and the date on other days', () => {
    expect(formatTime(at(0, -2, 5), en)).toBe('10:05')
    expect(formatTime(at(-2, 6, 10), en)).toBe('28 Sept')
    expect(formatTime(at(-1, 11, 59), en)).toBe('29 Sept')
  })
})

describe('calendarDaysBetween', () => {
  it('counts calendar days, not 24-hour periods', () => {
    expect(calendarDaysBetween(new Date(2026, 8, 30, 23, 30), new Date(2026, 9, 1, 0, 30))).toBe(1)
    // Across the October DST change in Europe.
    expect(calendarDaysBetween(new Date(2026, 9, 24, 12), new Date(2026, 9, 26, 12))).toBe(2)
  })
})

describe('currentLocale', () => {
  it('turns tags Intl rejects into ones it accepts', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-US@posix')
    expect(currentLocale()).toBe('en-US')
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('de-DE')
    expect(currentLocale()).toBe('de-DE')
  })
})
