# API contract: Phase 1 (ideas, owners, evaluators)

The REST contract the Phase 1 backend implements and the frontend builds against (with
MSW mocks). Source of truth, in order: the Pydantic schemas in `backend/app/schemas/`
and route stubs in `backend/app/api/v1/`, exported to
`frontend/src/api/generated/openapi.json` (TypeScript: `schema.d.ts`, `make gen-api`).
This page explains them and adds the business rules the backend must implement and
test. Permission rules are named as in [role-matrix.md](../role-matrix.md); blind
evaluation and scoring follow [ADR 0006](../adr/0006-blind-evaluation-and-aggregate-scoring.md).
Tables and columns: [erd.md](../erd.md). What changed after the contract review:
[section 7](#7-changes-after-the-contract-review).

Contract changes go through the lead ([ADR 0008](../adr/0008-contract-first-generated-client-msw.md)).
`backend/tests/test_contract_routes.py` pins every method, path and `operation_id`,
fails if two paths share a template, and fails if `openapi.json` is stale.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base URL | `/api/v1`. OpenAPI at `/api/v1/openapi.json`, Swagger UI at `/api/docs`. |
| JSON | snake_case. Timestamps ISO 8601 with offset, UTC. Request datetimes (`due_at`) must include an offset. Ids are UUIDs; ideas also have keys (`CUST-12`). |
| Idea paths | Every idea route is `/ideas/{idea}/…`, where `{idea}` is the UUID **or** the key in any case (`CUST-12`, `cust-12`). The SPA can call reads and writes with the key from its URL. Malformed values are 422. |
| Auth | Session cookie `soundings_session` (HttpOnly, `SameSite=Lax`, `Secure` over HTTPS, `Path=/`), OpenAPI security scheme `session`. Phase 1 signs in with the dev stub; Phase 2 adds OIDC with the same session. Every route except `list_dev_users`, `dev_login` and `logout` needs a session (401 `unauthorized` otherwise). |
| Principal | Signed-in routes take `PrincipalDep` (`app/api/v1/principal.py`), never a bare user: a `Principal` (`app/domain/principal.py`) is the user plus `auth` (`session`; Phase 5 `api_key`), `scopes` and `project_ids` (the key's restriction; `None` for sessions). Routes pass it to the authz policy, so API keys change how the principal is built, not the routes. |
| CSRF | `POST`/`PUT`/`PATCH`/`DELETE` must send `X-CSRF-Token` equal to the readable `soundings_csrf` cookie (set at sign-in); otherwise 403 `csrf_failed`. `src/api/client.ts` already does this. |
| Errors | `application/problem+json` (`Problem`: `type`, `title`, `status`, `detail`, `instance`, `code`, `request_id`). Branch on `code`. 422s are `ValidationProblem` with `errors[]` (`loc`, `msg`, `type`). As RFC 9457 allows, `detail`, `instance` and `request_id` may be absent. |
| Check order | 401 (and 403 `csrf_failed`) → 422 `validation_error` (malformed path, query or body: FastAPI checks the request's shape before the handler) → 404 (you may not know it exists) → 403 (you can see it, may not act) → 422 business codes (`user_not_found`, `assignee_not_eligible`, …) → 409 (state). First failure wins. Exception: a body that is not JSON at all is 422 before anything else. Nothing leaks: a shape error says nothing about the resource. |
| Pagination | Growing lists (ideas, owned ideas, activity, users) take `?cursor=&limit=` (default 50, max 200) and return `{items, next_cursor}` (`null` on the last page). Cursors are opaque and only valid for the same filters and sort. They are unsigned base64 JSON (`app/pagination.py`), so they must never hold anything the caller may not see (§3.7). Small fixed lists (projects, members, tags, evaluations) are plain arrays or objects. |
| PATCH | Omitted **or `null`** fields are unchanged, except inside `status_labels`, where `null` resets a label to its default. Unknown fields are rejected (422). Strings are trimmed. Where `null` must mean "none", the endpoint is a `PUT` of the complete value instead (`set_idea_owner`, `set_evaluation_due_date`). |
| Responses | Every documented response field is always present; nullable ones are `null`, never missing (problem bodies excepted, above). |
| Permissions | `permissions` objects (`ProjectSummary`, `Project`, `IdeaSummary`, `IdeaDetail`) carry booleans computed by the same policy the API enforces; use them to show or hide controls, never as security, and never work out roles in the client. In an archived project every idea-write flag is false. |

## 2. Endpoints

`Rule` names a row of the role matrix. "view" means the viewer passes `project.view` /
`idea.view`; otherwise the answer is 404. Common errors (401, 403 `csrf_failed`, 422
`validation_error`, 400 `invalid_cursor`) are not repeated per row.

### Auth (`tags: auth`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /auth/me` | `get_me` | signed in | → `CurrentUser` | 401 |
| `GET /auth/dev/users` | `list_dev_users` | dev login enabled | → `CurrentUser[]` (active users, platform admins first, then by name) | 404 when `SOUNDINGS_DEV_LOGIN_ENABLED` is off |
| `POST /auth/dev/login` | `dev_login` | dev login enabled | `DevLoginRequest {user_id}` → `CurrentUser`; sets `soundings_session` + `soundings_csrf`; rotates any existing session | 404 disabled; 422 `user_not_found` (unknown or inactive) |
| `POST /auth/logout` | `logout` | none | → 204; deletes the session row, clears both cookies | none (always 204) |

### Users (`tags: users`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /users?q=&project=&cursor=&limit=` | `search_users` | `user.search`; `project` also needs `project.view` | → `UserPage` of `UserSearchResult` (`UserRef` + `email`, `project_role`). Active, non-service-account users whose name or email contains `q` (case-insensitive), by display name. With `project`: users with an effective role in it only, `project_role` filled. | 404 project |

### Projects (`tags: projects`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /projects?include_archived=` | `list_projects` | `project.view` (filter) | → `ProjectSummary[]` by name, each with `permissions`: projects you have an effective role in, internal projects, all for platform admins | |
| `POST /projects` | `create_project` | `project.create` | `ProjectCreate {name, slug, key, description?, visibility?, admin_user_id?}` → 201 `Project` | 409 `slug_taken`, `key_taken`; 422 `user_not_found` |
| `GET /projects/{slug}` | `get_project` | `project.view` | → `Project` (settings, `status_labels` resolved, active `rubric`, `permissions`). The only way to read the rubric. | 404 |
| `PATCH /projects/{slug}` | `update_project` | `project.edit_settings`; `status_labels` needs `project.rename_status_labels` | `ProjectUpdate` → `Project` | 403, 404 |
| `GET /projects/{slug}/members` | `list_project_members` | `project.view` | → `Member[]` (direct members; admins first, then by name) | 404 |
| `POST /projects/{slug}/members` | `add_project_member` | `project.manage_members` | `MemberAdd {user_id, role=member}` → 201 `Member` | 409 `already_member`; 422 `user_not_found` |
| `PATCH /projects/{slug}/members/{user_id}` | `update_project_member` | `project.manage_members` (c11) | `MemberUpdate {role}` → `Member` | 404 not a member; 409 `last_admin` |
| `DELETE /projects/{slug}/members/{user_id}` | `remove_project_member` | `project.manage_members` (c11) | → 204 | 404; 409 `last_admin` |
| `PUT /projects/{slug}/rubric` | `replace_rubric` | `project.edit_rubric` | `RubricUpdate {criteria: 3..6}` → `Rubric` | 422 `unknown_criterion` |
| `GET /projects/{slug}/tags` | `list_project_tags` | `project.view` | → `TagInfo[] {id, name, idea_count ≥ 1}` by name: tags on at least one idea you can view | 404 |

### Ideas (`tags: ideas`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /projects/{slug}/ideas` | `list_ideas` | `project.view`; rows by `idea.view`; scores by `score.view_aggregate` | filters (§3.9) incl. `status`, `resolution` + `cursor`, `limit` → `IdeaPage {items: IdeaSummary[], next_cursor, total}` | 404 |
| `GET /projects/{slug}/board` | `get_board` | as `list_ideas` | filters without `status`/`resolution`, `limit` per column → `Board {columns[5]}` (the closed column has `resolution_counts`) | 404 |
| `POST /projects/{slug}/ideas` | `create_idea` | `idea.create` | `IdeaCreate {title, summary, description_md?, tags?}` → 201 `IdeaDetail` | 403, 404; 409 `project_archived` |
| `GET /ideas/{idea}` | `get_idea` | `idea.view` | → `IdeaDetail` | 404 |
| `PATCH /ideas/{idea}` | `update_idea` | `idea.edit_own` (c1) or `idea.edit_any` (owner: c5) | `IdeaUpdate` → `IdeaDetail` | 403 `not_submitter`; 409 `idea_not_new`, `idea_closed` |
| `DELETE /ideas/{idea}` | `delete_idea` | `idea.delete` | → 204 (the SPA confirms first; no undo) | 403 |
| `POST /ideas/{idea}/status` | `change_idea_status` | `idea.change_status` | `StatusChange {status, resolution?}` → `IdeaDetail` | 403; 422 (resolution rules) |
| `PUT /ideas/{idea}/owner` | `set_idea_owner` | `idea.assign_owner` (c4); the owner may send `null` only (`idea.release_owner`) | `OwnerAssign {user_id \| null}` → `IdeaDetail` | 403; 422 `assignee_not_eligible` |
| `POST /ideas/{idea}/volunteer` | `volunteer_as_owner` | `idea.volunteer_owner` (c3, c4 for platform admins, c13, c5) | → `IdeaDetail` | 403 `volunteering_disabled`; 422 `assignee_not_eligible`; 409 `idea_has_owner`, `idea_closed` |
| `POST /ideas/{idea}/evaluators` | `add_evaluators` | `evaluator.manage` (c4, c6) | `EvaluatorsAdd {user_ids[1..20], due_at?}` → `IdeaDetail` | 422 `assignee_not_eligible`; 409 `evaluation_closed` |
| `DELETE /ideas/{idea}/evaluators/{user_id}` | `remove_evaluator` | `evaluator.manage` (c16; **not** c6) | → `IdeaDetail` | 403 `cannot_remove_self`; 404 not assigned; 409 `evaluator_has_submitted` |
| `PUT /ideas/{idea}/evaluation/due-date` | `set_evaluation_due_date` | `idea.set_due_date` (c6) | `EvaluationDueDate {due_at \| null}` (required; `null` = no due date) → `IdeaDetail` | 409 `evaluation_closed` |
| `POST /ideas/{idea}/evaluation/close` | `close_evaluation` | `evaluation.close` (c5) | → `IdeaDetail`; idempotent | 409 `idea_closed` |
| `POST /ideas/{idea}/evaluation/reopen` | `reopen_evaluation` | `evaluation.close` (c5) | → `IdeaDetail`; idempotent | 409 `idea_closed` |
| `PUT /ideas/{idea}/vote` | `vote_idea` | `idea.vote` | → `VoteState {vote_count, has_voted}`; idempotent | 403 |
| `DELETE /ideas/{idea}/vote` | `unvote_idea` | `idea.vote` | → `VoteState`; idempotent | 403 |
| `PUT /ideas/{idea}/watch` | `watch_idea` | `idea.watch` | → `WatchState {watching}`; idempotent | |
| `DELETE /ideas/{idea}/watch` | `unwatch_idea` | `idea.watch` | → `WatchState`; idempotent | |

In an archived project every idea-level write (create, edit, delete, status, owner,
evaluators, due date, close/reopen, votes, evaluations, comments) returns 409
`project_archived`; reads, watching and project settings still work.

### Evaluations (`tags: evaluations`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /ideas/{idea}/evaluations` | `list_evaluations` | `idea.view` + `evaluation.view_others` (✱) | → `EvaluationList {items: Evaluation[], score_hidden}`: every submitted evaluation, oldest first; `items: []` and `score_hidden: true` for a pending evaluator | 404 |
| `GET /ideas/{idea}/evaluations/me` | `get_my_evaluation` | `evaluation.view_own` | → `MyEvaluation`, or `null` if you are not an evaluator of this idea | 404 |
| `PUT /ideas/{idea}/evaluations/me` | `save_my_evaluation` | `evaluation.submit_own` (c6) | `MyEvaluationIn {scores[], recommendation?, comment?, submit}` → `MyEvaluation` | 403; 409 `evaluation_closed`, `evaluation_already_submitted`; 422 `evaluation_incomplete`, `unknown_criterion` |

### Activity and comments (`tags: activity`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /ideas/{idea}/activity?cursor=&limit=` | `list_idea_activity` | `idea.view` | → `ActivityPage` of `ActivityItem`, **newest first** (reverse to render oldest → newest) | 404 |
| `POST /ideas/{idea}/comments` | `create_comment` | `comment.create` | `CommentCreate {body_md}` → 201 `CommentActivity` | 403; 409 `project_archived` |
| `PATCH /comments/{comment_id}` | `update_comment` | `comment.edit_own` (c2) | `CommentUpdate {body_md}` → `CommentActivity` | 403 `not_author`; 404 (also when deleted) |
| `DELETE /comments/{comment_id}` | `delete_comment` | `comment.edit_own` (c2) or `comment.delete_any` | → 204 | 403 `not_author`; 404 (also when deleted) |

### My work and search (`tags: work`, `search`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /me/work` | `get_my_work` | signed in; contents filtered by `idea.view` and `score.view_aggregate` | → `Work` (§3.10) | |
| `GET /me/owned-ideas?status=&cursor=&limit=` | `list_my_owned_ideas` | signed in; as `get_my_work` | → `IdeaPage` of ideas you own in non-archived projects, most recently active first; "load more" for a My work group | |
| `GET /search?q=&limit=` | `global_search` | signed in; results filtered by `project.view` / `idea.view` | `q` 1–200 chars, `limit` per kind (default 8, max 20) → `SearchResults {ideas: IdeaRef[], projects: ProjectRef[]}` | |

## 3. Business rules

Tests first for 3.2–3.7 (SPEC section 15). "Emit" means insert an `activity_events` row
(actor = current user) and set `ideas.last_activity_at = now()`, in the same
transaction as the change.

### 3.1 Projects, members, labels, roles

- **Effective role:** every query that needs a user's project role reads the
  `project_effective_roles` view (`app.models.project_effective_roles`), never
  `project_members`: `list_projects`, `search_users?project=`, My work, c4, c11 and the
  authz policy. Phase 1 the view mirrors `project_members`; Phase 2 redefines it with
  group grants and nothing else changes. `project_members` is read directly only to
  list and edit *direct* members.
- **Create:** `slug` and `key` are unique (409 `slug_taken` / `key_taken`) and immutable
  afterwards. The project gets the default rubric
  (`app/domain/rubric_defaults.py:default_rubric_criteria`) and one admin:
  `admin_user_id`, defaulting to the creator (a platform admin). `next_idea_number = 1`.
- **Permissions:** `ProjectSummary.permissions` (so also `Project.permissions`):
  `can_manage` = project or platform admin; `can_create_ideas` = passes `idea.create`
  (member, admin or platform admin) and the project is not archived. A platform admin
  who is not a member has `my_role: null` but `can_create_ideas: true`: the submit
  dialog's project picker and `N` use `permissions`, never `my_role`.
- **Status labels:** `projects.status_labels` stores overrides only. Resolved labels =
  `DEFAULT_STATUS_LABELS` (`app/schemas/projects.py`) overlaid with the overrides, for
  all five statuses and three resolutions. PATCH: omitted = unchanged, string = set
  (setting the default removes the override), `null` = reset. An idea's `status_label`
  is the label of its resolution when closed ("Accepted"), else of its status.
- **Members:** adding an unknown or inactive user → 422 `user_not_found`; an existing
  member → 409 `already_member`. Demoting or removing the last admin → 409
  `last_admin`. Removing or demoting a member keeps their owner/evaluator assignments,
  which grant nothing while they lack a member/admin role (role matrix §1).
- **Rubric:** `replace_rubric` validates 3–6 criteria with unique names
  (case-insensitive); weights are 0.01–10 in steps of 0.01 (the column is
  `numeric(4,2)`, `> 0`). Apply renames and archives before inserting new criteria:
  active names are unique in the database too. Read the rubric from `get_project`.
- **Archive:** `PATCH {archived: true}` sets `archived_at`; archived projects are left
  out of `list_projects` (unless `include_archived`), search and My work, and their
  ideas are read-only (§2, 409 `project_archived`). `{archived: false}` restores.
- **Counts:** `idea_count` = ideas the viewer can see; `member_count` = direct members.
- **Emails** appear in `CurrentUser` (yours), `Member` and `UserSearchResult` (people
  pickers), for signed-in colleagues only; `UserRef` never has one, and nothing public
  or anonymous shows them.

### 3.2 Ideas and keys

- **Key** = `<project.key>-<number>`. Numbers start at 1 per project and are allocated
  with `UPDATE projects SET next_idea_number = next_idea_number + 1 ... RETURNING` in
  the create transaction; never reused (deleted ideas leave gaps). Every
  `/ideas/{idea}` route accepts the UUID or the key in any case.
- **Create:** `title` and `summary` are required (the wireframe's two required fields).
  Status `new`, unowned, `submitted_by` = you, tags attached (see below). The
  submitter watches the idea. Emit `idea_created`.
- **Tags:** names are matched to the project's tags case-insensitively (the first
  spelling is kept); unknown names create tags. `tags` in `IdeaUpdate` replaces the
  set. Max 10 per idea. Tag rows are never deleted, but `list_project_tags` lists only
  tags on at least one idea you can view, so a typo disappears from the chips and the
  autocomplete once no idea carries it.
- **Edit:** submitter while `new` (else 409 `idea_not_new`), owner while not closed (409
  `idea_closed`), project/platform admins always; anyone else with view access → 403
  `not_submitter`. `summary` can't be emptied. Emit `idea_edited {fields}` listing the
  fields whose value actually changed; nothing changed → no event.
- **Delete:** admins only; hard delete with everything under the idea.

### 3.3 Status transitions

- Any status → any status, by the owner or an admin (`idea.change_status`). No
  transition graph.
- `closed` requires `resolution`; other statuses forbid it (422 from the schema).
  Leaving `closed` clears `resolution`. `closed → closed` with another resolution is a
  change.
- **No side effects.** Moving to `evaluating` does not set a due date (the first
  invite does, §3.5), so calling `change_idea_status` with the previous status and
  resolution undoes a move exactly.
- Same status and resolution → 200, no change, no event.
- Emit `status_changed {from_status, from_resolution, to_status, to_resolution}`.

### 3.4 Owner

- `PUT owner` by an admin: `user_id` must have effective role member/admin in the
  project (c4, else 422 `assignee_not_eligible`), or `null` to unassign.
- `PUT owner` by the current owner: only `{user_id: null}` (step down); anything else →
  403.
- `POST volunteer`: see the endpoint row. Sets you as owner.
- The new owner watches the idea. Emit `owner_changed {from_owner_id, to_owner_id,
  volunteered}` when the owner actually changes.

### 3.5 Evaluators and the evaluation window

- **Evaluation is open** when `evaluation_closed_at IS NULL` and `status <> 'closed'`
  (`IdeaDetail.evaluation_open`). Evaluations can be saved, evaluators invited and the
  due date changed only while open (409 `evaluation_closed`).
- **Invite** (`add_evaluators`): every new user needs effective role member/admin
  (c4); one ineligible user fails the whole request (422 `assignee_not_eligible`,
  nothing added). Users already assigned are skipped. Each new evaluator watches the
  idea; emit `evaluator_added {evaluator_id}` per new evaluator. If `due_at` is given
  and differs, set it and emit `due_date_changed`. Otherwise, **only the first invite**
  (the idea had no evaluators before this request) sets a default, and only when the
  idea has no due date: `now() + default_evaluation_days` (no event). Later invites
  never touch the due date, so a date someone cleared stays cleared.
- **Remove** (`remove_evaluator`), whatever the evaluation state (open, closed, or the
  idea closed), so an evaluator who never submitted can always be released from
  blindness (role matrix §3 rule 7):
  1. yourself → 403 `cannot_remove_self` (c16). Otherwise an owner or admin who is a
     pending evaluator could remove themselves, see every score, re-invite themselves
     and submit an anchored evaluation. Another owner/admin can remove you; or submit.
  2. not assigned → 404;
  3. already submitted → 409 `evaluator_has_submitted` (submitted work is never
     thrown away);
  4. otherwise delete the assignment (the draft goes with it) and emit
     `evaluator_removed {evaluator_id}`.
  In an archived project, 409 `project_archived` as for every idea write.
- **Due date:** `PUT evaluation/due-date {due_at}` sets it, or clears it with `null`;
  emit `due_date_changed {from_due_at, to_due_at}` when it changes.
- **Close / reopen:** set / clear `evaluation_closed_at`; emit `evaluation_closed` /
  `evaluation_reopened` only when the state changes (both calls are idempotent). 409
  `idea_closed` if the idea is closed.
- **Permissions:** `can_invite_evaluators` = `evaluator.manage` with c6 (also covers
  the due date: `idea.set_due_date` has the same conditions); `can_remove_evaluators` =
  `evaluator.manage` without c6. The SPA offers "remove" only on rows of *other*
  evaluators whose `state` isn't `submitted`.

### 3.6 Evaluations

- `PUT evaluations/me` needs an assignment and member/admin role (403 otherwise) and an
  open evaluation (409 `evaluation_closed`). The body **replaces** your saved scores,
  recommendation and comment. Every `criterion_id` must be an active criterion of the
  idea's project (422 `unknown_criterion`).
- `submit: false` saves a draft (the row is created on first save). After submitting,
  `submit: false` → 409 `evaluation_already_submitted`: an evaluation never goes back
  to draft.
- `submit: true` requires a non-null score for **every active criterion** and a
  `recommendation`; otherwise 422 `evaluation_incomplete`, a `ValidationProblem` whose
  `errors` has one entry per gap: `loc: ["body", "scores", "<criterion_id>"]` or
  `["body", "recommendation"]`, `type: "missing"`. The first submission sets
  `submitted_at` and emits `evaluation_submitted {evaluator_id}`. A later save of a
  submitted evaluation keeps `submitted_at`, sets `edited_at = now()` and emits
  nothing; `Evaluation.edited_at` lets the UI show "edited after submission" (the
  spec lets evaluators edit after seeing others' scores; this makes it visible).
- Every save of a submitted evaluation, and the first submission, recomputes the idea's
  aggregate cache (§3.8).
- Evaluations are editable until evaluation closes (or the idea closes); a submitted
  evaluation stays submitted if evaluation reopens.
- `Evaluation.is_ai` = the evaluator is a service account (`users.is_service_account`;
  there is no column on `evaluations`). `include_in_aggregate = true` for every Phase 1
  evaluation.
- Scores for archived criteria stay stored but are left out of every response and the
  aggregate. After a criterion is added, existing submissions stay submitted; their
  next save must score it.
- `MyEvaluation.state` is `invited` (nothing saved), `draft` or `submitted`;
  `editable` = evaluation open.

### 3.7 Blind evaluation

Normative text: [role matrix §3](../role-matrix.md#3-blind-evaluation-exact-visibility-rules).
In API terms, for viewer *V* and idea *I*, *V* is a **pending evaluator** when *V* is
assigned to *I* and *V*'s evaluation of *I* is missing or a draft. No role lifts this,
closing evaluation doesn't either, and *V* can't remove their own assignment (§3.5).
The API flags it with one boolean, `score_hidden`, everywhere.

| Surface | Pending evaluator sees | Everyone else with view access sees |
|---|---|---|
| `IdeaSummary` (list, board, My work, owned ideas) | `score: null`, `score_hidden: true`, `high_disagreement: false` | `score` (`null` only if `aggregate_count = 0`), `score_hidden: false`, the real flag |
| `IdeaDetail` | as above, plus `aggregate: null` | `aggregate` (or `null` with no included submissions) |
| `GET .../evaluations` | `items: []`, `score_hidden: true` | every submitted evaluation (human and AI, included or not), `score_hidden: false` |
| `sort=score` / `-score` | *I* sorts as unscored (after every scored idea) | by `aggregate_score`, nulls last |
| `sort=score` cursor | encodes the **masked** score (`null` for *I*), never the raw `aggregate_score` | encodes `aggregate_score` |
| `high_disagreement=true` filter, board counts under it | *I* never matches | matches when flagged |
| `IdeaDetail.evaluators[].state` | others: `invited` or `submitted`; own row may be `draft` | same (drafts are private to their author) |
| `evaluator_progress` (submitted / assigned) | shown: submission counts are not score data | same |
| activity, search, `WorkEvaluation` | unaffected: they never contain scores | same |

After *V* submits, *V* sees everything immediately (the next response). Nobody ever
sees another person's draft. Implement the mask in SQL, not per row, e.g.:

```sql
CASE WHEN EXISTS (
  SELECT 1 FROM idea_evaluators ie
  LEFT JOIN evaluations e ON e.idea_id = ie.idea_id AND e.evaluator_id = ie.user_id
  WHERE ie.idea_id = ideas.id AND ie.user_id = :viewer
    AND (e.status IS NULL OR e.status <> 'submitted')
) THEN NULL ELSE ideas.aggregate_score END
```

Required tests (role matrix §3): for each surface above, a pending evaluator with no
draft and with a draft, the same user after submitting, a project admin who is a
pending evaluator, a viewer, and an internal non-member, with at least two other
submitted evaluations present. Also: a `sort=score` cursor issued to a pending
evaluator decodes to no raw score; and an owner or admin who is a pending evaluator
gets 403 `cannot_remove_self` removing themselves, and still sees nothing afterwards.

### 3.8 Aggregate score

Over the **included set** *E* = submitted evaluations with `include_in_aggregate`:

1. For each active criterion *c*, take the non-null scores *s* in *E*. The adjusted
   score is *a = s*, or *6 − s* when *c* is inverted. *m_c* = mean of *a*.
2. `overall` = Σ *w_c · m_c* / Σ *w_c* over active criteria with at least one score,
   rounded half-up to 1 decimal (`round(numeric, 1)`); computed from unrounded means.
3. `count` = |*E*|. With `count = 0` there is no aggregate: `aggregate_score` null,
   `score`/`aggregate` null, flag false.
4. `high_disagreement` = some active criterion has ≥ 2 scores in *E* with
   `max − min ≥ 2` (raw scores; inversion doesn't change the spread).
5. `CriterionAggregate` reports **raw** scores (as entered): `mean` (1 decimal), `min`,
   `max`, `spread = max − min`, `count`; `inverted` tells the UI to mark it.
   `recommendations` tallies go / maybe / no over *E*.

Cache `aggregate_score`, `aggregate_count`, `high_disagreement` on `ideas` and recompute
them in the same transaction as: a first submission or an edit of a submitted
evaluation, an `include_in_aggregate` change (Phase 6), and `replace_rubric` (all ideas
of the project). Removing an evaluator never changes it (only unsubmitted evaluators
can be removed).

**Worked example.** Value (weight 2), Effort (weight 1, inverted). A: Value 4, Effort 2.
B: Value 5, Effort 4. C: Value 2, Effort 3.
Value: mean 11/3 = 3.667, min 2, max 5, spread 3. Effort raw: mean 3.0, spread 2;
adjusted 4, 2, 3 → mean 3.0. Overall = (2 × 3.667 + 1 × 3.0) / 3 = 3.444 → **3.4**,
`count` 3, `high_disagreement` true (Value spread 3).

### 3.9 List and board

- Filters combine with AND; multiple `status`, `resolution` or `tag` values combine
  with OR.
  - `status`: any of the given statuses (list only; the board always has five columns).
  - `resolution`: closed ideas with any of the given resolutions (list only).
  - `owner`: a user id, `me`, or `none` (unowned).
  - `tag`: has any of the tags (names, case-insensitive).
  - `needs_evaluators=true`: not closed and no evaluators assigned.
  - `high_disagreement=true`: flagged and not hidden from you (§3.7).
  - `q`: title or summary contains `q` (case-insensitive, `pg_trgm`), or `q` is the
    idea's key.
- `sort`: `score`, `updated` (= `last_activity_at`), `created`, `votes`, `title`
  (case-insensitive); `-` prefix = descending; default `-updated`. Ideas without a
  visible score come last in both score directions. Ties break on `id`. Indexes
  `(project_id, last_activity_at, id)` and `(project_id, status, last_activity_at, id)`
  serve the default order.
- `total` is the number of ideas matching the filters.
- **Board:** columns `new, evaluating, shortlisted, proposal, closed`, each with its
  resolved `label`, `count` (all matching ideas in that status), the first `limit`
  ideas in `sort` order, and `next_cursor`. Load more of one column with `list_ideas`
  (`status=<column>`, the same filters and sort, `cursor=<next_cursor>`): board and
  list share one keyset cursor format. The closed column also has `resolution_counts
  {accepted, rejected, parked}` (null on the other columns); expanding it loads each
  part with `list_ideas?status=closed&resolution=<r>`.
- `IdeaSummary.permissions.can_change_status` (`idea.change_status`, false in archived
  projects) decides the drag handle on each card.
- `IdeaSummary.tags` are names, alphabetical. `evaluator_progress` = submitted /
  assigned. `comment_count` excludes deleted comments. `has_voted` is yours. There is
  no `updated_at` on ideas in the API: `last_activity_at` is "updated" (a recomputed
  aggregate must not look like an edit).

### 3.10 My work (`GET /me/work`, `GET /me/owned-ideas`)

- `evaluations_due`: ideas where you are assigned, your evaluation is missing or a
  draft, evaluation is open, you hold effective role member/admin in the project, and
  the project is not archived. Order: overdue first, then soonest `due_at`, no due date
  last. `overdue` = `due_at < now()`. `state` = `invited` / `draft`. `idea.project`
  names the project; `owner` = the idea's owner.
- `owned`: ideas you own in non-archived projects, grouped by status in lifecycle order
  with `closed` last (the UI collapses it); empty groups omitted; each group has its
  `count`, the default status `label`, the first 50 ideas (most recently active first)
  and `next_cursor`. More of a group: `GET /me/owned-ideas?status=<status>&cursor=`.
  `list_my_owned_ideas` without `status` lists every owned idea in the same order.
- `recent`: the 20 most recently active ideas in projects where you have an effective
  role (not every internal project you could view), one entry each, with the newest
  `ActivityItem` as `latest_activity`.
- `counts`: `evaluations_due` (= length of the list), `evaluations_overdue`,
  `owned_open` (owned, not closed) for the sidebar.
- Score fields follow §3.7 everywhere.

### 3.11 Search (`GET /search`)

Ideas and projects you can view, in non-archived projects. An exact key match
(`cust-12` → `CUST-12`) is always the first idea; then ideas whose title or summary
contains `q`, by title similarity then `last_activity_at`. Projects match on name or
slug, by name. At most `limit` of each. Results are `IdeaRef` (with `project`) and
`ProjectRef`: no scores.

### 3.12 Comments, votes, watching

- Comments are Markdown (the SPA renders without raw HTML). Creating one inserts the
  `comments` row and an `activity_events` row (`type = 'comment'`, `comment_id`); the
  author watches the idea. Editing sets `edited_at` (no event). Deleting sets
  `deleted_at` and clears `body_md`; the feed shows `deleted: true` with an empty body.
- `CommentBody.can_edit` = you wrote it and still pass `comment.create`;
  `can_delete` = that, or you are an admin.
- Votes: one per user per idea, `vote_count` cached on `ideas`; allowed in any status;
  no event, no `last_activity_at` bump. Watching: no event.

### 3.13 Activity events

| Action | Event `type` | Stored `payload` (API resolves ids to `UserRef`) | Watcher added |
|---|---|---|---|
| create idea | `idea_created` | `{}` | submitter |
| edit idea (something changed) | `idea_edited` | `{fields: [...]}` | |
| change status | `status_changed` | `{from_status, from_resolution, to_status, to_resolution}` | |
| assign / release / volunteer | `owner_changed` | `{from_owner_id, to_owner_id, volunteered}` | new owner |
| invite evaluators | `evaluator_added` (one per new evaluator) | `{evaluator_id}` | each evaluator |
| remove evaluator | `evaluator_removed` | `{evaluator_id}` | |
| due date set explicitly (`set_evaluation_due_date`, or `add_evaluators` with `due_at`) | `due_date_changed` | `{from_due_at, to_due_at}` | |
| close / reopen evaluation | `evaluation_closed` / `evaluation_reopened` | `{}` | |
| first submission | `evaluation_submitted` | `{evaluator_id}` | |
| comment | `comment` (+ `comment_id` column) | `{}` | author |

No events for: votes, watching, comment edits and deletes, later edits of a submitted
evaluation, the first invite's default due date, project/member/rubric changes (the
audit log covers admin changes from Phase 2). Payloads **never** contain scores. `type`
values not in this table must not appear in Phase 1.

### 3.14 Undo

The SPA shows an "Undo" toast after quick actions. Two mechanisms, no undo endpoints:

| Action | Undo |
|---|---|
| Change status (incl. board drag) | `change_idea_status` back to the previous status and resolution (no side effects, §3.3). |
| Assign / change / clear owner (admin) | `set_idea_owner` with the previous owner. |
| Volunteer | `set_idea_owner {user_id: null}` (you are the owner, so you may step down). |
| Step down (owner) | `volunteer_as_owner`, offered only if the response's `permissions.can_volunteer` is true; otherwise no undo. |
| Close / reopen evaluation | the other call. |
| Archive / restore project | `update_project {archived: false / true}`. |
| Change a member's role | `update_project_member` with the previous role. |
| Remove a member | `add_project_member` with the previous role (assignments were kept, §3.1). |
| Vote, watch | the opposite call. |
| **Delete a comment** | **Deferred:** the SPA hides the comment and sends `DELETE` only when the toast expires (or the page unloads); Undo cancels it. Deleting clears `body_md`, so it can't be restored afterwards. |
| **Remove an evaluator** | **Deferred** the same way: removing deletes their draft, and re-inviting would re-send the invitation email in Phase 3. |
| **Delete an idea** | No undo: a confirm dialog before `DELETE`. |

Inverse calls emit their own events (the feed shows both); that is intended.

## 4. Error codes

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_cursor` | malformed or foreign cursor, or one holding a value its column can't hold |
| 400 | `invalid_host` | `Host` not in `SOUNDINGS_BASE_URLS` (localhost allowed outside production; `/healthz`, `/readyz` exempt) |
| 401 | `unauthorized` | no valid session |
| 403 | `forbidden` | can view, may not act (generic) |
| 403 | `csrf_failed` | missing or wrong `X-CSRF-Token` |
| 403 | `not_submitter` | editing someone else's idea without `idea.edit_any` |
| 403 | `not_author` | editing or deleting someone else's comment |
| 403 | `volunteering_disabled` | project has `allow_volunteer_owners = false` |
| 403 | `cannot_remove_self` | removing yourself as an evaluator (c16) |
| 404 | `not_found` | missing, or not visible to you (same answer) |
| 409 | `slug_taken`, `key_taken` | project create |
| 409 | `already_member` | adding an existing member |
| 409 | `last_admin` | would leave the project without an admin |
| 409 | `project_archived` | write in an archived project |
| 409 | `idea_not_new` | submitter editing after `new` |
| 409 | `idea_closed` | action needs a non-closed idea |
| 409 | `idea_has_owner` | volunteering for an owned idea |
| 409 | `evaluation_closed` | evaluation not open (save, invite, due date) |
| 409 | `evaluation_already_submitted` | saving a submitted evaluation as a draft |
| 409 | `evaluator_has_submitted` | removing an evaluator who submitted |
| 413 | `content_too_large` | request body over 1 MiB (checked before authentication) |
| 422 | `validation_error` | request path/query/body invalid (`errors[]`) |
| 422 | `user_not_found` | unknown or inactive user in a body |
| 422 | `assignee_not_eligible` | owner/evaluator without member/admin role |
| 422 | `unknown_criterion` | criterion not in the active rubric |
| 422 | `evaluation_incomplete` | submit with gaps (`errors[]` lists them) |
| 501 | `not_implemented` | contract stub not built yet |

## 5. Decisions

Simpler option chosen each time; the lead may revisit. Rows marked *review* came from
the contract review of 2026-09-30.

| Decision | Why |
|---|---|
| One `GET /projects/{slug}/board` returns all columns with counts and first pages; more of a column comes from `list_ideas` with the same cursor. | One request paints the board; each column virtualises and pages independently; no second pagination scheme. |
| Aggregate, count and disagreement are cached on `ideas` (raw) and masked per viewer at read time. | Sorting/filtering 10k ideas by score stays an indexed query ([ADR 0006](../adr/0006-blind-evaluation-and-aggregate-scoring.md)). |
| Search uses `pg_trgm` GIN indexes on title and summary with `ILIKE`, plus exact key match. | No tsvector column or language config; substring search is what a palette needs. |
| Evaluations reference their assignment with a composite FK; removing a *submitted* evaluator is refused (409). | An evaluation can't outlive its assignment, and submitted work is never silently deleted. |
| AI evaluators (Phase 6) are service-account users; `is_ai` everywhere derives from `users.is_service_account` (*review*: `evaluations.is_ai` dropped). | One source of truth; same rules as people. |
| Enums are `VARCHAR` + named `CHECK`, not Postgres enums. | Adding a value later is a constraint swap, not `ALTER TYPE`. |
| One boolean `score_hidden` on every surface, including `EvaluationList` (*review*: `score_hidden_reason` cut; it had one value). ADR 0006 and the role matrix say `scores_hidden`: the lead aligns them to `score_hidden`. | One flag, one name, matching the `score` field it qualifies. |
| Other people's evaluator state never shows `draft` (reported as `invited`). | Drafts are private (decisions log). |
| Status change is any → any in one endpoint with **no side effects**: no automatic transitions, and moving to Evaluating no longer sets a due date (*review*). | The owner is accountable for moving it; Undo is the inverse call; no stray due dates. |
| Only the **first invite** sets the default due date (*review*), matching decisions.md ("due 7 days after the first invite"). | Evaluators are never overdue on arrival; a cleared date stays cleared. |
| Nobody removes themselves as an evaluator: 403 `cannot_remove_self`, new condition c16 (*review*). | Closes the bypass where an owner/admin who is pending removes, peeks, re-invites and submits anchored. |
| Removing a non-submitted evaluator works whether evaluation is open or closed (*review*: c6 dropped for remove). | Otherwise a pending evaluator on a closed idea stays blind for good, contradicting role matrix §3 rule 7. |
| Evaluation "open" is derived (`evaluation_closed_at` null and idea not closed); closing the idea doesn't touch `evaluation_closed_at`. | One rule, reversible by reopening the idea. |
| Close/reopen evaluation stay two idempotent POSTs, not folded into a `PATCH /evaluation {open}` (*review* suggestion declined). | Each maps to one button, has its own rule (c5 vs c6 for the due date) and event; folding them mixes the rules in one body. |
| The due date is `PUT /ideas/{idea}/evaluation/due-date {due_at \| null}` (*review*: was a `PATCH` where `null` meant "clear"). | Keeps the PATCH rule (`null` = unchanged) without exceptions; PUT means "this is the whole value". |
| Every idea route uses `{idea}` = UUID or key (*review*: `{ref}` vs `{idea_id}` gave `/ideas/{ref}` and `/ideas/{idea_id}` the same template, invalid in OpenAPI 3.1). | One template per path; the SPA uses the key from its URL for writes too. |
| Routes take a `Principal`, not a `User` (*review*). | Phase 5 API keys (scopes, project restriction) change how the principal is built, not every route (ADR 0010). |
| Project roles are read only through the `project_effective_roles` view (*review*). | Phase 2 group grants change one view instead of every query. |
| `IdeaRef.project: ProjectRef` everywhere (*review*: replaces `project_slug`, `IdeaSearchHit.project_name`, `WorkEvaluation.project`). | One way to name an idea's project; the idea page header gets the name. |
| `ProjectSummary.permissions` (*review*). | Platform admins without a role can create ideas; the client never derives that from `my_role`. |
| Per-card `IdeaSummary.permissions.can_change_status` (*review*). | Board drag handles without client-side role logic. |
| Board closed column has `resolution_counts`; `list_ideas` filters by `resolution` (*review*). | The Closed column can expand into Accepted / Rejected / Parked. |
| `GET /me/owned-ideas` pages owned ideas; each My work group has `next_cursor` (*review*). | The closed group grows forever; 50 was a silent cap. |
| Tags: rows are kept, only tags in use are listed (*review*; deleting orphans in the same transaction was the alternative). | Typos leave the chips without delete races between concurrent edits. |
| `IdeaSummary.updated_at` removed; `last_activity_at` is "updated" (*review*). | It changed silently on aggregate recomputes, hinting at edits. |
| `Evaluation.status` removed (always submitted) and `get_rubric` removed (`Project.rubric` has it) (*review*). | Less surface. The MCP tool `get_rubric` (Phase 5) is unaffected. |
| `Evaluation.edited_at` (new column) instead of comparing `updated_at` (*review*). | Makes "edited after submission" visible without being fooled by bookkeeping updates. |
| Rubric weights 0.01–10 in steps of 0.01 (*review*: any `> 0` could round to 0.00 and 500). | Matches `numeric(4,2)`; out-of-range is a 422. |
| `evaluation_scores.criterion_id` FK is `DEFERRABLE INITIALLY DEFERRED` (*review*: deleting a project with scores failed). | Project delete cascades; deleting one scored criterion is still refused (at commit). |
| Active criterion names unique per project in the database (*review*); the other cross-table invariants stay in the application ([erd.md](../erd.md#invariants-the-application-enforces)). | Cheap partial index; the rest would need composite keys or triggers. |
| `summary` is required on create and can't be emptied (*review*: the wireframe requires it). | Lists and cards always have a line to show. |
| Check order documents FastAPI's shape validation before 404/403 (*review*). | Table-driven tests expect what FastAPI actually does; a shape error reveals nothing. |
| Problem bodies may omit `detail`, `instance`, `request_id` (*review*). | RFC 9457 makes them optional; `code` is what clients use. |
| `operation_id`s `global_search`, `vote_idea` / `unvote_idea` (*review*: were `search`, `add_vote` / `remove_vote`). | Specific names; votes mirror `watch_idea` / `unwatch_idea`. |
| Emails stay in `Member` and `UserSearchResult` for signed-in users (*review* concern weighed, kept). | One organisation per instance; pickers need emails to tell namesakes apart. Never shown publicly or in `UserRef`. |
| Undo: inverse calls, or DELETEs held back for the toast's lifetime (§3.14) (*review*). | No undo endpoints or soft-delete tables. |
| Keyset indexes `(project_id, last_activity_at, id)`, `(project_id, status, last_activity_at, id)`; partial index for open due dates (*review*). | Default list/board order and the Phase 3 reminder scan stay index-only. |
| `recent` in My work covers projects where you have a role, not every viewable internal project (*review*: wireframe differs; lead aligns it). | Keeps the home screen about your projects. |
| `GET evaluations/me` returns `null` for non-evaluators instead of 403. | Role matrix `evaluation.view_own` ("empty result"); the idea page can call it unconditionally. |
| PATCH treats `null` like omitted (except `status_labels` entries). | Forgiving for clients; no tri-state types in TypeScript. |
| Project `slug` and `key` are immutable. | Links and idea keys stay stable. |
| Archived projects are read-only and hidden by default. | Gives "archive" one clear meaning without a delete. |
| Removing a member keeps their assignments (they grant nothing until re-added). | Matches role matrix §1; admins can see and fix them. |
| Members list, projects list and tags are not paginated. | Small by nature; group grants (Phase 2) may revisit members. |
| Comments are flat; mentions and notifications come in Phase 3. | SPEC: flat comments in Phase 1. |
| `GET /me/work` returns every evaluation due, uncapped, and `counts.evaluations_due` stays "= length of the list" (code review F9 weighed, kept for Phase 1). | p95 118 ms for an evaluator with 1,000 due among 10k ideas (`test_performance.py`), inside the 150 ms budget; nobody has hundreds due in practice. Revisit (cap at 100, count = total) if real data says otherwise. |

## 6. Room for later phases

- **Phase 2:** OIDC routes under `/auth`; `user_identities`, external ids, groups,
  `project_group_grants`, and `project_effective_roles` redefined as the highest of
  direct and group roles (same columns); audit log writes (evaluator removals
  included); ID token on sessions.
- **Phase 3:** notifications read `activity_events` and `idea_watchers`; outbox table.
  Before notifying a watcher, re-check `idea.view` (they may have lost access). "All
  evaluations are in" also fires when the last pending evaluator is *removed*, not
  only when the last one submits. Reminders scan `ix_ideas_evaluation_due_at_open`.
- **Phase 4:** proposals, public submission (`public_submission_enabled`, submitter
  fields on `ideas`, moderation), branding; `ProjectUpdate` gains those settings.
  Moderated ideas are filtered in **one** shared idea query builder used by lists,
  board, search, My work, tags and counts.
- **Phase 5:** API keys (bearer auth, no CSRF) build a `Principal` with `auth="api_key"`,
  scopes and project restriction; MCP reuses these schemas.
- **Phase 6:** AI evaluators as service accounts, which must be members (role member)
  of every project they evaluate in; `PATCH` of `include_in_aggregate`
  (`evaluation.include_ai`); research notes as a new `ActivityItem` type.

## 7. Changes after the contract review

For the frontend (MSW handlers and screens) and the backend. Regenerated
`openapi.json` / `schema.d.ts` carry all of them.

- **Paths:** `/ideas/{ref}` and `/ideas/{idea_id}/…` → `/ideas/{idea}/…` (UUID or key).
  `PATCH /ideas/{id}/evaluation` → `PUT /ideas/{idea}/evaluation/due-date`
  (`set_evaluation_due_date`, body `EvaluationDueDate`). `GET /projects/{slug}/rubric`
  removed. New `GET /me/owned-ideas` (`list_my_owned_ideas`).
- **operation_ids:** `search` → `global_search`; `add_vote` / `remove_vote` →
  `vote_idea` / `unvote_idea`; `update_evaluation_window` → `set_evaluation_due_date`.
- **Schemas:** `IdeaRef.project_slug` → `IdeaRef.project` (`ProjectRef`);
  `IdeaSearchHit` removed (`SearchResults.ideas` is `IdeaRef[]`);
  `WorkEvaluation.project` removed (use `idea.project`); `IdeaSummary.updated_at`
  removed; `IdeaSummary.permissions {can_change_status}` added and
  `IdeaPermissions` extends it; `can_manage_evaluators` split into
  `can_invite_evaluators` and `can_remove_evaluators`; `IdeaDetail.score_hidden_reason`
  and `ScoreHiddenReason` removed; `EvaluationList.score_hidden_reason` →
  `score_hidden: bool`; `Evaluation.status` and `updated_at` removed, `edited_at`
  added; `ProjectSummary.permissions` added; `BoardColumn.resolution_counts` added;
  `WorkOwnedGroup.next_cursor` added; `IdeaCreate.summary` required; rubric `weight`
  0.01–10, `multipleOf` 0.01; `TagInfo.idea_count ≥ 1`.
- **Rules:** no due date on moving to Evaluating (first invite sets it); remove
  evaluator works when evaluation is closed, never on yourself (403
  `cannot_remove_self`); list only tags in use; `list_ideas?resolution=`.
- **Database:** deferred `evaluation_scores.criterion_id` FK, `evaluations.is_ai`
  dropped, `evaluations.edited_at` added, `project_effective_roles` view, unique active
  criterion names, keyset and due-date indexes, `pg_trgm` kept on downgrade.
- **Code review fixes (Phase 1 close; no schema or OpenAPI change, the generated
  client is unchanged):**
  - Any request body over 1 MiB: 413 `content_too_large` (problem+json), before
    authentication; a too-large `Content-Length` is refused unread, chunked bodies are
    cut off at the limit.
  - A NUL character (`\u0000`) in any body string, in `q` (list, board, `/search`,
    `/users`) or `tag`: 422 `validation_error`. A cursor carrying one, or a value its
    column can't hold (score outside 1–5, votes outside 0..2³¹−1, a timestamp that
    overflows UTC): 400 `invalid_cursor`.
  - `due_at` (`set_evaluation_due_date`, `add_evaluators`): at most a year ago and five
    years ahead, else 422 `validation_error` at `["body", "due_at"]`.
  - `save_my_evaluation` follows the check order: 403, then its 422s
    (`unknown_criterion`, `evaluation_incomplete`), then 409 (`evaluation_closed`,
    `project_archived`, `evaluation_already_submitted`).
  - Writes to an idea lock its project row (`FOR KEY SHARE`) before the idea row, so
    they serialise with `replace_rubric` instead of deadlocking (500) or leaving a stale
    cached aggregate.
