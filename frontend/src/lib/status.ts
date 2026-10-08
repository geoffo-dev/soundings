/**
 * Idea lifecycle (SPEC §2, amended by Phase 8): New → Evaluating → Shortlisted →
 * Proposal → Closed, plus an optional Research stage a project can switch on
 * before evaluation or before the proposal (contract-phase8 §3.2). Closed carries
 * a resolution. Admins can rename labels, so UI code takes labels from project
 * settings and falls back to these. A project's own order is `Project.lifecycle`
 * (from the API; `lifecycle(step)` here is the same rule); views across projects
 * use the canonical order, Research after New.
 */
export const IDEA_STATUSES = [
  'new',
  'research',
  'evaluating',
  'shortlisted',
  'proposal',
  'closed',
] as const
export type IdeaStatus = (typeof IDEA_STATUSES)[number]

export const CLOSED_RESOLUTIONS = ['accepted', 'rejected', 'parked'] as const
export type ClosedResolution = (typeof CLOSED_RESOLUTIONS)[number]

export type ResearchStep = 'off' | 'before_evaluation' | 'before_proposal'

/** Colour keys in the design tokens (bg-status-*). */
export type StatusTone = Exclude<IdeaStatus, 'closed'> | ClosedResolution

export const DEFAULT_STATUS_LABELS: Record<IdeaStatus, string> = {
  new: 'New',
  research: 'Research',
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

/* ------------------------------------------------------------------ */
/* The research step (contract-phase8 §3.2, §3.5; app.schemas.research) */
/* ------------------------------------------------------------------ */

const LIFECYCLES: Record<ResearchStep, readonly IdeaStatus[]> = {
  off: ['new', 'evaluating', 'shortlisted', 'proposal', 'closed'],
  before_evaluation: ['new', 'research', 'evaluating', 'shortlisted', 'proposal', 'closed'],
  before_proposal: ['new', 'evaluating', 'shortlisted', 'research', 'proposal', 'closed'],
}

/** A project's statuses in board order: five while the step is off, six with Research. */
export function lifecycle(step: ResearchStep): readonly IdeaStatus[] {
  return LIFECYCLES[step]
}

/** The status right after Research (`evaluating` or `proposal`); null while off. */
export function gateStatus(step: ResearchStep): IdeaStatus | null {
  if (step === 'off') return null
  const order = LIFECYCLES[step]
  return order[order.indexOf('research') + 1] ?? null
}

/** The status right before Research (`new` or `shortlisted`); null while off. */
export function statusBeforeResearch(step: ResearchStep): IdeaStatus | null {
  if (step === 'off') return null
  const order = LIFECYCLES[step]
  return order[order.indexOf('research') - 1] ?? null
}

/** The statuses after Research, Closed excluded: the ones the checklist guards. */
export function gatedStatuses(step: ResearchStep): readonly IdeaStatus[] {
  if (step === 'off') return []
  const order = LIFECYCLES[step]
  return order.slice(order.indexOf('research') + 1).filter((status) => status !== 'closed')
}

/**
 * A move the checklist guards: into a status after Research from one that isn't.
 * A closed idea counts from the status it was closed from (unknown: New).
 */
export function crossesGate(
  step: ResearchStep,
  from: IdeaStatus,
  to: IdeaStatus,
  closedFrom: IdeaStatus | null = null,
): boolean {
  const gated = gatedStatuses(step)
  const start =
    from === 'closed' ? (closedFrom && closedFrom !== 'closed' ? closedFrom : 'new') : from
  return gated.includes(to) && !gated.includes(start)
}

/** Whether a card shows research progress: an idea in Research or the status before it. */
export function showsResearchProgress(step: ResearchStep, status: IdeaStatus): boolean {
  return step !== 'off' && (status === 'research' || status === statusBeforeResearch(step))
}

/** What public tracking reports for a status: Research reads as the status before it. */
export function publicStatus(step: ResearchStep, status: IdeaStatus): IdeaStatus {
  if (status !== 'research') return status
  return statusBeforeResearch(step) ?? 'new'
}

/** "Before evaluation", "Before proposal", "Off": the step in words. */
export const RESEARCH_STEP_LABELS: Record<ResearchStep, string> = {
  off: 'Off',
  before_evaluation: 'Before evaluation',
  before_proposal: 'Before proposal',
}
