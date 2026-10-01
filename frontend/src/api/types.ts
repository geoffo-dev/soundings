/**
 * Named aliases for the generated OpenAPI schemas, so feature code can write
 * `IdeaDetail` instead of `components['schemas']['IdeaDetail']`. Types only:
 * everything here comes from `generated/schema.d.ts` (the lead-owned contract).
 */
import type { components, operations } from '@/api/generated/schema'

type Schemas = components['schemas']

export type ActivityItem = Schemas['ActivityPage']['items'][number]
export type ActivityPage = Schemas['ActivityPage']
export type ActivityType = ActivityItem['type']
export type AggregateScore = Schemas['AggregateScore']
export type AggregateScoreSummary = Schemas['AggregateScoreSummary']
export type Board = Schemas['Board']
export type BoardColumn = Schemas['BoardColumn']
export type CommentActivity = Schemas['CommentActivity']
export type CommentBody = Schemas['CommentBody']
export type CriterionAggregate = Schemas['CriterionAggregate']
export type CurrentUser = Schemas['CurrentUser']
export type Evaluation = Schemas['Evaluation']
export type EvaluationList = Schemas['EvaluationList']
export type EvaluatorState = Schemas['EvaluatorState']
export type FieldError = Schemas['FieldError']
export type IdeaCreate = Schemas['IdeaCreate']
export type IdeaDetail = Schemas['IdeaDetail']
export type IdeaEvaluator = Schemas['IdeaEvaluator']
export type IdeaPage = Schemas['IdeaPage']
export type IdeaPermissions = Schemas['IdeaPermissions']
export type IdeaRef = Schemas['IdeaRef']
export type IdeaStatus = Schemas['IdeaStatus']
export type IdeaSummary = Schemas['IdeaSummary']
export type IdeaUpdate = Schemas['IdeaUpdate']
export type Member = Schemas['Member']
export type MyEvaluation = Schemas['MyEvaluation']
export type MyEvaluationIn = Schemas['MyEvaluationIn']
export type MyScore = Schemas['MyScore']
export type Problem = Schemas['Problem']
export type Project = Schemas['Project']
export type ProjectCreate = Schemas['ProjectCreate']
export type ProjectPermissions = Schemas['ProjectPermissions']
export type ProjectRef = Schemas['ProjectRef']
export type ProjectRole = Schemas['ProjectRole']
export type ProjectSummary = Schemas['ProjectSummary']
export type ProjectUpdate = Schemas['ProjectUpdate']
export type ProjectVisibility = Schemas['ProjectVisibility']
export type Recommendation = Schemas['Recommendation']
export type Resolution = Schemas['Resolution']
export type Rubric = Schemas['Rubric']
export type RubricCriterion = Schemas['RubricCriterion']
export type RubricUpdate = Schemas['RubricUpdate']
export type SearchResults = Schemas['SearchResults']
export type StatusChange = Schemas['StatusChange']
export type StatusLabels = Schemas['StatusLabels']
export type TagInfo = Schemas['TagInfo']
export type UserPage = Schemas['UserPage']
export type UserRef = Schemas['UserRef']
export type UserSearchResult = Schemas['UserSearchResult']
export type ValidationProblem = Schemas['ValidationProblem']
export type VoteState = Schemas['VoteState']
export type WatchState = Schemas['WatchState']
export type Work = Schemas['Work']
export type WorkCounts = Schemas['WorkCounts']
export type WorkEvaluation = Schemas['WorkEvaluation']
export type WorkOwnedGroup = Schemas['WorkOwnedGroup']
export type WorkRecentIdea = Schemas['WorkRecentIdea']

/* Phase 2: sign-in and access (docs/api/contract-phase2.md) */
export type AdminUser = Schemas['AdminUser']
export type AdminUserCreate = Schemas['AdminUserCreate']
export type AdminUserPage = Schemas['AdminUserPage']
export type AdminUserSummary = Schemas['AdminUserSummary']
export type AdminUserUpdate = Schemas['AdminUserUpdate']
export type AuditAction = Schemas['AuditAction']
export type AuditEntry = Schemas['AuditEntry']
export type AuditPage = Schemas['AuditPage']
export type AuditTargetType = NonNullable<AuditEntry['target_type']>
export type AuthConfig = Schemas['AuthConfig']
export type BreakGlassLogin = Schemas['BreakGlassLogin']
export type BreakGlassStatus = Schemas['BreakGlassStatus']
export type ExternalId = Schemas['ExternalId']
export type ExternalIdIn = Schemas['ExternalIdIn']
export type ExternalIdsReplace = Schemas['ExternalIdsReplace']
export type Group = Schemas['Group']
export type GroupCreate = Schemas['GroupCreate']
export type GroupMappingUpdate = Schemas['GroupMappingUpdate']
export type GroupMember = Schemas['GroupMember']
export type GroupMemberPage = Schemas['GroupMemberPage']
export type GroupPage = Schemas['GroupPage']
export type GroupProjectGrant = Schemas['GroupProjectGrant']
export type GroupRef = Schemas['GroupRef']
export type GroupSearchResult = Schemas['GroupSearchResult']
export type GroupSummary = Schemas['GroupSummary']
export type GroupSyncMode = Schemas['GroupSyncMode']
export type GroupUpdate = Schemas['GroupUpdate']
export type LinkedIdentity = Schemas['LinkedIdentity']
export type MappingEffect = Schemas['MappingTestGroup']['effect']
export type MappingTestGroup = Schemas['MappingTestGroup']
export type MappingTestRequest = Schemas['MappingTestRequest']
export type MappingTestResult = Schemas['MappingTestResult']
export type ProjectAccessEntry = Schemas['ProjectAccessEntry']
export type ProjectAccessPage = Schemas['ProjectAccessPage']
export type ProjectGroupGrant = Schemas['ProjectGroupGrant']
export type ProjectGroupGrantAdd = Schemas['ProjectGroupGrantAdd']
export type RoleSource = Schemas['RoleSource']
export type SsoConfig = Schemas['SsoConfig']
export type SsoDiscovery = Schemas['SsoDiscovery']
export type SsoRedirect = Schemas['SsoRedirect']
export type UserGroup = Schemas['UserGroup']
export type UserProjectRole = Schemas['UserProjectRole']
/** How a session signed in (contract-phase2 §1): `CurrentUser.auth_method`. */
export type AuthMethod = Schemas['AuthMethod']
/** `GET /auth/login` and `/auth/callback` redirect to `/login?error=<code>` (contract-phase2 §4.2). */
export type LoginErrorCode =
  | 'sso_unavailable'
  | 'too_many_attempts'
  | 'login_expired'
  | 'login_cancelled'
  | 'sso_failed'
  | 'no_account'
  | 'account_disabled'
  | 'identity_conflict'
/** Query parameters of `list_audit_entries` (filters, cursor, limit). */
export type AuditQuery = NonNullable<operations['list_audit_entries']['parameters']['query']>
/** Query parameters of `list_admin_users`. */
export type AdminUserQuery = NonNullable<operations['list_admin_users']['parameters']['query']>

/** Query parameters of `list_ideas` (filters, sort, cursor, limit). */
export type IdeaListQuery = NonNullable<operations['list_ideas']['parameters']['query']>
/** Query parameters of `get_board` (filters without status/resolution, sort, limit per column). */
export type BoardQuery = NonNullable<operations['get_board']['parameters']['query']>
/** The `sort` values shared by list and board. */
export type IdeaSort = NonNullable<IdeaListQuery['sort']>
/**
 * Filters shared by the board and the list (no paging). `status` and
 * `resolution` only apply to the list; the board always has five columns.
 */
export type IdeaFilters = Omit<IdeaListQuery, 'cursor' | 'limit'>
