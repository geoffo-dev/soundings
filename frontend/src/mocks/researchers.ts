/**
 * Phase 8b in the mock API (contract-phase8b): one researcher per idea, the
 * research due date, the guest researcher's access (role matrix column R and the
 * +Rsr overlay, table L), "Research to do" and what ends an assignment. The
 * backend's policy module is the authority; this follows it closely enough to
 * build and test the screens.
 */
import type {
  ActivityType,
  IdeaStatus,
  NotificationType,
  ResearchAssignment,
  WorkResearch,
} from '@/api/types'
import { gatedStatuses, showsResearchProgress } from '@/lib/status'

import { recordAudit } from './access'
import type { MockDb, MockIdea, MockProject, MockUser } from './db'
import {
  canViewProject,
  effectiveRole,
  findUser,
  ideaRef,
  isListed,
  isProjectAdmin,
  projectOf,
  userRef,
  userRefById,
} from './domain'
import { researchProgress } from './research'

/** The feed a guest researcher reads (`RESEARCH_GUEST_ACTIVITY_TYPES`, an allow-list). */
export const RESEARCH_GUEST_ACTIVITY_TYPES: readonly ActivityType[] = [
  'comment',
  'idea_created',
  'idea_edited',
  'status_changed',
  'owner_changed',
  'ai_research_note',
  'researcher_changed',
  'research_due_date_changed',
]

/** The inbox items a guest researcher keeps (`RESEARCH_GUEST_NOTIFICATION_TYPES`). */
export const RESEARCH_GUEST_NOTIFICATION_TYPES: readonly NotificationType[] = [
  'status_changed',
  'comment',
  'mention',
  'researcher_assigned',
  'research_reminder',
]

const memberish = (role: string | null) => role === 'member' || role === 'admin'

/** c24: assigned, the project's step on and not archived, the idea open and not held. */
export function assignmentLive(db: MockDb, idea: MockIdea): boolean {
  if (!idea.researcher_id) return false
  const project = projectOf(db, idea)
  return (
    project.research_step !== 'off' &&
    project.archived_at === null &&
    idea.status !== 'closed' &&
    !idea.held_for
  )
}

/** The +Rsr overlay: the idea's live researcher (an active person). */
export function isLiveResearcher(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return (
    idea.researcher_id === user.id &&
    user.is_active &&
    !user.is_service_account &&
    assignmentLive(db, idea)
  )
}

/** Column R: the live researcher without `project.view` (a private project's non-member). */
export function isResearchGuest(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return isLiveResearcher(db, idea, user) && !canViewProject(db, projectOf(db, idea), user)
}

/** c23: any active person: never a service account, the break-glass account or inactive. */
export function eligibleResearcher(user: MockUser | undefined): user is MockUser {
  return Boolean(user?.is_active && !user.is_service_account && !user.is_break_glass)
}

export function hasRole(db: MockDb, projectId: string, userId: string): boolean {
  return effectiveRole(db, projectId, userId) !== null
}

/** `idea.assign_researcher` without its conditions: the owner (member or admin) and admins. */
export function mayAssignResearcher(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  if (user.is_service_account) return false
  const project = projectOf(db, idea)
  if (isProjectAdmin(db, project, user)) return true
  return idea.owner_id === user.id && memberish(effectiveRole(db, project.id, user.id))
}

/** The rule's conditions: the step on, the idea open, writable. */
function assignable(db: MockDb, idea: MockIdea): boolean {
  const project = projectOf(db, idea)
  return (
    project.research_step !== 'off' &&
    project.archived_at === null &&
    idea.status !== 'closed' &&
    !idea.held_for
  )
}

export function canAssignResearcher(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return mayAssignResearcher(db, idea, user) && assignable(db, idea)
}

/**
 * The product owner's S1 (a): in a private project only project and platform
 * admins may name someone without a role there; internal projects: the owner too.
 */
export function mayNameOutsider(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  const project = projectOf(db, idea)
  return project.visibility === 'internal' || isProjectAdmin(db, project, user)
}

export function canAssignOutsideResearcher(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return canAssignResearcher(db, idea, user) && mayNameOutsider(db, idea, user)
}

export function canHandBack(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return isLiveResearcher(db, idea, user)
}

function visibleWhileOn(db: MockDb, idea: MockIdea): boolean {
  return projectOf(db, idea).research_step !== 'off'
}

/** `IdeaSummary.researcher`: null while the step is off or nobody is assigned. */
export function summaryResearcher(db: MockDb, idea: MockIdea) {
  return visibleWhileOn(db, idea) ? userRefById(db, idea.researcher_id) : null
}

export function summaryResearchDue(db: MockDb, idea: MockIdea): string | null {
  return visibleWhileOn(db, idea) ? (idea.research_due_at ?? null) : null
}

/** Not past Research and open: the research still lies ahead or is under way. */
export function awaitsResearch(project: MockProject, status: IdeaStatus): boolean {
  if (project.research_step === 'off' || status === 'closed') return false
  return !gatedStatuses(project.research_step).includes(status)
}

export function researchAssignment(db: MockDb, idea: MockIdea): ResearchAssignment {
  const project = projectOf(db, idea)
  if (project.research_step === 'off') {
    return {
      researcher: null,
      researcher_in_project: false,
      assigned_at: null,
      due_at: null,
      overdue: false,
    }
  }
  const researcher = findUser(db, idea.researcher_id)
  const due = idea.research_due_at ?? null
  const progress = researchProgress(db, idea)
  return {
    researcher: researcher ? userRef(researcher) : null,
    researcher_in_project: researcher ? hasRole(db, project.id, researcher.id) : false,
    assigned_at: researcher ? (idea.research_assigned_at ?? null) : null,
    due_at: due,
    overdue:
      due !== null &&
      Date.parse(due) < Date.now() &&
      awaitsResearch(project, idea.status) &&
      progress.required_open > 0,
  }
}

/**
 * Clears an assignment without anyone removing it (deactivation, closing, the
 * step off, a lost role in a private project): audited, no event or notification,
 * the due date kept.
 */
export function clearAssignment(
  db: MockDb,
  idea: MockIdea,
  actor: MockUser | null,
  reason: 'deactivated' | 'closed' | 'step_off' | 'left_project',
): void {
  if (!idea.researcher_id) return
  const from = idea.researcher_id
  idea.researcher_id = null
  idea.research_assigned_at = null
  recordAudit(
    db,
    actor,
    'idea.researcher_change',
    { type: 'idea', id: idea.id },
    { from_user_id: from, to_user_id: null, reason, outside_project: false },
    idea.project_id,
  )
}

/** Who researches an idea of a private project while holding a role there (S1 b). */
export function researcherRoles(db: MockDb): Set<string> {
  const out = new Set<string>()
  for (const idea of db.ideas) {
    if (!idea.researcher_id) continue
    const project = projectOf(db, idea)
    if (project.visibility === 'private' && hasRole(db, project.id, idea.researcher_id)) {
      out.add(`${project.id}:${idea.researcher_id}`)
    }
  }
  return out
}

/**
 * S1 (b), the product owner's answer: someone who loses their role in a private
 * project stops being the researcher of its ideas (audited `left_project`, answers
 * kept, no event). Compare against `researcherRoles` taken before the change.
 */
export function clearLostResearchers(
  db: MockDb,
  actor: MockUser | null,
  before: Set<string>,
): void {
  for (const idea of db.ideas) {
    if (!idea.researcher_id) continue
    const key = `${idea.project_id}:${idea.researcher_id}`
    if (before.has(key) && !hasRole(db, idea.project_id, idea.researcher_id)) {
      clearAssignment(db, idea, actor, 'left_project')
    }
  }
}

/* ------------------------------------------------------------------ */
/* Guest access by route (table L): view, rule or hidden (404)        */
/* ------------------------------------------------------------------ */

export type GuestAccess = 'view' | 'rule' | 'hidden'

const GUEST_ROUTES: [method: string, pattern: RegExp, access: GuestAccess][] = [
  ['GET', /^$/, 'view'],
  ['PATCH', /^$/, 'rule'],
  ['DELETE', /^$/, 'rule'],
  ['GET', /^\/activity$/, 'view'],
  ['POST', /^\/comments$/, 'rule'],
  ['PUT', /^\/watch$/, 'view'],
  ['DELETE', /^\/watch$/, 'view'],
  ['GET', /^\/research$/, 'view'],
  ['PUT', /^\/research\/items\/[^/]+$/, 'rule'],
  ['DELETE', /^\/research\/items\/[^/]+$/, 'rule'],
  ['GET', /^\/similar-ideas$/, 'view'],
  ['PUT', /^\/research\/assignment$/, 'rule'],
  ['DELETE', /^\/research\/assignment$/, 'rule'],
  ['GET', /^\/research-notes\/[^/]+$/, 'view'],
  ['DELETE', /^\/research-notes\/[^/]+$/, 'rule'],
  ['POST', /^\/status$/, 'rule'],
  ['PUT', /^\/owner$/, 'rule'],
  ['POST', /^\/volunteer$/, 'rule'],
  ['PUT', /^\/vote$/, 'rule'],
  ['DELETE', /^\/vote$/, 'rule'],
]

/** A route's outcome for column R; anything not listed is hidden (deny by default). */
export function guestAccess(method: string, pathname: string): GuestAccess {
  const match = /\/api\/v1\/ideas\/[^/]+(.*)$/.exec(pathname)
  if (!match) return 'hidden'
  const rest = match[1] ?? ''
  const row = GUEST_ROUTES.find(([m, pattern]) => m === method.toUpperCase() && pattern.test(rest))
  return row ? row[2] : 'hidden'
}

/* ------------------------------------------------------------------ */
/* My work: "Research to do" (contract-phase8b §7)                     */
/* ------------------------------------------------------------------ */

function researchToDoRow(db: MockDb, idea: MockIdea, user: MockUser): WorkResearch | null {
  if (!isListed(idea)) return null
  const project = projectOf(db, idea)
  if (project.archived_at !== null || !awaitsResearch(project, idea.status)) return null
  const progress = researchProgress(db, idea)
  if (progress.required_open === 0) return null
  let asOwner = false
  if (idea.researcher_id) {
    if (!isLiveResearcher(db, idea, user)) return null
  } else {
    if (idea.owner_id !== user.id) return null
    const role = effectiveRole(db, project.id, user.id)
    if (!memberish(role) && !user.is_platform_admin) return null
    if (!showsResearchProgress(project.research_step, idea.status) && !idea.research_due_at) {
      return null
    }
    asOwner = true
  }
  const due = idea.research_due_at ?? null
  return {
    idea: ideaRef(db, idea),
    can_view_project: canViewProject(db, project, user),
    owner: userRefById(db, idea.owner_id),
    as_owner: asOwner,
    due_at: due,
    overdue: due !== null && Date.parse(due) < Date.now(),
    progress,
  }
}

/** Overdue first, then soonest due, no due date last; then by idea id. */
export function researchToDo(db: MockDb, user: MockUser): WorkResearch[] {
  const rows = db.ideas.flatMap((idea) => researchToDoRow(db, idea, user) ?? [])
  rows.sort((a, b) => {
    if (a.due_at !== b.due_at) {
      if (a.due_at === null) return 1
      if (b.due_at === null) return -1
      return a.due_at.localeCompare(b.due_at)
    }
    return a.idea.id.localeCompare(b.idea.id)
  })
  return rows
}

/** Ideas the user researches with the assignment live (`researched_ideas`). */
export function researchedIdeas(db: MockDb, user: MockUser): MockIdea[] {
  return db.ideas.filter((idea) => isListed(idea) && isLiveResearcher(db, idea, user))
}
