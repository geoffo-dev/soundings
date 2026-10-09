import { describe, expect, it } from 'vitest'

import type { ActivityItem } from '@/api/types'
import { activityActor, describeActivity, describeEntry, groupActivity } from '@/lib/activity'
import { formatDate } from '@/lib/dates'

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

describe('describeActivity (Phase 8)', () => {
  const moved = (overridden: boolean): ActivityItem => ({
    id: 'e-moved',
    idea_id: 'i-1',
    type: 'status_changed',
    actor: alice,
    created_at: '2026-10-07T10:00:00Z',
    from_status: 'research',
    from_resolution: null,
    to_status: 'evaluating',
    to_resolution: null,
    research_overridden: overridden,
    from_label: null,
    to_label: null,
  })

  it('names Research like any status, and says when an admin moved past it anyway', () => {
    expect(describeActivity(moved(false))).toBe('moved it from Research to Evaluating')
    expect(describeActivity(moved(true))).toBe(
      'moved it from Research to Evaluating without finishing research',
    )
  })
})

describe('describeActivity (Phase 8b)', () => {
  const bob = { id: 'u-bob', display_name: 'Bob Brown', avatar_url: null, initials: 'BB' }
  const ann = { id: 'u-ann', display_name: 'Ann Lee', avatar_url: null, initials: 'AL' }
  const base = { id: 'e-r', idea_id: 'i-1', actor: alice, created_at: '2026-10-08T10:00:00Z' }
  const changed = (
    from: typeof bob | null,
    to: typeof bob | null,
    handedBack = false,
    actor = alice,
  ): ActivityItem => ({
    ...base,
    actor,
    type: 'researcher_changed',
    from_researcher: from,
    to_researcher: to,
    handed_back: handedBack,
  })

  it('says who was asked to research, instead of whom, removed or handed back', () => {
    expect(describeActivity(changed(null, bob))).toBe('asked Bob Brown to research')
    expect(describeActivity(changed(ann, bob))).toBe('asked Bob Brown instead of Ann Lee to research')
    expect(describeActivity(changed(bob, null))).toBe('removed Bob Brown as researcher')
    expect(describeActivity(changed(bob, null, true, bob))).toBe('handed the research back')
    expect(describeActivity(changed(null, alice))).toBe('took on the research')
  })

  it('words the research due date, and prefers the event’s own status labels', () => {
    const due = (to: string | null): ActivityItem => ({
      ...base,
      type: 'research_due_date_changed',
      from_due_at: null,
      to_due_at: to,
    })
    expect(describeActivity(due('2026-10-09T16:00:00Z'))).toBe(
      `set the research due date to ${formatDate('2026-10-09T16:00:00Z')}`,
    )
    expect(describeActivity(due(null))).toBe('removed the research due date')
    const moved: ActivityItem = {
      ...base,
      type: 'status_changed',
      from_status: 'new',
      from_resolution: null,
      to_status: 'research',
      to_resolution: null,
      research_overridden: false,
      from_label: 'Triage',
      to_label: 'Research',
    }
    expect(describeActivity(moved)).toBe('moved it from Triage to Research')
  })
})
