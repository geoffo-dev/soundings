import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'

import {
  channelLabel,
  deliveryText,
  messageCount,
  NO_EMAIL_COPY,
  repliesLeftText,
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
      'Shown on their tracking page only, signed “The Sustainability team”.',
    )
    // Said plainly when no email will reach them (UX review M1).
    expect(NO_EMAIL_COPY.title).toBe('They won’t get an email')
  })

  it('names each message’s channel without claiming delivery (review C10, UX m1)', () => {
    expect(channelLabel(true)).toBe('By email too')
    expect(channelLabel(false)).toBe('Tracking page only')
    expect(channelLabel(true)).not.toMatch(/emailed|delivered|sent/i)
  })

  it('warns the submitter two replies before a limit, by the nearer one (UX review p9)', () => {
    const now = Date.parse('2026-10-17T12:00:00Z')
    const at = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString()
    const team = (minutesAgo: number) => ({
      direction: 'team' as const,
      created_at: at(minutesAgo),
    })
    const reply = (minutesAgo: number) => ({
      direction: 'submitter' as const,
      created_at: at(minutesAgo),
    })
    const replies = (count: number, from = 60) =>
      Array.from({ length: count }, (_, n) => reply(from - n))
    // Room to spare: nothing said.
    expect(repliesLeftText([team(120), ...replies(7)], now)).toBeNull()
    expect(repliesLeftText([team(120), ...replies(8)], now)).toBe(
      'You can send 2 more replies until the team writes back.',
    )
    expect(repliesLeftText([team(120), ...replies(9)], now)).toBe(
      'You can send 1 more reply until the team writes back.',
    )
    // None left: the blocked line says why instead.
    expect(repliesLeftText([team(120), ...replies(10)], now)).toBeNull()
    // The team wrote back after eight replies: the count starts again…
    expect(repliesLeftText([team(300), ...replies(8, 200), team(60)], now)).toBe(
      'You can send 2 more replies today.',
    )
    // …and replies older than a day don't count towards today.
    expect(
      repliesLeftText([team(3_000), ...replies(5, 2_000), team(60), reply(10)], now),
    ).toBeNull()
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
