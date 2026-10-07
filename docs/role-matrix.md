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
group-derived membership (`admin > member > viewer`), evaluated live on every request
from the `project_effective_roles` view. A user is in a group **manually** (added by a
platform admin) and/or **synced** (added by sign-in sync from the IdP's groups claim);
both count the same. Sync runs at each SSO sign-in: a *managed* mapping adds and
removes synced memberships, an *additive* one only adds, and manual memberships are
never touched ([contract-phase2 §3.6](api/contract-phase2.md#36-group-sync-at-sign-in)).
So removing someone from an IdP group removes the access at their next sign-in;
removing a direct membership, a group membership or a group grant in Soundings removes
it immediately.

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

- **API key:** acts as its owner, **live** (their roles, platform-admin flag and active
  state at each request), narrowed by its scopes and optional project restriction
  (section 5). Keys are created, listed and revoked in a session only; the break-glass
  account has none (c20); deactivating the owner revokes them; a key works only while
  the sign-in method that created it is available and, for a person, while they have
  used the app in the last 30 days
  ([contract-phase5 §3.1](api/contract-phase5.md#31-keys-format-storage-and-lifecycle)).
- **Tracking token:** the private link given to a public submitter
  (`<base>/track#<token>`). It grants `public.track` for one idea (see its public status
  and what was submitted, turn status emails on or off, resend the confirmation email,
  erase the submitter's details) and nothing else, whoever holds it; it stops working
  when the submitter's details are erased.
- **Confirmation-link token:** emailed to a public submitter (`<base>/<slug>/verify#<token>`;
  older links `<base>/verify#<token>`);
  grants `public.track` only to confirm that submission's address (and release an idea
  held for it), nothing else. Signed, valid 3 days
  ([contract-phase4 §3.7](api/contract-phase4.md#37-tracking-and-confirmation-links)).
- **Service account:** a user of kind `service` used by kagent agents via an API key.
  It needs a real project role like any user (member or viewer; **never admin**: 409
  `system_account`) and follows every rule here, including blind evaluation. **Without
  a role it is treated as NMp (a private non-member) in every project, internal ones
  included** (404 everywhere; lists leave those projects out; a key can't be restricted
  to them): it never gets the NMi column. Its people search (`user.search`) finds only
  people who share a project with it, inside its key's projects. It **never
  owns an idea** (c4 refuses it as owner, c21 as a volunteer), so it can't accept its own
  suggestions or include its own evaluation. It never signs in: platform admins create
  its keys (Phase 6, `platform.manage_agents`;
  [contract-phase5 §3.7](api/contract-phase5.md#37-service-accounts-minimum-now-phase-6-builds-the-ui)),
  restricted to the projects it serves, and its evaluations are left out of the
  aggregate by default (section 3 rule 10). **Phase 6:** each registered kagent agent
  has exactly one service account and one key, managed by the server (scopes from the
  agent's purposes, restriction = its projects;
  [contract-phase6 §3.1](api/contract-phase6.md#31-agents-their-service-accounts-and-keys));
  disabling the agent revokes its key. **Its key works only inside the agent's runs
  (c22, run scope):** on `/mcp` only (REST: 403 `insufficient_scope`); every call names
  its run (`run_id`) and reaches only that run's idea while it is `running` and nobody
  asked to cancel it, writing only through that run kind's tool. It **never sees others'
  score data**, and its own only inside its evaluate run (section 3 rule 9). Since it is never an owner or
  admin it can't start AI runs (table J).
- **Break-glass admin:** the one local account whose credentials come from a K8s
  Secret, a platform admin (column PA). Usable only while SSO is not configured; every
  action in its sessions is audited with `auth_method: break_glass`. It never holds
  project roles, group memberships or external IDs, is never matched by SSO sign-in,
  and doesn't count as the remaining platform admin for c18.
- **Deactivated users** keep their rows but hold no access: they can't sign in, and
  they don't count for c11, member counts or access lists.
- **How someone signed in** (SSO, break-glass, dev login) changes nothing in these
  tables: a session is a session. Sign-in itself is not a rule (section 2a).

## 1a. Principal traits (Phase 7)

Decisions that follow from *who* the principal is, not from a rule's cells. They are
named functions in `app/authz/policy.py`, so no service, route, job or MCP tool branches
on account kinds or roles itself (ADR 0010; security review P7 N4).
`tests/authz/test_principal_traits.py` pins them.

| Function | Trait | Who | Used by |
|---|---|---|---|
| `is_agent` | principal.agent | an AI agent's service account | c21, c22, rule 9; the docs gate (an agent's key is MCP only) |
| `sees_email_trouble` | principal.sees_email_trouble | whoever `platform.configure_email` allows (platform admins) | the bell's `email_trouble` banner |
| `may_cite_sources` | evaluation.cite_sources | agents only | `save_my_evaluation` / `submit_evaluation`: a person's sources are 422 |
| `counted_by_default` | evaluation.counted_by_default | people (not agents) | a first submission's `include_in_aggregate` (section 3 rule 10) |
| `writes_as_ai` | proposal.suggest_as_ai | agents | suggestion `source` = `ai`; the MCP dispatcher strips invisible and direction characters from an agent's text |
| `searches_co_members_only` | user.search (co-members only) | agents | `search_users` finds only people who share a project |

Traits are not rules: they have no cells and no API-key scope (the trait names are
written without backticks so the rule tables' parser, `tests/authz/test_policy_matrix.py`,
never reads them as rules).

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
conditions). Every idea-scoped rule implies `idea.view` first, so an idea held for
moderation or email confirmation (c12) returns 404, not 403. Platform rules (table H) are not about a
resource the caller may not know, so a non-admin gets 403 before any 404.

## 2a. Signing in (not rules)

Signing in decides *who* the principal is, before any rule runs, so these are
conditions on public endpoints rather than rows of the matrix
([contract-phase2 §3](api/contract-phase2.md#3-business-rules)):

| Method | Available when | Who can use it |
|---|---|---|
| SSO (OIDC) | `SOUNDINGS_OIDC_ISSUER` is set | A user matched by (issuer, subject), then external ID, then verified email, then auto-create (verified email) if enabled; otherwise denied. Never a deactivated, service or break-glass account. The external-ID claim must be admin-controlled at the IdP. |
| Break-glass | enabled, both credentials set **and SSO not configured** | Whoever has the Secret's username and password; throttled per IP; every use audited; sessions last at most 8 hours (1 hour idle). |
| Dev login | `SOUNDINGS_DEV_LOGIN_ENABLED` (refused in production) | Any active person (development and demos only). |

Every session works only while the method that started it is available (an SSO
session needs SSO configured, and so on); otherwise the request is unauthenticated
(401). Deactivating a user ends their sessions.

## 2b. Notifications and email (not rules)

Notifications are about one idea each, so they follow the idea's rules rather than
having rows of their own ([contract-phase3 §3](api/contract-phase3.md#3-business-rules)):

- **Who is notified:** a recipient must pass `idea.view` (and the notification type's
  condition) when the notification is created, and again when its email is sent;
  otherwise nothing is sent. The actor, deactivated users, service accounts and the
  break-glass account are never notified.
- **Type conditions are rules, not role checks:** evaluation invitations and reminders
  need `evaluation.submit_own` on the idea (an assigned evaluator holding member or
  admin, c6) plus "hasn't submitted"; owner notifications need the recipient to be the
  idea's owner; @mentions notify only people with a role in the idea's project (whom
  the mention picker offers), not every viewer of an internal project.
- **The inbox** (signed in, like My work) lists only notifications about ideas the
  user can view now; marking read needs nothing more. Polling the unread count doesn't
  keep a session alive (section 2a's idle timeouts still apply).
- **Email preferences** are `self.manage_profile` (sessions only); unsubscribe links
  are `self.unsubscribe` (c14), usable without signing in.
- **Admin settings → Email** is `platform.configure_email`.
- Section 3 rule 8 applies to every notification, email and digest.

## 2c. Branding, public pages and held ideas (not rules)

- **Branding is public data:** `GET /branding` (the global effective branding) and the
  uploaded logos and favicons (`GET /branding/assets/{id}`) need no sign-in: the sign-in
  page and the public form show them. Editing is `platform.edit_branding` (global) and
  `project.edit_settings` (a project's override and its images), session only.
- **Public pages** (`/{slug}/submit`, `/track`, `/{slug}/verify`, `/verify`) are governed by
  `public.submit` (c8) and `public.track` (c9) and show nothing but the project's name,
  intro and branding, and the submitter's own idea and status
  ([contract-phase4 §3.5–3.7](api/contract-phase4.md#35-the-public-form)).
- **Held ideas are listed nowhere:** an idea held for email confirmation or moderation
  is in no list, board, search, count, tag list, My work, inbox or notification, for any
  role. That is a property of lists, not a rule: `idea.view` (c12) still lets project and
  platform admins open an idea held for moderation by its link and in the moderation
  queue (`idea.moderate`).

### A. Projects and ideas

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `project.view` | View a project: board, list, rubric, status labels, members, group grants, everyone with access and why | Y | Y | Y | Y | Y | 404 | 401 | · | · |
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
| `comment.edit_own` | Edit or delete your own comment (idea comments; delete only for proposal margin comments) | Y (c2) | Y (c2) | Y (c2) | 403 | 403 | 404 | 401 | · | · |
| `comment.delete_any` | Delete anyone's comment, on the idea or in its proposal's margin (moderation) | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
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
| `idea.moderate` | See the moderation queue; approve or reject (delete) a public submission held for moderation | Y | Y | 404 | 404 | 404 | 404 | 401 | · | · |

Notes: `idea.moderate` at project level (the moderation queue) is 403 for members,
viewers and internal non-members, who can see the project; approving or rejecting
needs the idea held for moderation (409 `not_awaiting_moderation`, a domain rule).
`evaluation.submit_own` is `403` in the PA and PAd columns because only the
evaluator overlay grants it; an admin who is also an assigned evaluator gets it through
+Evl. Admins bypass c3 because they could assign themselves anyway; a platform admin
still needs a real project role to become owner (c4). c21 (a service account can't
volunteer) is not written in the cells: like c20 it is a property of the principal.
Which status transitions are valid is a domain rule (backend), not authorisation.

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

Notes ([contract-phase4 §3.1–3.4](api/contract-phase4.md#31-proposal-lifecycle-and-permissions)):

- One proposal per idea over the fixed template. `proposal.write` covers starting it
  (which moves a Shortlisted idea to Proposal: the owner and admins also hold
  `idea.change_status`) and saving sections; c7 makes it read-only outside Shortlisted
  and Proposal, where it stays viewable, commentable and exportable.
- `proposal.comment` covers opening margin threads, replying, resolving and reopening
  them. Deleting a margin comment is `comment.edit_own` (your own, c2) or
  `comment.delete_any` (admins). No edits, notifications or @mentions in Phase 4.
- Exports include the aggregate score only when the exporting user passes
  `score.view_aggregate` (so never for a pending evaluator, section 3); they never
  include margin comments. Export is rate-limited (10 per user per minute).
- Proposals hold no score data; every proposal surface is safe for pending evaluators.
- In an archived project every proposal write is 409 `project_archived`; on an idea held
  for moderation there is no proposal (c7 needs Shortlisted).
- Phase 5 suggestions ([contract-phase5 §3.4](api/contract-phase5.md#34-proposal-suggestions)):
  `proposal.suggest_section` creates one (REST, or MCP `propose_proposal_section`; the
  whole text of one section), `proposal.view` lists the pending ones, `proposal.write`
  accepts (a normal versioned section save) or discards. Suggestions hold no score data.

### F. Project administration

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `project.manage_members` | Add or remove users and groups (group grants), change their roles | Y (c11) | Y (c11) | 403 | 403 | 403 | 404 | 401 | · | · |
| `project.edit_rubric` | Edit rubric criteria (3–6: name, description, weight, inverted, guidance) | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `project.rename_status_labels` | Rename status labels (the stages themselves are fixed) | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `project.edit_settings` | Name, description, visibility, volunteer owners, evaluation window, public form (on/off, moderation, email verification, intro), project branding override and its images, archive | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |
| `public.erase_submitter` | See a public submitter's contact details (email, confirmed, wants updates); erase their name, address and tracking link but keep the idea | Y | Y | 403 | 403 | 403 | 404 | 401 | · | · |

### G. Public submission

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `public.submit` | Submit via `/{project}/submit` (honeypot, rate limit, ALTCHA) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | Y (c8) | · | · |
| `public.track` | Open the private tracking link: own submission and its status only | Y (c9) | Y (c9) | Y (c9) | Y (c9) | Y (c9) | Y (c9) | Y (c9) | · | · |

The public form of a private project shows only the project's name, intro and
branding. The tracking page shows the title and summary **as submitted** (a copy kept
with the submission), the current status label and the status history (dates and
labels); never people, comments, evaluations, scores, tags, the idea key, anything the
team wrote or edited, or other submissions.

Notes ([contract-phase4 §3.5–3.9](api/contract-phase4.md#35-the-public-form)):

- `public.submit` covers the form's project info, its ALTCHA challenge (bound to that
  form) and sending an idea (JSON only, per-IP limit, ALTCHA with replay protection,
  per-project limit, then the honeypot). Signed-in users may use it too; the idea is
  still anonymous (`submitted_by` null).
- `public.track` covers the tracking page, turning status emails on or off, resending
  the confirmation email, the submitter erasing their own details, and confirming the
  address with the emailed link (on a Confirm click). It depends on the token and the
  instance switch only, so turning a project's form off doesn't break links already
  sent.
- A public idea may be **held**: for email confirmation (when the project requires it;
  nobody can see it, and it is deleted after 3 days unless confirmed) or for moderation
  (only PA and PAd can see it, c12). While held for moderation, idea writes other than
  delete, approve, reject and erase are refused (c19), watching included, and every
  permission flag the API returns for it is false except `can_delete`.
- The submitter's name is visible to everyone who can view the idea; their email,
  confirmation and update preference only with `public.erase_submitter`. Status emails go
  only to an opted-in, confirmed address.

### H. Platform administration

These rules are not project-scoped: the PAd…NMp columns mean "signed in, not a
platform admin".

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub |
|---|---|---|---|---|---|---|---|---|
| `platform.manage_users` | Users: list, pre-create, edit, deactivate (c17, c18), external IDs, unlink an SSO identity, sign out everywhere | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.manage_groups` | Groups, IdP group mappings (managed/additive), manual members, "test mapping" | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.configure_sso` | View the effective SSO configuration (read-only: set by Helm values), the redirect URIs to register, break-glass status | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.configure_email` | View the effective SMTP configuration (read-only: set by Helm values, credentials masked), send a test email (rate-limited, one address), list the email outbox, retry failed sends; see the "email failing" banner | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.edit_branding` | Global branding: app name, logo, favicon, primary and accent colours, font, email footer; upload its images | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.manage_agents` | Register kagent agents and their service accounts | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `platform.view_audit_log` | Read the audit log (filters, newest first) | Y | 403 | 403 | 403 | 403 | 403 | 401 |
| `api_key.manage_any` | List and revoke any user's API keys, including service accounts' (session only) | Y | 403 | 403 | 403 | 403 | 403 | 401 |

Notes: c17 applies to `platform.manage_users`: a platform admin can't deactivate
themselves or remove their own platform-admin flag (403 `cannot_change_self`), and c18
keeps at least one other active platform admin (409 `last_platform_admin`). Service
and break-glass accounts can't get an email change, the platform-admin flag or external
IDs (409 `system_account`; contract-phase2 §3.4).

### I. Self-service, API keys and MCP

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub |
|---|---|---|---|---|---|---|---|---|
| `self.manage_profile` | Own profile and email notification preferences (immediate / daily digest / off, per notification type) | Y | Y | Y | Y | Y | Y | 401 |
| `self.unsubscribe` | One-click unsubscribe from an email link (turns email off for that type, the digest's types, or, with the footer's "all email" link, every type), no sign-in needed | Y (c14) | Y (c14) | Y (c14) | Y (c14) | Y (c14) | Y (c14) | Y (c14) |
| `user.search` | Find users by name or email, and groups by name (member, group-grant, owner and evaluator pickers, @mentions) | Y | Y | Y | Y | Y | Y | 401 |
| `api_key.manage_own` | Create, list and revoke your own API keys (session only) | Y | Y | Y | Y | Y | Y | 401 |
| `mcp.connect` | Call `/mcp`; each tool then checks its own rule (section 6) | Y (c15) | Y (c15) | Y (c15) | Y (c15) | Y (c15) | Y (c15) | 401 |

Notes: c20 is not written in the cells: like c19 it is a property of the principal, not
of a column. It applies to `api_key.manage_own` when **creating** a key: the break-glass
account (a PA) gets 403 `break_glass_account`; listing shows it no keys and revoking
finds none (404). `api_key.*` are session-only rules (section 5).

### J. AI assistance (kagent)

| Rule | Action | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl |
|---|---|---|---|---|---|---|---|---|---|---|
| `ai.request_evaluation` | "Ask AI to evaluate" (adds the agent as an AI evaluator) | Y (c6, c10) | Y (c6, c10) | 403 | 403 | 403 | 404 | 401 | + (c6, c10) | · |
| `ai.research` | "Research this": a cited note in the activity feed | Y (c5, c10) | Y (c5, c10) | 403 | 403 | 403 | 404 | 401 | + (c5, c10) | · |
| `ai.draft_section` | "Draft section" in the proposal editor | Y (c7, c10) | Y (c7, c10) | 403 | 403 | 403 | 404 | 401 | + (c7, c10) | · |
| `ai.cancel_run` | Cancel a running AI job on the idea | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · |
| `ai.delete_note` | Delete an AI research note (clears its text and sources) | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · |

Notes ([contract-phase6 §3.5](api/contract-phase6.md#35-authorisation-role-matrix-section-j)):

- **Watching** a run (the idea's run list, a run with its events, the SSE stream) needs
  only `idea.view`. Runs, events and permission flags never carry score data, so pending
  evaluators may watch; an open stream re-checks the principal and `idea.view` every 30
  seconds. Reading a research note is `idea.view`; deleting one is `ai.delete_note`
  (the idea's owner and project/platform admins; lead decision on review item C4).
- **c10 names one agent:** it must be enabled, have the run's kind among its purposes,
  serve the idea's project with a service account that is active and has effective role
  **member** there, and hold an active key; and AI must be on for the instance. The
  idea page's agent list and flags are exactly the agents and actions that pass.
- **Idempotent:** a request while the same run (idea, agent, kind, section) is queued or
  running returns that run.
- The request rules are idea writes (409 `project_archived`; c19 `awaiting_moderation`);
  `ai.cancel_run` isn't (it only stops work). `ai.request_evaluation` also assigns the
  agent's service account as an evaluator (no separate `evaluator.manage` check: the
  rule's holders have it anyway).
- `evaluation.include_ai` (table C) acts on a submitted AI evaluation the principal may
  see under section 3 (a pending evaluator, admin or owner, gets 404); on a person's
  evaluation 409 `not_ai_evaluation`.
- **Agents' own work** goes through ordinary rules with their key, narrowed by c22 (run
  scope): `evaluation.submit_own` during an open evaluate run (they are assigned
  evaluators), `proposal.suggest_section` during an open draft run for that section, and
  `comment.create` during an open research run for MCP `add_research_note`; reads only
  on the named open run's idea; `create_idea`, `add_comment` and REST never. Section 3 applies
  to them, with rule 9: they never see others' score data.
- `platform.manage_agents` (table H) is session only; registering an agent and rotating
  its key also need c20 (403 `break_glass_account`).

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
8. **Emails and in-app notifications never contain score data**, for any recipient:
   no scores, aggregate, `n`, per-criterion data, disagreement flag, recommendations or
   evaluation comments ("all evaluations are in" carries a count only). They link to the
   app, which applies the rules above (contract-phase3 §3.11).
9. **Service accounts** (AI agents) **never see other evaluators' score data, before
   or after they submit**: on every idea they are treated as pending evaluators
   (`score_hidden: true`; no aggregate, `n`, others' evaluations or their comments;
   unscored for sorting and filters), through every surface (`get_idea`,
   `search_ideas`, the shared queries; REST is refused to them anyway, c22). They see
   their own evaluation **only inside their evaluate run** on that idea (`get_idea`'s
   `my_evaluation` is null in research and draft runs). So the agent evaluates blind, and
   nothing it writes (a research note, a suggestion, a rationale) can carry anyone's
   scores to a pending evaluator.
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
| c4 | The user being assigned (owner or evaluator) has effective role `member` or `admin` in the project; an **owner** is also a person, not a service account (an AI agent can be an evaluator, never an owner) | 422 `assignee_not_eligible` |
| c5 | The idea's status is not `closed` | 409 `idea_closed` |
| c6 | Evaluation is open: idea not `closed` and evaluation not closed | 409 `evaluation_closed` |
| c7 | The idea's status is `shortlisted` or `proposal` | 409 `proposal_not_available` |
| c8 | Public submission is on for the instance (`SOUNDINGS_PUBLIC_SUBMISSION_ENABLED`) and for the project, the project isn't archived and its slug isn't reserved (`RESERVED_SLUGS`, older projects only) | 404 (the same for an unknown project) |
| c9 | The request carries a valid token for this submission, and public submission is on for the instance: a tracking token whose hash matches a submission that isn't erased, or (confirming only) a confirmation-link token with a valid signature and expiry for a submission that isn't erased and still has that address | 404 (unknown, erased, expired and invalid alike) |
| c10 | AI is enabled (Helm feature toggle, `SOUNDINGS_AI_ENABLED`) and the agent named in the request is suitable: enabled, the run's kind among its purposes, serving the idea's project, its service account active with effective role `member` there, and an active key (contract-phase6 §3.5) | 409 `ai_unavailable` |
| c11 | After the change, the project still has at least one admin (effective role, direct or via a group) who is active and not a service account | 409 `last_admin` |
| c12 | The idea is not held (`ideas.held_for` null). Held for moderation: always true for PA and PAd. Held for email confirmation: false for everyone, PA and PAd included (the idea doesn't exist yet) | 404 |
| c13 | The idea has no owner | 409 `idea_has_owner` |
| c14 | The request carries a valid unsubscribe token (signed with a key derived from the instance secret key) whose user exists and is active, and the token's scope covers the request: `all=true` needs a token scoped to `all` (contract-phase3 §3.5) | invalid token or user → 404; `all=true` with a type or digest token → 403 `insufficient_scope` |
| c15 | The request authenticates with an API key that has the `mcp` scope | no key → 401; no scope → 403 `insufficient_scope` |
| c16 | Removing an evaluator: the evaluator is not the principal (contract-phase1 §3.5) | 403 `cannot_remove_self` |
| c17 | Changing a user's `is_active` or `is_platform_admin`: the user is not the principal (contract-phase2 §3.4) | 403 `cannot_change_self` |
| c18 | Demoting or deactivating a platform admin: another active platform admin (not the break-glass account) remains, counted under a lock (contract-phase2 §3.4) | 409 `last_platform_admin` |
| c19 | The idea is not held for moderation. Not written in the cells: like `project_archived`, it applies to every idea write (`idea_write` rows) except `idea.delete` and `idea.moderate`, and to `idea.watch`, after the 404/403 checks (contract-phase4 §3.6) | 409 `awaiting_moderation` |
| c20 | The principal is not the break-glass account (a key would outlive the emergency and keep working after SSO is configured; contract-phase5 §3.1). Covers agents' keys too (Phase 6) | 403 `break_glass_account` |
| c21 | The principal is a person, not a service account. Not written in the cells (a property of the principal, like c20); applies to `idea.volunteer_owner` (contract-phase5 §3.7) | 403 `forbidden` |
| c22 | **Run scope** (a property of the principal, like c20/c21; not written in the cells). For a service-account principal: REST is refused; every MCP call **names its run** (`run_id`, required for agents) and must be an **open run** of its agent (`running`, no cancel request), checked **before any idea is looked up**; every tool must target that run's idea (`get_rubric` also by its project; `list_projects` / `search_ideas` list only that run's project / idea); the only write is the named run's kind's tool (evaluate → `submit_evaluation`, research → `add_research_note`, draft_section → `propose_proposal_section` for the run's section); `create_idea` and `add_comment` never. For people: `run_id` is ignored and `add_research_note` is refused (contract-phase6 §3.5) | REST → 403 `insufficient_scope`; no `run_id`, a run that isn't open, another idea (existing or not), another kind or section → `ai_run_not_active`; `create_idea`, `add_comment` by an agent, `add_research_note` by a person → `forbidden` |

## 5. API keys

A request authenticated by API key is evaluated as the key's owner, **live** (a
demoted owner's key loses access immediately), then narrowed
([contract-phase5 §3.3](api/contract-phase5.md#33-what-a-key-may-do-role-matrix-5-exactly)):
**effective permission = the owner's live permission ∩ the key's scopes ∩ the key's
projects.**

| Scope | Grants the rules |
|---|---|
| `read` | `project.view`, `idea.view`, `user.search`, `evaluation.view_own`, `evaluation.view_others`, `score.view_aggregate`, `proposal.view`, `proposal.export` |
| `write` | `idea.create`, `idea.edit_own`, `idea.edit_any`, `comment.*`, `idea.vote`, `idea.watch`, `idea.volunteer_owner`, `idea.release_owner`, `idea.assign_owner`, `evaluator.manage`, `idea.set_due_date`, `evaluation.close`, `evaluation.include_ai`, `idea.change_status`, `proposal.write`, `proposal.comment`, `proposal.suggest_section`, `ai.*` (not `idea.delete` or `idea.moderate`: session only); a `write` key always has `read` too |
| `evaluate` | `evaluation.submit_own`; an `evaluate` key always has `read` too |
| `mcp` | `mcp.connect` only; tools also need the scope of their own rule |

- A rule the key's scopes don't grant → 403 `insufficient_scope` (after the 404s, so a
  scope error never reveals a hidden resource). `write` and `evaluate` include `read`
  (their responses return readable data; the API adds it when the key is created);
  otherwise scopes don't imply each other.
- The implied view rule (`project.view` / `idea.view` before an idea or project rule)
  is the owner's, not a scope check. Blind evaluation (✱) depends on the owner, never on
  scopes.
- A key restricted to projects *S*: any resource outside *S* → 404, and lists, boards,
  counts, search and My work only contain projects in *S* (`app.authz.queries`
  `visible_projects` / `listed_ideas`). Rules that aren't about a project
  (`user.search` without a project: the people directory every signed-in person sees)
  are unaffected for people; a **service account's** search finds only people with a
  role in a project where it has one, inside its key's projects. A platform admin's key
  is narrowed the same way.
- **Service accounts' keys** (Phase 6, c22): every REST operation → 403
  `insufficient_scope` after the key check, whatever its scopes; on `/mcp` they work
  only within the run scope.
- **Session only** (never through an API key, whatever its scopes; 403
  `insufficient_scope`): `project.create`, `project.manage_members`,
  `project.edit_rubric`, `project.rename_status_labels`, `project.edit_settings`,
  `public.erase_submitter`, `idea.delete` and `idea.moderate` (irreversible: a hard
  delete, a rejection that deletes), `platform.*`, `api_key.*`, `self.manage_profile`,
  and the inbox routes (list, unread count, mark read: a person's reading state).
- **Signed-in routes without a rule of their own** (`get_me`, My work, owned ideas,
  global search) need `read` with a key, and so does every route that loads an idea or
  project to read it (`require_view`, after the 404s): an `mcp`-only key reads nothing
  through REST.
- **Every operation is classified for keys** in `app.authz.keys.ROUTE_KEY_ACCESS`:
  `policy` (its rule decides, as above), `read` (needs `read`), `session` (403
  `insufficient_scope` for any key: the rules above plus the moderation queue,
  `get_idea_submission` and the public-form and branding settings) or `public`; an
  operation without a row is refused to keys. A key on a `session` route, or on a `read`
  route without `read`, gets 403 before the route's own 404 or 422 (the answer doesn't
  depend on the resource).
- Missing, malformed, unknown, expired or revoked keys, keys whose owner is
  deactivated or the break-glass account, keys whose creating sign-in method is no
  longer available, and a person's keys while they haven't used the app for 30 days
  (`dormant`; signing in reactivates them) → 401 (one response for all). Revocation and
  expiry apply to the very next request (no cache). Deactivating a user revokes their
  keys. Requests with a key are exempt from CSRF checks; a request with a key and a
  session cookie is decided by the key.
- Failed key authentications are counted per client address (30 a minute; beyond it a
  failing key gets 429 while a valid key still works), and each key may make 300
  requests (refused ones included) and 30 writes a minute (429 `too_many_attempts`).
- Public routes (`public.submit`, `public.track`, `self.unsubscribe`, branding reads)
  ignore keys and sessions alike: the setting or token decides.

## 6. MCP tools

`/mcp` needs `mcp.connect` (a key with the `mcp` scope, c15). Every tool call is then
authorised with the rule below, through the same policy and services as the REST API,
and audited (`mcp.call`) with the tool, rule name, decision, error code, user and key
id, whatever the outcome (a cancelled call: `cancelled`, a crash: `internal_error`);
never the arguments
([contract-phase5 §3.6 and §4](api/contract-phase5.md#4-mcp-server-and-tool-catalogue)).
Requests refused before any tool runs are audited at most **once a minute per key**: a
c15 refusal (`mcp.connect`, `insufficient_scope`) and the key's request budget
(`too_many_attempts`); what the SDK refuses as malformed (400, 406, 415) isn't audited.
Each tool call reads the key and its owner again inside its own transaction: a key
revoked or expired, or an owner deactivated or demoted, while the request waited takes
effect for that very call (the tool error `unauthorized`, audited as a denial).

| Tool | Rule | Scope |
|---|---|---|
| `list_projects` | `project.view` (as a filter) | `read` |
| `search_ideas` | `idea.view` (as a filter); score fields per `score.view_aggregate` | `read` |
| `get_idea` | `idea.view`; evaluations and aggregate per `evaluation.view_others` / `score.view_aggregate`; your own per `evaluation.view_own` | `read` |
| `get_rubric` | `project.view` | `read` |
| `get_proposal` | `proposal.view` | `read` |
| `create_idea` | `idea.create` | `write` |
| `add_comment` | `comment.create` | `write` |
| `propose_proposal_section` | `proposal.suggest_section` | `write` |
| `submit_evaluation` | `evaluation.submit_own` | `evaluate` |
| `add_research_note` (Phase 6, lands with its handler) | `comment.create` + c22 | `write` |

- Tools that filter (`list_projects`, `search_ideas`) check their scope first
  (`insufficient_scope`), then list only what the owner can view inside the key's
  projects.
- **Held ideas are not found through MCP, for everyone** (stricter than REST, where
  project and platform admins can open an idea held for moderation by its link: no
  tool moderates, and text waiting for moderation doesn't reach an agent). Public ideas
  in projects without moderation are visible, flagged `via_public_form`, and every
  people-written field in tool results is described as untrusted.
- Section 3 applies to every tool: a pending evaluator's key gets no score data
  (`score_hidden`), whatever its scopes or role; service accounts evaluate blind.
- Tool errors carry the REST problem code (`not_found`, `forbidden`,
  `insufficient_scope`, `evaluation_closed`, …), or `unauthorized` (above).
- The write tools refuse arguments they don't know (`validation_error`: a typo such as
  `sumbit` never falls back to a default); the read tools ignore them. Request text with
  Unicode tag characters is refused everywhere (REST 422, MCP `validation_error`), and
  tool results carry no invisible characters.

- **Phase 6:** for a service account every tool applies c22 (the run scope: targets,
  filtered lists, the one write tool, all bound to the run named by `run_id`) and rule 9
  (no others' score data, ever; its own only in its evaluate run);
  `submit_evaluation` takes per-criterion `sources` from service accounts only (people:
  `validation_error`) and needs an AI evaluator's rationale (the comment) on every
  scored criterion; every call of a known tool by an agent that names its open run and
  that run's idea adds a `tool_called` event (Soundings' sentence for the tool only) to
  that run
  ([contract-phase6 §4](api/contract-phase6.md#4-mcp-additions)).

## 7. Writing the tests

- One parametrised test per rule. Each case: principal column (plus overlays and auth
  kind), the resource state that matters (project visibility, idea status, evaluation
  open or closed, owner present, evaluator state `none | invited | draft | submitted`,
  `allow_volunteer_owners`, `public_submission_enabled`, moderation), and the expected
  result (`allow`, `401`, `403`, `404`, or the condition's 409/422 code).
- Cover the role source: direct membership, group membership (manual and synced),
  both (highest wins), several groups (highest wins), a membership removed by sync or by
  an admin (access gone on the next request), and an overlay on a demoted user.
- Sign-in (section 2a) gets its own table-driven tests: each login-matching step and
  its denials (contract-phase2 §3.3 worked examples, including the external-ID-only
  rule and auto-create without a verified email), group sync for every before/after
  cell of §3.6 in both modes (and group overage), break-glass availability, throttling
  and session limits, and every method's sessions ending when it stops being available.
- c11 with a deactivated or service-account admin (doesn't count), and c18 with two
  concurrent demotions (one gets 409).
- Cover API keys: each scope alone, a project-restricted key, an expired key, a
  revoked key, and a key whose owner was demoted after it was created.
- Phase 5 ([contract-phase5 §3.8 and §4.6](api/contract-phase5.md#38-minimum-tests-tests-first)):
  every rule × each scope alone × restricted or not × the owner's column and overlays,
  through a key, equals the session decision narrowed by section 5; every session-only
  rule and route is 403 for a key with all four scopes; revocation, expiry and demotion
  take effect on the next request, and so do a dormant owner (30 days) and an
  unavailable creating method; c20; c21 and c4 for service accounts, and the admin role
  refused to them; `idea.delete` / `idea.moderate` refused to every key; every MCP
  tool's rule and scope, its blind filtering and holds for every column; one `mcp.call`
  audit entry per tool call.
- A meta-test fails if any route or MCP tool has no rule, or if a rule name used in
  code is missing from this file.
- Phase 6 ([contract-phase6 §3.13](api/contract-phase6.md#313-minimum-tests-tests-first)):
  table J for every column and the owner overlay (also demoted), each part of c10, c5 /
  c6 / c7, c19, archived and held ideas; a service account's key can't request a run;
  `evaluation.include_ai` with a pending evaluator (404), a person's evaluation (409) and
  a draft (404); c22 for every MCP tool (no open run, no `run_id`, another of the
  agent's open runs, another idea whether it exists or not, another kind or section,
  after cancel, timeout and `worker_lost`, even with a newer run open; `create_idea` /
  `add_comment` forbidden; REST refused to agents; `add_research_note` by people); rule
  9 for agents before and after submitting, and their own evaluation only in evaluate
  runs; the event stream for every column (404 / 401) and with
  access removed mid-stream; a pending evaluator's stream and run responses hold no score
  data; `platform.manage_agents` refused to keys and non-admins, c20 on register and
  rotate.
- Phase 4: table E for every column and overlay (a demoted owner can't write; c7 on
  start and save; archived → 409); c8 for each of its parts (instance switch, project
  setting, archived, reserved slug, unknown slug: identical 404s); c9 with unknown,
  erased and instance-switched-off tokens, and a confirmation token after the project's
  form was turned off (still works); c12 and c19 with ideas held for moderation and for
  confirmation, for every column; the moderation queue's 403 for members and viewers;
  `public.erase_submitter` contact visibility; `platform.edit_branding` and
  `project.edit_settings` on the branding routes (session only, keys refused).
