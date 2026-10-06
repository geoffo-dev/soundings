import { describe, expect, it } from 'vitest'

import type { ActivityItem } from '@/api/types'
import { activityActor, describeActivity, describeEntry, groupActivity } from '@/lib/activity'

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

describe('public submissions', () => {
  it('reads "A visitor sent it through the public form", not "Someone submitted the idea"', () => {
    const item: ActivityItem = {
      id: 'e-public',
      idea_id: 'i-1',
      type: 'idea_created',
      actor: null,
      created_at: '2026-10-01T09:00:00Z',
    }
    expect(`${activityActor(item)} ${describeActivity(item)}`).toBe(
      'A visitor sent it through the public form',
    )
    expect(describeActivity({ ...item, actor: alice })).toBe('submitted the idea')
  })

  it('names the sender when they gave a name, as the idea header does', () => {
    const item: ActivityItem = {
      id: 'e-public',
      idea_id: 'i-1',
      type: 'idea_created',
      actor: null,
      created_at: '2026-10-01T09:00:00Z',
    }
    expect(activityActor(item, 'Jo Public')).toBe('Jo Public')
    expect(activityActor(item, '  ')).toBe('A visitor')
    expect(activityActor({ ...item, type: 'idea_edited', fields: ['title'] }, 'Jo Public')).toBe(
      'Someone',
    )
  })
})

describe('AI assistance (Phase 6)', () => {
  const agent = person('u-agent', 'Idea evaluator')
  it('reads an AI evaluator taken off after its run as the agent’s line, not “Someone”', () => {
    const item = {
      id: 'e-ai-1',
      idea_id: 'i-1',
      type: 'evaluator_removed',
      actor: null,
      created_at: '2026-10-06T09:00:00Z',
      evaluator: agent,
    } as ActivityItem
    expect(`${activityActor(item)} ${describeActivity(item)}`).toBe(
      'Idea evaluator ended its run without an evaluation and was taken off the evaluators',
    )
  })

  it('describes research notes, and deleted ones without blaming the agent', () => {
    const note = (deleted: boolean) =>
      ({
        id: 'e-ai-2',
        idea_id: 'i-1',
        type: 'ai_research_note',
        actor: agent,
        created_at: '2026-10-06T09:00:00Z',
        note: {
          id: 'e-ai-2',
          run_id: 'r-1',
          agent: null,
          body_md: deleted ? '' : 'Text',
          sources: [],
          deleted,
          can_delete: false,
        },
      }) as ActivityItem
    expect(describeActivity(note(false))).toBe('wrote a research note')
    expect(describeActivity(note(true))).toBe('wrote a research note, since deleted')
  })
})
