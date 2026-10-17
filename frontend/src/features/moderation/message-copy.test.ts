import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'

import {
  deliveryText,
  messageCount,
  REPLY_BLOCKED_COPY,
  replyProblem,
  SEND_BLOCKED_COPY,
  sendProblem,
  waitWords,
} from './message-copy'

const problem = (status: number, code: string, extra: Partial<ApiError> = {}) =>
  new ApiError({ status, code, title: code, ...extra })

describe('messages with public submitters: plain words (contract-phase11 §5)', () => {
  it('says where a message goes, signed by the team, never by a person', () => {
    expect(deliveryText('email', 'Sustainability')).toBe(
      'Emailed to them and shown on their tracking page, signed “The Sustainability team”.',
    )
    expect(deliveryText('tracking_page', 'Sustainability')).toBe(
      'They’ll see it only on their tracking page, signed “The Sustainability team”.',
    )
  })

  it('words every refusal of the team’s message by its code', () => {
    for (const code of Object.keys(SEND_BLOCKED_COPY) as (keyof typeof SEND_BLOCKED_COPY)[]) {
      if (code === 'daily_limit') continue
      expect(sendProblem(problem(409, code))).toEqual(SEND_BLOCKED_COPY[code])
    }
    expect(sendProblem(problem(429, 'too_many_attempts', { retryAfterSeconds: 20_000 }))).toEqual(
      SEND_BLOCKED_COPY.daily_limit,
    )
    expect(sendProblem(problem(429, 'too_many_attempts', { retryAfterSeconds: 600 }))).toEqual({
      title: 'You’ve sent a lot of messages in the last hour',
      text: 'Try again in 10 minutes.',
    })
    expect(sendProblem(problem(403, 'forbidden')).title).toBe(
      'You can’t message this person any more',
    )
    expect(sendProblem(new Error('offline')).text).toContain('Your text is kept')
  })

  it('words the submitter’s refusals and blocked replies', () => {
    expect(replyProblem(problem(409, 'awaiting_team'))).toBe(REPLY_BLOCKED_COPY.awaiting_team)
    expect(replyProblem(problem(429, 'too_many_attempts', { retryAfterSeconds: 50_000 }))).toBe(
      'You’ve replied 10 times today. You can reply again tomorrow.',
    )
    expect(replyProblem(problem(429, 'too_many_attempts', { retryAfterSeconds: 30 }))).toBe(
      'You’ve sent a lot of replies in a short time. Try again in a minute or two.',
    )
    expect(replyProblem(problem(404, 'not_found'))).toContain('no longer works')
  })

  it('rounds waits and counts', () => {
    expect(waitWords(undefined)).toBe('in a minute or two')
    expect(waitWords(3_000)).toBe('in 50 minutes')
    expect(waitWords(7_200)).toBe('in about 2 hours')
    expect(messageCount(1)).toBe('1 message')
    expect(messageCount(100)).toBe('100 messages')
  })
})
