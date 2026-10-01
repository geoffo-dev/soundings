import { describe, expect, it } from 'vitest'

import type { ActivityItem } from '@/api/types'
import { describeEntry, groupActivity } from '@/lib/activity'

const person = (id: string, display_name: string) => ({
  id,
  display_name,
  avatar_url: null,
  initials: display_name.slice(0, 2).toUpperCase(),
})
const alice = person('u-alice', 'Alice')
const bob = person('u-bob', 'Bob')

let n = 0
function invited(name: string, at: string, actor = alice): ActivityItem {
  n += 1
  return {
    id: `e-${n}`,
    idea_id: 'i-1',
    type: 'evaluator_added',
    actor,
    created_at: at,
    evaluator: person(`u-${name}`, name),
  }
}
function submitted(at: string): ActivityItem {
  n += 1
  return {
    id: `e-${n}`,
    idea_id: 'i-1',
    type: 'evaluation_submitted',
    actor: bob,
    created_at: at,
  } as ActivityItem
}

describe('groupActivity', () => {
  it('folds invitations by one person, minutes apart, into one line', () => {
    const entries = groupActivity([
      invited('Bob', '2026-09-21T10:00:00Z'),
      invited('Carol', '2026-09-21T10:00:05Z'),
      invited('Dave', '2026-09-21T10:03:00Z'),
      submitted('2026-09-22T09:00:00Z'),
      invited('Erin', '2026-09-23T09:00:00Z'),
    ])
    expect(entries.map((entry) => describeEntry(entry))).toEqual([
      'invited Bob, Carol and Dave to evaluate',
      'submitted an evaluation',
      'invited Erin to evaluate',
    ])
    // The line shows the run's latest time.
    expect(entries[0]?.item.created_at).toBe('2026-09-21T10:03:00Z')
  })

  it('keeps invitations apart when someone else sent them, or much later', () => {
    const entries = groupActivity([
      invited('Bob', '2026-09-21T10:00:00Z'),
      invited('Carol', '2026-09-21T10:01:00Z', bob),
      invited('Dave', '2026-09-21T12:00:00Z', bob),
    ])
    expect(entries).toHaveLength(3)
  })
})
