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
/** `GET /auth/login?prompt=`: passed on to the IdP ("Use a different account"). */
export type LoginPrompt = Schemas['LoginPrompt']
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

/* Phase 3: email and notifications (docs/api/contract-phase3.md) */
export type CommentExcerpt = Schemas['CommentExcerpt']
export type NotificationItem = Schemas['NotificationPage']['items'][number]
export type NotificationPage = Schemas['NotificationPage']
export type NotificationType = Schemas['NotificationType']
export type NotificationMode = Schemas['NotificationMode']
export type NotificationSummary = Schemas['NotificationSummary']
export type NotificationPreference = Schemas['NotificationPreference']
export type NotificationPreferences = Schemas['NotificationPreferences']
export type NotificationPreferencesUpdate = Schemas['NotificationPreferencesUpdate']
export type UnsubscribeInfo = Schemas['UnsubscribeInfo']
export type UnsubscribeScope = Schemas['UnsubscribeScope']
export type EmailConfig = Schemas['EmailConfig']
export type EmailStatus = Schemas['EmailStatus']
export type EmailType = Schemas['EmailType']
export type EmailTestRequest = Schemas['EmailTestRequest']
export type OutboxEmail = Schemas['OutboxEmail']
export type OutboxEmailPage = Schemas['OutboxEmailPage']
export type OutboxRetryResult = Schemas['OutboxRetryResult']
export type OutboxStats = Schemas['OutboxStats']
export type SmtpSecurity = EmailConfig['security']
/** Query parameters of `list_outbox_emails` (filters, cursor, limit). */
export type OutboxQuery = NonNullable<operations['list_outbox_emails']['parameters']['query']>

/* Phase 4: proposals, public submission, branding (docs/api/contract-phase4.md) */
export type Proposal = Schemas['Proposal']
export type ProposalComment = Schemas['ProposalComment']
export type ProposalCommentCreate = Schemas['ProposalCommentCreate']
export type ProposalConflictProblem = Schemas['ProposalConflictProblem']
export type ProposalPermissions = Schemas['ProposalPermissions']
export type ProposalSection = Schemas['ProposalSection']
/** Phase 8: a section's stable key in the project's template (`^[a-z][a-z0-9_]{0,39}$`). */
export type ProposalSectionKey = string
export type ProposalSectionUpdate = Schemas['ProposalSectionUpdate']
export type ProposalThread = Schemas['ProposalThread']
export type ProposalThreadCreate = Schemas['ProposalThreadCreate']
export type ProposalThreadList = Schemas['ProposalThreadList']
export type ProposalView = Schemas['ProposalView']
export type AltchaChallenge = Schemas['AltchaChallenge']
export type AltchaParameters = Schemas['AltchaParameters']
export type EmailVerified = Schemas['EmailVerified']
export type HoldReason = Schemas['HoldReason']
export type IdeaSubmission = Schemas['IdeaSubmission']
export type IdeaSubmissionPermissions = Schemas['IdeaSubmissionPermissions']
export type ModerationItem = Schemas['ModerationItem']
export type ModerationPage = Schemas['ModerationPage']
export type PublicFormSettings = Schemas['PublicFormSettings']
export type PublicFormSettingsUpdate = Schemas['PublicFormSettingsUpdate']
export type PublicProject = Schemas['PublicProject']
export type PublicProjectRef = Schemas['PublicProjectRef']
export type PublicSubmissionCreate = Schemas['PublicSubmissionCreate']
export type PublicSubmissionReceipt = Schemas['PublicSubmissionReceipt']
export type SubmitterContact = Schemas['SubmitterContact']
export type TrackedStatusChange = Schemas['TrackedStatusChange']
export type TrackedSubmission = Schemas['TrackedSubmission']
export type TrackingRequest = Schemas['TrackingRequest']
export type TrackingUpdatesRequest = Schemas['TrackingUpdatesRequest']
export type VerificationRequest = Schemas['VerificationRequest']
export type BrandAsset = Schemas['BrandAsset']
export type BrandAssetKind = Schemas['BrandAssetKind']
export type BrandFont = Schemas['BrandFont']
export type BrandingSettings = Schemas['BrandingSettings']
export type BrandingUpdate = Schemas['BrandingUpdate']
export type EffectiveBranding = Schemas['EffectiveBranding']
export type InheritedBranding = Schemas['InheritedBranding']

/* Phase 5: API keys and proposal suggestions (docs/api/contract-phase5.md) */
export type AcceptedProposalSuggestion = Schemas['AcceptedProposalSuggestion']
export type AdminApiKey = Schemas['AdminApiKey']
export type AdminApiKeyPage = Schemas['AdminApiKeyPage']
export type ApiKey = Schemas['ApiKey']
export type ApiKeyCreate = Schemas['ApiKeyCreate']
export type ApiKeyList = Schemas['ApiKeyList']
export type ApiKeyScope = Schemas['ApiKeyScope']
export type ApiKeyState = Schemas['ApiKeyState']
export type CreatedApiKey = Schemas['CreatedApiKey']
export type ProposalSuggestion = Schemas['ProposalSuggestion']
export type ProposalSuggestionAccept = Schemas['ProposalSuggestionAccept']
export type ProposalSuggestionCreate = Schemas['ProposalSuggestionCreate']
export type ProposalSuggestionList = Schemas['ProposalSuggestionList']
export type ProposalSuggestionPermissions = Schemas['ProposalSuggestionPermissions']
export type SuggestionSource = Schemas['SuggestionSource']
export type SuggestionStatus = Schemas['SuggestionStatus']
/** Query parameters of `list_admin_api_keys` (filters, cursor, limit). */
export type AdminApiKeyQuery = NonNullable<operations['list_admin_api_keys']['parameters']['query']>

/* Phase 6: AI assistance (docs/api/contract-phase6.md) */
export type AiAgent = Schemas['AiAgent']
export type AiAgentCard = Schemas['AiAgentCard']
export type AiAgentCreate = Schemas['AiAgentCreate']
export type AiAgentList = Schemas['AiAgentList']
export type AiAgentProjectRef = Schemas['AiAgentProjectRef']
export type AiAgentProtocol = Schemas['AiAgentProtocol']
export type AiAgentRef = Schemas['AiAgentRef']
export type AiAgentSkill = Schemas['AiAgentSkill']
export type AiAgentTest = Schemas['AiAgentTest']
export type AiAgentUpdate = Schemas['AiAgentUpdate']
export type AiBlockedReason = Schemas['AiBlockedReason']
export type AiPermissions = Schemas['AiPermissions']
export type AiResearchNoteActivity = Schemas['AiResearchNoteActivity']
export type AiRun = Schemas['AiRun']
export type AiRunDetail = Schemas['AiRunDetail']
export type AiRunError = Schemas['AiRunError']
export type AiRunErrorInfo = Schemas['AiRunErrorInfo']
export type AiRunEvent = Schemas['AiRunEvent']
export type AiRunEventType = Schemas['AiRunEventType']
export type AiRunKind = Schemas['AiRunKind']
export type AiRunList = Schemas['AiRunList']
export type AiRunRequest = Schemas['AiRunRequest']
export type AiRunResult = Schemas['AiRunResult']
export type AiRunStatus = Schemas['AiRunStatus']
export type AiSectionDraftRequest = Schemas['AiSectionDraftRequest']
export type AiSettingsInEffect = Schemas['AiSettingsInEffect']
export type Citation = Schemas['Citation']
export type CreatedAiAgent = Schemas['CreatedAiAgent']
export type EvaluationInclusionUpdate = Schemas['EvaluationInclusionUpdate']
export type EvaluationScore = Schemas['EvaluationScore']
export type ResearchNote = Schemas['ResearchNote']
export type RotatedAiAgentKey = Schemas['RotatedAiAgentKey']

/* Phase 8: per-project proposal templates and the research step (docs/api/contract-phase8.md) */
export type DefaultChecklistItem = Schemas['DefaultChecklistItem']
export type IdeaResearch = Schemas['IdeaResearch']
export type IdeaResearchItem = Schemas['IdeaResearchItem']
export type IdeasInResearchProblem = Schemas['IdeasInResearchProblem']
export type ProposalStart = Schemas['ProposalStart']
export type ProposalTemplate = Schemas['ProposalTemplate']
export type ProposalTemplateSection = Schemas['ProposalTemplateSection']
export type ProposalTemplateUpdate = Schemas['ProposalTemplateUpdate']
export type RemovedResearchItem = Schemas['RemovedResearchItem']
export type RemovedTemplateSection = Schemas['RemovedTemplateSection']
export type ResearchAnswer = Schemas['ResearchAnswer']
export type ResearchAnswerIn = Schemas['ResearchAnswerIn']
export type ResearchChecklistItem = Schemas['ResearchChecklistItem']
export type ResearchIncompleteProblem = Schemas['ResearchIncompleteProblem']
export type ResearchItemIn = Schemas['ResearchItemIn']
export type ResearchOpenItem = Schemas['ResearchOpenItem']
export type ResearchPermissions = Schemas['ResearchPermissions']
export type ResearchProgress = Schemas['ResearchProgress']
export type ResearchSettings = Schemas['ResearchSettings']
export type ResearchSettingsUpdate = Schemas['ResearchSettingsUpdate']
export type ResearchStep = Schemas['ResearchStep']
export type SimilarIdea = Schemas['SimilarIdea']
export type SimilarIdeas = Schemas['SimilarIdeas']
export type TemplateSectionIn = Schemas['TemplateSectionIn']
export type AiEvaluationRequest = Schemas['AiEvaluationRequest']
/** "Move anyway" on a request the research gate guards (contract-phase8 §3.5). */
export interface ResearchOverride {
  override_research?: boolean | null
  override_reason?: string | null
}
