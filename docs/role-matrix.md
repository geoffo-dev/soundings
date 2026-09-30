# Role matrix

This is the authoritative permission table for Soundings. `backend/app/authz/`
implements it ([ADR 0010](adr/0010-central-authorisation-policy.md)), the identity agent
turns every row into table-driven tests, and code, audit entries and docs refer to
rules by the **stable names** in the first column. If code and this file disagree, the
code is wrong. To change a rule, message the lead, who updates this file first.

## 1. Principals (columns)

| Column | Who | How it is determined |
|---|---|---|
| **PA** | Platform admin | `user.is_platform_admin`. Acts as project admin in *every* project, private ones included. |
| **PAd** | Project admin | Effective project role `admin` |
| **Mem** | Member | Effective project role `member` |
| **Vwr** | Viewer | Effective project role `viewer` |
| **NMi** | Signed-in non-member, project visibility `internal` | Signed in, no project role, project is `internal` |
| **NMp** | Signed-in non-member, project visibility `private` | Signed in, no project role, project is `private` |
| **Pub** | Public (anonymous) | No session and no API key |

**Effective project role** = the highest of the user's direct membership and every
group-derived membership (`admin > member > viewer`), evaluated live on every request.
Removing a group mapping removes access at the next sign-in sync; removing a direct
membership removes it immediately.

**Per-idea overlays** add to a column; they are assignments, not roles:

| Overlay | Meaning |
|---|---|
| **+Own** | The user is the idea's owner. |
| **+Evl** | The user is an assigned evaluator on the idea. |

- Overlays only count while the user holds effective role `member` or `admin` in the
  project. A demoted owner or evaluator keeps the assignment in the data (so admins can
  see and fix it) but it grants nothing. The blind rule (✱) still applies to them.
- Being platform admin does **not** make someone eligible to be assigned as owner or
  evaluator; assignment needs a real project role (condition c4).

**Other principals**

- **API key:** acts as its owner, narrowed by scopes and project restriction (section 5).
- **Tracking token:** the private link given to a public submitter. It grants
  `public.track` for one idea and nothing else, whoever holds it.
- **Service account:** a user of kind `service` used by kagent agents via an API key.
  It needs a real project role like any user and follows every rule here, including
  blind evaluation.

## 2. Reading the tables

| Cell | Meaning |
|---|---|
| `Y` | Allowed |
| `Y (c3, c5)` | Allowed if the listed conditions hold; each failed condition has its own response (section 4) |
| `401` | Not signed in; nothing about the resource is revealed |
| `403` | The principal can view the resource but may not do this (`code: forbidden`) |
| `404` | The principal may not know the resource exists (`code: not_found`) |
| `+` | Overlay column: the owner or evaluator gets this on top of their Member role |
| `·` | Overlay column: no change |
| `✱` | Allowed except for **pending evaluators** on that idea: data is hidden, not an error (section 3) |

Evaluation order, first failure wins: **401** (no identity) → **404** (cannot view the
project or idea, key's project restriction, c8, c9, c12) → **403** (rule or key scope,
then principal conditions) → **422** (request body conditions) → **409** (state
conditions). Every idea-scoped rule implies `idea.view` first, so an idea hidden by
moderation (c12) returns 404, not 403.

### A. Projects and ideas

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `project.view` | View a project: board, list, rubric, status labels, members | Y | Y | Y | Y | Y | 404 | 401 | · | · |
| `project.create` | Create a project and name its first admin | Y | 403 | 403 | 403 | 403 | 403 | 401 | · | · |
| `idea.view` | View an idea: overview, activity, owner, evaluators and their progress | Y | Y | Y (c12) | Y (c12) | Y (c12) | 404 | 401 | · | · |
| `idea.create` | Submit an idea (signed-in form, `N`) | Y | Y | Y | 403 | 403 | 404 | 401 | · | · |
| `idea.edit_own` | Edit title, summary, description and tags of an idea you submitted | Y | Y | Y (c1) | 403 | 403 | 404 | 401 | · | · |
| `idea.edit_any` | Edit any idea's content and tags | Y | Y | 403 | 403 | 403 | 404 | 401 | + (c5) | · |
| `idea.delete` | Delete an idea (spam, duplicates); audited | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |

### B. Collaboration

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `comment.create` | Comment on an idea, including @mentions | Y | Y | Y | 403 | 403 | 404 | 401 | · | · |
| `comment.edit_own` | Edit or delete your own comment | Y (c2) | Y (c2) | Y (c2) | 403 | 403 | 404 | 401 | · | · |
| `comment.delete_any` | Delete anyone's comment (moderation) | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `idea.vote` | Vote for an idea (toggle; one vote per user) | Y | Y | Y | 403 | 403 | 404 | 401 | · | · |
| `idea.watch` | Watch or unwatch an idea (notifications only) | Y | Y | Y | Y | Y | 404 | 401 | · | · |

### C. Ownership and evaluation management

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `idea.volunteer_owner` | "I'll own this" on an unowned idea | Y (c4, c13, c5) | Y (c13, c5) | Y (c3, c13, c5) | 403 | 403 | 404 | 401 | · | · |
| `idea.release_owner` | Step down as owner (the idea becomes unowned) | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · |
| `idea.assign_owner` | Assign, change or clear an idea's owner | Y (c4) | Y (c4) | 403 | 403 | 403 | 404 | 401 | · | · |
| `evaluator.manage` | Invite or remove evaluators | Y (c4, c6) | Y (c4, c6) | 403 | 403 | 403 | 404 | 401 | + (c4, c6) | · |
| `idea.set_due_date` | Set or change the evaluation due date | Y (c6) | Y (c6) | 403 | 403 | 403 | 404 | 401 | + (c6) | · |
| `evaluation.submit_own` | Save a draft of, submit, or edit **your own** evaluation | 403 | 403 | 403 | 403 | 403 | 404 | 401 | · | + (c6) |
| `evaluation.close` | Close or reopen evaluation on an idea | Y (c5) | Y (c5) | 403 | 403 | 403 | 404 | 401 | + (c5) | · |
| `evaluation.include_ai` | Include or exclude an AI evaluation in the aggregate | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · |
| `idea.change_status` | Change status: board drag, close with a resolution, reopen | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · |
| `idea.moderate` | Approve or reject a public submission awaiting moderation | Y | Y | 404 | 404 | 404 | 404 | 401 | · | · |

Notes: `evaluation.submit_own` is `403` in the PA and PAd columns because only the
evaluator overlay grants it; an admin who is also an assigned evaluator gets it through
+Evl. Admins bypass c3 because they could assign themselves anyway; a platform admin
still needs a real project role to become owner (c4). Which status transitions are
valid is a domain rule (backend), not authorisation.

### D. Evaluation visibility (blind evaluation, section 3)

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `evaluation.view_own` | See your own evaluation, including a draft | Y | Y | Y | Y | Y | 404 | 401 | · | · |
| `evaluation.view_others` | See other people's **submitted** evaluations: scores, comments, recommendation, AI rationale and sources | Y ✱ | Y ✱ | Y ✱ | Y ✱ | Y ✱ | 404 | 401 | · | ✱ |
| `score.view_aggregate` | See the aggregate score, `n`, per-criterion bars and disagreement flag; sort and filter by score | Y ✱ | Y ✱ | Y ✱ | Y ✱ | Y ✱ | 404 | 401 | · | ✱ |

`evaluation.view_own` returns an empty result for someone with no evaluation. Nobody,
including platform admins and the owner, can see another person's **draft**.

### E. Proposals

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `proposal.view` | Read the proposal and its margin comments | Y | Y | Y | Y | Y | 404 | 401 | · | · |
| `proposal.write` | Create and edit the proposal; accept or discard suggested text | Y (c7) | Y (c7) | 403 | 403 | 403 | 404 | 401 | + (c7) | · |
| `proposal.comment` | Comment in the proposal's margin threads | Y | Y | Y | 403 | 403 | 404 | 401 | · | · |
| `proposal.suggest_section` | Suggest text for a section; the owner accepts or discards it | Y (c7) | Y (c7) | Y (c7) | 403 | 403 | 404 | 401 | · | · |
| `proposal.export` | Export the proposal as PDF or Markdown (rate-limited) | Y | Y | Y | Y | Y | 404 | 401 | · | · |

Exports include the aggregate score only when the exporting user passes
`score.view_aggregate`.

### F. Project administration

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `project.manage_members` | Add or remove users and groups, change roles | Y (c11) | Y (c11) | 403 | 403 | 403 | 404 | 401 | · | · |
| `project.edit_rubric` | Edit rubric criteria (3–6: name, description, weight, inverted, guidance) | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `project.rename_status_labels` | Rename status labels (the stages themselves are fixed) | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `project.edit_settings` | Name, description, visibility, volunteer owners, evaluation window, public submission (moderation, email verification), project branding, archive | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `public.erase_submitter` | Erase a public submitter's personal data but keep the idea | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |

### G. Public submission

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `public.submit` | Submit via `/{project}/submit` (honeypot, rate limit, ALTCHA) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | · | · |
| `public.track` | Open the private tracking link: own submission and its status only | Y (c9) | Y (c9) | Y (c9) | Y (c9) | Y (c9) | Y (c9) | Y (c9) | · | · |

The public form of a private project shows only the project's name and branding. The
tracking page shows the submitted title, summary and description, the current status
label and status history; never people, comments, evaluations or scores.

### H. Platform administration

These rules are not project-scoped: the PAd…NMp columns mean "signed in, not a
platform admin".

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub |
|---|---|---|---|---|---|---|---|---|
| `platform.manage_users` | Users, pre-created users, external IDs, deactivation, sessions | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.manage_groups` | Groups, IdP group mappings (managed/additive), "test mapping" | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.configure_sso` | OIDC providers, login matching, break-glass status | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.configure_email` | Effective SMTP config, send test email, failed sends and retry | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.edit_branding` | Global branding and email footer | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.manage_agents` | Register kagent agents and their service accounts | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.view_audit_log` | Read the audit log | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `api_key.manage_any` | List and revoke any user's API keys, including service accounts' | Y | 403 | 403 | 403 | 403 | 403 | 401 |

### I. Self-service, API keys and MCP

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub |
|---|---|---|---|---|---|---|---|---|
| `self.manage_profile` | Own profile and notification preferences (immediate / digest / off) | Y | Y | Y | Y | Y | Y | 401 |
| `self.unsubscribe` | One-click unsubscribe from an email link, no sign-in needed | Y (c14) | Y (c14) | Y (c14) | Y (c14) | Y (c14) | Y (c14) | Y (c14) |
| `user.search` | Find users by name or email (member, owner and evaluator pickers, @mentions) | Y | Y | Y | Y | Y | Y | 401 |
| `api_key.manage_own` | Create, list and revoke your own API keys | Y | Y | Y | Y | Y | Y | 401 |
| `mcp.connect` | Call `/mcp`; each tool then checks its own rule (section 6) | Y (c15) | Y (c15) | Y (c15) | Y (c15) | Y (c15) | Y (c15) | 401 |

### J. AI assistance (kagent)

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `ai.request_evaluation` | "Ask AI to evaluate" (adds the agent as an AI evaluator) | Y (c6, c10) | Y (c6, c10) | 403 | 403 | 403 | 404 | 401 | + (c6, c10) | · |
| `ai.research` | "Research this": a cited note in the activity feed | Y (c5, c10) | Y (c5, c10) | 403 | 403 | 403 | 404 | 401 | + (c5, c10) | · |
| `ai.draft_section` | "Draft section" in the proposal editor | Y (c7, c10) | Y (c7, c10) | 403 | 403 | 403 | 404 | 401 | + (c7, c10) | · |
| `ai.cancel_run` | Cancel a running AI job on the idea | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · |

Watching a run's live progress needs only `idea.view`; progress events never carry
scores.

## 3. Blind evaluation: exact visibility rules

Definitions, for one idea *I* and one principal *P* (see also
[ADR 0006](adr/0006-blind-evaluation-and-aggregate-scoring.md)):

- *P* is a **pending evaluator** on *I* when *P* has an evaluator assignment on *I*
  and no evaluation of *I* by *P* has status `submitted` (no evaluation, or a draft).
- **Score data** of *I* means: other evaluators' per-criterion scores and comments,
  their overall recommendation, AI rationale and sources, the aggregate score, `n`,
  per-criterion means and bars, the disagreement flag, recommendation tallies, and
  anything computed from them (rank, sort position, filter membership).

Rules:

1. **A pending evaluator sees no score data for *I*, anywhere.** This holds for every
   role, including project admin, platform admin and the idea's owner. Surfaces
   covered: My work, project list and board (score badge, disagreement chip), idea
   page (sidebar aggregate, per-criterion bars, Evaluations tab), evaluate sheet,
   command palette and search results, sorting by score, the "high disagreement" and
   any score filters, every REST endpoint (including list, search, export and live
   update payloads), every MCP tool (`get_idea`, `search_ideas`, `get_proposal`),
   proposal exports, in-app notifications, and emails.
2. What a pending evaluator **does** see on *I*: the evaluator list, each evaluator's
   binary progress (submitted or not; never "draft"), the due date, the rubric, their
   own draft, and activity events such as "Bob submitted an evaluation" (without
   content).
3. **Sorting and filtering:** for a pending evaluator, *I* sorts exactly as if it had no
   score (after every scored idea) and never matches a score-derived filter. The API
   returns score fields as `null` with `scores_hidden: true`; the UI shows "Hidden
   until you submit". The final field name is the contract's, not this doc's.
4. **After *P* submits**, *P* sees every submitted evaluation of *I* (human and AI) and
   the aggregate, immediately. *P* may keep editing their evaluation until evaluation
   is closed; it never becomes hidden again.
5. **Everyone else who passes `idea.view`** (admins, members, viewers, internal
   non-members, the owner when not a pending evaluator) sees all submitted evaluations
   and the aggregate.
6. **Drafts are private to their author.** No role can read another person's draft,
   through any surface.
7. **Closing evaluation doesn't lift the rule.** An evaluator who never submitted stays
   pending (and blind) after close. Removing their assignment ends it; the owner does
   this knowingly (it is audited).
8. **Emails never contain score data**, for any recipient. They link to the app, which
   applies the rules above.
9. **Service accounts** (AI evaluators) are pending until they submit, so the agent
   evaluates blind too.
10. **The aggregate's included set** is submitted evaluations with
    `include_in_aggregate = true`; AI evaluations are excluded by default
    (`evaluation.include_ai` changes that). Visibility (rules 1–5) is about all
    submitted evaluations, included or not.

Minimum tests for blind evaluation: for each surface in rule 1, a pending evaluator
(draft and no-draft), the same user after submitting, a project admin who is a pending
evaluator, a viewer, and an internal non-member, with at least two other submitted
evaluations and one AI evaluation present.

## 4. Conditions

| Id | Condition | Response when it fails |
|---|---|---|
| c1 | The principal submitted the idea, and its status is `new` | not submitter → 403 `not_submitter`; status ≠ new → 409 `idea_not_new` |
| c2 | The principal wrote the comment | 403 `not_author` |
| c3 | The project allows volunteer owners (`allow_volunteer_owners`, default true) | 403 `volunteering_disabled` |
| c4 | The user being assigned (owner or evaluator) has effective role `member` or `admin` in the project | 422 `assignee_not_eligible` |
| c5 | The idea's status is not `closed` | 409 `idea_closed` |
| c6 | Evaluation is open: idea not `closed` and evaluation not closed | 409 `evaluation_closed` |
| c7 | The idea's status is `shortlisted` or `proposal` | 409 `proposal_not_available` |
| c8 | The project has public submission enabled | 404 |
| c9 | The request carries a valid tracking token for this idea | 404 |
| c10 | AI is enabled (Helm feature toggle) and a suitable agent is registered | 409 `ai_unavailable` |
| c11 | After the change, the project still has at least one admin | 409 `last_admin` |
| c12 | The idea is not awaiting moderation (always true for PA and PAd) | 404 |
| c13 | The idea has no owner | 409 `idea_has_owner` |
| c14 | The request carries a valid unsubscribe token | 404 |
| c15 | The request authenticates with an API key that has the `mcp` scope | no key → 401; no scope → 403 `insufficient_scope` |

## 5. API keys

A request authenticated by API key is evaluated as the key's owner, **live** (a
demoted owner's key loses access immediately), then narrowed:

| Scope | Grants the rules |
|---|---|
| `read` | `project.view`, `idea.view`, `user.search`, `evaluation.view_own`, `evaluation.view_others`, `score.view_aggregate`, `proposal.view`, `proposal.export` |
| `write` | `idea.create`, `idea.edit_own`, `idea.edit_any`, `idea.delete`, `comment.*`, `idea.vote`, `idea.watch`, `idea.volunteer_owner`, `idea.release_owner`, `idea.assign_owner`, `evaluator.manage`, `idea.set_due_date`, `evaluation.close`, `evaluation.include_ai`, `idea.change_status`, `idea.moderate`, `proposal.write`, `proposal.comment`, `proposal.suggest_section`, `ai.*` |
| `evaluate` | `evaluation.submit_own` |
| `mcp` | `mcp.connect` only; tools also need the scope of their own rule |

- A rule the key's scopes don't grant → 403 `insufficient_scope`.
- A key restricted to projects *S*: any resource outside *S* → 404, and lists only
  contain projects in *S*.
- **Session only** (never through an API key, whatever its scopes):
  `project.create`, `project.manage_members`, `project.edit_rubric`,
  `project.rename_status_labels`, `project.edit_settings`, `public.erase_submitter`,
  `platform.*`, `api_key.*`, `self.manage_profile`.
- Expired or revoked keys → 401. Requests with a key are exempt from CSRF checks.

## 6. MCP tools

Every tool call is authorised with the rule below (after `mcp.connect`) and audited
with the rule name, decision, user and key id.

| Tool | Rule | Scope |
|---|---|---|
| `list_projects` | `project.view` (as a filter) | `read` |
| `search_ideas` | `idea.view` (as a filter); score fields per `score.view_aggregate` | `read` |
| `get_idea` | `idea.view`; evaluations and aggregate per `evaluation.view_others` / `score.view_aggregate` | `read` |
| `get_rubric` | `project.view` | `read` |
| `get_proposal` | `proposal.view` | `read` |
| `create_idea` | `idea.create` | `write` |
| `add_comment` | `comment.create` | `write` |
| `propose_proposal_section` | `proposal.suggest_section` | `write` |
| `submit_evaluation` | `evaluation.submit_own` | `evaluate` |

## 7. Writing the tests

- One parametrised test per rule. Each case: principal column (plus overlays and auth
  kind), the resource state that matters (project visibility, idea status, evaluation
  open or closed, owner present, evaluator state `none | invited | draft | submitted`,
  `allow_volunteer_owners`, `public_submission_enabled`, moderation), and the expected
  result (`allow`, `401`, `403`, `404`, or the condition's 409/422 code).
- Cover the role source: direct membership, group membership, both (highest wins), and
  an overlay on a demoted user.
- Cover API keys: each scope alone, a project-restricted key, an expired key, a
  revoked key, and a key whose owner was demoted after it was created.
- A meta-test fails if any route or MCP tool has no rule, or if a rule name used in
  code is missing from this file.
