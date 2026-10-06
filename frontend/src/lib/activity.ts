import type { ActivityItem, IdeaStatus, Resolution } from '@/api/types'
import { formatDate } from '@/lib/dates'
import { defaultStatusLabel } from '@/lib/status'

const FIELD_NAMES: Record<string, string> = {
  title: 'title',
  summary: 'summary',
  description_md: 'description',
  tags: 'tags',
}

function status(status: IdeaStatus, resolution: Resolution | null, labels?: StatusLabelLookup) {
  return labels ? labels(status, resolution) : defaultStatusLabel(status, resolution)
}

/** Optional project-specific labels (admins can rename statuses). */
export type StatusLabelLookup = (status: IdeaStatus, resolution: Resolution | null) => string

function list(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1] ?? ''}`
}

/**
 * One line of plain text for an activity event, without the actor
 * ("commented", "moved it from New to Evaluating"). Never contains scores —
 * the API doesn't send any in activity.
 */
export function describeActivity(item: ActivityItem, labels?: StatusLabelLookup): string {
  switch (item.type) {
    case 'comment':
      return item.comment.deleted ? 'deleted a comment' : 'commented'
    case 'idea_created':
      // Only the public form creates an idea without an actor (users are never deleted).
      return item.actor ? 'submitted the idea' : 'sent it through the public form'
    case 'idea_edited':
      return `edited the ${list(item.fields.map((field) => FIELD_NAMES[field] ?? field))}`
    case 'status_changed':
      return `moved it from ${status(item.from_status, item.from_resolution, labels)} to ${status(item.to_status, item.to_resolution, labels)}`
    case 'owner_changed':
      if (item.volunteered) return 'volunteered to own it'
      if (item.to_owner && item.to_owner.id === item.actor?.id) return 'took ownership'
      if (!item.to_owner)
        return item.from_owner
          ? `removed ${item.from_owner.display_name} as owner`
          : 'cleared the owner'
      return `made ${item.to_owner.display_name} the owner`
    case 'evaluator_added':
      return `invited ${item.evaluator?.display_name ?? 'someone'} to evaluate`
    case 'evaluator_removed':
      // No actor: an AI run that assigned its agent ended without its evaluation
      // (contract-phase6 §3.3); the agent is the line's subject (activityActor).
      if (!item.actor) return 'ended its run without an evaluation and was taken off the evaluators'
      return `removed ${item.evaluator?.display_name ?? 'an evaluator'} as evaluator`
    case 'evaluation_submitted':
      return 'submitted an evaluation'
    case 'evaluation_closed':
      return 'closed evaluation'
    case 'evaluation_reopened':
      return 'reopened evaluation'
    case 'due_date_changed':
      return item.to_due_at
        ? `set the due date to ${formatDate(item.to_due_at)}`
        : 'cleared the due date'
    case 'ai_research_note':
      // The actor is the agent; someone else deleted it (the agent never deletes).
      return item.note.deleted ? 'wrote a research note, since deleted' : 'wrote a research note'
  }
}

/**
 * Actor name for an event. A public submission has no actor: the name its
 * sender gave (as the idea's header shows it), else "A visitor"; an evaluator
 * taken off by an AI run that ended without its evaluation is the agent itself;
 * anything else without an actor is "Someone".
 */
export function activityActor(item: ActivityItem, submitterName?: string | null): string {
  if (item.actor) return item.actor.display_name
  // An AI run that ended without its evaluation took its agent off the evaluators.
  if (item.type === 'evaluator_removed') return item.evaluator?.display_name ?? 'An AI agent'
  if (item.type !== 'idea_created') return 'Someone'
  const name = submitterName?.trim()
  return name === undefined || name === '' ? 'A visitor' : name
}

/** Invitations this close together read as one: "invited Bob, Carol and Dave to evaluate". */
const GROUP_WITHIN_MS = 10 * 60_000

export interface ActivityEntry {
  /** The run's latest event (its time is shown). */
  item: ActivityItem
  /** Everyone invited in a run of invitations by one person; undefined otherwise. */
  invited?: string[]
}

/**
 * Folds consecutive "invited X to evaluate" events by the same person, a few
 * minutes apart, into one line, so inviting four evaluators isn't four lines.
 */
export function groupActivity(items: readonly ActivityItem[]): ActivityEntry[] {
  const entries: ActivityEntry[] = []
  for (const item of items) {
    const previous = entries.at(-1)
    const name = item.type === 'evaluator_added' ? item.evaluator?.display_name : undefined
    if (
      name &&
      previous?.item.type === 'evaluator_added' &&
      previous.item.actor?.id === item.actor?.id &&
      new Date(item.created_at).getTime() - new Date(previous.item.created_at).getTime() <=
        GROUP_WITHIN_MS
    ) {
      const invited = previous.invited ?? [previous.item.evaluator?.display_name ?? 'someone']
      entries[entries.length - 1] = { item, invited: [...invited, name] }
    } else {
      entries.push({ item })
    }
  }
  return entries
}

/** describeActivity for a grouped entry. */
export function describeEntry(entry: ActivityEntry, labels?: StatusLabelLookup): string {
  return entry.invited && entry.invited.length > 1
    ? `invited ${list(entry.invited)} to evaluate`
    : describeActivity(entry.item, labels)
}
