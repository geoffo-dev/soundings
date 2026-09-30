/**
 * Business rules of the mock API (docs/api/contract-phase1.md, docs/role-matrix.md):
 * effective roles, permissions booleans, blind evaluation, the aggregate score,
 * list filters/sorts/cursors, the board, My work and search. Everything takes
 * the database and the viewer explicitly so it is easy to unit test.
 *
 * It follows the contract closely enough for UI work; the backend is the real
 * implementation and its tests are the authority.
 */
import type {
  ActivityItem,
  AggregateScore,
  Board,
  CommentBody,
  CriterionAggregate,
  CurrentUser,
  Evaluation,
  IdeaDetail,
  IdeaEvaluator,
  IdeaFilters,
  IdeaPermissions,
  IdeaRef,
  IdeaSort,
  IdeaStatus,
  IdeaSummary,
  Member,
  MyEvaluation,
  Project,
  ProjectPermissions,
  ProjectRef,
  ProjectRole,
  ProjectSummary,
  Resolution,
  RubricCriterion,
  StatusLabels,
  UserRef,
  UserSearchResult,
  WorkEvaluation,
  WorkOwnedGroup,
} from '@/api/types'

import type {
  MockComment,
  MockCriterion,
  MockDb,
  MockEvaluation,
  MockEvent,
  MockIdea,
  MockProject,
  MockUser,
} from './db'

export const STATUSES: IdeaStatus[] = ['new', 'evaluating', 'shortlisted', 'proposal', 'closed']
export const RESOLUTIONS: Resolution[] = ['accepted', 'rejected', 'parked']

export const DEFAULT_STATUS_LABELS: StatusLabels = {
  new: 'New',
  evaluating: 'Evaluating',
  shortlisted: 'Shortlisted',
  proposal: 'Proposal',
  closed: 'Closed',
  accepted: 'Accepted',
  rejected: 'Rejected',
  parked: 'Parked',
}

/* ------------------------------------------------------------------ */
/* Lookups                                                             */
/* ------------------------------------------------------------------ */

export function findUser(db: MockDb, id: string | null | undefined): MockUser | undefined {
  return id ? db.users.find((user) => user.id === id) : undefined
}

export function findProjectBySlug(db: MockDb, slug: string): MockProject | undefined {
  return db.projects.find((project) => project.slug === slug)
}

export function projectOf(db: MockDb, idea: MockIdea): MockProject {
  const project = db.projects.find((p) => p.id === idea.project_id)
  if (!project) throw new Error(`idea ${idea.id} has no project`)
  return project
}

export function ideaKey(db: MockDb, idea: MockIdea): string {
  return `${projectOf(db, idea).key}-${idea.number}`
}

/** `{idea}` path parameter: a UUID or a key in any case. */
export function findIdea(db: MockDb, ref: string): MockIdea | undefined {
  const lower = ref.toLowerCase()
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(lower)) {
    return db.ideas.find((idea) => idea.id === lower)
  }
  const match = /^([a-z][a-z0-9]{1,5})-([1-9][0-9]*)$/.exec(lower)
  if (!match) return undefined
  const project = db.projects.find((p) => p.key.toLowerCase() === match[1])
  if (!project) return undefined
  const number = Number(match[2])
  return db.ideas.find((idea) => idea.project_id === project.id && idea.number === number)
}

export function isValidIdeaRef(ref: string): boolean {
  return (
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(ref) ||
    /^[a-z][a-z0-9]{1,5}-[1-9][0-9]*$/i.test(ref)
  )
}

export function activeCriteria(db: MockDb, projectId: string): MockCriterion[] {
  return db.criteria
    .filter((criterion) => criterion.project_id === projectId && !criterion.archived)
    .sort((a, b) => a.position - b.position)
}

/**
 * Per-idea indexes for the row arrays (assignments, evaluations, comments,
 * events) and vote counts, so the 10k-idea dataset stays fast. An index is
 * rebuilt when its array's length changes or after `invalidateIndexes()`,
 * which the handlers call after every write.
 */
let indexGeneration = 0

export function invalidateIndexes(): void {
  indexGeneration += 1
}

interface IndexEntry<V> {
  size: number
  generation: number
  map: Map<string, V>
}

const ideaIndexCache = new WeakMap<object, IndexEntry<unknown[]>>()

export function rowsForIdea<T extends { idea_id: string }>(rows: T[], ideaId: string): T[] {
  let cached = ideaIndexCache.get(rows)
  if (cached?.size !== rows.length || cached.generation !== indexGeneration) {
    const map = new Map<string, unknown[]>()
    for (const row of rows) {
      const list = map.get(row.idea_id)
      if (list) list.push(row)
      else map.set(row.idea_id, [row])
    }
    cached = { size: rows.length, generation: indexGeneration, map }
    ideaIndexCache.set(rows, cached)
  }
  return (cached.map.get(ideaId) ?? []) as T[]
}

const voteIndexCache = new WeakMap<Set<string>, IndexEntry<number>>()

export function countVotes(db: MockDb, ideaId: string): number {
  let cached = voteIndexCache.get(db.votes)
  if (cached?.size !== db.votes.size || cached.generation !== indexGeneration) {
    const map = new Map<string, number>()
    for (const vote of db.votes) {
      const id = vote.slice(0, vote.indexOf(':'))
      map.set(id, (map.get(id) ?? 0) + 1)
    }
    cached = { size: db.votes.size, generation: indexGeneration, map }
    voteIndexCache.set(db.votes, cached)
  }
  return cached.map.get(ideaId) ?? 0
}

/* ------------------------------------------------------------------ */
/* Roles and visibility                                                */
/* ------------------------------------------------------------------ */

/** Effective project role (Phase 1: direct membership only). */
export function effectiveRole(
  db: MockDb,
  projectId: string,
  userId: string | undefined,
): ProjectRole | null {
  if (!userId) return null
  return (
    db.members.find((member) => member.project_id === projectId && member.user_id === userId)
      ?.role ?? null
  )
}

const isMemberish = (role: ProjectRole | null) => role === 'member' || role === 'admin'

export function isProjectAdmin(db: MockDb, project: MockProject, user: MockUser): boolean {
  return user.is_platform_admin || effectiveRole(db, project.id, user.id) === 'admin'
}

/** project.view: platform admins, anyone with a role, and everyone for internal projects. */
export function canViewProject(db: MockDb, project: MockProject, user: MockUser): boolean {
  if (user.is_platform_admin) return true
  if (project.visibility === 'internal') return true
  return effectiveRole(db, project.id, user.id) !== null
}

/** idea.view (no moderation in Phase 1, so the same as project.view). */
export function canViewIdea(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return canViewProject(db, projectOf(db, idea), user)
}

export function evaluationOf(
  db: MockDb,
  ideaId: string,
  userId: string,
): MockEvaluation | undefined {
  return rowsForIdea(db.evaluations, ideaId).find((e) => e.evaluator_id === userId)
}

export function isAssigned(db: MockDb, ideaId: string, userId: string): boolean {
  return rowsForIdea(db.assignments, ideaId).some((a) => a.user_id === userId)
}

/**
 * Role matrix §3: assigned to the idea and no submitted evaluation (none, or a
 * draft). No role lifts this; closing evaluation doesn't either.
 */
export function isPendingEvaluator(db: MockDb, idea: MockIdea, userId: string): boolean {
  if (!isAssigned(db, idea.id, userId)) return false
  return evaluationOf(db, idea.id, userId)?.status !== 'submitted'
}

export function evaluationOpen(idea: MockIdea): boolean {
  return idea.evaluation_closed_at === null && idea.status !== 'closed'
}

/* ------------------------------------------------------------------ */
/* Permissions                                                         */
/* ------------------------------------------------------------------ */

export function projectPermissions(
  db: MockDb,
  project: MockProject,
  user: MockUser,
): ProjectPermissions {
  const role = effectiveRole(db, project.id, user.id)
  return {
    can_manage: user.is_platform_admin || role === 'admin',
    can_create_ideas: project.archived_at === null && (user.is_platform_admin || isMemberish(role)),
  }
}

/** The IdeaPermissions booleans, computed by the same rules the handlers enforce. */
export function ideaPermissions(db: MockDb, idea: MockIdea, user: MockUser): IdeaPermissions {
  const project = projectOf(db, idea)
  const role = effectiveRole(db, project.id, user.id)
  const admin = user.is_platform_admin || role === 'admin'
  const memberish = isMemberish(role)
  // Overlays count only while the user holds member/admin (role matrix §1).
  const owner = idea.owner_id === user.id && memberish
  const writable = project.archived_at === null
  const notClosed = idea.status !== 'closed'
  const open = evaluationOpen(idea)
  const manager = admin || owner
  const canVolunteer =
    idea.owner_id === null &&
    notClosed &&
    (role === 'admin' ||
      (user.is_platform_admin && memberish) ||
      (role === 'member' && project.allow_volunteer_owners))
  const none: IdeaPermissions = {
    can_assign_owner: false,
    can_change_status: false,
    can_close_evaluation: false,
    can_comment: false,
    can_delete: false,
    can_edit: false,
    can_evaluate: false,
    can_invite_evaluators: false,
    can_release_owner: false,
    can_remove_evaluators: false,
    can_volunteer: false,
    can_vote: false,
  }
  if (!writable) return none
  return {
    can_assign_owner: admin,
    can_change_status: manager,
    can_close_evaluation: manager && notClosed,
    can_comment: admin || memberish,
    can_delete: admin,
    can_edit:
      admin ||
      (owner && notClosed) ||
      (idea.submitted_by === user.id && memberish && idea.status === 'new'),
    can_evaluate: isAssigned(db, idea.id, user.id) && memberish && open,
    can_invite_evaluators: manager && open,
    can_release_owner: idea.owner_id === user.id && (memberish || admin),
    can_remove_evaluators: manager,
    can_volunteer: canVolunteer,
    can_vote: admin || memberish,
  }
}

/* ------------------------------------------------------------------ */
/* Aggregate (contract §3.8)                                           */
/* ------------------------------------------------------------------ */

/** Round half-up to one decimal, like Postgres `round(numeric, 1)`. */
export function round1(value: number): number {
  return Math.round((value + Number.EPSILON) * 10) / 10
}

/**
 * The aggregate over submitted evaluations with include_in_aggregate. Returns
 * null when nothing is included. Pure: callers apply the blind mask.
 */
export function computeAggregate(db: MockDb, idea: MockIdea): AggregateScore | null {
  const included = rowsForIdea(db.evaluations, idea.id).filter(
    (e) => e.status === 'submitted' && e.include_in_aggregate,
  )
  if (included.length === 0) return null
  const criteria = activeCriteria(db, idea.project_id)
  let weighted = 0
  let weights = 0
  let disagreement = false
  const perCriterion: CriterionAggregate[] = []
  for (const criterion of criteria) {
    const scores = included
      .map((e) => e.scores.find((s) => s.criterion_id === criterion.id)?.score)
      .filter((score): score is number => typeof score === 'number')
    if (scores.length === 0) continue
    const rawMean = scores.reduce((sum, s) => sum + s, 0) / scores.length
    const adjustedMean = criterion.inverted ? 6 - rawMean : rawMean
    weighted += criterion.weight * adjustedMean
    weights += criterion.weight
    const min = Math.min(...scores)
    const max = Math.max(...scores)
    if (scores.length >= 2 && max - min >= 2) disagreement = true
    perCriterion.push({
      criterion_id: criterion.id,
      name: criterion.name,
      weight: criterion.weight,
      inverted: criterion.inverted,
      mean: round1(rawMean),
      min,
      max,
      spread: max - min,
      count: scores.length,
    })
  }
  if (weights === 0) return null
  const recommendations = { go: 0, maybe: 0, no: 0 }
  for (const e of included) if (e.recommendation) recommendations[e.recommendation] += 1
  return {
    overall: round1(weighted / weights),
    count: included.length,
    high_disagreement: disagreement,
    criteria: perCriterion,
    recommendations,
  }
}

/** Score fields as the viewer may see them (contract §3.7). */
export function visibleScore(
  db: MockDb,
  idea: MockIdea,
  user: MockUser,
): { hidden: boolean; aggregate: AggregateScore | null } {
  if (isPendingEvaluator(db, idea, user.id)) return { hidden: true, aggregate: null }
  return { hidden: false, aggregate: computeAggregate(db, idea) }
}

/* ------------------------------------------------------------------ */
/* Serialisers                                                         */
/* ------------------------------------------------------------------ */

export function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] ?? '?'
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return (first + last).toUpperCase()
}

export function userRef(user: MockUser): UserRef {
  return {
    id: user.id,
    display_name: user.display_name,
    avatar_url: user.avatar_url,
    initials: initialsFor(user.display_name),
  }
}

export function userRefById(db: MockDb, id: string | null | undefined): UserRef | null {
  const user = findUser(db, id)
  return user ? userRef(user) : null
}

export function currentUser(user: MockUser): CurrentUser {
  return { ...userRef(user), email: user.email, is_platform_admin: user.is_platform_admin }
}

export function userSearchResult(user: MockUser, role: ProjectRole | null): UserSearchResult {
  return { ...userRef(user), email: user.email, project_role: role }
}

export function projectRef(project: MockProject): ProjectRef {
  return { id: project.id, key: project.key, name: project.name, slug: project.slug }
}

export function statusLabels(project: MockProject): StatusLabels {
  return { ...DEFAULT_STATUS_LABELS, ...project.status_labels }
}

export function statusLabel(project: MockProject, idea: Pick<MockIdea, 'status' | 'resolution'>) {
  const labels = statusLabels(project)
  return idea.status === 'closed' && idea.resolution ? labels[idea.resolution] : labels[idea.status]
}

export function projectSummary(db: MockDb, project: MockProject, user: MockUser): ProjectSummary {
  return {
    id: project.id,
    slug: project.slug,
    key: project.key,
    name: project.name,
    description: project.description,
    visibility: project.visibility,
    archived_at: project.archived_at,
    my_role: effectiveRole(db, project.id, user.id),
    idea_count: db.ideas.filter((idea) => idea.project_id === project.id).length,
    member_count: db.members.filter((member) => member.project_id === project.id).length,
    permissions: projectPermissions(db, project, user),
  }
}

export function rubricCriterion(criterion: MockCriterion): RubricCriterion {
  return {
    id: criterion.id,
    name: criterion.name,
    description: criterion.description,
    weight: criterion.weight,
    inverted: criterion.inverted,
    guidance: { ...criterion.guidance },
    position: criterion.position,
  }
}

export function projectDetail(db: MockDb, project: MockProject, user: MockUser): Project {
  return {
    ...projectSummary(db, project, user),
    allow_volunteer_owners: project.allow_volunteer_owners,
    default_evaluation_days: project.default_evaluation_days,
    created_at: project.created_at,
    status_labels: statusLabels(project),
    rubric: activeCriteria(db, project.id).map(rubricCriterion),
  }
}

export function member(db: MockDb, projectId: string, userId: string): Member | null {
  const row = db.members.find((m) => m.project_id === projectId && m.user_id === userId)
  const user = findUser(db, userId)
  if (!row || !user) return null
  return { user: userRef(user), email: user.email, role: row.role, joined_at: row.joined_at }
}

export function tagNames(db: MockDb, idea: MockIdea): string[] {
  return idea.tag_ids
    .map((id) => db.tags.find((tag) => tag.id === id)?.name)
    .filter((name): name is string => Boolean(name))
    .sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' }))
}

export function ideaRef(db: MockDb, idea: MockIdea): IdeaRef {
  const project = projectOf(db, idea)
  return {
    id: idea.id,
    key: ideaKey(db, idea),
    number: idea.number,
    title: idea.title,
    status: idea.status,
    resolution: idea.resolution,
    status_label: statusLabel(project, idea),
    project: projectRef(project),
  }
}

function evaluatorProgress(db: MockDb, idea: MockIdea) {
  const assigned = rowsForIdea(db.assignments, idea.id)
  const submitted = assigned.filter(
    (a) => evaluationOf(db, idea.id, a.user_id)?.status === 'submitted',
  ).length
  return { submitted, total: assigned.length }
}

export function ideaSummary(db: MockDb, idea: MockIdea, user: MockUser): IdeaSummary {
  const { hidden, aggregate } = visibleScore(db, idea, user)
  return {
    ...ideaRef(db, idea),
    summary: idea.summary,
    tags: tagNames(db, idea),
    owner: userRefById(db, idea.owner_id),
    created_at: idea.created_at,
    last_activity_at: idea.last_activity_at,
    evaluator_progress: evaluatorProgress(db, idea),
    score: aggregate ? { overall: aggregate.overall, count: aggregate.count } : null,
    score_hidden: hidden,
    high_disagreement: aggregate?.high_disagreement ?? false,
    comment_count: rowsForIdea(db.comments, idea.id).filter((c) => c.deleted_at === null).length,
    vote_count: countVotes(db, idea.id),
    has_voted: db.votes.has(`${idea.id}:${user.id}`),
    permissions: { can_change_status: ideaPermissions(db, idea, user).can_change_status },
  }
}

export function ideaEvaluators(db: MockDb, idea: MockIdea, user: MockUser): IdeaEvaluator[] {
  return rowsForIdea(db.assignments, idea.id).map((assignment) => {
    const evaluator = findUser(db, assignment.user_id)
    const evaluation = evaluationOf(db, idea.id, assignment.user_id)
    let state: IdeaEvaluator['state'] = 'invited'
    if (evaluation?.status === 'submitted') state = 'submitted'
    // Drafts are private: only your own row may say "draft".
    else if (evaluation && assignment.user_id === user.id) state = 'draft'
    return {
      user: evaluator ? userRef(evaluator) : userRefFallback(assignment.user_id),
      invited_at: assignment.invited_at,
      is_ai: evaluator?.is_service_account ?? false,
      state,
      submitted_at: evaluation?.status === 'submitted' ? evaluation.submitted_at : null,
    }
  })
}

function userRefFallback(id: string): UserRef {
  return { id, display_name: 'Unknown user', avatar_url: null, initials: '?' }
}

export function ideaDetail(db: MockDb, idea: MockIdea, user: MockUser): IdeaDetail {
  const { aggregate } = visibleScore(db, idea, user)
  return {
    ...ideaSummary(db, idea, user),
    description_md: idea.description_md,
    submitted_by: userRefById(db, idea.submitted_by),
    evaluators: ideaEvaluators(db, idea, user),
    evaluation_due_at: idea.evaluation_due_at,
    evaluation_closed_at: idea.evaluation_closed_at,
    evaluation_open: evaluationOpen(idea),
    aggregate,
    watching: db.watchers.has(`${idea.id}:${user.id}`),
    permissions: ideaPermissions(db, idea, user),
  }
}

export function evaluationOut(db: MockDb, evaluation: MockEvaluation): Evaluation {
  const idea = db.ideas.find((i) => i.id === evaluation.idea_id)
  const criteria = idea ? activeCriteria(db, idea.project_id) : []
  const evaluator = findUser(db, evaluation.evaluator_id)
  return {
    id: evaluation.id,
    evaluator: evaluator ? userRef(evaluator) : userRefFallback(evaluation.evaluator_id),
    is_ai: evaluator?.is_service_account ?? false,
    include_in_aggregate: evaluation.include_in_aggregate,
    recommendation: evaluation.recommendation ?? 'maybe',
    comment: evaluation.comment,
    submitted_at: evaluation.submitted_at ?? evaluation.updated_at,
    edited_at: evaluation.edited_at,
    scores: criteria.flatMap((criterion) => {
      const score = evaluation.scores.find((s) => s.criterion_id === criterion.id)
      return score && score.score !== null
        ? [{ criterion_id: criterion.id, score: score.score, comment: score.comment }]
        : []
    }),
  }
}

export function myEvaluation(db: MockDb, idea: MockIdea, user: MockUser): MyEvaluation | null {
  if (!isAssigned(db, idea.id, user.id)) return null
  const evaluation = evaluationOf(db, idea.id, user.id)
  const criteria = activeCriteria(db, idea.project_id)
  return {
    idea_id: idea.id,
    state: evaluation ? (evaluation.status === 'submitted' ? 'submitted' : 'draft') : 'invited',
    editable: evaluationOpen(idea),
    due_at: idea.evaluation_due_at,
    recommendation: evaluation?.recommendation ?? null,
    comment: evaluation?.comment ?? '',
    submitted_at: evaluation?.submitted_at ?? null,
    updated_at: evaluation?.updated_at ?? null,
    scores: evaluation
      ? criteria.flatMap((criterion) => {
          const score = evaluation.scores.find((s) => s.criterion_id === criterion.id)
          return score
            ? [{ criterion_id: criterion.id, score: score.score, comment: score.comment }]
            : []
        })
      : [],
  }
}

export function commentBody(db: MockDb, comment: MockComment, user: MockUser): CommentBody {
  const idea = db.ideas.find((i) => i.id === comment.idea_id)
  const permissions = idea ? ideaPermissions(db, idea, user) : null
  const own = comment.author_id === user.id
  const canEdit = own && Boolean(permissions?.can_comment) && comment.deleted_at === null
  const project = idea ? projectOf(db, idea) : null
  const admin = project ? isProjectAdmin(db, project, user) : false
  return {
    id: comment.id,
    body_md: comment.deleted_at ? '' : comment.body_md,
    deleted: comment.deleted_at !== null,
    edited_at: comment.edited_at,
    can_edit: canEdit,
    can_delete: comment.deleted_at === null && project?.archived_at === null && (canEdit || admin),
  }
}

export function activityItem(db: MockDb, event: MockEvent, user: MockUser): ActivityItem | null {
  const base = {
    id: event.id,
    idea_id: event.idea_id,
    actor: userRefById(db, event.actor_id),
    created_at: event.created_at,
  }
  const p = event.payload
  const str = (key: string) => {
    const value = p[key]
    return typeof value === 'string' ? value : null
  }
  switch (event.type) {
    case 'comment': {
      const comment = db.comments.find((c) => c.id === event.comment_id)
      if (!comment) return null
      return { ...base, type: 'comment', comment: commentBody(db, comment, user) }
    }
    case 'idea_created':
      return { ...base, type: 'idea_created' }
    case 'idea_edited':
      return {
        ...base,
        type: 'idea_edited',
        fields: (p.fields as ('title' | 'summary' | 'description_md' | 'tags')[] | undefined) ?? [],
      }
    case 'status_changed':
      return {
        ...base,
        type: 'status_changed',
        from_status: p.from_status as IdeaStatus,
        from_resolution: (p.from_resolution as Resolution | null) ?? null,
        to_status: p.to_status as IdeaStatus,
        to_resolution: (p.to_resolution as Resolution | null) ?? null,
      }
    case 'owner_changed':
      return {
        ...base,
        type: 'owner_changed',
        from_owner: userRefById(db, str('from_owner_id')),
        to_owner: userRefById(db, str('to_owner_id')),
        volunteered: Boolean(p.volunteered),
      }
    case 'evaluator_added':
    case 'evaluator_removed':
    case 'evaluation_submitted':
      return { ...base, type: event.type, evaluator: userRefById(db, str('evaluator_id')) }
    case 'evaluation_closed':
    case 'evaluation_reopened':
      return { ...base, type: event.type }
    case 'due_date_changed':
      return {
        ...base,
        type: 'due_date_changed',
        from_due_at: str('from_due_at'),
        to_due_at: str('to_due_at'),
      }
  }
}

/* ------------------------------------------------------------------ */
/* Lists, sorting, cursors (contract §3.9)                             */
/* ------------------------------------------------------------------ */

export interface ListQuery extends IdeaFilters {
  status?: IdeaStatus[] | null
  resolution?: Resolution[] | null
}

export function matchesFilters(
  db: MockDb,
  idea: MockIdea,
  user: MockUser,
  query: ListQuery,
): boolean {
  if (query.status?.length && !query.status.includes(idea.status)) return false
  if (query.resolution?.length) {
    if (idea.status !== 'closed' || !idea.resolution) return false
    if (!query.resolution.includes(idea.resolution)) return false
  }
  if (query.owner) {
    if (query.owner === 'me' && idea.owner_id !== user.id) return false
    if (query.owner === 'none' && idea.owner_id !== null) return false
    if (query.owner !== 'me' && query.owner !== 'none' && idea.owner_id !== query.owner)
      return false
  }
  if (query.tag?.length) {
    const names = tagNames(db, idea).map((name) => name.toLowerCase())
    if (!query.tag.some((tag) => names.includes(tag.toLowerCase()))) return false
  }
  if (query.needs_evaluators) {
    if (idea.status === 'closed') return false
    if (rowsForIdea(db.assignments, idea.id).length > 0) return false
  }
  if (query.high_disagreement) {
    const { aggregate } = visibleScore(db, idea, user)
    if (!aggregate?.high_disagreement) return false
  }
  if (query.q) {
    const q = query.q.toLowerCase()
    const inText = idea.title.toLowerCase().includes(q) || idea.summary.toLowerCase().includes(q)
    if (!inText && ideaKey(db, idea).toLowerCase() !== q) return false
  }
  return true
}

/** Sorts in place by the contract's rules; hidden scores sort as unscored. */
export function sortIdeas(db: MockDb, ideas: MockIdea[], user: MockUser, sort: IdeaSort): void {
  const descending = sort.startsWith('-')
  const field = descending ? sort.slice(1) : sort
  const dir = descending ? -1 : 1
  const scoreCache = new Map<string, number | null>()
  const maskedScore = (idea: MockIdea) => {
    if (!scoreCache.has(idea.id)) {
      scoreCache.set(idea.id, visibleScore(db, idea, user).aggregate?.overall ?? null)
    }
    return scoreCache.get(idea.id) ?? null
  }
  const voteCache = new Map<string, number>()
  const votes = (idea: MockIdea) => {
    if (!voteCache.has(idea.id)) voteCache.set(idea.id, countVotes(db, idea.id))
    return voteCache.get(idea.id) ?? 0
  }
  ideas.sort((a, b) => {
    let cmp = 0
    if (field === 'score') {
      const sa = maskedScore(a)
      const sb = maskedScore(b)
      // Unscored (or hidden) ideas come last in both directions.
      if (sa === null && sb !== null) return 1
      if (sb === null && sa !== null) return -1
      cmp = sa === null || sb === null ? 0 : (sa - sb) * dir
    } else if (field === 'updated') {
      cmp = a.last_activity_at.localeCompare(b.last_activity_at) * dir
    } else if (field === 'created') {
      cmp = a.created_at.localeCompare(b.created_at) * dir
    } else if (field === 'votes') {
      cmp = (votes(a) - votes(b)) * dir
    } else if (field === 'title') {
      cmp = a.title.localeCompare(b.title, 'en', { sensitivity: 'base' }) * dir
    }
    return cmp !== 0 ? cmp : a.id.localeCompare(b.id) * (descending ? -1 : 1)
  })
}

/** Cursor = base64 JSON of the offset and a fingerprint of the query it belongs to. */
export function encodeCursor(offset: number, fingerprint: string): string {
  return btoa(JSON.stringify({ o: offset, f: fingerprint }))
}

export function decodeCursor(cursor: string, fingerprint: string): number | null {
  try {
    const value = JSON.parse(atob(cursor)) as { o?: unknown; f?: unknown }
    if (typeof value.o !== 'number' || value.f !== fingerprint || value.o < 0) return null
    return value.o
  } catch {
    return null
  }
}

export function queryFingerprint(scope: string, query: ListQuery & { sort?: string }): string {
  const parts = [
    scope,
    [...(query.status ?? [])].sort().join(','),
    [...(query.resolution ?? [])].sort().join(','),
    query.owner ?? '',
    [...(query.tag ?? [])]
      .map((t) => t.toLowerCase())
      .sort()
      .join(','),
    query.needs_evaluators ? '1' : '',
    query.high_disagreement ? '1' : '',
    query.q ?? '',
    query.sort ?? '-updated',
  ]
  return parts.join('|')
}

export class InvalidCursorError extends Error {}

export function paginate<T>(
  items: T[],
  cursor: string | null | undefined,
  limit: number,
  fingerprint: string,
): { page: T[]; next_cursor: string | null } {
  let offset = 0
  if (cursor) {
    const decoded = decodeCursor(cursor, fingerprint)
    if (decoded === null) throw new InvalidCursorError()
    offset = decoded
  }
  const page = items.slice(offset, offset + limit)
  const next = offset + limit < items.length ? encodeCursor(offset + limit, fingerprint) : null
  return { page, next_cursor: next }
}

/** Every idea in a project the viewer can see, filtered and sorted. */
export function queryProjectIdeas(
  db: MockDb,
  project: MockProject,
  user: MockUser,
  query: ListQuery & { sort?: IdeaSort },
): MockIdea[] {
  const ideas = db.ideas.filter(
    (idea) =>
      idea.project_id === project.id &&
      canViewIdea(db, idea, user) &&
      matchesFilters(db, idea, user, query),
  )
  sortIdeas(db, ideas, user, query.sort ?? '-updated')
  return ideas
}

export function board(
  db: MockDb,
  project: MockProject,
  user: MockUser,
  query: ListQuery & { sort?: IdeaSort },
  limit: number,
): Board {
  const filters = { ...query, status: null, resolution: null }
  const all = queryProjectIdeas(db, project, user, filters)
  const labels = statusLabels(project)
  return {
    columns: STATUSES.map((status) => {
      const ideas = all.filter((idea) => idea.status === status)
      const fingerprint = queryFingerprint(`project:${project.id}`, {
        ...filters,
        status: [status],
      })
      const { page, next_cursor } = paginate(ideas, null, limit, fingerprint)
      return {
        status,
        label: labels[status],
        count: ideas.length,
        items: page.map((idea) => ideaSummary(db, idea, user)),
        next_cursor,
        resolution_counts:
          status === 'closed'
            ? {
                accepted: ideas.filter((i) => i.resolution === 'accepted').length,
                rejected: ideas.filter((i) => i.resolution === 'rejected').length,
                parked: ideas.filter((i) => i.resolution === 'parked').length,
              }
            : null,
      }
    }),
  }
}

/* ------------------------------------------------------------------ */
/* My work (contract §3.10)                                            */
/* ------------------------------------------------------------------ */

function activeProjects(db: MockDb): MockProject[] {
  return db.projects.filter((project) => project.archived_at === null)
}

export function evaluationsDue(db: MockDb, user: MockUser): WorkEvaluation[] {
  const now = Date.now()
  const projects = new Set(
    activeProjects(db)
      .filter((project) => isMemberish(effectiveRole(db, project.id, user.id)))
      .map((project) => project.id),
  )
  const ideasById = new Map(db.ideas.map((idea) => [idea.id, idea]))
  const rows = db.assignments
    .filter((a) => a.user_id === user.id)
    .map((a) => ideasById.get(a.idea_id))
    .filter((idea): idea is MockIdea => Boolean(idea))
    .filter(
      (idea) =>
        projects.has(idea.project_id) &&
        evaluationOpen(idea) &&
        evaluationOf(db, idea.id, user.id)?.status !== 'submitted',
    )
    .map<WorkEvaluation>((idea) => ({
      idea: ideaRef(db, idea),
      due_at: idea.evaluation_due_at,
      overdue: idea.evaluation_due_at !== null && Date.parse(idea.evaluation_due_at) < now,
      owner: userRefById(db, idea.owner_id),
      state: evaluationOf(db, idea.id, user.id) ? 'draft' : 'invited',
    }))
  rows.sort((a, b) => {
    if (a.due_at === null && b.due_at === null) return a.idea.key.localeCompare(b.idea.key)
    if (a.due_at === null) return 1
    if (b.due_at === null) return -1
    return a.due_at.localeCompare(b.due_at)
  })
  return rows
}

export function ownedIdeas(db: MockDb, user: MockUser, statuses?: IdeaStatus[] | null) {
  const projects = new Set(activeProjects(db).map((project) => project.id))
  const ideas = db.ideas.filter(
    (idea) =>
      idea.owner_id === user.id &&
      projects.has(idea.project_id) &&
      canViewIdea(db, idea, user) &&
      (!statuses?.length || statuses.includes(idea.status)),
  )
  ideas.sort(
    (a, b) => b.last_activity_at.localeCompare(a.last_activity_at) || b.id.localeCompare(a.id),
  )
  return ideas
}

export const OWNED_GROUP_SIZE = 50

export function ownedGroups(db: MockDb, user: MockUser): WorkOwnedGroup[] {
  return STATUSES.flatMap((status) => {
    const ideas = ownedIdeas(db, user, [status])
    if (ideas.length === 0) return []
    const { page, next_cursor } = paginate(
      ideas,
      null,
      OWNED_GROUP_SIZE,
      ownedFingerprint(user, [status]),
    )
    return [
      {
        status,
        label: DEFAULT_STATUS_LABELS[status],
        count: ideas.length,
        ideas: page.map((idea) => ideaSummary(db, idea, user)),
        next_cursor,
      },
    ]
  })
}

export function ownedFingerprint(user: MockUser, statuses?: IdeaStatus[] | null): string {
  return `owned:${user.id}:${[...(statuses ?? [])].sort().join(',')}`
}

export function recentIdeas(db: MockDb, user: MockUser) {
  const projects = new Set(
    activeProjects(db)
      .filter((project) => effectiveRole(db, project.id, user.id) !== null)
      .map((project) => project.id),
  )
  const ideas = db.ideas
    .filter((idea) => projects.has(idea.project_id))
    .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at))
    .slice(0, 20)
  return ideas.map((idea) => {
    const events = rowsForIdea(db.events, idea.id)
    const latest = events.reduce<MockEvent | undefined>(
      (newest, event) => (!newest || event.created_at >= newest.created_at ? event : newest),
      undefined,
    )
    return {
      idea: ideaSummary(db, idea, user),
      latest_activity: latest ? activityItem(db, latest, user) : null,
    }
  })
}

/* ------------------------------------------------------------------ */
/* Search (contract §3.11)                                             */
/* ------------------------------------------------------------------ */

export function search(db: MockDb, user: MockUser, q: string, limit: number) {
  const needle = q.trim().toLowerCase()
  const projects = db.projects.filter(
    (project) => project.archived_at === null && canViewProject(db, project, user),
  )
  const projectIds = new Set(projects.map((project) => project.id))
  const exact = findIdea(db, needle)
  const scored = db.ideas
    .filter((idea) => projectIds.has(idea.project_id) && idea !== exact)
    .flatMap((idea) => {
      const title = idea.title.toLowerCase()
      let rank = -1
      if (title.startsWith(needle)) rank = 0
      else if (new RegExp(`\\b${escapeRegExp(needle)}`).test(title)) rank = 1
      else if (title.includes(needle)) rank = 2
      else if (idea.summary.toLowerCase().includes(needle)) rank = 3
      return rank < 0 ? [] : [{ idea, rank }]
    })
    .sort(
      (a, b) => a.rank - b.rank || b.idea.last_activity_at.localeCompare(a.idea.last_activity_at),
    )
    .map(({ idea }) => idea)
  const ideas = [...(exact && projectIds.has(exact.project_id) ? [exact] : []), ...scored]
  return {
    ideas: ideas.slice(0, limit).map((idea) => ideaRef(db, idea)),
    projects: projects
      .filter(
        (project) => project.name.toLowerCase().includes(needle) || project.slug.includes(needle),
      )
      .sort((a, b) => a.name.localeCompare(b.name))
      .slice(0, limit)
      .map(projectRef),
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
