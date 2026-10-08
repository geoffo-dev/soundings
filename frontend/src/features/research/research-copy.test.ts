import { describe, expect, it } from 'vitest'

import { badgeLabel, badgeWords, showsResearchBadge } from './research-copy'

const progress = (answered: number, requiredOpen: number, total = 3) => ({
  answered,
  required_open: requiredOpen,
  total,
})

describe('the cards’ research badge (UX review m1)', () => {
  it('shows in Research, and before it only once something is answered', () => {
    expect(showsResearchBadge({ status: 'research', research: progress(0, 2) })).toBe(true)
    expect(showsResearchBadge({ status: 'new', research: progress(0, 2) })).toBe(false)
    expect(showsResearchBadge({ status: 'new', research: progress(1, 1) })).toBe(true)
    expect(showsResearchBadge({ status: 'evaluating', research: null })).toBe(false)
    expect(showsResearchBadge({ status: 'research', research: progress(0, 0, 0) })).toBe(false)
  })

  it('reads "2 open" or "Ready", with the whole sentence as its name', () => {
    expect(badgeWords(progress(1, 2))).toBe('2 open')
    expect(badgeWords(progress(2, 0))).toBe('Ready')
    expect(badgeLabel(progress(1, 2))).toBe('Research 1 of 3 answered, 2 required items open')
    expect(badgeLabel(progress(2, 0))).toBe('Research 2 of 3 answered, complete')
  })
})
