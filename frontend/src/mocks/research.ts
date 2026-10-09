/**
 * Phase 8 research step in the mock API (contract-phase8 §3): the project's step
 * and checklist, each idea's answers, the gate and "Similar ideas". Records mirror
 * `research_checklist_items` and `research_answers`; the lifecycle rules are the
 * shared ones in `lib/status.ts` (the backend's `app.schemas.research`). The
 * backend is the authority.
 */
import type {
  DefaultChecklistItem,
  IdeaResearch,
  IdeaStatus,
  ResearchProgress,
  ResearchSettings,
  SimilarIdea,
} from '@/api/types'
import {
  crossesGate,
  gatedStatuses,
  gateStatus,
  showsResearchProgress,
  type ResearchStep,
} from '@/lib/status'

import type { MockDb, MockIdea, MockProject, MockUser } from './db'
import {
  canViewIdea,
  canViewProject,
  effectiveRole,
  ideaRef,
  isListed,
  isProjectAdmin,
  projectOf,
  rowsForIdea,
  statusLabels,
  userRefById,
} from './domain'
import {
  canAssignOutsideResearcher,
  canAssignResearcher,
  canHandBack,
  isLiveResearcher,
  researchAssignment,
  researchedIdeas,
} from './researchers'

export interface MockResearchItem {
  id: string
  project_id: string
  title: string
  hint: string
  required: boolean
  position: number
  archived_at: string | null
}

export interface MockResearchAnswer {
  idea_id: string
  item_id: string
  answer: string
  answered_by_id: string | null
  answered_at: string
  updated_by_id: string | null
  updated_at: string
}

export const MIN_RESEARCH_ITEMS = 1
export const MAX_RESEARCH_ITEMS = 10
export const RESEARCH_TITLE_MAX_LENGTH = 80
export const RESEARCH_HINT_MAX_LENGTH = 200
export const RESEARCH_ANSWER_MAX_LENGTH = 2000
export const OVERRIDE_REASON_MAX_LENGTH = 200
/** `pg_trgm`'s default threshold, and the panel's limit (contract-phase8 §3.7). */
export const SIMILARITY_THRESHOLD = 0.3
export const SIMILAR_LIMIT = 5

/** `DEFAULT_RESEARCH_CHECKLIST`: offered when the step is turned on with no checklist. */
export const DEFAULT_RESEARCH_CHECKLIST: readonly DefaultChecklistItem[] = [
  {
    title: 'Not already being done elsewhere',
    hint: 'Search Soundings and ask around; note what you found.',
    required: true,
  },
  {
    title: 'Departments or teams consulted',
    hint: 'Who you spoke to and what they said.',
    required: true,
  },
  {
    title: 'Data protection considered',
    hint: 'Personal data involved, and who you checked with.',
    required: false,
  },
]

/** Invisible characters removed from answers (`INVISIBLE_CHARACTERS`; ZWJ/ZWNJ kept). */
const INVISIBLE =
  /[\u00ad\u061c\u180e\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]/g

export function visibleAnswer(text: string): string {
  return text.replace(INVISIBLE, '').trim()
}

export function stepOf(db: MockDb, idea: MockIdea): ResearchStep {
  return projectOf(db, idea).research_step
}

export function activeItems(db: MockDb, projectId: string): MockResearchItem[] {
  return db.researchItems
    .filter((item) => item.project_id === projectId && item.archived_at === null)
    .sort((a, b) => a.position - b.position)
}

export function answerOf(db: MockDb, ideaId: string, itemId: string) {
  return db.researchAnswers.find((a) => a.idea_id === ideaId && a.item_id === itemId)
}

function answeredIds(db: MockDb, idea: MockIdea): Set<string> {
  return new Set(rowsForIdea(db.researchAnswers, idea.id).map((a) => a.item_id))
}

/** Active required items this idea hasn't answered, in checklist order. */
export function openRequired(db: MockDb, idea: MockIdea): MockResearchItem[] {
  const answered = answeredIds(db, idea)
  return activeItems(db, idea.project_id).filter((i) => i.required && !answered.has(i.id))
}

export function researchProgress(db: MockDb, idea: MockIdea): ResearchProgress {
  const items = activeItems(db, idea.project_id)
  const answered = answeredIds(db, idea)
  return {
    answered: items.filter((i) => answered.has(i.id)).length,
    total: items.length,
    required_open: items.filter((i) => i.required && !answered.has(i.id)).length,
  }
}

/** `IdeaSummary.research`: only for an idea in Research or the status right before it. */
export function summaryResearch(db: MockDb, idea: MockIdea): ResearchProgress | null {
  const step = stepOf(db, idea)
  return showsResearchProgress(step, idea.status) ? researchProgress(db, idea) : null
}

/**
 * `idea.answer_research` without its conditions: the owner (member or admin), admins
 * and (Phase 8b, +Rsr) the idea's live researcher, guest or not.
 */
export function mayAnswer(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  if (user.is_service_account) return false
  const project = projectOf(db, idea)
  if (isProjectAdmin(db, project, user)) return true
  if (isLiveResearcher(db, idea, user)) return true
  const role = effectiveRole(db, project.id, user.id)
  return idea.owner_id === user.id && (role === 'member' || role === 'admin')
}

/** `idea.research_override`: project and platform admins, in a session. */
export function mayOverride(db: MockDb, project: MockProject, user: MockUser): boolean {
  return !user.is_service_account && isProjectAdmin(db, project, user)
}

/** The rule with its conditions: step on, not closed, writable (archived, held). */
export function canAnswer(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  const project = projectOf(db, idea)
  return (
    mayAnswer(db, idea, user) &&
    project.research_step !== 'off' &&
    idea.status !== 'closed' &&
    project.archived_at === null &&
    !idea.held_for
  )
}

/** The status the idea was closed from (its latest `status_changed` into closed). */
export function closedFrom(db: MockDb, idea: MockIdea): IdeaStatus | null {
  const event = rowsForIdea(db.events, idea.id)
    .filter((e) => e.type === 'status_changed' && e.payload.to_status === 'closed')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  return (event?.payload.from_status as IdeaStatus | undefined) ?? null
}

/** An invite (or "Ask AI to evaluate") the gate guards: the first evaluator before evaluation. */
export function startsEvaluation(db: MockDb, idea: MockIdea): boolean {
  const step = stepOf(db, idea)
  return (
    step === 'before_evaluation' &&
    rowsForIdea(db.assignments, idea.id).length === 0 &&
    !gatedStatuses(step).includes(idea.status)
  )
}

export function inviteBlocked(db: MockDb, idea: MockIdea): boolean {
  return startsEvaluation(db, idea) && openRequired(db, idea).length > 0
}

/** "Start proposal" would move the idea past Research with required items open. */
export function proposalStartBlocked(db: MockDb, idea: MockIdea): boolean {
  const step = stepOf(db, idea)
  return (
    idea.status !== 'proposal' &&
    crossesGate(step, idea.status, 'proposal') &&
    openRequired(db, idea).length > 0
  )
}

export function ideaResearch(db: MockDb, idea: MockIdea, user: MockUser): IdeaResearch {
  const project = projectOf(db, idea)
  const step = project.research_step
  const on = step !== 'off'
  const progress: ResearchProgress = on
    ? researchProgress(db, idea)
    : { answered: 0, total: 0, required_open: 0 }
  const gate = gateStatus(step)
  return {
    step,
    gate_status: gate,
    gate_status_label: gate ? statusLabels(project)[gate] : null,
    assignment: researchAssignment(db, idea),
    items: on
      ? activeItems(db, project.id).map((item) => {
          const answer = answerOf(db, idea.id, item.id)
          return {
            item_id: item.id,
            title: item.title,
            hint: item.hint,
            required: item.required,
            answer: answer
              ? {
                  answer: answer.answer,
                  answered_by: userRefById(db, answer.answered_by_id),
                  answered_at: answer.answered_at,
                  updated_by: userRefById(db, answer.updated_by_id),
                  updated_at: answer.updated_at,
                }
              : null,
          }
        })
      : [],
    progress,
    blocking:
      on &&
      progress.required_open > 0 &&
      idea.status !== 'closed' &&
      !gatedStatuses(step).includes(idea.status),
    permissions: {
      can_answer: canAnswer(db, idea, user),
      can_override: on && mayOverride(db, project, user),
      can_assign: canAssignResearcher(db, idea, user),
      can_assign_outside_researcher: canAssignOutsideResearcher(db, idea, user),
      can_hand_back: canHandBack(db, idea, user),
    },
  }
}

export function researchSettingsOut(db: MockDb, project: MockProject): ResearchSettings {
  const answers = new Map<string, number>()
  for (const answer of db.researchAnswers) {
    answers.set(answer.item_id, (answers.get(answer.item_id) ?? 0) + 1)
  }
  return {
    step: project.research_step,
    items: activeItems(db, project.id).map((item) => ({
      id: item.id,
      title: item.title,
      hint: item.hint,
      required: item.required,
      position: item.position,
    })),
    removed_items: db.researchItems
      .filter((item) => item.project_id === project.id && item.archived_at !== null)
      .sort((a, b) => (b.archived_at ?? '').localeCompare(a.archived_at ?? ''))
      .map((item) => ({
        id: item.id,
        title: item.title,
        hint: item.hint,
        required: item.required,
        // Phase 8b (D): where it was, so Restore puts it back there.
        position: item.position,
        removed_at: item.archived_at ?? '',
        answer_count: Math.max(1, answers.get(item.id) ?? 0),
      })),
    default_items: DEFAULT_RESEARCH_CHECKLIST.map((item) => ({ ...item })),
    ideas_in_research: db.ideas.filter(
      (idea) => idea.project_id === project.id && idea.status === 'research',
    ).length,
  }
}

/* ------------------------------------------------------------------ */
/* Similar ideas (pg_trgm similarity, contract-phase8 §3.7)            */
/* ------------------------------------------------------------------ */

/** pg_trgm's trigrams: each alphanumeric word lower-cased, padded "  word ". */
function trigrams(text: string): Set<string> {
  const out = new Set<string>()
  for (const word of text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []) {
    const padded = `  ${word} `
    for (let i = 0; i + 3 <= padded.length; i += 1) out.add(padded.slice(i, i + 3))
  }
  return out
}

/** `similarity(a, b)`: shared trigrams over all trigrams of both. */
export function similarity(a: string, b: string): number {
  const left = trigrams(a)
  const right = trigrams(b)
  if (left.size === 0 || right.size === 0) return 0
  let shared = 0
  for (const t of left) if (right.has(t)) shared += 1
  return shared / (left.size + right.size - shared)
}

export function similarIdeas(db: MockDb, idea: MockIdea, user: MockUser): SimilarIdea[] {
  // Phase 8b: the ideas the viewer can list, or researches (never a private project's others).
  const researched = new Set(researchedIdeas(db, user).map((i) => i.id))
  const candidates = db.ideas.filter(
    (other) =>
      other.id !== idea.id &&
      isListed(other) &&
      ((canViewProject(db, projectOf(db, other), user) && canViewIdea(db, other, user)) ||
        researched.has(other.id)),
  )
  return candidates
    .map((other) => ({
      other,
      score:
        Math.round(
          Math.max(similarity(idea.title, other.title), similarity(idea.summary, other.summary)) *
            100,
        ) / 100,
    }))
    .filter(({ score }) => score >= SIMILARITY_THRESHOLD)
    .sort(
      (a, b) =>
        b.score - a.score ||
        b.other.last_activity_at.localeCompare(a.other.last_activity_at) ||
        a.other.id.localeCompare(b.other.id),
    )
    .slice(0, SIMILAR_LIMIT)
    .map(({ other, score }) => ({
      ...ideaRef(db, other),
      summary: other.summary,
      owner: userRefById(db, other.owner_id),
      last_activity_at: other.last_activity_at,
      similarity: score,
    }))
}
