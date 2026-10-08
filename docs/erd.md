# Data model (ERD)

Schema after Phase 8: `backend/app/models/` (SQLAlchemy 2, typed), created by the
Alembic revisions `backend/app/migrations/versions/20260930_0002_domain_tables.py`
(Phase 1), `20261001_0003_sign_in_and_access.py` (Phase 2: identities, external IDs,
groups, group grants, the group-aware effective-roles view, audit indexes),
`20261001_0004_stateless_sso_sign_in.py` (Phase 2 review: drops the login-attempts
table, since sign-in attempts now travel sealed in the `soundings_oidc` cookie, and
clears plain-text ID tokens, which are now stored sealed) and
`20261001_0005_notifications_and_email.py` (Phase 3: the email outbox, in-app
notifications and email preferences), `20261001_0006_email_cleanup_indexes.py`
(Phase 3 review: indexes for the hourly cleanup) and
`20261001_0007_proposals_public_branding.py` (Phase 4: proposals and margin comments,
public submitters, held ideas, ALTCHA replay protection, submitter emails, branding
profiles and images), `20261002_0008_confirmation_email_sends.py` (Phase 4 review: the
per-address confirmation-email limit counts its own keyed rows) and
`20261002_0009_submission_reached_team_at.py` (Phase 4 UX review: when a public idea
reached the team), `20261002_0010_api_keys_and_suggestions.py` (Phase 5: API keys
and proposal suggestions) and `20261006_0011_ai_agents_and_runs.py` (Phase 6: kagent
agents, the projects they serve, AI runs and their events, an AI evaluator's cited
sources per criterion) and `20261007_0012_templates_and_research.py` (Phase 8:
per-project proposal templates, template keys instead of the fixed eight, the research
step, the research checklist and answers). The procrastinate job-queue tables (revision
`0001`) are not shown. API shapes are in [api/contract-phase1.md](api/contract-phase1.md)
to [api/contract-phase8.md](api/contract-phase8.md).

**Operators:** the migration runs `CREATE EXTENSION IF NOT EXISTS pg_trgm`. `pg_trgm`
is a trusted extension, so the application's database user needs `CREATE` on the
database (the database owner has it), or a DBA installs the extension beforehand.
Downgrades leave it installed.

```mermaid
erDiagram
    users ||--o{ user_sessions : "signs in with"
    users ||--o{ user_identities : "is linked to"
    users ||--o{ user_external_ids : "is known by"
    users ||--o{ group_memberships : "belongs via"
    groups ||--o{ group_memberships : has
    groups ||--o{ group_idp_values : "is mapped to"
    groups ||--o{ project_group_grants : "is granted"
    projects ||--o{ project_group_grants : "grants roles to"
    users ||--o{ project_members : "is member via"
    projects ||--o{ project_members : has
    projects ||--o{ rubric_criteria : "scores with"
    projects ||--o{ tags : defines
    projects ||--o{ ideas : contains
    users |o--o{ ideas : "owns (owner_id)"
    users |o--o{ ideas : "submitted (submitted_by_id)"
    ideas ||--o{ idea_tags : tagged
    tags ||--o{ idea_tags : "applied as"
    ideas ||--o{ idea_evaluators : "is evaluated by"
    users ||--o{ idea_evaluators : "evaluates as"
    idea_evaluators ||--o| evaluations : "writes (idea_id, evaluator_id)"
    evaluations ||--o{ evaluation_scores : contains
    rubric_criteria ||--o{ evaluation_scores : "scored in"
    ideas ||--o{ idea_votes : "voted by"
    ideas ||--o{ idea_watchers : "watched by"
    ideas ||--o{ comments : has
    users |o--o{ comments : wrote
    projects ||--o{ activity_events : logs
    ideas |o--o{ activity_events : "feed of"
    comments |o--o| activity_events : "placed by"
    users |o--o{ activity_events : "actor of"
    users ||--o{ notifications : receives
    ideas ||--o{ notifications : "is the subject of"
    comments |o--o{ notifications : "comment or mention"
    outbound_email |o--o{ notifications : "carries (immediate or digest)"
    users |o--o{ outbound_email : "is sent (recipient_user_id)"
    users ||--o{ notification_preferences : chooses
    ideas ||--o| proposals : "has (Phase 4)"
    proposals ||--|{ proposal_sections : "is written in"
    proposals ||--o{ proposal_threads : "is discussed in"
    proposal_threads ||--|{ proposal_comments : contains
    users |o--o{ proposal_comments : wrote
    ideas ||--o| public_submissions : "came in as"
    projects ||--o{ public_submissions : "received"
    ideas |o--o{ outbound_email : "submitter emails (idea_id)"
    projects |o--o| branding_profiles : "overrides (null: global)"
    projects |o--o{ brand_assets : "owns (null: global)"
    brand_assets |o--o{ branding_profiles : "logo or favicon of"
    users ||--o{ api_keys : "owns (Phase 5)"
    users |o--o{ api_keys : "created or revoked"
    proposals ||--o{ proposal_suggestions : "is suggested text for"
    users |o--o{ proposal_suggestions : "suggested or decided"
    users ||--o| ai_agents : "acts as (service account, Phase 6)"
    ai_agents ||--o{ ai_agent_projects : serves
    projects ||--o{ ai_agent_projects : "is served by"
    ideas ||--o{ ai_runs : "AI runs on"
    ai_agents ||--o{ ai_runs : "runs"
    users |o--o{ ai_runs : "requested or cancelled"
    ai_runs ||--o{ ai_run_events : "progress of"
    evaluations |o--o{ ai_runs : "result (evaluate)"
    proposal_suggestions |o--o{ ai_runs : "result (draft_section)"
    activity_events |o--o{ ai_runs : "result (research note)"
    projects ||--o{ proposal_template_sections : "writes proposals with (Phase 8)"
    projects ||--o{ research_checklist_items : "checks ideas with (Phase 8)"
    ideas ||--o{ research_answers : "is researched in"
    research_checklist_items ||--o{ research_answers : "is answered in"
    users |o--o{ research_answers : "answered or updated"

    users {
        uuid id PK
        varchar email "unique on lower(email)"
        varchar display_name
        varchar avatar_url "nullable"
        bool is_platform_admin
        bool is_active
        bool is_service_account "AI agents (Phase 6: ai_agents)"
        bool is_break_glass "at most one row"
        timestamptz last_seen_at
    }
    user_sessions {
        uuid id PK
        varchar token_hash UK "sha256 of cookie token"
        uuid user_id FK
        varchar csrf_token
        varchar auth_method "sso, break_glass, dev_login"
        text id_token "SSO only, sealed, for sign-out"
        timestamptz created_at
        timestamptz last_seen_at
        timestamptz expires_at "absolute expiry"
        varchar user_agent "short summary"
    }
    user_identities {
        uuid id PK
        uuid user_id FK "unique with issuer"
        varchar issuer "unique with subject"
        varchar subject
        timestamptz created_at "linked at"
        timestamptz last_login_at
    }
    user_external_ids {
        uuid user_id PK, FK
        varchar kind PK "employee_no, gitlab"
        varchar value "unique per kind, case-insensitive"
        timestamptz created_at
    }
    groups {
        uuid id PK
        varchar name "unique on lower(name)"
        varchar description
        varchar sync_mode "managed or additive"
    }
    group_idp_values {
        uuid group_id PK, FK
        varchar value PK "normalised"
    }
    group_memberships {
        uuid group_id PK, FK
        uuid user_id PK, FK
        bool manual "admin-added; sync never touches"
        bool synced "added by sign-in sync"
    }
    project_group_grants {
        uuid project_id PK, FK
        uuid group_id PK, FK
        varchar role "admin, member, viewer"
    }
    projects {
        uuid id PK
        varchar slug UK "immutable"
        varchar key UK "immutable, CUST"
        varchar name
        text description
        varchar visibility "private or internal"
        bool allow_volunteer_owners "default true"
        bool public_submission_enabled "public form on"
        bool public_require_email_verification "hold until confirmed"
        bool public_moderation_required "hold until approved, default true"
        text public_intro_md "above the form"
        jsonb status_labels "overrides only"
        int default_evaluation_days "default 7"
        varchar research_step "off, before_evaluation, before_proposal"
        int next_idea_number
        timestamptz archived_at
    }
    project_members {
        uuid project_id PK, FK
        uuid user_id PK, FK
        varchar role "admin, member, viewer"
    }
    rubric_criteria {
        uuid id PK
        uuid project_id FK
        int position
        varchar name
        varchar description
        numeric weight "0.01 to 10, 2 decimals"
        bool inverted
        jsonb guidance "hints keyed 1..5"
        timestamptz archived_at
    }
    tags {
        uuid id PK
        uuid project_id FK "unique with lower(name)"
        varchar name
    }
    ideas {
        uuid id PK
        uuid project_id FK "unique with number"
        int number "key = project.key-number"
        varchar title
        varchar summary
        text description_md
        varchar status "new, research, evaluating ... closed"
        varchar resolution "iff closed"
        uuid owner_id FK "nullable"
        uuid submitted_by_id FK "nullable"
        timestamptz evaluation_due_at
        timestamptz evaluation_closed_at
        timestamptz last_activity_at
        int vote_count "cache"
        numeric aggregate_score "cache, raw"
        int aggregate_count "cache"
        bool high_disagreement "cache"
        varchar held_for "email_verification, moderation; null = visible"
    }
    idea_tags {
        uuid idea_id PK, FK
        uuid tag_id PK, FK
    }
    idea_evaluators {
        uuid idea_id PK, FK
        uuid user_id PK, FK
        uuid invited_by_id FK
        timestamptz invited_at
    }
    evaluations {
        uuid id PK
        uuid idea_id FK "with evaluator_id to idea_evaluators"
        uuid evaluator_id FK
        varchar status "draft, submitted"
        varchar recommendation "go, maybe, no"
        text comment
        timestamptz submitted_at "first submission"
        timestamptz edited_at "saved again after submitting"
        bool include_in_aggregate "Phase 6: AI excluded by default"
    }
    evaluation_scores {
        uuid evaluation_id PK, FK
        uuid criterion_id PK, FK
        smallint score "1..5, null in drafts"
        varchar comment "an AI evaluator's rationale"
        jsonb sources "AI only: [{title, url}], at most 5"
    }
    idea_votes {
        uuid idea_id PK, FK
        uuid user_id PK, FK
    }
    idea_watchers {
        uuid idea_id PK, FK
        uuid user_id PK, FK
    }
    comments {
        uuid id PK
        uuid idea_id FK
        uuid author_id FK "nullable"
        text body_md
        timestamptz edited_at
        timestamptz deleted_at
    }
    activity_events {
        uuid id PK
        uuid project_id FK
        uuid idea_id FK "nullable"
        uuid actor_id FK "nullable"
        varchar type
        uuid comment_id FK "type comment"
        jsonb payload "never scores"
        timestamptz created_at
    }
    audit_log {
        uuid id PK
        uuid actor_id "no FK"
        varchar action
        varchar target_type
        uuid target_id "no FK"
        uuid project_id "no FK"
        jsonb details
        timestamptz created_at
    }
    notifications {
        uuid id PK
        uuid user_id FK "recipient; unique with dedupe_key"
        varchar type "owner_assigned ... mention"
        uuid idea_id FK
        uuid actor_id FK "nullable: reminders"
        uuid comment_id FK "iff comment or mention"
        jsonb payload "never scores"
        varchar dedupe_key
        varchar email_mode "immediate, digest, off"
        uuid email_id FK "the email that carried it"
        timestamptz read_at
        timestamptz created_at
    }
    notification_preferences {
        uuid user_id PK, FK
        varchar type PK
        varchar mode "immediate, digest, off"
        timestamptz updated_at
    }
    outbound_email {
        uuid id PK
        varchar type "notification type, digest, test, Phase 4"
        varchar status "queued, sending, sent, failed, cancelled"
        uuid recipient_user_id FK "or to_address"
        varchar to_address "non-user recipients only"
        uuid requested_by_id FK "test email"
        jsonb payload "never scores"
        varchar message_id UK "fixed at insert"
        varchar idempotency_key UK "digest per day"
        smallint attempts
        smallint max_attempts "12; test 1"
        timestamptz next_attempt_at "queued: due; sending: lease"
        varchar last_error "sanitised"
        timestamptz sent_at
        uuid idea_id FK "submitter emails only"
    }
    proposals {
        uuid id PK
        uuid idea_id FK, UK
        uuid created_by_id FK
        timestamptz updated_at "latest section save"
    }
    proposal_sections {
        uuid proposal_id PK, FK
        varchar key PK "a template key of the project"
        text body_md
        int version "optimistic concurrency"
        uuid updated_by_id FK
        timestamptz updated_at
    }
    proposal_threads {
        uuid id PK
        uuid proposal_id FK
        varchar section_key
        uuid created_by_id FK
        timestamptz resolved_at
        uuid resolved_by_id FK
    }
    proposal_comments {
        uuid id PK
        uuid thread_id FK
        uuid author_id FK "nullable"
        text body_md
        timestamptz deleted_at
    }
    public_submissions {
        uuid id PK
        uuid idea_id FK, UK
        uuid project_id FK "rate limit"
        varchar name "optional, erasable"
        varchar email "optional, erasable"
        timestamptz email_verified_at
        bool wants_updates
        varchar tracking_token_hash UK "sha256"
        varchar tracking_token_sealed "AES-GCM"
        varchar submitted_title "as sent, erasable"
        varchar submitted_summary "as sent, erasable"
        timestamptz reached_team_at "null while held"
        timestamptz erased_at
        uuid erased_by_id FK
    }
    altcha_used_challenges {
        varchar signature PK
        timestamptz expires_at
    }
    confirmation_email_sends {
        uuid id PK
        varchar address_key "HMAC of the canonical address"
        timestamptz created_at
    }
    branding_profiles {
        uuid id PK
        uuid project_id FK, UK "null = global, nulls not distinct"
        varchar app_name
        varchar primary_color "#rrggbb"
        varchar accent_color "#rrggbb"
        varchar font "bundled font key"
        varchar email_footer "plain text"
        uuid logo_asset_id FK
        uuid favicon_asset_id FK
        uuid updated_by_id FK
    }
    brand_assets {
        uuid id PK
        uuid project_id FK "null = global"
        varchar kind "logo, favicon"
        varchar content_type "image/png, image/svg+xml"
        bytea data
        int byte_size
        varchar sha256
        int width
        int height
        uuid created_by_id FK
    }
    api_keys {
        uuid id PK
        uuid user_id FK "owner"
        varchar name "unique per owner, any case, until revoked"
        varchar lookup_id UK "12 base62 characters, public"
        varchar secret_hash "sha256 hex of the whole key"
        varchar_array scopes "read, write, evaluate, mcp"
        uuid_array project_ids "null = every project"
        timestamptz expires_at "null = never"
        timestamptz last_used_at "at most once a minute"
        timestamptz revoked_at
        uuid revoked_by_id FK
        uuid created_by_id FK "owner, or an admin (agents)"
        varchar created_auth_method "dev_login, sso, break_glass"
    }
    proposal_suggestions {
        uuid id PK
        uuid proposal_id FK
        varchar section_key
        text body_md "whole section, verbatim"
        int base_version "the version its author read"
        uuid author_id FK "nullable"
        varchar source "api, mcp, ai"
        varchar status "pending, accepted, discarded"
        uuid decided_by_id FK
        timestamptz decided_at "set iff not pending"
    }
    ai_agents {
        uuid id PK
        varchar display_name "also the service account's name"
        varchar description
        varchar namespace "kagent, DNS label"
        varchar name "kagent, DNS label; unique with namespace"
        varchar protocol "kagent_v0_10, kagent_v1_0"
        varchar_array purposes "evaluate, research, draft_section"
        uuid service_account_id FK, UK "users.is_service_account"
        bool enabled
        uuid created_by_id FK
    }
    ai_agent_projects {
        uuid agent_id PK, FK
        uuid project_id PK, FK
    }
    ai_runs {
        uuid id PK
        uuid idea_id FK
        uuid agent_id FK
        varchar kind "evaluate, research, draft_section"
        varchar section_key "draft_section only"
        uuid requested_by_id FK
        varchar status "queued, running, succeeded, failed, cancelled, timed_out"
        int timeout_seconds "30..3600"
        timestamptz started_at
        timestamptz finished_at "set iff final"
        timestamptz heartbeat_at
        timestamptz cancel_requested_at
        uuid cancel_requested_by_id FK
        varchar a2a_task_id
        varchar a2a_context_id
        varchar error_code "set iff failed or timed_out"
        varchar error_message "Soundings' sentence"
        int event_count "last event's seq"
        uuid evaluation_id FK "result"
        uuid suggestion_id FK "result"
        uuid activity_event_id FK "result: research note"
        bool assigned_evaluator "evaluate: this run assigned the agent"
    }
    ai_run_events {
        uuid run_id PK, FK
        int seq PK "1, 2, ... (SSE id)"
        varchar type
        varchar message "Soundings' sentence, never agent text"
    }
    proposal_template_sections {
        uuid id PK
        uuid project_id FK "unique with key"
        varchar key "stable slug, immutable"
        varchar title "1-60, unique among active"
        varchar hint "one line, the placeholder"
        int position "order among active"
        timestamptz archived_at "removed: text kept"
    }
    research_checklist_items {
        uuid id PK
        uuid project_id FK
        int position
        varchar title "1-80, unique among active"
        varchar hint "what to write"
        bool required "default true: gates"
        timestamptz archived_at "removed: answers kept"
    }
    research_answers {
        uuid idea_id PK, FK
        uuid item_id PK, FK "NO ACTION"
        text answer "1-2000, plain text"
        uuid answered_by_id FK "first answer"
        timestamptz answered_at
        uuid updated_by_id FK "last change"
        timestamptz updated_at
    }
```

Every table with a `uuid id` also has `created_at`, and most have `updated_at`
(timestamptz, UTC). Join tables use composite primary keys.

**View `project_effective_roles` (project_id, user_id, role):** each user's *effective*
role per project, one row per pair: the highest (`admin > member > viewer`) of the
direct role (`project_members`) and the role of every grant (`project_group_grants`) to
a group the user belongs to (`group_memberships`, manual or synced). Revision 0003
defines it as a `UNION ALL` of both sources grouped by `(project_id, user_id)` (Phase 1
it mirrored `project_members`; same columns and types). Filters on `project_id` or
`user_id` are pushed into both branches, which use the primary keys and the
`user_id`/`group_id` indexes. **Every query that needs a project role reads this view,
never `project_members`:** `list_projects`, `search_users?project=`, My work
(`evaluations_due`, `recent`), eligibility c4, last admin c11, `member_count`, the
access list and the authz policy. `project_members` is read directly only to list and
edit *direct* members, `project_group_grants` only to list and edit grants. In Python
it is `app.models.project_effective_roles` (a lightweight `table()`, kept out of
`Base.metadata` so Alembic never tries to create it).

## Conventions

- **Ids** are UUIDs generated in Python (`uuid4`), known before flush.
- **Enums** (`status`, `resolution`, `role`, `visibility`, `recommendation`) are
  `VARCHAR` plus a named `CHECK` constraint holding the wire values
  (`app/models/types.py:str_enum`), not native Postgres enums: adding a value later is
  a constraint swap. The Python `StrEnum`s in `app/models/enums.py` are shared with the
  API schemas.
- **Constraint names** follow `Base.metadata`'s naming convention (`pk_`, `fk_`, `uq_`,
  `ck_<table>_<name>`, `ix_`), so migrations can drop them by name.
- **Timestamps** are `timestamptz`, set in Python (UTC) with `now()` server defaults.
- **Soft vs hard delete:** users are deactivated (`is_active`), projects archived
  (`archived_at`), rubric criteria archived once scored, comments soft-deleted
  (`deleted_at`, body cleared). Ideas are hard-deleted by admins, with everything
  under them.
- **Schema checks:** `tests/test_domain_schema.py` runs upgrade → downgrade → upgrade on
  a scratch database, `alembic check`, and compares every constraint, index and column
  of the migrated schema with `Base.metadata.create_all` (stricter than autogenerate,
  which ignores `CHECK` constraints and index operator classes).

## Table notes

| Table | Notes |
|---|---|
| `users` | Email unique case-insensitively (`uq_users_email_lower` on `lower(email)`); look up with `lower(email) = lower(:email)`. Never deleted in normal use (deactivate). A pre-created user is a normal row without an identity. `is_service_account` is reserved for Phase 5/6 agent accounts. `is_break_glass` marks the single break-glass admin (`uq_users_is_break_glass`, partial unique on `is_break_glass` where true), created at its first sign-in with the reserved address `break-glass@soundings.invalid` (`.invalid` emails can't be given to users). Login matching never selects service or break-glass accounts. Downgrading 0003 leaves that row as an ordinary user; upgrading again marks it as the break-glass account by its email. |
| `user_sessions` | Cookie holds a 256-bit random token; only its SHA-256 (`token_hash`) is stored. `csrf_token` is mirrored in the readable `soundings_csrf` cookie. `expires_at` is the absolute expiry; idle expiry is `last_seen_at` + idle timeout (settings). `auth_method` (`sso`, `break_glass`, `dev_login`; no server default, existing rows became `dev_login`) says how it started; a session only works while that method is available (break-glass sessions also at most 8 hours, 1 hour idle). `id_token` (SSO only, and only when the token is at most 3,072 characters) is kept solely as `id_token_hint` for RP-initiated logout, sealed (AES-256-GCM with a key derived from the secret key, `app/auth/sealing.py`; [ADR 0005](adr/0005-server-side-sessions-oidc-csrf.md)); never logged or returned. Revision 0004 cleared plain-text tokens (those sessions sign out without the hint). Downgrading 0003 deletes SSO and break-glass sessions. |
| `user_identities` | An OIDC account linked to a user: the ID token's `(iss, sub)`, unique (`uq_user_identities_issuer_subject`), and at most one per user per issuer (`uq_user_identities_user_id_issuer`). Linked at the first sign-in that matches the user; `last_login_at` is updated at every SSO sign-in. Admins can unlink one (the user is matched again next time). |
| `user_external_ids` | Admin-managed ids (`employee_no = E1001`) that link a pre-created user at first sign-in. One value per kind per user (primary key `(user_id, kind)`); `(kind, lower(value))` unique (`uq_user_external_ids_kind_value_lower`). `kind` matches `^[a-z][a-z0-9_]{0,39}$`. |
| `groups` | Internal groups; names unique case-insensitively (`uq_groups_name_lower`). `sync_mode` (`managed` default, `additive`) decides what sign-in sync does with synced memberships. |
| `group_idp_values` | IdP group values mapped to a group, stored normalised (trim, strip `/` at both ends, lower-case); primary key `(group_id, value)`, indexed by `value` for the sign-in lookup. A value may map to several groups. |
| `group_memberships` | One row per (group, user) with provenance flags `manual` (admin) and `synced` (sign-in sync); `ck_group_memberships_has_source` keeps at least one true. Sync sets and clears only `synced` (deleting the row when neither is left); admins set `manual`, and "remove member" deletes the row. Sync and the admin add/remove both lock the user's `users` row first, so they serialise. Indexed by `user_id`. Deactivated users' rows stay (they can't sign in) and don't count for c11 or member counts. |
| `project_group_grants` | A project role for every member of a group; primary key `(project_id, group_id)`, indexed by `group_id`. Feeds the effective-roles view. |
| `projects` | `slug` (URLs) and `key` (idea keys) are immutable. `key` matches `^[A-Z][A-Z0-9]{1,5}$`; new slugs can't be one of the app's own paths (`RESERVED_SLUGS`, API validation: the public form is `/{slug}/submit`). `status_labels` stores overrides only, keyed by status and resolution values. `next_idea_number` is allocated with `UPDATE ... SET next_idea_number = next_idea_number + 1 RETURNING next_idea_number - 1` (race-free, numbers never reused). `archived_at` makes the project read-only and hides it by default. Public form (Phase 4, `GET/PATCH /projects/{slug}/public-form`): `public_submission_enabled` (default off), `public_require_email_verification` (default off), `public_moderation_required` (default **on**), `public_intro_md` (≤ 2,000 characters through the API). **Phase 8:** `research_step` (`off` default, `before_evaluation`, `before_proposal`; `ck_projects_research_step`) places the Research status in the project's lifecycle ([contract-phase8 §3.2](api/contract-phase8.md#32-the-step-and-the-lifecycle)); it can't change while an idea of the project is in Research (application). `status_labels` may also override `research`. |
| `project_members` | Direct membership only. Group grants are in `project_group_grants`; the `project_effective_roles` view (above) combines both, and queries read the view. |
| `rubric_criteria` | 3–6 active (`archived_at IS NULL`) per project, ordered by `position`. Active names are unique per project, case-insensitively (`uq_rubric_criteria_project_id_name_lower`, partial on `archived_at IS NULL`; unique indexes aren't deferrable, so `replace_rubric` applies renames and archives before inserts). `weight` is `numeric(4,2)`, `> 0`; the API accepts 0.01–10 in steps of 0.01 so nothing rounds to 0. Criteria with scores are archived when removed from the rubric; unscored ones are deleted. Scores reference criteria with a `NO ACTION` FK that is `DEFERRABLE INITIALLY DEFERRED`: deleting a scored criterion fails **at commit**, while deleting the whole project (which cascades to scores too) succeeds. New projects get `app/domain/rubric_defaults.py`. |
| `tags` | Per project, created on first use; unique on `(project_id, lower(name))`, first spelling wins. Rows are never deleted; `list_project_tags` lists only tags on at least one idea, so typos drop out of the chips once no idea uses them. |
| `ideas` | `(project_id, number)` unique; key = `project.key || '-' || number`. `resolution` set iff `status = 'closed'` (`ck_ideas_resolution_iff_closed`). Cached, **unmasked** aggregate: `aggregate_score` (1 decimal), `aggregate_count`, `high_disagreement`, recomputed in the same transaction as any evaluation, evaluator or rubric change; blind masking is applied per viewer when reading ([ADR 0006](adr/0006-blind-evaluation-and-aggregate-scoring.md)). `vote_count` caches `idea_votes`. `last_activity_at` is bumped by every activity event. Search: `ILIKE '%q%'` on `title`/`summary` served by `pg_trgm` GIN indexes. **Phase 8 (migration 0013):** trigram **GiST** indexes `ix_ideas_title_trgm_gist` and `ix_ideas_summary_trgm_gist` serve "Similar ideas" (nearest by `<->`, then ranked by `similarity`; [contract-phase8 §3.7](api/contract-phase8.md#37-similar-ideas)). Indexes for board/list keyset pages in the default order: `(project_id, last_activity_at, id)` and `(project_id, status, last_activity_at, id)` (also the per-status counts); plus `(project_id, aggregate_score)`, `owner_id`, `last_activity_at` (cross-project My work). Phase 3 reminder scan: partial index `ix_ideas_evaluation_due_at_open` on `evaluation_due_at` where it is set and evaluation is open. **Phase 4:** a public idea has `submitted_by_id` null and a `public_submissions` row; `held_for` (`email_verification` \| `moderation`, null = visible, `ck_ideas_held_for`) hides it from every list and count for everyone ([contract-phase4 §3.6](api/contract-phase4.md#36-holds-moderation-and-visibility)); partial indexes `ix_ideas_project_id_created_at_moderation (project_id, created_at, id) WHERE held_for = 'moderation'` (the moderation queue) and `ix_ideas_created_at_email_verification (created_at) WHERE held_for = 'email_verification'` (the 3-day cleanup). |
| `idea_evaluators` | The assignment. AI evaluators (Phase 6) are service-account users, so no extra column: `is_ai` in the API is `users.is_service_account`. Indexed by `user_id` for My work. |
| `evaluations` | One per assignment: composite FK `(idea_id, evaluator_id)` → `idea_evaluators` with `ON DELETE CASCADE`, so removing the assignment removes the evaluation. Created on first save. `submitted` requires `recommendation` and `submitted_at` (`ck_evaluations_submitted_complete`). `submitted_at` is the first submission; `edited_at` is the last save after it (null if none; the UI shows "edited after submission"). Whether an evaluation is AI is `users.is_service_account` of the evaluator (no column here); `include_in_aggregate` is for Phase 6 (AI excluded by default). |
| `evaluation_scores` | `score` 1–5 (`ck_evaluation_scores_score_range`), null only in drafts. `criterion_id` FK is deferred (see `rubric_criteria`). Phase 6: for an AI evaluator `comment` is the criterion's rationale (required when it submits) and `sources` its cited sources, a JSON array of at most five `{title, url}` objects (`ck_evaluation_scores_sources_array`; `'[]'` for people). |
| `idea_votes`, `idea_watchers` | One row per user per idea. Watchers are added automatically for the submitter, owner, evaluators and commenters (Phase 3 notifications). |
| `comments` | Flat. Every comment also has an `activity_events` row (`type = 'comment'`, `comment_id`) that places it in the feed. Deleting sets `deleted_at` and clears `body_md`. |
| `activity_events` | The idea feed and, from Phase 3, the source of notifications. `type` is validated in the application (the set grows per phase); `payload` holds ids and from/to values and **never scores**. `idea_id` is nullable for future project-level events. Feed index `(idea_id, created_at, id)`. |
| `notifications` | The in-app inbox and the record of who was told what ([contract-phase3 §3.2–3.3](api/contract-phase3.md#33-fan-out-which-events-notify-whom)). One row per recipient and event, written by the fan-out in the event's transaction; `uq_notifications_user_id_dedupe_key` (`<type>:<event id>`, `mention:<comment id>`, `evaluation_reminder:<idea id>:<local due date>:<days before>`) makes the fan-out, the reminder scan and retries idempotent, and **is** the reminder bookkeeping. `idea_id` is required (every type is about one idea); `comment_id` is set exactly for `comment` and `mention` (`ck_notifications_comment_iff_comment_type`). `payload` holds the type's data (from/to status, due date, days before, submitted count), never scores. `email_mode` is the recipient's preference when it was created (`off` also when email isn't configured or the address is unusable); `email_id` is the outbox row that carried it: its own immediate email, or the digest that collected it. **Digest bookkeeping:** pending = `email_mode = 'digest' AND email_id IS NULL` (`ix_notifications_digest_pending`), and only items from the last 7 days are collected; the hourly cleanup sets `email_mode = 'off'` on older pending items, including those whose digest row was pruned (`email_id` back to null), so nothing is mailed twice; `ck_notifications_no_email_when_off`. Indexes: inbox `(user_id, created_at, id)`, unread (partial on `read_at IS NULL`), `email_id`, `comment_id` (partial), `idea_id`, `ix_notifications_mention_actor (actor_id, created_at)` partial on `type = 'mention'` (the per-author cap on mention emails), and `ix_notifications_created_at` (revision 0006: the 90-day cleanup). Deleted after 90 days. |
| `notification_preferences` | A user's email mode per notification type, only where it differs from the defaults in code (`app.schemas.notifications.DEFAULT_MODES`); primary key `(user_id, type)`. |
| `outbound_email` | The transactional outbox ([ADR 0003](adr/0003-background-jobs-procrastinate-and-email-outbox.md), [contract-phase3 §3.9](api/contract-phase3.md#39-the-outbox-and-the-worker)). One row per email, inserted with its `send_email` job in the event's transaction; the row is the truth. Exactly one recipient: `recipient_user_id` (address looked up at send time, and checked to be one plain address) or `to_address` (a test email to an address; Phase 4 public submitters), `ck_outbound_email_one_recipient`. Content is rendered at send time from the notifications pointing at it, so no subject or body is stored. `status`: `queued` (waiting for `next_attempt_at`), `sending` (claimed; `next_attempt_at` is the 5-minute lease), `sent` (`sent_at` set, `ck_outbound_email_sent_at_iff_sent`), `failed` (admins may retry it for 3 days, digests 2), `cancelled` (by the send-time checks); `next_attempt_at` is set exactly while queued or sending (`ck_outbound_email_next_attempt_iff_pending`). `message_id` is unique and fixed at insert (a resend after a crash has the same Message-ID); `idempotency_key` unique when set (`digest:<user id>:<local date>`; Phase 4 below). `attempts`/`max_attempts` (12, test emails 1) drive the capped exponential backoff; `last_error` is a phrase built by our code, never the server's text. `payload` is for what can't be looked up at send time (a status change's from/to; never tokens or personal data: submitter emails are rendered from the idea and its `public_submissions` row, whose sealed token gives the link). Indexes: the due partial index on `next_attempt_at` (status queued or sending) for claims and the sweep, `(created_at, id)` and `(status, created_at, id)` for the admin outbox, counts and the admins' "email failing" flag, `recipient_user_id`, and `ix_outbound_email_status_updated_at (status, updated_at)` (revision 0006: the cleanup and the 24-hour failure check). Sent and cancelled rows are deleted after 30 days, failed after 90 (hourly cleanup). **Phase 4:** `idea_id` (FK `ideas`, `ON DELETE CASCADE`) names the idea of a public-submitter email: set exactly for the types `submission_received` and `submission_status_changed` (`ck_outbound_email_idea_iff_submission_type`: `(idea_id IS NOT NULL) = (type IN (…))`, so erasure, which deletes them by idea, finds every one; `NewEmail.idea_id`), and with it the recipient is `to_address` (`ck_outbound_email_submission_to_address`); partial indexes `ix_outbound_email_idea_id (idea_id, created_at) WHERE idea_id IS NOT NULL` (resend limit, erasure) (revision 0008 dropped `ix_outbound_email_submission_address`: the per-address limit counts `confirmation_email_sends`, which erasure can't reset). Their idempotency keys: `submission_received:<submission id>:<n>`, `submission_status:<event id>`. Migration 0007 deletes submitter-type rows queued before it (they name no idea). |
| `proposals` | One per idea (`uq_proposals_idea_id`), created by the owner or an admin once the idea is Shortlisted or in Proposal; `updated_at` follows section saves ([contract-phase4 §3.1](api/contract-phase4.md#31-proposal-lifecycle-and-permissions)). No status of its own: the idea's status decides whether it is editable (c7). |
| `proposal_sections` | One row per active section of the project's template (Phase 8: created with the proposal, and for every proposal of the project when a section is added or restored; rows of removed sections keep their text, hidden); primary key `(proposal_id, key)`, `key` a key of the idea's project's template, `varchar(40)` in the key format (`ck_proposal_sections_key_format`; no foreign key, [contract-phase8 §2.6](api/contract-phase8.md#26-storage-keys-not-foreign-keys)). `version` (≥ 1, `ck_proposal_sections_version_positive`) goes up by one per save that changes the text: `UPDATE … WHERE version = :base_version` is the optimistic-concurrency check (409 `proposal_conflict`). `updated_by_id` null for a section nobody has written. |
| `proposal_threads` | A margin thread on one section (`section_key`: a template key, `ck_proposal_threads_section_key_format`; threads of a removed section are hidden with it); `resolved_at`/`resolved_by_id` set while resolved (no pairing check: deleting a user sets `resolved_by_id` null). Index `(proposal_id, created_at)`. |
| `proposal_comments` | Flat comments in a thread, oldest first (`ix_proposal_comments_thread_id_created_at`), indexed by `author_id`. Deleting sets `deleted_at` and clears `body_md`; a thread whose comments are all deleted isn't listed. No edits. |
| `public_submissions` | The public submitter of one idea (`uq_public_submissions_idea_id`); `project_id` repeats the idea's project for the per-project rate limit (`ix_public_submissions_project_id_created_at`). Minimal personal data: optional `name` and `email`, `email_verified_at`, `wants_updates`; no IP address, user agent or account. The tracking token is stored only as `tracking_token_hash` (SHA-256 hex, unique: the lookup) and `tracking_token_sealed` (AES-256-GCM, purpose `submission-tracking-token`: for links in later emails); both set or both null (`ck_public_submissions_tracking_token_pair`). `submitted_title` / `submitted_summary`: the title and summary as sent, for the tracking page and status emails (never the idea's current, team-edited text), set until erased (`ck_public_submissions_submitted_copy_until_erased`). Checks: a confirmation or `wants_updates` needs an address (`ck_public_submissions_verified_needs_email`, `ck_public_submissions_updates_need_email`); once `erased_at` is set (an admin, the submitter from the tracking page, or the retention cleanup), name, email, token and the copy are null (`ck_public_submissions_erased_is_empty`). `reached_team_at` (revision 0009): when the idea stopped being held (at submission when nothing held it, else the confirmation or approval that released it; null while held; not personal data, kept on erasure), the tracking page's "With the team" date. The 3-day cleanup of unconfirmed addresses uses `ix_public_submissions_created_at_unconfirmed (created_at) WHERE email IS NOT NULL AND email_verified_at IS NULL`; the per-address email limit counts `confirmation_email_sends`. Retention: unconfirmed addresses after 3 days, contact details of closed ideas idle for 180 days ([contract-phase4 §3.9](api/contract-phase4.md#39-personal-data-what-is-kept-erasure-retention)). |
| `confirmation_email_sends` | One row per confirmation email (`submission_received`) queued to an address, first sends and resends alike (revision 0008): `address_key` = HMAC-SHA256 (hex) of the canonical address (lower-cased, `+tag` removed, Gmail's dots and `googlemail.com`, Yahoo's `-keyword` folded) with a key derived from the secret key; no address is stored. `ix_confirmation_email_sends_address_key_created_at` serves the limit of 3 per address per 24 hours; nothing deletes rows but the hourly cleanup, after 24 hours (`ix_confirmation_email_sends_created_at`), so erasing, rejecting or forgetting a submission can't reset the count. No foreign keys. |
| `altcha_used_challenges` | ALTCHA replay protection: the signature of every solved challenge, kept until `expires_at` (indexed; the hourly cleanup deletes expired rows). Inserting a signature twice fails: a solution is accepted once. |
| `branding_profiles` | The global branding (`project_id` null) and per-project overrides; `uq_branding_profiles_project_id` is `UNIQUE NULLS NOT DISTINCT`, so there is at most one global row (created on its first save) and one per project. Every field nullable = inherit (project → global → built-in default). `primary_color`, `accent_color` match `^#[0-9a-f]{6}$` (`ck_branding_profiles_*_color_hex`), `font` is a `BrandFont` key (`ck_branding_profiles_font`), `app_name` 1–40 characters, `email_footer` ≤ 500 (plain text, ≤ 5 lines: API validation). `logo_asset_id`, `favicon_asset_id` reference `brand_assets` (`ON DELETE SET NULL`). |
| `brand_assets` | Uploaded logos and favicons ([ADR 0012](adr/0012-branding-and-uploaded-images.md)): the bytes in the database (`bytea`, `byte_size` = `octet_length(data)`, 1 byte to 1 MiB), `content_type` only `image/png` (re-encoded PNG uploads) or `image/svg+xml` (allow-listed, re-serialised SVG), `sha256` (the ETag), pixel `width`/`height` (≤ 4096; null for an SVG without a size). `project_id` null = a global image. Immutable: a new image is a new row, so URLs cache for ever. Unreferenced rows are deleted by the hourly cleanup 24 hours after upload. Index `(project_id, created_at)` (upload quota, cleanup). |
| `api_keys` | Personal API keys ([contract-phase5 §3.1](api/contract-phase5.md#31-keys-format-storage-and-lifecycle), [ADR 0013](adr/0013-api-keys-and-mcp-server.md)). A key is `sdg_<lookup_id>_<secret>`; only `lookup_id` (12 base62 characters, `ck_api_keys_lookup_id_format`, unique: the lookup) and `secret_hash` (SHA-256 hex of the whole key, `ck_api_keys_secret_hash_format`, compared in constant time) are stored, never the key. `scopes` is a `varchar[]` of 1–4 `ApiKeyScope` values (`ck_api_keys_scopes`, no NULL element), distinct and in canonical order (application); `write` or `evaluate` always comes with `read` (`ck_api_keys_scopes_include_read`). `project_ids` is a `uuid[]` restriction (null = every project the owner can access; else 1–50 ids and no NULL element, `ck_api_keys_project_ids_not_empty`, so a restriction can never read as "every project"; no foreign key: a deleted project's id matches nothing, so a restriction never widens). `created_auth_method` is the creating session's sign-in method (`ck_api_keys_created_auth_method`): the key works only while that method is available. `name` 1–80 characters, unique per owner case-insensitively among keys that aren't revoked (`uq_api_keys_user_id_name_lower`, partial on `revoked_at IS NULL`). `expires_at` null = never. `last_used_at` moves at most once a minute. Revoking sets `revoked_at` and `revoked_by_id` (`ck_api_keys_revoked_by_needs_revoked`); the row stays, never listed again, so audit entries can name the key. `created_by_id` is the owner, or from Phase 6 the platform admin who registered an agent. A person's key also stops working (state `dormant`, no column) while the owner's `users.last_seen_at` is older than 30 days. Indexes: `user_id`, and `ix_api_keys_created_at_id_unrevoked (created_at, id) WHERE revoked_at IS NULL` (Admin → API keys, newest first). At most 25 per user that aren't revoked (application, under the owner's row lock). |
| `proposal_suggestions` | Suggested text for one proposal section ([contract-phase5 §3.4](api/contract-phase5.md#34-proposal-suggestions); `section_key` a template key, `ck_proposal_suggestions_section_key_format`, Phase 8): `body_md` is the whole section, verbatim (`ck_proposal_suggestions_body_not_empty`); `base_version` (≥ 1) the section version its author read; `source` `api` (REST), `mcp` (a person's key) or `ai` (a service account through MCP); `status` `pending` until the owner or an admin accepts (a normal versioned section save) or discards it, with `decided_by_id` / `decided_at` set exactly when not pending (`ck_proposal_suggestions_decided_iff_not_pending`). One pending suggestion per author per section (`uq_proposal_suggestions_pending_author_section`, partial on `status = 'pending'`: a newer one discards the older, decided by its author); at most 50 pending per proposal (application). Indexes: `proposal_id`, `author_id`, and `(proposal_id, created_at) WHERE status = 'pending'` (the editor's list and the cap). No score data. |
| `ai_agents` | kagent agents registered by a platform admin ([contract-phase6 §3.1](api/contract-phase6.md#31-agents-their-service-accounts-and-keys), [ADR 0014](adr/0014-kagent-a2a-integration.md)). `namespace` and `name` are DNS-1123 labels (`ck_ai_agents_namespace_format`, `ck_ai_agents_name_format`), unique together (`uq_ai_agents_namespace_name`); the A2A URL is **not stored**: it is built from `SOUNDINGS_KAGENT_URL`, `protocol` and these two, so no row can point Soundings at another host. `purposes` is a `varchar[]` of 1–3 distinct `AiRunKind` values (`ck_ai_agents_purposes`, which also compares the elements pairwise: no purpose twice). `service_account_id` is unique (one agent per service account) and NO ACTION (users are never deleted). Agents are disabled (which revokes their key), never deleted. |
| `ai_agent_projects` | The projects an agent serves: primary key `(agent_id, project_id)`, indexed by `project_id`, cascading with either side. Its key's `project_ids` mirror these rows. |
| `ai_runs` | One AI job on an idea ([contract-phase6 §3.3](api/contract-phase6.md#33-runs-lifecycle-statuses-and-a2a-states)). `section_key` iff `kind = 'draft_section'` (Phase 8: a template key of the idea's project, `ck_ai_runs_section_key_format`; revision 0012 recreated `uq_ai_runs_active` around the type change); `finished_at` iff final; `started_at` for `running` and `succeeded`; `error_code` and `error_message` iff `failed` or `timed_out`; each result column only for its kind (`ck_ai_runs_result_matches_kind`). **Idempotency:** `uq_ai_runs_active` (`UNIQUE NULLS NOT DISTINCT (idea_id, agent_id, kind, section_key) WHERE status IN ('queued', 'running')`); it also serves c22's "open run of this agent on this idea" lookup. `ix_ai_runs_created_at_active` (partial) is the sweep's (stale running runs, expired queued runs; the queue itself is procrastinate's `ai` queue); `ix_ai_runs_requested_by_id_created_at` the per-person hourly limit; `ix_ai_runs_evaluation_id`, `_suggestion_id`, `_activity_event_id` (partial, `WHERE … IS NOT NULL`) keep the `ON DELETE SET NULL` cascades from scanning the table. `assigned_evaluator` (evaluate only, `ck_ai_runs_assigned_evaluator_evaluate`): the run's request assigned the agent as the idea's evaluator, so a run ending without its submitted evaluation removes that assignment. Status changes are compare-and-set updates; `a2a_task_id` holds at most 200 characters (a longer id fails the run). `event_count` numbers events (`UPDATE … SET event_count = event_count + 1 RETURNING event_count`). |
| `ai_run_events` | A run's progress, primary key `(run_id, seq)` (seq from 1: the SSE event id), cascading with the run. `message` is Soundings' own sentence (never the agent's text, never score data); at most 200 per run, the final included (application). |
| `proposal_template_sections` | Phase 8: a project's proposal template ([contract-phase8 §2](api/contract-phase8.md#2-per-project-proposal-templates)). 1–12 active (`archived_at IS NULL`) per project, ordered by `position` (≥ 0; `ix_proposal_template_sections_project_id_position`). `key` matches `^[a-z][a-z0-9_]{0,39}$` (`ck_proposal_template_sections_key_format`), unique per project among all rows, removed ones included (`uq_proposal_template_sections_project_id_key`), never changed; active titles unique case-insensitively (`uq_proposal_template_sections_project_id_title_lower`, partial; the replace applies archives and renames before inserts). Removing a section archives it when a proposal has text in it or a thread, suggestion or AI run names its key, else deletes it (and its empty section rows). Revision 0012 gave every project the eight defaults. Cascades with the project. |
| `research_checklist_items` | Phase 8: a project's research checklist ([contract-phase8 §3.3](api/contract-phase8.md#33-settings-the-step-and-the-checklist-replace_research_settings)). 1–10 active per project while the step is on (application), ordered by `position`; title 1–80 (`ck_research_checklist_items_title_not_empty`), unique among active case-insensitively (`uq_research_checklist_items_project_id_title_lower`, partial); `hint` ≤ 200; `required` default true (required items gate the statuses after Research). Answered items are archived when removed, unanswered ones deleted. Empty for every project until a project admin saves one. Turning the step off leaves the items as they are (hidden). |
| `research_answers` | Phase 8: an idea's answer to one item, primary key `(idea_id, item_id)` (no row = unanswered), indexed by `item_id`. `answer` plain text, 1–2,000 characters (`ck_research_answers_answer_length`). `answered_by_id` / `answered_at`: the first answer; `updated_by_id` / `updated_at`: the last change (`SET NULL` when a user is deleted). Cascades with the idea; `item_id` is `NO ACTION` (an answered item can't be deleted, only archived; deleting the project removes items and answers in one statement). Never score data. |
| `audit_log` | Append-only. No foreign keys, so entries outlive what they mention. `details` holds ids, enum values, field names, the IdP issuer/subject and group mapping values; never secrets, tokens, emails or claims. The admin viewer pages newest first on `ix_audit_log_created_at_id (created_at, id)`; its filters use `(actor_id, created_at)`, `(action, created_at)`, `(project_id, created_at)` and `(target_type, target_id)`. Actions: `app.schemas.audit.AuditAction`. Phase 5: `api_key.create`, `api_key.revoke` and `mcp.call` (one per MCP tool call, with the tool, rule, decision and code; deleted after 90 days by the hourly cleanup on `(action, created_at)`; every other entry is kept). Entries made through a key carry `details.auth = "api_key"` and `details.api_key_id`. |

## Delete behaviour

| Deleting | Effect |
|---|---|
| a project | Cascades to members, rubric, tags, ideas and everything under them, activity. |
| an idea | Cascades to tags, evaluators → evaluations → scores, votes, watchers, comments, activity. |
| an evaluator assignment | Cascades to their evaluation and scores. |
| a user (not a feature: users are deactivated) | Sessions, identities, external IDs, project and group memberships, assignments, votes and watches cascade; `owner_id`, `submitted_by_id`, `invited_by_id`, comment authors and activity actors become null. |
| a group | Cascades to its IdP values, memberships and project grants: access through it ends at once. |
| a project | Also cascades to its group grants. |
| a scored rubric criterion | Refused by the database at commit (deferred FK); archive it instead. |
| an idea (Phase 3) | Also cascades to its notifications; immediate emails about it lose their notification and are cancelled at send time ("no longer applies"). |
| a user (Phase 3) | Also cascades to their notifications, preferences and outbox rows addressed to them; `actor_id` and `requested_by_id` become null. |
| an outbox row (cleanup) | Its notifications stay, with `email_id` null; the same cleanup then turns pending digest items older than 7 days `off`, so a pruned digest's items never look pending again. |
| an idea (Phase 4) | Also cascades to its proposal (sections, threads, comments), its public submission and its submitter emails (`outbound_email.idea_id`). Rejecting a held public idea is deleting it. |
| a proposal thread | Cascades to its comments. |
| a project (Phase 4) | Also cascades to its public submissions, branding override and uploaded images. |
| a brand asset (cleanup, unreferenced) | A profile still naming it (it can't: the cleanup only deletes unreferenced rows) would get `null`. |
| a user (Phase 4) | Proposal authorship, section editors, thread creators and resolvers, comment authors, erasers, uploaders and branding editors become null. |
| a user (Phase 5) | Also cascades to their API keys; keys they created or revoked keep `created_by_id` / `revoked_by_id` null; their suggestions stay with `author_id` / `decided_by_id` null. |
| a proposal (with its idea) | Also cascades to its suggestions. |
| a project (Phase 5) | Nothing changes in `api_keys`: the id stays in restrictions and matches nothing. |
| an idea (Phase 6) | Also cascades to its AI runs and their events (an active run's worker finds it gone and stops; its A2A task is cancelled best effort). |
| an agent | Never deleted (disabled instead); its runs and service account stay. |
| a project (Phase 6) | Also cascades to its `ai_agent_projects` rows; the agent's key restriction keeps the id, which matches nothing. |
| an evaluation, suggestion or research note | The run that produced it keeps its row with that result column null. |
| a project (Phase 8) | Also cascades to its template sections, checklist items and (through its ideas) research answers. |
| an idea (Phase 8) | Also cascades to its research answers. |
| an answered checklist item | Refused (`NO ACTION`): archive it instead. |
| a template section | Only when nothing names its key (the replace archives it otherwise); its empty section rows go first. |
| downgrading 0012 | Moves ideas in Research back to the stage before it (New, or Shortlisted before a proposal step) and rewrites `research` in status payloads (activity, notifications, outbox) the same way (so the feed may show a no-op line such as "Shortlisted → Shortlisted", and a pending team email, which names no idea, gets `new`); drops `research` label overrides, the research tables and `projects.research_step`; deletes AI runs, suggestions, threads and section texts of sections that aren't one of the eight defaults; gives every proposal back its eight default rows; restores the eight-key checks and drops the template table. |
| downgrading 0011 | First revokes every agent's API key (older code doesn't confine agents' keys to their runs, c22) and deletes the research notes (`activity_events` of type `ai_research_note`, which older code can't show), then drops `ai_run_events`, `ai_runs`, `ai_agent_projects`, `ai_agents` and `evaluation_scores.sources`: agents, run history and AI evaluations' cited sources are lost; the evaluations and service accounts stay, their keys listed as revoked. |
| downgrading 0010 | Drops `api_keys` (every key stops working) and `proposal_suggestions`. |
| downgrading 0009 / 0008 | 0009 drops `reached_team_at`; 0008 drops `confirmation_email_sends` (the limit then counts `outbound_email` again, by the old index it recreates). |
| downgrading 0007 | Deletes ideas still held and every submitter email, then drops the Phase 4 tables and columns: proposals, submitter details, branding and images are lost; public ideas stay as anonymous ideas. |

## Invariants the application enforces

The database does not check these (they span tables); the backend validates them in the
same transaction and tests them:

- A score's criterion belongs to the evaluated idea's project (else 422 `unknown_criterion`).
- An idea's tags belong to the idea's project.
- An activity event's `project_id` is its idea's project.
- A submitted evaluation has a non-null score for every active criterion (422
  `evaluation_incomplete`).
- `ideas.vote_count` and the aggregate cache match their source rows.
- Service and break-glass accounts have no identities or external IDs; the break-glass
  admin also has no project roles or group memberships (it acts as platform admin only)
  and no API keys. From Phase 6 a service account may hold a direct project role
  (member or viewer, never admin) and has keys created by a platform admin.
- `group_idp_values.value` is already normalised
  (`app.schemas.groups.normalise_idp_value`).
- A notification's recipient passed `idea.view` when it was created; an email goes out
  only if they still do (re-checked at send time, contract-phase3 §3.9).
- A notification's `comment_id` belongs to its idea; an outbox row's notifications all
  have the row's recipient.
- No notification `payload` or outbox `payload` holds score data.
- (Phase 4; Phase 8) A proposal has a row for every active section of its project's
  template (and may keep rows of removed ones); every stored section key (sections,
  threads, suggestions, AI runs) is a key of the idea's project's template.
- (Phase 4) `public_submissions.project_id` is its idea's project; an outbox row has
  `idea_id` exactly when it has a submitter type, and its `to_address` was the
  submission's address when queued (re-checked at send time).
- (Phase 4) No idea held for moderation or email confirmation appears in a list, count,
  search, My work or notification; nothing but delete, approve, reject and erase writes
  to an idea held for moderation.
- (Phase 4) A branding profile's images are of its own scope (global or that project)
  and of the right kind (logo / favicon).
- (Phase 4) No column stores a tracking token in clear, and no log or audit entry holds
  a submitter's name, address or token.
- (Phase 5) No column, log, trace or audit entry holds an API key or its hash outside
  `api_keys.secret_hash`; a key's `scopes` and `project_ids` are distinct; a key
  authenticates only while it isn't revoked or expired and its owner is active and not
  the break-glass account.
- (Phase 5) A suggestion's `section_key` is a template section of its proposal (Phase 8:
  an active one when it is created); its
  text never holds score data; an accepted suggestion's text was saved as the section's
  text (one versioned save) in the same transaction.
- (Phase 6) An agent's `service_account_id` is a service account (`is_service_account`,
  never a person or the break-glass account); its key's scopes are
  `agent_key_scopes(purposes)` and its `project_ids` the agent's `ai_agent_projects`
  (kept equal on every change); the service account never holds the admin role.
- (Phase 6) An AI run's `agent_id` served the idea's project when it was requested; its
  result is the agent's own (the evaluation's evaluator, the suggestion's or note's
  author is the agent's service account) and on the run's idea.
- (Phase 6) `evaluation_scores.sources` is empty for people's evaluations; each entry is
  `{title, url}` with a one-line title and an http(s) URL without credentials, stored as
  plain ASCII (punycode host); so are research notes' sources.
- (Phase 6) An agent's key does nothing outside the agent's `running` runs (c22): the
  run rows are part of its authorisation.
- (Phase 6) No `ai_run_events.message`, `ai_runs.error_message` or A2A message holds
  agent text, score data, keys or tokens; research notes (`activity_events` of type
  `ai_research_note`) hold no score data.
- (Phase 8) An idea is in `research` only while its project's `research_step` isn't
  `off`; the step changes only while no idea of the project is in Research.
- (Phase 8) A research answer's item belongs to the idea's project; no idea crosses into
  a status after Research while an active required item has no answer, unless a project
  or platform admin overrode it (audited `idea.research_override`); a closed idea counts
  from the status it was closed from (the latest `status_changed` event into `closed`).
  An answer has at least one visible character (the API removes invisible ones).
