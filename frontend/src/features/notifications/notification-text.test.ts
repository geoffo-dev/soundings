import { describe, expect, it } from 'vitest'

import type { NotificationItem } from '@/api/types'

import {
  describeNotification,
  dueOn,
  groupByDay,
  isKnownNotification,
  notificationLink,
  notificationText,
  unreadBadge,
} from './notification-text'

// Thursday 1 October 2026, 15:00 local time.
const NOW = new Date(2026, 9, 1, 15, 0).getTime()
const at = (day: number, hour = 9) => new Date(2026, 9, day, hour, 0).toISOString()

const CAROL = { id: 'u-carol', display_name: 'Carol Díaz', avatar_url: null, initials: 'CD' }
const IDEA = {
  id: 'i-1',
  key: 'CUST-1',
  number: 1,
  title: 'Self-serve returns portal',
  status: 'evaluating' as const,
  resolution: null,
  status_label: 'Evaluating',
  project: { id: 'p-1', key: 'CUST', name: 'Customer Innovation', slug: 'customer-innovation' },
}
const base = { id: 'n-1', created_at: at(1, 14), read_at: null, idea: IDEA, actor: CAROL }

function item(extra: Record<string, unknown>): NotificationItem {
  return { ...base, ...extra } as NotificationItem
}

describe('inbox sentences (contract-phase3 §3.2)', () => {
  it('says who did what, in plain words', () => {
    expect(notificationText(item({ type: 'owner_assigned' }), NOW)).toBe(
      'Carol Díaz made you the owner',
    )
    expect(notificationText(item({ type: 'evaluator_invited', due_at: at(9, 17) }), NOW)).toBe(
      'Carol Díaz asked you to evaluate, due Fri, Oct 9',
    )
    expect(notificationText(item({ type: 'evaluator_invited', due_at: null }), NOW)).toBe(
      'Carol Díaz asked you to evaluate',
    )
    // The date is kept on one line when the sentence wraps (QA K3-4).
    const invited = describeNotification(
      item({ type: 'evaluator_invited', due_at: at(9, 17) }),
      NOW,
    )
    expect(invited.keepTogether).toBe('Fri, Oct 9')
    expect(invited.text.endsWith(invited.keepTogether ?? '-')).toBe(true)
    expect(
      describeNotification(item({ type: 'evaluator_invited', due_at: null }), NOW).keepTogether,
    ).toBeUndefined()
    expect(
      notificationText(
        item({
          type: 'status_changed',
          from_status: 'evaluating',
          from_resolution: null,
          from_label: 'Evaluating',
          to_status: 'closed',
          to_resolution: 'accepted',
          to_label: 'Adopted',
        }),
        NOW,
      ),
    ).toBe('Carol Díaz moved it from Evaluating to Adopted')
  })

  it('quotes comments and mentions, and says when the comment is gone', () => {
    const comment = { id: 'c-1', excerpt: 'Have we checked the limits?', deleted: false }
    expect(notificationText(item({ type: 'mention', comment }), NOW)).toBe(
      'Carol Díaz mentioned you: “Have we checked the limits?”',
    )
    expect(describeNotification(item({ type: 'comment', comment }), NOW)).toEqual({
      actor: 'Carol Díaz',
      text: 'commented',
      quote: 'Have we checked the limits?',
    })
    expect(
      notificationText(
        item({ type: 'comment', comment: { id: 'c-1', excerpt: '', deleted: true } }),
        NOW,
      ),
    ).toBe('Carol Díaz commented (since deleted)')
  })

  it('phrases reminders as a date, never a countdown', () => {
    const reminder = (due: string, daysBefore: number) =>
      notificationText(
        item({ type: 'evaluation_reminder', actor: null, due_at: due, days_before: daysBefore }),
        NOW,
      )
    expect(reminder(at(3, 17), 2)).toBe('Your evaluation is due Sat, Oct 3')
    expect(reminder(at(1, 17), 0)).toBe('Your evaluation is due today, Thu, Oct 1')
    // A reminder read days later still names the date, not "in -2 days".
    expect(dueOn(at(1, 17), new Date(2026, 9, 3).getTime())).toBe('due Thu, Oct 1')
  })

  it('never contains score data: "all evaluations are in" is a count of submissions', () => {
    const text = notificationText(
      item({ type: 'evaluations_complete', actor: null, evaluator_count: 3 }),
      NOW,
    )
    expect(text).toBe('All 3 evaluations are in')
    expect(text).not.toMatch(/score|aggregate|\d\.\d|recommend/i)
    expect(
      notificationText(item({ type: 'evaluations_complete', actor: null, evaluator_count: 1 })),
    ).toBe('The evaluation is in')
  })

  it('names "Someone" when the actor is gone', () => {
    expect(notificationText(item({ type: 'owner_assigned', actor: null }), NOW)).toBe(
      'Someone made you the owner',
    )
  })

  it('skips types it doesn’t know (a newer API)', () => {
    expect(isKnownNotification({ type: 'mention' })).toBe(true)
    expect(isKnownNotification({ type: 'agent_finished' })).toBe(false)
  })
})

describe('where a notification leads', () => {
  it('opens the evaluate sheet for invitations and reminders', () => {
    expect(notificationLink(item({ type: 'evaluator_invited', due_at: null }))).toEqual({
      ideaKey: 'CUST-1',
      evaluate: true,
    })
    expect(
      notificationLink(item({ type: 'evaluation_reminder', due_at: at(3), days_before: 2 })),
    ).toMatchObject({ evaluate: true })
  })

  it('jumps to the comment, unless it was deleted', () => {
    const comment = { id: 'c-9', excerpt: 'x', deleted: false }
    expect(notificationLink(item({ type: 'mention', comment }))).toEqual({
      ideaKey: 'CUST-1',
      evaluate: false,
      hash: 'comment-c-9',
    })
    expect(
      notificationLink(item({ type: 'comment', comment: { ...comment, deleted: true } })).hash,
    ).toBeUndefined()
    expect(notificationLink(item({ type: 'owner_assigned' }))).toEqual({
      ideaKey: 'CUST-1',
      evaluate: false,
    })
  })
})

describe('grouping by day', () => {
  it('keeps the order and labels Today, Yesterday, then dates', () => {
    const items = [
      { id: 'a', created_at: at(1, 14) },
      { id: 'b', created_at: at(1, 8) },
      { id: 'c', created_at: new Date(2026, 8, 30, 23, 30).toISOString() },
      { id: 'd', created_at: new Date(2026, 8, 28, 10).toISOString() },
    ]
    const groups = groupByDay(items, NOW)
    expect(groups.map((g) => g.label)).toEqual(['Today', 'Yesterday', 'Mon, Sep 28'])
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([['a', 'b'], ['c'], ['d']])
    expect(groupByDay([], NOW)).toEqual([])
  })
})

describe('the bell’s badge', () => {
  it('shows the count, "99+" above 99, nothing at zero', () => {
    expect(unreadBadge(0)).toBeNull()
    expect(unreadBadge(7)).toBe('7')
    expect(unreadBadge(99)).toBe('99')
    expect(unreadBadge(100)).toBe('99+')
  })
})
