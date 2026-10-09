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
    case 'status_changed': {
      // Phase 8b (review C6): the project's labels come with the event (a guest
      // researcher can't read the project); older shapes fall back to the lookup.
      const from = item.from_label ?? status(item.from_status, item.from_resolution, labels)
      const to = item.to_label ?? status(item.to_status, item.to_resolution, labels)
      // Phase 8: an admin's "Move anyway" past open research items says so.
      return `moved it from ${from} to ${to}${item.research_overridden ? ' without finishing research' : ''}`
    }
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
    // Phase 8b (contract-phase8b §3.6).
    case 'researcher_changed': {
      if (item.handed_back) return 'handed the research back'
      const to = item.to_researcher
      const from = item.from_researcher
      if (!to) return from ? `removed ${from.display_name} as researcher` : 'removed the researcher'
      if (to.id === item.actor?.id) {
        return from
          ? `took on the research instead of ${from.display_name}`
          : 'took on the research'
      }
      return from
        ? `asked ${to.display_name} instead of ${from.display_name} to research`
        : `asked ${to.display_name} to research`
    }
    case 'research_due_date_changed':
      return item.to_due_at
        ? `set the research due date to ${formatDate(item.to_due_at)}`
        : 'removed the research due date'
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
  /**
   * Phase 8b (UX m3): the research due date set in the same change as the researcher
   * (one line, "asked Bob Brown to research, due Mon 12 Oct"); null when it was removed,
   * undefined when nothing was folded in.
   */
  researchDue?: string | null
}

type ResearcherChanged = Extract<ActivityItem, { type: 'researcher_changed' }>
type ResearchDueChanged = Extract<ActivityItem, { type: 'research_due_date_changed' }>

/** The researcher and the due date changed by one request: its two events, a moment apart. */
const SAME_CHANGE_MS = 5_000

function sameChange(a: ActivityItem, b: ActivityItem): boolean {
  return (
    a.actor?.id === b.actor?.id &&
    Math.abs(new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) <= SAME_CHANGE_MS
  )
}

/** A researcher change and a due-date change from one request, as one entry. */
function foldResearchDue(previous: ActivityEntry, item: ActivityItem): ActivityEntry | null {
  if (previous.researchDue !== undefined || !sameChange(previous.item, item)) return null
  const pair: [ActivityItem, ActivityItem] = [previous.item, item]
  const researcher = pair.find((one): one is ResearcherChanged => one.type === 'researcher_changed')
  const due = pair.find(
    (one): one is ResearchDueChanged => one.type === 'research_due_date_changed',
  )
  if (!researcher || !due || researcher.handed_back) return null
  return { item: researcher, researchDue: due.to_due_at }
}

/**
 * Folds consecutive "invited X to evaluate" events by the same person, a few
 * minutes apart, into one line, so inviting four evaluators isn't four lines.
 */
export function groupActivity(items: readonly ActivityItem[]): ActivityEntry[] {
  const entries: ActivityEntry[] = []
  for (const item of items) {
    const previous = entries.at(-1)
    const folded = previous ? foldResearchDue(previous, item) : null
    if (folded) {
      entries[entries.length - 1] = folded
      continue
    }
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
  if (entry.invited && entry.invited.length > 1) return `invited ${list(entry.invited)} to evaluate`
  const text = describeActivity(entry.item, labels)
  if (entry.researchDue === undefined || entry.item.type !== 'researcher_changed') return text
  if (entry.researchDue === null) return `${text} and removed the research due date`
  const day = formatDate(entry.researchDue)
  return entry.item.to_researcher
    ? `${text}, due ${day}`
    : `${text} and set the research due date to ${day}`
}
