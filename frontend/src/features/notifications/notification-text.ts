import type { NotificationItem, NotificationType } from '@/api/types'
import { calendarDaysBetween, formatDate, type DateInput } from '@/lib/dates'

/**
 * Inbox wording (contract-phase3 §3.2, §3.11): one plain sentence per
 * notification, where it leads, and the day groups. Built only from what the
 * API sends (names, labels, dates, a comment excerpt): never a score.
 */

/** The parts of a sentence; `actor` is shown emphasised. */
export interface NotificationSentence {
  actor: string | null
  text: string
  /** A comment excerpt, shown quoted on its own line. */
  quote: string | null
  /** The end of `text` that must not break across lines: a due date ("Sat, 3 Oct"). */
  keepTogether?: string
}

/** Unknown types (a newer API) are skipped, not shown wrongly (schema: "skip types you don't know"). */
export const KNOWN_TYPES = new Set<string>([
  'owner_assigned',
  'evaluator_invited',
  'evaluation_reminder',
  'evaluations_complete',
  'status_changed',
  'comment',
  'mention',
])

export function isKnownNotification(item: { type: string }): item is NotificationItem {
  return KNOWN_TYPES.has(item.type)
}

/** "due Fri 9 Oct", or "due today, Fri 9 Oct" on that day; always a date, never a countdown. */
export function dueOn(value: DateInput, now: DateInput = Date.now()): string {
  const date = formatDate(value, { now })
  return calendarDaysBetween(now, value) === 0 ? `due today, ${date}` : `due ${date}`
}

function plural(count: number, one: string, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`
}

export function describeNotification(
  item: NotificationItem,
  now: DateInput = Date.now(),
): NotificationSentence {
  const actor = item.actor?.display_name ?? null
  const someone = actor ? '' : 'Someone '
  switch (item.type) {
    case 'owner_assigned':
      return { actor, text: `${someone}made you the owner`, quote: null }
    case 'evaluator_invited':
      return {
        actor,
        text: `${someone}asked you to evaluate${item.due_at ? `, ${dueOn(item.due_at, now)}` : ''}`,
        quote: null,
        ...(item.due_at ? { keepTogether: formatDate(item.due_at, { now }) } : {}),
      }
    case 'evaluation_reminder':
      return {
        actor: null,
        text: `Your evaluation is ${dueOn(item.due_at, now)}`,
        quote: null,
        keepTogether: formatDate(item.due_at, { now }),
      }
    case 'evaluations_complete':
      return {
        actor: null,
        text:
          item.evaluator_count === 1
            ? 'The evaluation is in'
            : `All ${plural(item.evaluator_count, 'evaluation')} are in`,
        quote: null,
      }
    case 'status_changed':
      return {
        actor,
        text: `${someone}moved it from ${item.from_label} to ${item.to_label}`,
        quote: null,
      }
    case 'comment':
      return item.comment.deleted
        ? { actor, text: `${someone}commented (since deleted)`, quote: null }
        : { actor, text: `${someone}commented`, quote: item.comment.excerpt || null }
    case 'mention':
      return item.comment.deleted
        ? { actor, text: `${someone}mentioned you in a comment (since deleted)`, quote: null }
        : { actor, text: `${someone}mentioned you`, quote: item.comment.excerpt || null }
  }
}

/** The sentence as one line of text (accessible names, tests). */
export function notificationText(item: NotificationItem, now: DateInput = Date.now()): string {
  const { actor, text, quote } = describeNotification(item, now)
  return `${actor ? `${actor} ` : ''}${text}${quote ? `: “${quote}”` : ''}`
}

export interface NotificationLink {
  ideaKey: string
  /** `?evaluate=1` opens the evaluate sheet (invitations and reminders). */
  evaluate: boolean
  /** `#comment-<id>` for comments and mentions that still exist. */
  hash?: string
}

export function notificationLink(item: NotificationItem): NotificationLink {
  const ideaKey = item.idea.key
  switch (item.type) {
    case 'evaluator_invited':
    case 'evaluation_reminder':
      return { ideaKey, evaluate: true }
    case 'comment':
    case 'mention':
      return item.comment.deleted
        ? { ideaKey, evaluate: false }
        : { ideaKey, evaluate: false, hash: `comment-${item.comment.id}` }
    default:
      return { ideaKey, evaluate: false }
  }
}

export interface DayGroup<T> {
  /** Stable key: the local date `YYYY-MM-DD`. */
  key: string
  /** "Today", "Yesterday", or "Mon 28 Sept". */
  label: string
  items: T[]
}

function localDay(value: DateInput): string {
  const date = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Groups newest-first items by local calendar day, keeping their order. */
export function groupByDay<T extends { created_at: string }>(
  items: readonly T[],
  now: DateInput = Date.now(),
): DayGroup<T>[] {
  const groups: DayGroup<T>[] = []
  for (const item of items) {
    const key = localDay(item.created_at)
    let group = groups.at(-1)
    if (group?.key !== key) {
      const days = calendarDaysBetween(item.created_at, now)
      const label =
        days <= 0 ? 'Today' : days === 1 ? 'Yesterday' : formatDate(item.created_at, { now })
      group = { key, label, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
}

/** The bell's badge: the number, "99+" above 99 (the API counts up to 100). */
export function unreadBadge(count: number): string | null {
  if (count <= 0) return null
  return count > 99 ? '99+' : String(count)
}

/* ------------------------------------------------------------------ */
/* Types and modes (Settings → Notifications, the unsubscribe page)    */
/* ------------------------------------------------------------------ */

/**
 * One name per notification type, everywhere: Settings → Notifications, the
 * unsubscribe page, the admin outbox (`one`) and, in lower case (`phrase`),
 * the emails' "Unsubscribe from …" footer (`app.email.model.TYPE_LABELS`).
 */
export const TYPE_COPY: Record<
  NotificationType,
  {
    /** A list label: "Evaluation requests". */
    label: string
    /** One email of the type (the outbox): "Evaluation request". */
    one: string
    /** Inside a sentence: "Unsubscribe from evaluation requests". */
    phrase: string
    /** "… when someone asks you to evaluate an idea". */
    when: string
    /** Under the label in Settings → Notifications. */
    description: string
  }
> = {
  owner_assigned: {
    label: 'Owner assignments',
    one: 'Owner assignment',
    phrase: 'owner assignments',
    when: 'someone makes you the owner of an idea',
    description: 'Someone else makes you the owner of an idea.',
  },
  evaluator_invited: {
    label: 'Evaluation requests',
    one: 'Evaluation request',
    phrase: 'evaluation requests',
    when: 'someone asks you to evaluate an idea',
    description:
      'Someone asks you to evaluate an idea: with the due date and a link to the evaluation.',
  },
  evaluation_reminder: {
    label: 'Evaluation reminders',
    one: 'Evaluation reminder',
    phrase: 'evaluation reminders',
    when: 'an evaluation you still owe is nearly due',
    description: 'Before an evaluation you still owe is due, and on the day.',
  },
  evaluations_complete: {
    label: 'All evaluations are in',
    one: 'All evaluations are in',
    phrase: '“all evaluations are in” emails',
    when: 'every evaluator of an idea you own has submitted',
    description: 'Every evaluator of an idea you own has submitted.',
  },
  status_changed: {
    label: 'Status changes',
    one: 'Status change',
    phrase: 'status changes',
    when: 'an idea you own, evaluate or watch moves to another status',
    description: 'An idea you own, evaluate or watch moves to another status.',
  },
  comment: {
    label: 'New comments',
    one: 'New comment',
    phrase: 'new comments',
    when: 'someone comments on an idea you watch',
    description: 'Someone comments on an idea you watch.',
  },
  mention: {
    label: 'Mentions',
    one: 'Mention',
    phrase: 'mentions',
    when: 'someone mentions you in a comment',
    description: 'Someone mentions you in a comment.',
  },
}

/** "evaluation requests", "new comments" (inside a sentence). */
export function typePhrase(type: NotificationType): string {
  return TYPE_COPY[type].phrase
}

/** "08:00" for the digest hour (24-hour, like the instance setting). */
export function digestTime(hour: number): string {
  return `${String(hour).padStart(2, '0')}:00`
}
