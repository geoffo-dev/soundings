import { describe, expect, it } from 'vitest'

import { allTypes, applyPreferenceUpdate } from '@/api/notifications'
import type { NotificationPreferences } from '@/api/types'

import {
  changedModes,
  describeMode,
  MODE_OPTIONS,
  previousModes,
  unsubscribeSubject,
} from './preferences'

const PREFERENCES: NotificationPreferences = {
  email_available: true,
  digest_hour: 8,
  timezone: 'Europe/London',
  items: [
    { type: 'owner_assigned', mode: 'immediate', default_mode: 'immediate' },
    { type: 'evaluator_invited', mode: 'immediate', default_mode: 'immediate' },
    { type: 'evaluation_reminder', mode: 'off', default_mode: 'immediate' },
    { type: 'evaluations_complete', mode: 'immediate', default_mode: 'immediate' },
    { type: 'status_changed', mode: 'digest', default_mode: 'digest' },
    { type: 'comment', mode: 'immediate', default_mode: 'digest' },
    { type: 'mention', mode: 'immediate', default_mode: 'immediate' },
  ],
}

describe('email preference mapping (contract-phase3 §3.4)', () => {
  it('offers the three modes in order, in words people use', () => {
    expect(MODE_OPTIONS.map((option) => option.value)).toEqual(['immediate', 'digest', 'off'])
    expect(MODE_OPTIONS.map((option) => option.label)).toEqual(['Immediate', 'Daily digest', 'Off'])
    expect(describeMode('digest')).toBe('In the daily digest')
    expect(describeMode('off')).toBe('Not emailed')
  })

  it('applies a partial update and leaves other types alone (the optimistic save)', () => {
    const next = applyPreferenceUpdate(PREFERENCES, { comment: 'digest', mention: 'off' })
    expect(next.items.find((item) => item.type === 'comment')?.mode).toBe('digest')
    expect(next.items.find((item) => item.type === 'mention')?.mode).toBe('off')
    expect(next.items.find((item) => item.type === 'evaluation_reminder')?.mode).toBe('off')
    expect(next.items.map((item) => item.type)).toEqual(PREFERENCES.items.map((item) => item.type))
  })

  it('turns everything off, and restores exactly what was there (Undo)', () => {
    const off = allTypes(PREFERENCES, 'off')
    expect(Object.values(off)).toEqual(Array(7).fill('off'))
    const before = previousModes(PREFERENCES)
    const restored = applyPreferenceUpdate(applyPreferenceUpdate(PREFERENCES, off), before)
    expect(restored).toEqual(PREFERENCES)
  })

  it('only sends what changes', () => {
    expect(changedModes(PREFERENCES, { comment: 'immediate', mention: 'digest' })).toEqual({
      mention: 'digest',
    })
  })
})

describe('what an unsubscribe link turns off (contract-phase3 §3.5)', () => {
  it('one type: names it and says what those emails are', () => {
    expect(unsubscribeSubject({ scope: 'comment', types: ['comment'] })).toMatchObject({
      title: 'Unsubscribe from “New comments” emails?',
      detail: 'someone comments on an idea you watch.',
    })
  })

  it('the digest and everything list the types', () => {
    const digest = unsubscribeSubject({ scope: 'digest', types: ['status_changed', 'comment'] })
    expect(digest.title).toBe('Stop the daily digest?')
    expect(digest.list).toEqual(['Status changes', 'New comments'])
    expect(digest.done).toBe('You won’t get the daily digest (status changes and new comments)')
    const all = unsubscribeSubject({ scope: 'all', types: ['owner_assigned', 'mention'] })
    expect(all.title).toBe('Unsubscribe from all Soundings email?')
    expect(all.detail).toBeUndefined()
  })
})
