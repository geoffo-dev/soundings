/**
 * Idea lifecycle (SPEC §2): New → Evaluating → Shortlisted → Proposal → Closed.
 * Closed carries a resolution. Admins can rename labels but not add stages, so
 * UI code should take labels from project settings and fall back to these.
 */
export const IDEA_STATUSES = ['new', 'evaluating', 'shortlisted', 'proposal', 'closed'] as const
export type IdeaStatus = (typeof IDEA_STATUSES)[number]

export const CLOSED_RESOLUTIONS = ['accepted', 'rejected', 'parked'] as const
export type ClosedResolution = (typeof CLOSED_RESOLUTIONS)[number]

/** Colour keys in the design tokens (bg-status-*). */
export type StatusTone = Exclude<IdeaStatus, 'closed'> | ClosedResolution

export const DEFAULT_STATUS_LABELS: Record<IdeaStatus, string> = {
  new: 'New',
  evaluating: 'Evaluating',
  shortlisted: 'Shortlisted',
  proposal: 'Proposal',
  closed: 'Closed',
}

export const DEFAULT_RESOLUTION_LABELS: Record<ClosedResolution, string> = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  parked: 'Parked',
}

export function statusTone(status: IdeaStatus, resolution?: ClosedResolution | null): StatusTone {
  if (status !== 'closed') return status
  return resolution ?? 'parked'
}

export function defaultStatusLabel(
  status: IdeaStatus,
  resolution?: ClosedResolution | null,
): string {
  if (status === 'closed' && resolution) return DEFAULT_RESOLUTION_LABELS[resolution]
  return DEFAULT_STATUS_LABELS[status]
}
