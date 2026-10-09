import { describe, expect, it } from 'vitest'

import { fromDateInput, latestDueInput, pickerMin, toDateInput, todayInput } from './due-date'

const noonUtc = Date.UTC(2026, 9, 1, 12)

describe('due dates', () => {
  it('turns a picked day into the end of that local day and back', () => {
    const iso = fromDateInput('2026-10-08')
    expect(iso).not.toBeNull()
    expect(toDateInput(iso)).toBe('2026-10-08')
    expect(fromDateInput('2026-02-30')).toBeNull()
    expect(fromDateInput('')).toBeNull()
  })

  it('offers today up to five years ahead, inside what the API accepts', () => {
    expect(todayInput(noonUtc)).toBe('2026-10-01')
    const latest = latestDueInput(noonUtc)
    expect(latest).toBe('2031-10-01')
    // The API refuses due_at more than 5 × 366 days from now.
    const dueAt = Date.parse(fromDateInput(latest) ?? '')
    expect(dueAt - noonUtc).toBeLessThan(5 * 366 * 24 * 3600 * 1000)
  })

  it('keeps an overdue date valid until it changes (Phase 8b UX M1)', () => {
    // Nothing set, or a date ahead: today is the earliest day offered.
    expect(pickerMin('', noonUtc)).toBe('2026-10-01')
    expect(pickerMin('2026-10-09', noonUtc)).toBe('2026-10-01')
    // Already overdue: that day stays allowed, so a form that keeps it still submits.
    expect(pickerMin('2026-09-27', noonUtc)).toBe('2026-09-27')
  })
})
