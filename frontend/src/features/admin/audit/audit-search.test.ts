import { describe, expect, it } from 'vitest'

import { localDay, matchingPreset, presetFrom, toAuditFilters } from './audit-search'

// Wednesday 1 October 2026, 15:00 local time.
const NOW = new Date(2026, 9, 1, 15, 0).getTime()

describe('audit "When" quick ranges', () => {
  it('counts back whole local days, today included', () => {
    expect(localDay(NOW)).toBe('2026-10-01')
    expect(presetFrom(1, NOW)).toBe('2026-10-01')
    expect(presetFrom(7, NOW)).toBe('2026-09-25')
    expect(presetFrom(30, NOW)).toBe('2026-09-02')
  })

  it('names a range that is a preset, and only then', () => {
    expect(matchingPreset('2026-09-25', undefined, NOW)?.label).toBe('Last 7 days')
    expect(matchingPreset('2026-10-01', '2026-10-01', NOW)?.label).toBe('Today')
    expect(matchingPreset('2026-09-25', '2026-09-30', NOW)).toBeUndefined()
    expect(matchingPreset('2026-09-24', undefined, NOW)).toBeUndefined()
    expect(matchingPreset(undefined, undefined, NOW)).toBeUndefined()
  })

  it('filters from the start of the first day', () => {
    expect(toAuditFilters({ from: presetFrom(7, NOW) }).since).toBe(
      new Date(2026, 8, 25).toISOString(),
    )
  })
})
