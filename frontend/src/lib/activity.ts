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
      return 'submitted the idea'
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
  }
}

/** Actor name for an event ("Someone" when the user no longer exists). */
export function activityActor(item: ActivityItem): string {
  return item.actor?.display_name ?? 'Someone'
}
