import { describe, expect, it } from 'vitest'

import { fromDateInput, latestDueInput, toDateInput, todayInput } from './due-date'

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
})
