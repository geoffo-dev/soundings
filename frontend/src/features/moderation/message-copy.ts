import { isApiError } from '@/api/errors'
import type { MessageDelivery, ReplyBlocked, SendBlocked } from '@/api/types'

/**
 * Words for the messages between the team and the person who sent an idea through
 * the public form (contract-phase11 §3, §5): why sending is impossible, what a
 * refusal means, where a message goes. Only fixed text: a message's own text is
 * shown as plain text and never put in a sentence, a toast or an announcement.
 */

/** `SubmissionMessageCreate.body` / `TrackingReplyRequest.body`: 1-4,000 characters. */
export const MESSAGE_MAX_LENGTH = 4_000

/** The team's 409s and `blocked`, in plain words (the order the API checks them). */
export const SEND_BLOCKED_COPY: Record<SendBlocked, { title: string; text: string }> = {
  project_archived: {
    title: 'This project is archived',
    text: 'You can read the messages, but nobody can send new ones.',
  },
  submitter_erased: {
    title: 'Their details were erased',
    text: 'There’s no one to write to any more.',
  },
  public_submission_off: {
    title: 'Public submission is turned off',
    text: 'Their tracking link doesn’t open while it’s off, so they couldn’t read a message.',
  },
  conversation_full: {
    title: 'This conversation is full',
    text: 'It has 100 messages, the most one conversation holds.',
  },
  daily_limit: {
    title: 'That’s 20 messages to them today',
    text: 'That’s the most the team can send one person in a day. You can write again tomorrow.',
  },
}

/** Where a message sent now reaches them. */
export function deliveryText(delivery: MessageDelivery, projectName: string): string {
  const signed = `signed “The ${projectName} team”`
  return delivery === 'email'
    ? `Emailed to them and shown on their tracking page, ${signed}.`
    : `They’ll see it only on their tracking page, ${signed}.`
}

/** "in 12 minutes", "in about 2 hours", from a 429's `Retry-After`. */
export function waitWords(seconds: number | undefined): string {
  if (!seconds || seconds < 90) return 'in a minute or two'
  const minutes = Math.ceil(seconds / 60)
  if (minutes < 60) return `in ${minutes} minutes`
  const hours = Math.round(minutes / 60)
  return hours <= 1 ? 'in about an hour' : `in about ${hours} hours`
}

export interface MessageProblem {
  title: string
  text?: string
}

/** Why the team's message wasn't sent (the composer keeps the text). */
export function sendProblem(error: unknown): MessageProblem {
  if (isApiError(error)) {
    if (error.code in SEND_BLOCKED_COPY) return SEND_BLOCKED_COPY[error.code as SendBlocked]
    if (error.code === 'too_many_attempts') {
      // 20 to this person in a day, or 30 of yours in an hour (contract-phase11 §5).
      return (error.retryAfterSeconds ?? 0) > 3_600
        ? SEND_BLOCKED_COPY.daily_limit
        : {
            title: 'You’ve sent a lot of messages in the last hour',
            text: `Try again ${waitWords(error.retryAfterSeconds)}.`,
          }
    }
    if (error.code === 'rate_limited') {
      return { title: 'Too many changes at once', text: 'Wait a moment, then send it again.' }
    }
    if (error.status === 422) {
      const reason = Object.values(error.fieldErrors)[0]
      return {
        title: 'This message can’t be sent as it is',
        text: reason ? `${reason}.`.replace(/\.\.$/, '.') : 'Check the text and try again.',
      }
    }
    if (error.status === 403) {
      return {
        title: 'You can’t message this person any more',
        text: 'Only the idea’s owner and admins can.',
      }
    }
    if (error.status === 404) {
      return { title: 'This idea or its submission is gone', text: 'Reload the page.' }
    }
  }
  return { title: 'Not sent', text: 'Check your connection and try again. Your text is kept.' }
}

/** Why the submitter can't reply now (`reply_blocked`), on their tracking page. */
export const REPLY_BLOCKED_COPY: Record<ReplyBlocked, string> = {
  project_archived: 'The team isn’t taking messages about this idea any more.',
  awaiting_team: 'You can reply again once the team writes back.',
  conversation_full: 'This conversation is full: it has 100 messages.',
  daily_limit: 'You’ve replied 10 times today. You can reply again tomorrow.',
}

/** Why the submitter's reply wasn't sent (their text is kept). */
export function replyProblem(error: unknown): string {
  if (isApiError(error)) {
    if (error.code in REPLY_BLOCKED_COPY) return REPLY_BLOCKED_COPY[error.code as ReplyBlocked]
    if (error.code === 'too_many_attempts') {
      return (error.retryAfterSeconds ?? 0) > 3_600
        ? REPLY_BLOCKED_COPY.daily_limit
        : `You’ve sent a lot of replies in a short time. Try again ${waitWords(error.retryAfterSeconds)}.`
    }
    if (error.status === 404) {
      return 'This link no longer works: your details may have been deleted.'
    }
    if (error.status === 422) {
      return 'Your reply can’t be sent as it is: write some text (at most 4,000 characters).'
    }
  }
  return 'Not sent. Check your connection and try again: your reply is still here.'
}

/** "2 messages · They replied 40 minutes ago" (the panel's summary, before opening). */
export function messageCount(count: number): string {
  return count === 1 ? '1 message' : `${count.toLocaleString('en')} messages`
}
