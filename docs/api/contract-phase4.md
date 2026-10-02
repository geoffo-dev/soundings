# API contract: Phase 4 (proposals, public submission, branding)

The REST contract and business rules for Phase 4 (SPEC sections 2, 5 screens 5–7, 10
and 13): the proposal editor with margin comments and PDF / Markdown export, the public
submission form with ALTCHA, tracking links, email confirmation and moderation, erasing
a submitter's details, and branding profiles. It extends
[contract-phase1.md](contract-phase1.md), [contract-phase2.md](contract-phase2.md) and
[contract-phase3.md](contract-phase3.md), whose conventions all still apply. Source of
truth, in order: the Pydantic schemas in `backend/app/schemas/` (`proposals`, `public`,
`branding`, plus `RESERVED_SLUGS` in `projects`), the route stubs in
`backend/app/api/v1/` (`proposals`, `public`, `submissions`, `branding`), the models in
`backend/app/models/` (`proposal.py`, `public.py`, `branding.py`, `ideas.held_for`, the
new `projects` columns, `outbound_email.idea_id`) with migration `0007`, and the
settings in `backend/app/config.py`, exported to
`frontend/src/api/generated/openapi.json` / `schema.d.ts` (`make gen-api`). Rules are
named as in [role-matrix.md](../role-matrix.md); tables in [erd.md](../erd.md); the
image and PDF decisions in [ADR 0011](../adr/0011-ubuntu-runtime-image-and-weasyprint.md)
and [ADR 0012](../adr/0012-branding-and-uploaded-images.md).

`backend/tests/test_contract_routes.py` pins every method, path and `operation_id` and
keeps a valid request per unimplemented route (`STUBS`, answered with 501
`not_implemented`): delete a stub row when you implement its endpoint.
`tests/authz/test_route_rules.py` names the rule of every operation.
`tests/test_schemas_phase4.py` and `tests/test_config_public.py` pin the validation
rules below; `tests/test_domain_schema.py` the constraints and migration 0007.

**Who builds what (suggested):** backend: everything in section 3 except what follows
(proposal service and exports with WeasyPrint in a child process, markdown-it-py as the
new Markdown dependency, public submission, holds and list filters, tracking, submitter
emails in the Phase 3 outbox and fan-out, erasure and retention, branding resolution,
image checks and serving, cleanup jobs, the endpoints); identity: ALTCHA (challenge
with the project in `data`, verification, replay table), the per-IP throttles, the
honeypot check and the JSON-only check for public writes in `app/auth/`
(ownership.md: public-form anti-abuse is identity's), the signed confirmation-link
token and the sealed tracking token (`app/auth/sealing.py` purpose), c9 for both
tokens, c12 from `ideas.held_for`, the new condition c19 and `listed_ideas` in
`app/authz/` (§3.6); frontend: the Proposal tab, the public form at `/{slug}/submit`,
`/track` (with "Delete my details") and `/verify` (Confirm click), project settings →
Public form and Branding, Admin settings →
Branding with live preview, the moderation queue and the submission panel on the idea
page, runtime branding (CSS variables, logo, favicon, title), the bundled fonts;
platform: the Ubuntu runtime image with Pango and the font files (ADR 0011), Helm values
for the new settings (`features.publicSubmission` and §3.12); qa: §3.15 and the
acceptance in §3.16 as e2e and API tests.

## 1. Conventions (new in Phase 4)

| Topic | Rule |
|---|---|
| Additive only | New endpoints and schemas only. No existing response model gains a field and no enum the SPA maps exhaustively (`NotificationType`, `EmailType`, `AuditAction`, `ActivityItem` types) gains a value in this contract: that breaks the frontend's typecheck and mocks. Public ideas reuse `IdeaDetail.submitted_by = null` plus `GET /ideas/{idea}/submission`; project settings for the form and branding have their own endpoints instead of new `Project` fields; the four new audit actions and two `IdeaDetail` fields land at integration with the SPA's phrases and mocks (§3.14). |
| Public routes | No session, no CSRF token: `get_public_project`, `get_altcha_challenge`, `submit_public_idea`, `track_submission`, `set_submission_updates`, `resend_verification_email`, `erase_tracked_submission`, `verify_submission_email`, `get_branding`, `get_brand_asset`. The project setting (`public.submit`, c8) or the token in the body (`public.track`, c9) is the authority. They never return people, comments, evaluations, scores, other submitters' details, anything the team wrote, or anything about a project beyond its name, intro and branding. |
| Public writes are JSON only | Every `POST` / `PUT` under `/api/v1/public/` needs `Content-Type: application/json` (parameters such as `; charset=utf-8` allowed), else **415 `unsupported_media_type`** before the body is read. FastAPI would otherwise parse a body sent with no `Content-Type` as JSON, so another site could submit or confirm through its visitors' browsers with a `no-cors` request (spreading the per-IP limit over them); `application/json` makes a cross-site browser request need a CORS preflight, which the API never grants. Identity builds it (a dependency on the public router, or `app/auth/` helper the router uses). |
| Tokens never in URLs | Tracking and confirmation tokens travel only in JSON request bodies. Links put them after `#` (`<base>/track#<token>`, `<base>/verify#<token>`), which browsers never send to a server, so no access log, proxy log, trace (spans carry URL paths) or `Referer` can hold one. The SPA reads `location.hash` and posts the token; it **keeps** the fragment (the tracking link is meant to be bookmarked and reloaded). `/verify` posts its token only when the person clicks **Confirm**, never on load (mail link scanners that run JavaScript must not confirm). `tests/test_contract_routes.py` checks no public path or query parameter carries a token. |
| Held ideas | A public idea may be **held** (`ideas.held_for`): waiting for its submitter's email confirmation or for moderation. Held ideas are in no list, board, search, count, tag list, My work, inbox or notification for anyone; admins see those held for moderation in the moderation queue and on their own page (§3.6). |
| Raw bodies | Image uploads are the file itself as the request body (`image/png` or `image/svg+xml`), not multipart (no `python-multipart` dependency) and not JSON. Exports and served images are binary responses (`application/pdf`, `text/markdown`, `image/png`, `image/svg+xml`). |
| Branding scope | The signed-in app always uses the **global** branding. A project's override applies where the project faces outward: its public form, tracking page (`/track`) and address confirmation page (`/verify`), its emails to public submitters, and its exported proposals (§3.10). |
| Privacy | Never log or audit names, email addresses, tokens, ALTCHA payloads, proposal or comment text, or image bytes. Submitter details are minimal, erasable and expire (§3.9). |
| Order of checks | As before: 401 → 404 → 403 → 422 → 409 (→ 429). Public routes: 415 (not JSON) → 422 (shape) → 404 (form not available / token unknown) → 429 → business 422 → 409. |

## 2. Endpoints

Common errors (401, 403 `csrf_failed`, 422 `validation_error`, 400 `invalid_cursor`) are
not repeated per row. "Session only" = never through an API key (role matrix §5).

### Proposals (`tags: proposals`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /ideas/{idea}/proposal` | `get_proposal` | `proposal.view` (permission flags from `proposal.write`, `proposal.comment`, `proposal.export`) | → `ProposalView {proposal: Proposal \| null, permissions}` | 404 |
| `POST /ideas/{idea}/proposal` | `create_proposal` | `proposal.write` (c7) | no body → 201 `ProposalView`; all 8 sections created; a Shortlisted idea moves to Proposal (§3.1) | 403; 404; 409 `proposal_not_available` (c7), `proposal_exists`, `project_archived` |
| `PUT /ideas/{idea}/proposal/sections/{section_key}` | `update_proposal_section` | `proposal.write` (c7) | `ProposalSectionUpdate {body_md ≤ 20,000 (verbatim, not trimmed), base_version}` → `ProposalSection` (§3.2) | 403; 404 (no proposal); 409 `proposal_conflict` (`ProposalConflictProblem` with `current`), `proposal_not_available`, `project_archived`; 422 unknown key |
| `GET /ideas/{idea}/proposal/markdown` | `export_proposal_markdown` | `proposal.export` (+ `score.view_aggregate` for the score line) | → 200 `text/markdown; charset=utf-8`, `Content-Disposition: attachment; filename="CUST-12-proposal.md"` (§3.4) | 404 (no proposal); 429 `too_many_attempts` + `Retry-After` |
| `GET /ideas/{idea}/proposal/pdf` | `export_proposal_pdf` | `proposal.export` (+ `score.view_aggregate`) | → 200 `application/pdf`, `filename="CUST-12-proposal.pdf"` (§3.4) | 404; 429; 503 `export_busy` (busy for 30 s, or the render hit its 20 s limit) |
| `GET /ideas/{idea}/proposal/threads` | `list_proposal_threads` | `proposal.view` | → `ProposalThreadList {items: [ProposalThread]}`, not paged (§3.3) | 404 |
| `POST /ideas/{idea}/proposal/threads` | `create_proposal_thread` | `proposal.comment` | `ProposalThreadCreate {section_key, body_md 1–5,000}` → 201 `ProposalThread` | 403; 404; 409 `too_many_comments`, `project_archived` |
| `POST /ideas/{idea}/proposal/threads/{thread_id}/comments` | `reply_to_proposal_thread` | `proposal.comment` | `ProposalCommentCreate {body_md}` → 201 `ProposalThread` (a reply reopens a resolved thread) | 403; 404; 409 `too_many_comments`, `project_archived` |
| `PUT /ideas/{idea}/proposal/threads/{thread_id}/resolved` | `resolve_proposal_thread` | `proposal.comment` | → `ProposalThread`; idempotent | 403; 404; 409 `project_archived` |
| `DELETE /ideas/{idea}/proposal/threads/{thread_id}/resolved` | `reopen_proposal_thread` | `proposal.comment` | → `ProposalThread`; idempotent | 403; 404; 409 `project_archived` |
| `DELETE /ideas/{idea}/proposal/threads/{thread_id}/comments/{comment_id}` | `delete_proposal_comment` | `comment.edit_own` (c2) or `comment.delete_any` | → 204; soft delete; idempotent | 403 `not_author`; 404; 409 `project_archived` |

### Public submission (`tags: public`, no session)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /public/projects/{slug}` | `get_public_project` | `public.submit` (c8) | → `PublicProject {slug, name, intro_md, asks_for_email, email_required, moderated, branding}` | 404 (form off, archived, unknown, reserved slug, instance switch off: no hint which) |
| `GET /public/projects/{slug}/altcha` | `get_altcha_challenge` | `public.submit` (c8) | → `AltchaChallenge {parameters {algorithm, cost, keyLength, keyPrefix, nonce, salt, expiresAt, data: {project: slug}}, signature}` (the widget's camelCase format) | 404; 429 |
| `POST /public/projects/{slug}/submissions` | `submit_public_idea` | `public.submit` (c8) | `PublicSubmissionCreate {title, summary, description_md?, name?, email?, wants_updates, altcha, website}` → 201 `PublicSubmissionReceipt {tracking_token, tracking_url, held_for, email_sent}` (§3.5) | 404; 415; 422 `email_required`, `challenge_failed`; 429 `too_many_attempts` + `Retry-After` |
| `POST /public/track` | `track_submission` | `public.track` (c9) | `TrackingRequest {token}` → `TrackedSubmission` (§3.7) | 404; 415; 429 |
| `PUT /public/track/updates` | `set_submission_updates` | `public.track` (c9) | `TrackingUpdatesRequest {token, wants_updates}` → `TrackedSubmission`; idempotent | 404; 409 `no_email`; 415; 429 |
| `POST /public/track/verification-email` | `resend_verification_email` | `public.track` (c9) | `TrackingRequest {token}` → 202 `TrackedSubmission` | 404; 409 `no_email`, `already_verified`, `smtp_not_configured`; 415; 429 |
| `POST /public/track/erase` | `erase_tracked_submission` | `public.track` (c9) | `TrackingRequest {token}` → 204; the submitter's own erase, same effect as `erase_submitter` (§3.9) | 404 (also a second call); 415; 429 |
| `POST /public/verify-email` | `verify_submission_email` | `public.track` (c9: a valid confirmation token, instance switch on) | `VerificationRequest {token}` (from `/verify#<token>`, posted on the Confirm click) → `EmailVerified {project, title, held_for, branding}`; idempotent | 404 (invalid, expired or spent token); 415; 429 |

### Public form settings, moderation and submitters (`tags: submissions`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /projects/{slug}/public-form` | `get_public_form_settings` | `project.edit_settings` (session only) | → `PublicFormSettings {available, email_available, enabled, require_email_verification, moderation_required, intro_md, form_url, awaiting_moderation}` | 403; 404 |
| `PATCH /projects/{slug}/public-form` | `update_public_form_settings` | `project.edit_settings` (session only) | `PublicFormSettingsUpdate {enabled?, require_email_verification?, moderation_required?, intro_md? ≤ 2,000}` → `PublicFormSettings`; audited `project.update` | 403; 404; 409 `public_submission_unavailable` (instance switch off, or a reserved slug), `smtp_not_configured`, `project_archived` |
| `GET /projects/{slug}/moderation?cursor=&limit=` | `list_moderation_queue` | `project.view`, then `idea.moderate` at project level | → `ModerationPage {items: [ModerationItem], next_cursor, total}`, oldest first | 403 (member, viewer, internal non-member); 404 |
| `GET /ideas/{idea}/submission` | `get_idea_submission` | `idea.view` (contact details by `public.erase_submitter`, moderation by `idea.moderate`) | → `IdeaSubmission {idea_id, submitted_at, held_for, name, contact, erased_at, permissions}` | 404 (no public submission behind it) |
| `POST /ideas/{idea}/submission/approve` | `approve_submission` | `idea.moderate` | → `IdeaSubmission` (held_for null); audited | 404; 409 `not_awaiting_moderation`, `project_archived` |
| `POST /ideas/{idea}/submission/reject` | `reject_submission` | `idea.moderate` | → 204; deletes the idea (§3.6); audited | 404; 409 `not_awaiting_moderation`, `project_archived` |
| `POST /ideas/{idea}/submission/erase` | `erase_submitter` | `public.erase_submitter` (session only) | → `IdeaSubmission` (erased); idempotent; audited (§3.9) | 403; 404 |

### Branding (`tags: branding`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /branding` | `get_branding` | public | → `EffectiveBranding {app_name, primary_color, accent_color, font, logo_url, favicon_url}` (global) | |
| `GET /branding/assets/{asset_id}` | `get_brand_asset` | public | → 200 the bytes (`image/png` or `image/svg+xml`), headers in §3.11; 304 on `If-None-Match` | 404 |
| `GET /admin/branding` | `get_global_branding` | `platform.edit_branding` (session only) | → `BrandingSettings` (scope `global`) | 403 |
| `PUT /admin/branding` | `update_global_branding` | `platform.edit_branding` (session only) | `BrandingUpdate` (complete; null = default) → `BrandingSettings`; audited `branding.update` | 403; 422 `invalid_asset` |
| `POST /admin/branding/assets?kind=logo\|favicon` | `upload_global_brand_asset` | `platform.edit_branding` (session only) | raw PNG or SVG body → 201 `BrandAsset` (§3.11) | 403; 413 `content_too_large`; 422 `invalid_image`; 429 |
| `GET /projects/{slug}/branding` | `get_project_branding` | `project.edit_settings` (session only) | → `BrandingSettings` (scope `project`; `inherited` = the global effective values) | 403; 404 |
| `PUT /projects/{slug}/branding` | `update_project_branding` | `project.edit_settings` (session only) | `BrandingUpdate` (complete; null = inherit; `{}` removes the override) → `BrandingSettings`; audited `project.update` | 403; 404; 409 `project_archived`; 422 `invalid_asset` |
| `POST /projects/{slug}/branding/assets?kind=` | `upload_project_brand_asset` | `project.edit_settings` (session only) | raw PNG or SVG body → 201 `BrandAsset` | 403; 404; 409 `project_archived`; 413; 422 `invalid_image`; 429 |

Admin routes follow the Phase 2 order: 401 → 422 shape → 403 `forbidden` (not a platform
admin) → 404 → 422 business → 409 → 429.

### Unchanged endpoints with new behaviour

- **Every list** (`list_ideas`, `get_board`, `global_search`, `get_my_work`,
  `list_my_owned_ideas`, `list_project_tags`, `list_notifications`, the summary count)
  and every count (`Project.idea_count`, board column counts) **leaves held ideas out**
  for everyone (§3.6). `get_idea` and the idea's sub-resources still answer for a held
  idea to project and platform admins (c12); for an idea held for email verification
  they answer 404 to everyone.
- **Idea writes on an idea held for moderation** (status, owner, evaluators, due date,
  edits, comments, votes, watching, proposal) → 409 `awaiting_moderation` (c19), except
  `delete_idea`, `approve_submission`, `reject_submission`, `erase_submitter`.
- `create_project`: a slug in `RESERVED_SLUGS` (`settings`, `track`, `verify`, `ideas`,
  `api`, … the app's own top-level paths) → 422 `validation_error`, because the public
  form lives at `/{slug}/submit`. An older project that already has such a slug keeps
  it but can't turn its public form on (409 `public_submission_unavailable`;
  `PublicFormSettings.available` false; c8 fails).
- `change_idea_status` (and the status move inside `create_proposal`): an opted-in,
  confirmed public submitter gets a `submission_status_changed` email (§3.8).

## 3. Business rules

Tests first (SPEC section 15, lead's quality bar) for: 3.5 (honeypot, rate limits,
ALTCHA expiry and replay, email required), 3.6 (holds and moderation visibility on every
surface), 3.7 (tracking-link secrecy), 3.9 (erasure and retention), 3.1–3.3 (proposal
permissions and concurrency), 3.4 (export safety: no remote fetch, sanitised Markdown,
branding values), 3.10–3.11 (CSS injection through branding, SVG XSS). §3.15 lists the
minimum cases.

### 3.1 Proposal lifecycle and permissions

- **One proposal per idea** (`proposals.idea_id` unique), over the fixed template
  (`app.schemas.proposals.PROPOSAL_TEMPLATE`, SPEC section 2): Summary, Problem,
  Solution, Market & users, Cost & effort, Benefits / revenue, Risks, Next steps / the
  ask. Keys: `summary, problem, solution, market, cost, benefits, risks, next_steps`. No
  custom sections, no reordering.
- **Start** (`create_proposal`, `proposal.write`: the owner, project admins, platform
  admins; c7: status `shortlisted` or `proposal`): creates the proposal and its eight
  sections (version 1; Summary starts as the idea's summary, the rest empty), under the
  idea's lock (`load_idea(for_update=True)`); a second call → 409 `proposal_exists`.
  **A Shortlisted idea moves to Proposal** in the same transaction, exactly like
  `change_idea_status` (activity `status_changed`, notifications, the submitter email,
  audit `idea.status_change`), so the board shows where it is. An idea already in
  Proposal (moved on the board) just gets its proposal.
- **No proposal status** of its own: the idea's status is the state. Editing needs c7
  (Shortlisted or Proposal); moving the idea back to Evaluating or New, or closing it,
  makes the proposal read-only (409 `proposal_not_available`) but it stays readable,
  commentable and exportable; moving it to Shortlisted or Proposal again makes it
  editable. Deleting the idea deletes the proposal.
- **Who** (role matrix section E): `proposal.view` and `proposal.export` for everyone
  who can view the idea (viewers and internal non-members included); `proposal.write`
  for the owner (while member or admin) and admins; `proposal.comment` for members and
  admins (not viewers). In an archived project every write is 409 `project_archived`.
  `proposal.suggest_section` and AI drafting are Phase 6.
- **Blind evaluation:** proposals hold no score data; the only score anywhere in this
  phase is the export's aggregate line, for people who pass `score.view_aggregate` (§3.4).
- **Permissions** (`ProposalPermissions`): `can_create` = `proposal.write` passes and
  there is no proposal; `can_edit` = `proposal.write` passes and there is one;
  `can_comment` = `proposal.comment`; `can_export` = `proposal.export` and there is one.
- **Not in Phase 4:** notifications about proposal edits or margin comments (no new
  `NotificationType`; §6), @mentions in margin comments, edit history.

### 3.2 Saving sections: optimistic concurrency

- One `PUT` per section (the SPA autosaves each section separately, debounced).
  `base_version` is the `version` the text was based on. **The text is stored exactly
  as sent:** `body_md` is the one request string that isn't whitespace-stripped
  (`SectionText`: leading indentation is an indented code block, and autosave must not
  eat the spaces and newlines someone is typing); NUL is still refused.
- **Locking:** the project row `FOR KEY SHARE`, then the idea row **`FOR SHARE`** (not
  `FOR UPDATE`): saves to different sections run side by side, while a status change
  (which updates the idea row) waits for saves in flight and they wait for it, so c7 is
  checked against a status that can't change before the save commits. Then, in one
  statement: `UPDATE proposal_sections SET body_md = :text, version = version + 1,
  updated_by_id = :me, updated_at = now() WHERE proposal_id = :p AND key = :k AND
  version = :base_version RETURNING …`, plus `proposals.updated_at = now()`.
- **No row updated:** if the stored text equals the new text, return the section
  unchanged (a retried save is a no-op, even if the version moved since); otherwise 409
  **`proposal_conflict`** as a `ProposalConflictProblem` whose **`current`** is the
  section as saved now (read in the same transaction). The SPA shows "Someone else
  changed this section" with **Reload** (show `current`) or **Keep mine** (save again
  with `current.version`), without a refetch another save could overtake. Other 409s
  from this route (`proposal_not_available`, `project_archived`, `awaiting_moderation`)
  have no `current`.
- Identical text with the current `base_version`: no version bump, 200.
- Two people editing **different** sections never conflict. Limits: 20,000 characters
  per section (422 `validation_error`); NUL refused.
- Section saves are not activity events and don't bump `ideas.last_activity_at`.

### 3.3 Margin comments

- A **thread** is anchored to one section key (not to character ranges), opened with its
  first comment; replies are flat, oldest first. Threads can be **resolved** and
  **reopened** by anyone with `proposal.comment` (idempotent; `resolved_by`, `resolved_at`
  set or cleared); a reply to a resolved thread reopens it. Resolved threads collapse.
- **Delete** a comment: the author (`comment.edit_own`, c2 → 403 `not_author`) or a
  project/platform admin (`comment.delete_any`). Soft: `deleted_at`, `body_md` cleared,
  shown as a stub; a thread whose comments are all deleted is no longer listed. No edit
  (delete and write again).
- `list_proposal_threads` returns every listed thread (template order, then oldest
  first) with all its comments; there is no paging. Caps: 500 threads per proposal and
  200 comments per thread (409 `too_many_comments`); comments 1–5,000 characters.
- Comments are Markdown rendered without raw HTML (react-markdown defaults, as for idea
  comments). Not activity events, no notifications in Phase 4.

### 3.4 Exports (Markdown and PDF)

Both are `GET`s returning an attachment (the SPA downloads them with `fetch` and a blob,
or a plain link: the session cookie authenticates a same-origin `GET`).

- **Content, both formats:** the idea's title; a metadata block: project name, idea key,
  status label, owner, "Exported <date, instance time zone> by <name>", and **only if
  the exporter passes `score.view_aggregate`** (not a pending evaluator, role matrix §3)
  "Aggregate score 4.1 from 5 evaluations" (no per-criterion data); then the eight
  sections in template order as `## <title>` with their Markdown, an empty section as
  "_Not written yet._". Headings inside a section are demoted below the section heading
  (`#` → `###`, never deeper than `######`), **found with the parser** (markdown-it
  tokens), never by matching text: setext headings (`Title` over `===`) are demoted
  too, and a `#` line inside a code fence is left alone. Comments are never exported.
- **Markdown:** UTF-8, `\n` line endings, the section text verbatim apart from the
  heading demotion (each `heading_open` token's `map` gives its source lines: an ATX
  heading gets two more `#`, capped at six; a setext heading is rewritten as the
  demoted ATX heading); `Content-Disposition: attachment;
  filename="<KEY>-proposal.md"` (the key is ASCII, so no injection through the
  filename).
- **PDF** (WeasyPrint 70, ADR 0011): A4, the project's **effective branding** (§3.10):
  a cover with the logo (embedded from the database as a `data:` URI) or the app name as
  a wordmark, the title, project and metadata, a band or rule in the primary colour; the
  chosen font for everything (bundled files served by name, §3.10); running header with
  the app name and idea key, footer "Page X of Y"; PDF metadata title (the idea's title), author (the
  owner), creator (the app name). Colours reach the stylesheet only as validated hex;
  text colour on a coloured band is chosen by contrast (white or ink, ≥ 4.5:1).
- **Safety (tests first):**
  - Markdown is rendered **as the SPA renders it** (`components/ui/markdown.tsx`), so the
    editor's preview is what the PDF shows: CommonMark + GFM tables (markdown-it-py, a
    new backend dependency: pure Python, token stream with source maps; nesting limit
    `maxNesting` 20); **raw HTML is dropped** (the parser's `html_block`
    and `html_inline` tokens render as nothing, like react-markdown's `skipHtml`: `a
    <b>x</b> c` prints "a x c", a `<div>` block prints nothing); link targets limited to
    `http`, `https` and `mailto` (others become plain text); **an image is never an
    image**: `![alt](url)` renders as a link labelled with its alt text (or "Image") to
    `url` when that is `http(s)`, else as the plain alt text, exactly as the SPA shows
    it. Nothing in a proposal ever produces an `<img>`, `<link>`, `<object>` or CSS
    `url()`.
  - WeasyPrint gets a **local-only URL fetcher** (research R1 §4) that answers exactly
    two kinds of URL and raises for everything else (`http(s)`, `file:`, `ftp:`,
    `169.254.169.254`, relative paths, …): `data:` URIs (decoded by the fetcher itself)
    and `soundings-font:<font>-<weight>` names (`soundings-font:inter-600`) looked up
    in a fixed in-memory map of the bundled font files (§3.10), so no path from a URL
    ever reaches the file system. It **never** calls WeasyPrint's default fetcher
    (`URLFetcher.fetch` follows `HTTP(S)_PROXY` and redirects), not even as a
    fallback. Both layers are needed: in the review, `![a](http://169.254.169.254/y)`
    rendered as an image did reach the fetcher. An SVG logo's external references are
    refused at upload (§3.11) and blocked by the fetcher anyway.
  - Every user value (title, names, section text, app name, footer) goes through the
    template engine's escaping; nothing user-controlled is ever placed in CSS except the
    validated colours and the font key mapped to a fixed family name.
  - `import weasyprint` lazily inside the export, so the API starts without Pango.
- **Limits:** per user, at most **10 exports per minute** (Markdown and PDF together,
  in-process like the sign-in throttles) → 429 `too_many_attempts` + `Retry-After`.
  - **A separate process with a hard time limit.** Each PDF renders in a child process
    (multiprocessing `spawn` context: never `fork` from the threaded API process),
    one at a time per API process (a semaphore of 1): the HTML (logo inlined as a
    `data:` URI) goes in, the PDF bytes come out, and the child builds its font map
    at import. The child gets **20 seconds**
    of wall-clock time; then it is killed (`SIGKILL`) and the request answers 503
    **`export_busy`** with `Retry-After: 10`, logged at WARNING with the idea id. A
    request that waits more than 30 s for the slot → the same 503. The event loop never
    renders (the review measured 448 ms pauses with a render in a thread, because
    WeasyPrint holds the GIL). A fresh child per render (about a second of start-up)
    or one kept warm and replaced after a kill are both fine.
  - **Tables are bounded:** per proposal at most **2,000 table cells** (header cells
    included) and **200 rows per table** render as tables; any further table, or a
    larger one, renders as its Markdown source in a monospaced block (the Markdown
    export is unaffected). Tables are what is slow: eight sections of ~1,500-row tables
    (within the 20,000-character limit) took 34.7 s in the review, while the longest
    prose proposal (8 × 20,000 characters) takes about 2 s.
- Not audited (a read). Rate-limit refusals are logged with the user id only.

### 3.5 The public form

**Availability (c8):** the instance switch `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` is on,
the project's `public_submission_enabled` is on, the project isn't archived and its
slug isn't in `RESERVED_SLUGS` (only older projects can have one; they can't turn the
form on). Otherwise every public route about the project answers the same 404 (unknown
slug included): "This form isn't available", no hint whether the project exists. The
form at `/{slug}/submit` (SPA route) shows only the project's name, `intro_md` and
effective branding, even for a private project.

**`PublicProject`:** `asks_for_email` = SMTP is configured (without email the form asks
for no address at all: minimal data); `email_required` = `public_require_email_verification`
and SMTP configured; `moderated` = `public_moderation_required`.

**Fields** (`PublicSubmissionCreate`, sent as `application/json`, else 415): `title`
(1–200, one line), `summary` (1–500), `description_md` (≤ 10,000, optional), `name`
(≤ 80, one line, optional; blank = none), `email` (one plain ASCII address, Phase 3's
`MailAddress`, optional; blank = none; not under `.invalid`), `wants_updates` (needs
`email`, else 422), `altcha` (the widget's payload, ≤ 4,096 base64 characters),
`website` (the honeypot: any string of any length, described neutrally as "Leave
empty." in the public OpenAPI document). No tags (internal vocabulary). Unknown fields
→ 422. When `asks_for_email` is false, `email` **and** `wants_updates` are ignored
(neither is stored: keeping one without the other would break
`ck_public_submissions_updates_need_email`), so a form loaded before email was turned
off still goes through.

**Checks, in order** (each step's failure is the response):

1. `Content-Type` not `application/json` → 415 `unsupported_media_type` (§1). Body
   shape → 422 `validation_error`.
2. Form available (c8) → 404.
3. **Per-IP limit:** `SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP` (default 10) per client
   address per hour, every attempt counted (honeypot hits and failed challenges
   included). The client address is Phase 2's (`ProxyHeadersMiddleware`, trusted
   proxies and hops only; IPv6 per /64; `app.auth.throttle.client_key`), an in-process
   sliding window like the sign-in throttles (limits multiply with API replicas;
   contract-phase2 §6) → 429 `too_many_attempts` with `Retry-After`. The SPA says
   "You've sent several ideas in a short time. Try again in a few minutes." Refusals
   are logged at INFO (`public submission refused`, `reason=rate_limited`, project id,
   never the address); the first refusal of a key in an hour is a WARNING, so
   operators notice a shared NAT or a wrong `trustedProxyHops` (the per-project limit,
   step 6, is the real backstop against address rotation such as IPv6 /64s).
4. **Email required:** `email_required` and no `email` → 422 **`email_required`**.
5. **ALTCHA** (identity): `verify_solution(altcha, hmac_key)` (Python `altcha` 2.x, PoW
   v2, `PBKDF2/SHA-256`, random mode with key prefix `00`, research R1 §7), then the
   challenge's signed `data.project` must equal the form's slug (a challenge fetched
   for another project's form is refused). Not verified, a bad signature, expired,
   another project, malformed → 422 **`challenge_failed`**. **Replay:** insert the
   challenge's `signature` with its `expiresAt` into `altcha_used_challenges` in the
   request's transaction (`ON CONFLICT DO NOTHING RETURNING`); no row → 422
   `challenge_failed` (a solution is accepted once, honeypot hits included). The key is
   `HKDF-SHA256(SOUNDINGS_SECRET_KEY, info="soundings/altcha/v1")` (hex), so all
   replicas agree and rotating the secret key invalidates outstanding challenges.
   Challenges are signed, carry `expiresAt` = now + `SOUNDINGS_ALTCHA_EXPIRY` (default
   30 minutes), `data = {"project": "<slug>"}` and cost `SOUNDINGS_ALTCHA_COST`
   (default 5,000). The SPA starts solving when the form gets its first input (or on
   submit) and, on `challenge_failed`, fetches a new challenge and retries once before
   saying "We couldn't verify this browser. Retry".
6. **Per-project limit:** more than `SOUNDINGS_PUBLIC_SUBMISSIONS_PER_PROJECT` (default
   100) `public_submissions` rows for the project in the last hour (counted in the
   database on `ix_public_submissions_project_id_created_at`, so across replicas) → 429
   `too_many_attempts` with `Retry-After` (seconds until the oldest of them is an hour
   old).
7. **Honeypot:** `website` not empty → commit the ALTCHA replay row only and answer
   **201 with a normal-looking receipt** (a random 43-character token that tracks
   nothing, `held_for` as this project would set it, `email_sent` by the same rule as
   a real one), nothing else stored, no email. It comes **after** every other check, so
   a filled honeypot gets exactly the answers a real submission would (a bad challenge
   is 422, a missing required address is 422, a saturated project is 429) and costs
   the same proof of work. Logged at INFO as `public submission dropped (honeypot)`
   with the project id only.
8. **Create**, in one transaction (the project row `FOR KEY SHARE` first, as for every
   idea write): the idea (status `new`, `submitted_by_id` null, next number of the
   project, `held_for` = `email_verification` if `email_required`, else `moderation` if
   `moderated`, else null), an `idea_created` activity event with no actor, the
   `public_submissions` row (name, email, `wants_updates`, `submitted_title` /
   `submitted_summary` = the title and summary as sent, `tracking_token_hash` = SHA-256
   hex of a new 32-byte random token, `tracking_token_sealed` = the token sealed with
   purpose `submission-tracking-token`), the ALTCHA replay row, and, with an address
   (and SMTP configured, and the per-address limit below not reached), a
   `submission_received` outbox email (§3.8). No watchers (there is no user), no
   notifications (§3.6).
9. → 201 `PublicSubmissionReceipt`: `tracking_token`, `tracking_url` =
   `<public_base_url>/track#<token>` (a configured base URL, never the `Host` header),
   `held_for`, `email_sent` = an address was kept and SMTP is configured.

**Per-address limit:** at most **3** `submission_received` emails per address per 24
hours, first sends and resends together, counted over `outbound_email`
(`ix_outbound_email_submission_address`) on the address **lower-cased with any `+tag`
removed** (`SUBMITTER_ADDRESS_KEY_SQL`: `Victim+1@x` and `victim+2@x` count as
`victim@x`). Beyond it the submission is accepted without an email, **silently**:
`email_sent` is still true (it can't reveal how often an address was used), and the
tracking page offers a resend later. Together with the confirmation email's fixed
content (§3.8) the form can't be used to send anyone more than three short "confirm
your idea" emails a day.

**The form page** (frontend):

- **Honeypot input:** visually off-screen (not `display: none`, which some bots skip),
  `aria-hidden="true"`, `tabindex="-1"`, `autocomplete="off"`, with a `name`, `id` and
  label that browsers and password managers don't autofill (not `website`, `url`,
  `homepage`, `email`, `name`, `company`, …; e.g. `name="hp_ref"`, label "Leave this
  empty"); its value is sent as `website`. A real idea must never be lost to autofill.
- **Privacy notice**, fixed text under the form (not configurable): what we keep (what
  you write, and your name and email address only if you give them; no IP address);
  how long (an unconfirmed address is forgotten after 3 days; your name and address are
  erased 180 days after your idea is closed); how to remove them ("Delete my details"
  on your tracking page, or ask the team); the idea itself stays with the team.

The SPA needs a CSP-compatible ALTCHA setup: import the widget from `altcha/external`
and bundle its worker (no `blob:` workers, no CDN); prefer the WebCrypto PBKDF2 path; if
the widget needs WebAssembly the CSP must gain `'wasm-unsafe-eval'` in `script-src`
(backend owns `app/middleware.py`; verify in a real browser with the production CSP).
The widget must pass the challenge's `data` back unchanged (it is signed).

### 3.6 Holds, moderation and visibility

`ideas.held_for` (`HoldReason`; null = visible):

| Value | Set when | Who can see the idea | Ends when |
|---|---|---|---|
| `email_verification` | the project requires a confirmed address | **nobody** (404 everywhere, admins included: it isn't a submission until confirmed) | the submitter confirms (→ `moderation` if the project is moderated, else null), or it is **deleted after 3 days** by the cleanup |
| `moderation` | the project is moderated (default for a new form) | project and platform admins only (c12): the moderation queue, the idea page (by link), `get_idea_submission` | an admin approves (→ null) or rejects (→ the idea is deleted) |

- **Lists leave held ideas out for everyone**, admins included: board and list (and their
  counts), search and ⌘K, My work, owned ideas, tag lists and counts,
  `Project.idea_count`, the inbox and its count. Admins find ideas held for moderation
  in the **moderation queue** (`list_moderation_queue`, oldest first, `total` for the
  board's "3 ideas waiting for review" link) and on the project's Public form settings
  (`awaiting_moderation`). Implementation (identity + backend): `viewable_ideas` gains
  c12 (held for moderation only for project and platform admins; held for verification
  for nobody), and a new `listed_ideas(principal)` = `viewable_ideas AND held_for IS
  NULL` is what every list, count and search uses. `load_idea` treats an idea held for
  verification as absent (404).
- **Nothing happens on a held idea:** no notifications are created about it (no events
  besides its own `idea_created`), and every idea write except `delete_idea`,
  `approve_submission`, `reject_submission` and `erase_submitter` answers 409
  **`awaiting_moderation`** (c19, the policy's idea-write family, like
  `project_archived`). Non-admins get 404 before that (c12).
- **The idea page while held for moderation** (admins only): every `IdeaPermissions`
  flag except `can_delete` is **false** (as in an archived project), and so are the
  idea's sub-resource permissions (`ProposalPermissions`, comment and vote flags), so
  the page shows the idea read-only with the submission panel's Approve / Reject
  (`IdeaSubmissionPermissions.can_moderate`). Until the integration step adds
  `IdeaDetail.held_for` (`HoldReason | null`) and `IdeaDetail.via_public_form` (bool)
  (§3.14), the SPA calls `get_idea_submission` only when `IdeaDetail.submitted_by` is
  null (public ideas, and the rare internal idea whose author was deleted, which
  answers 404); afterwards it reads the two fields and makes no extra call.
- **Approve** (`idea.moderate`): `held_for` null and `last_activity_at = now()` (so it
  shows at the top of New); audited `submission.approve`. No email, no notification.
  409 **`not_awaiting_moderation`** when it isn't held for moderation (a second click).
- **Reject** (`idea.moderate`): deletes the idea (cascading to its submission, outbox
  rows, activity) and audits `submission.reject` with ids only. For spam, abuse and
  off-topic posts; a genuine but unwanted idea is approved and later closed as
  Rejected, so its submitter sees that. The tracking link then answers 404 ("We can't
  find this submission. It may have been removed."). 409 `not_awaiting_moderation` when
  not held for moderation (use `delete_idea` for other ideas).
- **Changing the settings** affects new submissions only: ideas already held stay held
  (and stay moderatable when moderation or the form is turned off).
- **Confirming** (see §3.7): an idea held for verification moves to `moderation` or to
  visible, with `last_activity_at = now()`.

### 3.7 Tracking and confirmation links

- **Tracking token:** 32 random bytes, base64url without padding (43 characters, pattern
  `^[A-Za-z0-9_-]{43}$`). Stored as `tracking_token_hash` (SHA-256 hex, unique: the
  lookup) and `tracking_token_sealed` (AES-256-GCM with a key derived from the secret
  key, purpose `submission-tracking-token`, so later emails can include the link; a
  database leak alone reveals no token). Shown **once** in the receipt and emailed with
  the confirmation; never logged, audited or put in a URL the server sees
  (`<base>/track#<token>`). Whoever holds it can see the idea's public status, turn
  status emails on or off, ask for the confirmation email again and erase the
  submitter's details, nothing else (role matrix: tracking-token principal).
- **`track_submission`** (c9: a token whose hash matches a submission that isn't erased,
  and the instance switch is on; else 404, unknown and erased alike): `TrackedSubmission`
  = the project's public name, the title and summary **as submitted**
  (`submitted_title`, `submitted_summary`: never the idea's current text, which the
  team may have edited or added internal notes to), `submitted_at`, `held_for`, status,
  resolution and status label (the project's labels; closed: the resolution's),
  `history` = its `status_changed` events after it reached the team (dates and labels
  only, no people), `email_hint` (masked: first character, `•••`, `@domain`),
  `email_verified`, `wants_updates`, `can_resend_verification`, and the project's
  effective branding. Never: people, owner, evaluators, comments, evaluations, scores,
  votes, tags, the idea key, the current title or description, other submissions. Works
  while the idea exists and the submission isn't erased, whether or not the project's
  form is still on (the instance switch `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED=false`
  turns tracking off too).
- **`set_submission_updates`:** `wants_updates=true` needs an address on file (409
  **`no_email`**: no way to add one later, simple beats configurable); status emails go
  only to a **confirmed** address (§3.8), so the page offers "Confirm your address to get
  updates" + resend while unconfirmed. `false` stops them at once (queued status emails
  are cancelled at send time). This is the submitter's opt-out ("Stop these emails" in
  every status email links to the tracking page).
- **Confirmation link:** `<base>/verify#<token>`, a **signed** token (no table, like
  Phase 3's unsubscribe tokens): `base64url(payload) "." base64url(HMAC-SHA256(key,
  base64url(payload)))`, payload compact JSON `{"v": 1, "s": "<submission id>", "e":
  "<first 16 hex of SHA-256(lower(email))>", "x": <expiry unix seconds>}`, key
  `HKDF-SHA256(secret key, info="soundings/submission-verify/v1")`, compared in constant
  time, valid **3 days**. `verify_submission_email` (`public.track`, c9: the token is
  the authority and only the instance switch must be on, so turning a project's form
  off doesn't break confirmations already on their way) checks signature and expiry,
  that the submission exists, isn't erased and still has an address with that digest →
  sets `email_verified_at` (idempotent: already confirmed → 200 again) and releases a
  hold for verification (§3.6). Anything else → 404 (expired and invalid alike; the
  page offers "Open your tracking link to send a new one"). **The `/verify` page posts
  only when the person clicks "Confirm my email address"**, never on load: mail
  security scanners open links, and some run JavaScript. Before the click it shows the
  global branding (it can't know the project yet) and fixed text; `EmailVerified`
  then brings the project's name, branding and the title as submitted.
- **Resend** (`resend_verification_email`, c9): an unconfirmed address on file (409
  `no_email`, `already_verified`), SMTP configured (409 `smtp_not_configured`), at most
  **3** `submission_received` emails per submission per 24 hours, the first included
  (`ix_outbound_email_idea_id`; 429 `too_many_attempts` + `Retry-After`) and within the
  per-address limit (§3.5; silent: still 202). → 202 `TrackedSubmission`.
- **Erase my details** (`erase_tracked_submission`, c9): the submitter's own erasure
  (UK GDPR), the same effect as an admin's `erase_submitter` (§3.9): name, address,
  confirmation, opt-in, the copy of what they sent and the link go, the idea stays with
  the team. → 204; the link stops working at once, so a second call is 404. Audited
  `submission.erase` with no actor and `details.reason = "submitter"`. The tracking
  page asks first ("This removes your name, email address and this private link. You
  won't be able to follow your idea any more. The idea stays with the team.").
- **Throttle:** `track_submission`, `set_submission_updates`,
  `resend_verification_email`, `erase_tracked_submission` and `verify_submission_email`
  share a per-IP throttle of **60 requests per minute** (constant), and
  `get_altcha_challenge` one of **30 per minute**: tokens can't be guessed (256 bits),
  this only bounds load.

### 3.8 Submitter emails (Phase 3 outbox)

Two existing `EmailType`s, sent through the Phase 3 outbox and worker unchanged
(transactional insert + defer, retries, send-time checks, Message-ID, one recipient):

| Type | When | Content (rendered at send time from the idea and its submission) | Idempotency key |
|---|---|---|---|
| `submission_received` | on submission with an address; each resend (always to an unconfirmed address) | **Fixed text, nothing the submitter typed** (no title, name or description: anyone can put any address in the form, so this email must be useless for spam). Subject `Confirm your idea for <project's public name>`. Body: "Someone sent an idea to <project> and gave this email address." — the **confirmation link** (signed at send time, valid 3 days from then) as the main button, "Confirm my email address"; what confirming does (the team gets the idea, when the project holds ideas until confirmed; status emails, when asked for); the **tracking link** (unsealed at send time); "If this wasn't you, ignore this email: nothing more will be sent unless you confirm." | `submission_received:<submission id>:<n>` (n = 1, 2, 3) |
| `submission_status_changed` | in the fan-out of every `status_changed` event of a public idea (also the move inside `create_proposal`) whose submission has `wants_updates`, a **confirmed** address and isn't erased | Subject `Your idea "<title as submitted>" is now <label>`. The new status label (closed: the resolution's), the tracking link, and "Stop these emails" (→ the tracking page). Only the submitter's own title (`submitted_title`), never the idea's current text; no people, comments or scores. | `submission_status:<event id>` |

- Rows: `to_address` = the submission's address at insert, `idea_id` = the idea
  (**required** for these two types and refused for every other:
  `ck_outbound_email_idea_iff_submission_type`, so erasure, which finds them by idea,
  can't miss one; `NewEmail.idea_id` in `app/email/outbox.py`), `payload` = `{}` for
  `submission_received` and `{from_status, from_resolution, to_status, to_resolution}`
  for status emails (never personal data or tokens: rendering reads the submission).
  Not written when SMTP isn't configured.
- **Send-time checks** (Phase 3 §3.9 step 3, plus): the idea still exists (a deleted idea
  deletes its rows anyway); the submission isn't erased and still has `to_address` as its
  address (else cancelled "Not sent: no longer applies"); for status emails still
  `wants_updates` and confirmed (else "Not sent: turned off by the recipient"); the
  idea isn't held for moderation (no status email can concern one). Out-of-date rule as
  Phase 3 (3 days).
- **Branding:** the project's effective branding (app name as the wordmark, primary
  colour with a contrast-checked text colour, the email footer text); no images (Phase
  3: no remote resources in emails). The sender is `SOUNDINGS_SMTP_FROM` as always.
- **No `List-Unsubscribe`** header (that needs a token in a URL) and no unsubscribe
  token: the tracking page is the opt-out; these are requested transactional emails.
  `Auto-Submitted: auto-generated` as for notifications.
- Phase 3's plumbing renders these types from `payload` (`app/email/content.py`
  `_submission`); Phase 4 renders them from the submission (and the idea's status) as
  above and adds the links.
- **Admin → Email outbox** (Phase 3, `app/email/admin.py`): when it fills
  `OutboxEmail.idea` from `idea_id` for submitter emails, it leaves it null for an idea
  that is held (only `listed_ideas` are referenced), and the address stays masked
  (`address_hint`).

### 3.9 Personal data: what is kept, erasure, retention

- **Stored** per public idea (`public_submissions`): optional name, optional email,
  confirmation time, `wants_updates`, the tracking token's hash and sealed copy, the
  title and summary as submitted (for the tracking page and status emails), and
  timestamps. **Not stored:** IP address (rate limits are in memory), user agent,
  account, cookies, ALTCHA payloads. The idea's own text is the submitter's
  contribution, not contact data. The form tells people this in a fixed privacy notice
  (§3.5).
- **Who sees it:** the name, to everyone who can view the idea ("Submitted by Jo via the
  public form"; "via the public form" without one); email, confirmation and
  `wants_updates` only to project and platform admins (`IdeaSubmission.contact`,
  `public.erase_submitter`). Nothing about the submitter on public pages except their own
  masked address on their own tracking page.
- **Erase** (`erase_submitter`, `public.erase_submitter`, session only, idempotent; or
  the submitter's own `erase_tracked_submission`, §3.7): name, email,
  `email_verified_at`, `wants_updates`, both tracking-token columns,
  `submitted_title`, `submitted_summary` → null/false, `erased_at = now()`,
  `erased_by_id` (null for the submitter and the cleanup); **all** the idea's submitter
  outbox rows are deleted (queued and sent, so no address lingers; every one names the
  idea, §3.8); the tracking link stops working (404). The idea, its content and history
  stay. Audited `submission.erase` (idea id only; `reason` `submitter` or `retention`
  when there is no actor). The admin dialog names what goes ("Jo's name, email address and
  private link") and confirms (it can't be undone). Personal data the submitter typed
  into the idea's text is removed by editing the idea (admins may always edit).
- **Retention** (hourly cleanup, §3.13): unconfirmed addresses are forgotten **3 days**
  after the submission (email → null, `wants_updates` → false; the tracking link keeps
  working); ideas still held for verification after 3 days are deleted; contact details
  of submissions whose idea is **closed** and has had no activity for **180 days** are
  erased automatically (audited `submission.erase` with no actor, `details.reason =
  "retention"`). Constants, not settings.
- **Logs and audit** never hold names, addresses, tokens, payloads or idea text: ids,
  project ids, outcome codes (`honeypot`, `challenge_failed`, `rate_limited`) only.

### 3.10 Branding: resolution and where it applies

- **Profiles:** one global (`branding_profiles.project_id` null, at most one) and at
  most one override per project. Fields: `app_name` (1–40, one line), `primary_color`,
  `accent_color` (`#rrggbb`, normalised lower-case), `font` (`BrandFont`: `inter`,
  `ibm_plex_sans`, `source_serif_4`, `atkinson_hyperlegible`), `email_footer` (plain
  text, ≤ 500 characters, ≤ 5 lines, no other control or bidi characters), `logo`,
  `favicon` (uploaded images, §3.11). Every field nullable.
- **Resolution, field by field:** project override → global → built-in default
  (`DEFAULT_BRANDING`: "Soundings", `#1d5fa8` for both colours, Inter, no logo (the app
  name is the wordmark), no footer, the bundled favicon). The global profile row is
  created on its first save; a missing row means all defaults.
- **Where:**

  | Surface | Branding |
  |---|---|
  | SPA shell, sign-in page, every signed-in page, ⌘K, settings | global (`GET /branding`), applied at boot and after an admin saves |
  | Public form (`/{slug}/submit`), tracking page (`/track`), address confirmation page (`/verify`) | the project's effective branding (in `PublicProject`, `TrackedSubmission`, `EmailVerified`) |
  | Emails to staff (Phase 3 notifications, digests, test) | global: app name, primary colour, footer |
  | Emails to public submitters | the project's effective branding |
  | Exported proposals (PDF; Markdown has no styling) | the project's effective branding |

  The signed-in app doesn't re-theme per project: one product for staff, and a project
  never changes how the shell looks to other projects' members.
- **Applied through CSS variables at runtime:** `--brand-primary`, `--brand-accent`,
  `--brand-font` (ADR 0007; `lib/branding.ts` derives contrast-safe tokens: any colour
  stays WCAG AA readable in light and dark mode); `document.title` uses the app name;
  the favicon `<link>` is swapped to `favicon_url`. **Live preview** in both settings
  pages is client-side (the form's values applied to a preview pane), before Save.
- **No CSS injection:** colours are hex only and the font is a key the SPA, PDF and
  email code map to fixed family names; the database checks both too. The SPA sets the
  variables with `style.setProperty` or its existing `<style id="soundings-branding">`
  element (allowed by the CSP's `style-src 'unsafe-inline'`, already needed by Radix).
  The app name and footer are text, always escaped.
- **Fonts are bundled, never fetched:** the SPA imports `@fontsource` packages for the
  four fonts (Inter is already bundled; frontend adds `@fontsource/ibm-plex-sans`,
  `@fontsource/source-serif-4`, `@fontsource/atkinson-hyperlegible`, latin + latin-ext,
  weights 400/600/700, loaded only when chosen); the image ships the same fonts as
  `woff2` files for WeasyPrint (backend vendors them under `app/assets/fonts/` with
  their OFL licence texts; ADR 0011). The PDF stylesheet names them only as
  `soundings-font:<font>-<weight>` URLs, which the export's fetcher answers from a
  fixed map built at import (`BrandFont` × 400/600/700 → bytes): no path from a URL
  ever reaches the file system (§3.4). Emails use a font stack starting with the chosen
  family and ending in system fonts (nothing to download).
- **Cache busting:** images are immutable per id (§3.11), so changing a logo changes
  `logo_url`. `GET /branding` is `Cache-Control: no-store` (API default); the SPA
  refetches it after a save and on window focus at most every 5 minutes.
- Audit: global saves `branding.update` (field names only); project saves
  `project.update` with `details.fields = ["branding"]`.

### 3.11 Uploaded images (logos and favicons)

- **Upload** (`upload_global_brand_asset`, `upload_project_brand_asset`): the raw file as
  the body (`Content-Type` `image/png` or `image/svg+xml`; the header is a hint, the
  **bytes decide**: PNG by its signature, SVG by parsing). **PNG and SVG only**, for
  logos and favicons alike (browsers take PNG favicons; no ICO, WebP or JPEG decoder is
  exposed to uploads). At most `SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES` (512 KiB default,
  900 KiB max: under the 1 MiB request limit) → 413 `content_too_large`. 20 uploads per
  profile (global, or one project) per 24 hours → 429 (bounds what an admin account
  can pile into the database before the cleanup).
- **PNG** decoded with Pillow (already a WeasyPrint dependency), defensively:
  `Image.open(fp, formats=("PNG",))` (no other decoder is ever tried);
  `Image.MAX_IMAGE_PIXELS` set to 2048 × 2048 and, inside `warnings.catch_warnings()`,
  `simplefilter("error", Image.DecompressionBombWarning)` (Pillow otherwise only
  *warns* up to twice the limit); `img.size` checked against the limits (at most 2048 ×
  2048 pixels, favicons 512 × 512) **before** `img.load()`; any Pillow error → 422
  `invalid_image`. **Re-encoded as PNG** (strips metadata such as EXIF location and
  text chunks, defeats polyglot files). Stored `content_type` `image/png` with its width
  and height.
- **SVG** (tests first; ADR 0012), checked against an **allow-list**, never "cleaned":
  - **Parser:** the standard library's expat (`xml.parsers.expat`, no new dependency)
    with handlers that refuse — 422 — any `<!DOCTYPE` (`StartDoctypeDeclHandler`),
    entity declaration, processing instruction (`<?xml-stylesheet …?>` included; the
    XML declaration itself is fine) and external entity reference; namespaces on
    (`namespace_separator`). Not `xml.etree`, which silently expands internal entities
    and whose C parser has no DOCTYPE hook. Comments are dropped.
  - **Size, checked while parsing:** at most **2,000 elements** and nesting depth
    **32** (stop at the first one over: 100,000 nested `<g>` would otherwise crash
    re-serialisation with `RecursionError`, a 500).
  - **Elements:** `svg, g, defs, title, desc, path, rect, circle, ellipse, line,
    polyline, polygon, linearGradient, radialGradient, stop, clipPath, mask, text,
    tspan`, in the SVG namespace only. **No `use` or `symbol`** (a 1.1 KB file of
    nested `use` took 23.5 s to render at 10⁵ copies in the review), no `pattern`,
    `marker`, `filter`, `image`, `a`, `script`, `style`, `foreignObject`, `animate*`,
    `set` or other namespaces.
  - **Attributes:** presentation attributes only (`fill, stroke, stroke-*, opacity,
    fill-opacity, fill-rule, clip-rule, clip-path, mask, transform, d, points, x, y,
    x1, y1, x2, y2, cx, cy, r, rx, ry, fx, fy, width, height, viewBox,
    preserveAspectRatio, offset, stop-color, stop-opacity, gradientUnits,
    gradientTransform, spreadMethod, clipPathUnits, maskUnits, maskContentUnits,
    font-family, font-size, font-weight, font-style, text-anchor, dominant-baseline,
    letter-spacing, id, class, version, xml:space`, …as the backend's list pins).
    **No `href` or `xlink:href` at all** (nothing left that needs one; namespace
    declarations such as `xmlns:xlink` are fine), no `style` attribute, no event
    handlers (`on*`), no attribute in another namespace.
  - **References:** the only `url(…)` allowed is `url(#id)` naming an element of the
    same document, in `fill`, `stroke`, `clip-path` and `mask`. **No chains:** nothing
    inside a `clipPath`, `mask` or gradient may carry a `url(…)` (in the review, a
    2.6 KB chain of 16 masks, each using the previous one twice, took 39.5 s to
    render; clip paths 17.8 s). **A budget:** counting each `url(#id)` reference as a
    copy of the element it names (that element and everything inside it), the drawing
    has at most **10,000** elements (one mask of 1,000 shapes used by 1,000 shapes took
    72.6 s; 100 × 100 takes under a second).
  - Anything outside these rules → 422 `invalid_image` naming the element, attribute
    or limit. The stored bytes are the **re-serialised** tree (UTF-8, the SVG namespace
    as the default namespace: `<svg xmlns="http://www.w3.org/2000/svg" …>`, never
    `ns0:` prefixes, e.g. `ElementTree.register_namespace("", SVG_NS)` or a small
    serialiser of the checked tree), `content_type` `image/svg+xml`, width and height
    from the root's numeric `width`/`height` or `viewBox` (else null).
- **Serving** (`get_brand_asset`, public): the stored bytes with the stored
  `Content-Type` only, `X-Content-Type-Options: nosniff`, `Content-Disposition: inline;
  filename="<kind>.<png|svg>"`, `Content-Security-Policy: default-src 'none'; style-src
  'unsafe-inline'; sandbox` (so an SVG opened directly can never run script, defence in
  depth behind the allow-list), `Cache-Control: public, max-age=31536000, immutable`,
  `ETag: "<sha256>"` (304 on `If-None-Match`). Ids are random UUIDs; images of private
  projects are served by id like any other (they are meant to be shown publicly).
- **Using an image:** `BrandingUpdate.logo_asset_id` / `favicon_asset_id` must name an
  asset of that `kind` uploaded for the **same profile** (global ones for the global
  profile, the project's for its override) → else 422 **`invalid_asset`**. If the
  cleanup deletes the asset between that check and the save (the foreign key fails),
  the answer is the same 422 `invalid_asset`, never a 500.
- **Showing an image:** the SPA shows logos and favicons only through `<img src>` and
  `<link rel="icon">`, never inline (`dangerouslySetInnerHTML`, `<object>`, `<embed>`
  or `<iframe>`), so even an SVG that slipped past the allow-list can't run script in
  the app's origin; emails carry no images.
- **No delete endpoint:** removing a logo is saving the profile with `null`; images no
  profile references are deleted by the hourly cleanup **24 hours** after upload (the
  old URL keeps working meanwhile, for caches and open pages). Deleting a project
  deletes its images.

### 3.12 Settings

Configured by environment / Helm values only (the chart's names; platform adds them):

| Variable | Default | Notes |
|---|---|---|
| `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` | `true` | Chart `features.publicSubmission`. `false`: every public route 404s, `PublicFormSettings.available` is false and turning a form on is 409 `public_submission_unavailable`; existing tracking links 404 too. |
| `SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP` | `10` | Per client address (IPv6 /64) per hour, across projects, per API process. 1–1,000. |
| `SOUNDINGS_PUBLIC_SUBMISSIONS_PER_PROJECT` | `100` | Per project per hour, from everyone, counted in the database. 1–10,000. |
| `SOUNDINGS_ALTCHA_COST` | `5000` | PBKDF2/SHA-256 iterations per attempt (random mode, ~250 attempts on average). 1,000–1,000,000. Tune with Playwright on a phone-class CPU (research R1 §7). |
| `SOUNDINGS_ALTCHA_EXPIRY` | `PT30M` | ISO 8601 duration, 1 minute to 1 day. |
| `SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES` | `524288` | 16 KiB to 900 KiB. |

Derived, not configurable: the ALTCHA HMAC key, the confirmation-link key and the
tracking-token sealing key (HKDF from `SOUNDINGS_SECRET_KEY`, one purpose each). The
export limits, throttles, caps and retention periods in this document are constants.

### 3.13 Cleanup (hourly, with Phase 3's)

Added to the hourly cleanup (`notification_schedule`'s end, or a sibling periodic task;
idempotent, indexed, batched):

1. delete `altcha_used_challenges` past `expires_at`;
2. delete ideas held for `email_verification` created more than 3 days ago
   (`ix_ideas_created_at_email_verification`);
3. forget unconfirmed addresses older than 3 days (§3.9;
   `ix_public_submissions_created_at_unconfirmed`);
4. erase contact details of closed ideas idle for 180 days (§3.9);
5. delete `brand_assets` older than 24 hours that no profile references.

### 3.14 Audit, and the integration step

New `AuditAction` values, **agreed but not yet in the schema** (a new value breaks the
SPA's typecheck until its phrase exists: `audit-phrases.test.ts`, as in Phase 3); the
lead lands them in one integration step with frontend's phrases and backend's
`audit.record` calls:

| Action | Target | Details (never personal data) |
|---|---|---|
| `submission.approve` | idea | `rule: idea.moderate` |
| `submission.reject` | idea (deleted afterwards: the entry keeps the id and `details.key`) | `rule`, `key` |
| `submission.erase` | idea | `rule: public.erase_submitter`, or no actor with `reason: "submitter"` (the tracking page) or `"retention"` (the cleanup) |
| `branding.update` | none (global) | `rule: platform.edit_branding`, `fields` (names) |

Project branding and public-form changes use the existing `project.update` with
`details.fields` (`branding`, `public_submission_enabled`, …). Creating a proposal's
status move is `idea.status_change`. Exports, tracking and confirmations are not
audited.

The same integration step adds two `IdeaDetail` fields (a new required field breaks
the SPA's mocks until they set it): `held_for: HoldReason | null` (always null except
for admins viewing an idea held for moderation) and `via_public_form: bool` (a
`public_submissions` row exists), so the idea page needs no `get_idea_submission`
call for internal ideas (§3.6).

### 3.15 Minimum tests (tests first)

- **Public form anti-abuse:** a `POST`/`PUT` under `/public/` with no `Content-Type`,
  `text/plain` or a form type → 415 and nothing happens; honeypot (any value, 5,000
  characters included) → 201 lookalike, nothing stored but the ALTCHA replay row, no
  email, the attempt counted; a filled honeypot with a bad ALTCHA payload → 422
  `challenge_failed`, without the required address → 422 `email_required`, on a
  saturated project → 429 (exactly as a real submission); the 11th submission from one
  IP in an hour → 429 with `Retry-After`, another IP fine, a spoofed `X-Forwarded-For`
  from an untrusted peer doesn't change the key; per-project limit across "replicas"
  (two app instances, one database); ALTCHA: valid → 201, the same payload again → 422,
  expired → 422, wrong key / tampered parameters / malformed → 422, a solution for
  another challenge → 422, a challenge fetched for another project's form → 422; email
  required → 422 without an address; `wants_updates` without email → 422; with email
  off, an address and `wants_updates=true` are both dropped (201, nothing stored, no
  500); the per-address limit counts `jo@x`, `Jo+1@x` and resends together → the 4th
  is accepted without an email and `email_sent` still true; form off / archived /
  unknown / reserved slug / instance switch off → identical 404s.
- **Holds everywhere:** with one idea held for moderation and one for verification,
  every list and count (board columns, list `total`, search and ⌘K, My work, owned
  ideas, tags and their counts, `Project.idea_count`, the inbox and its count, the admin
  outbox's idea references) omits both for a member, a viewer, an internal non-member,
  a project admin and a platform admin; `get_idea` 404 for non-admins and 200 for admins
  (moderation, every permission flag false but `can_delete`) / 404 for all
  (verification); idea writes on a moderation-held idea → 409 `awaiting_moderation` for
  admins; approve → visible, at the top by activity; reject → gone, tracking 404; no
  notification anywhere about a held idea; confirm → moves to moderation or visible;
  confirming still works after the project's form is turned off.
- **Tracking secrecy:** responses carry nothing private (assert the absence of owner,
  evaluator, comment, score, tag, key and other submissions' fields); after the team
  edits the idea's title, summary and description, the tracking page and status emails
  still show what was submitted; unknown and erased tokens give the same 404; tokens are
  stored only hashed and sealed (no column holds the token); logs captured during the
  flow contain no token, address or name; no public route takes a token in its path or
  query (contract test).
- **Confirmation email:** its subject and body contain none of the submitted title,
  summary, description or name (a submission whose title is a spam line produces the
  fixed text only); it has the confirmation and tracking links.
- **Erasure and retention:** erase (admin and the submitter's own) clears exactly the
  listed columns, deletes the idea's outbox rows (queued and sent), keeps the idea,
  ends the link, is idempotent for the admin (the submitter's second call is 404) and
  audited without personal data; a submitter email can't be queued without `idea_id`
  (database); the cleanup's three retention rules with a moved clock.
- **Proposals:** the role matrix rows E for every column and overlay (owner demoted to
  viewer can't write); c7 on create and save; create moves Shortlisted → Proposal with a
  status event, notification and submitter email; `proposal_exists`; concurrency: two
  saves from version 3 → one 200, one 409 whose `current` is the winner's section;
  identical retry → 200 without a bump; different sections never conflict (concurrent
  saves both succeed); a status change racing a save leaves c7 consistent; section text
  with leading indentation and trailing blank lines is stored and returned verbatim;
  archived project → 409; thread caps; delete own / other's (403 `not_author`) / admin;
  a reply reopens a resolved thread.
- **Exports:** Markdown and PDF for a pending evaluator contain no score, for others the
  aggregate line; a proposal containing raw HTML (`<script>`, `<img src=http://…>`,
  `<iframe>`, `<link>`, `<style>`), Markdown images and links to
  `http://169.254.169.254/`, `file:///etc/passwd` and `javascript:` makes **no network
  or file access** (a fetcher that fails the test if called with anything but `data:`
  or `soundings-font:`; `URLFetcher.fetch` patched to fail) and renders HTML as nothing
  and images as links, like the SPA; setext headings and `#` lines in code fences are
  demoted or left alone correctly in both formats; branding colours and fonts in the
  PDF stylesheet come only from validated values; a proposal with more than 2,000 table
  cells renders the excess as source; a render that outlives 20 s (a patched slow
  renderer) is killed → 503 `export_busy`, and the next export works; the event loop
  stays responsive during a render; the 11th export in a minute → 429.
- **Branding and images:** non-hex colours, unknown fonts, multi-line app names, long or
  6-line footers → 422 (schemas); a PNG with EXIF comes back without it; a 4096 × 4096
  PNG, a decompression bomb (between 1× and 2× `MAX_IMAGE_PIXELS` too), a truncated
  file, an HTML file named `.png`, a GIF, JPEG, WebP or ICO → 422; SVGs with
  `<script>`, `onload=`, `<foreignObject>`, `<image href="http://…">`,
  `xlink:href="javascript:…"`, any `href`, `<use>`, `<symbol>`,
  `style="background:url(http://…)"`, `<?xml-stylesheet?>`, `<!DOCTYPE>` / entities
  (billion laughs, and an internal entity with no expansion), 2,001 elements, 33 levels
  of `<g>`, a mask or clip-path chain, a reference fan-out over 10,000 → 422 (each
  rejected quickly: no render or recursion); a clean SVG (a Figma-style export with
  `clipPath`, gradients and `xmlns:xlink`) round-trips with a default-namespace root;
  served headers exactly as §3.11 (nosniff, CSP sandbox, immutable cache, ETag, 304);
  an asset of another profile or kind → 422 `invalid_asset`, also when the cleanup
  deletes it mid-save; unreferenced assets are deleted after 24 hours, referenced ones
  never.

### 3.16 Acceptance (SPEC Phase 4): anonymous idea → evaluated → shortlisted → exported branded proposal

1. A platform admin sets the global branding (name "Acme Ideas", a primary colour, IBM
   Plex Sans, a PNG logo, a footer); the shell shows them after Save (live preview
   before). The project admin of "Customer Innovation" turns on the public form with
   moderation and gives the project an override colour.
2. Signed out, `/{slug}/submit` shows the project's branding (logo, colour, font) and
   intro; an anonymous visitor sends an idea with an email address and "Email me when the
   status changes"; the ALTCHA solves by itself; the receipt shows the private link.
   Mailpit receives "Confirm your idea for Customer Innovation" (fixed text, no title)
   with the confirmation and tracking links; the visitor opens the confirmation link and
   clicks Confirm.
3. The idea is in no list for anyone; the project admin sees "1 idea waiting for review",
   approves it; it appears in New.
4. The owner edits the idea's summary, invites three evaluators who score it blind
   (Phase 1) and moves it to Shortlisted: the submitter gets "Your idea … is now
   Shortlisted" (Mailpit) and the tracking page shows the new status and its history,
   with the title and summary as they sent them and nothing internal.
5. The owner starts the proposal (the idea moves to Proposal: another email), writes the
   sections; a member comments on Problem; the owner resolves the thread.
6. The owner exports the PDF: the cover has the project's branding (logo or name, colour,
   font), the sections, page numbers and the aggregate score; the Markdown export has
   the same text. A pending evaluator's export has no score.
7. The project admin erases the submitter's details: the tracking link stops working; the
   idea and its proposal stay.

## 4. Error codes

New in Phase 4:

| Status | `code` | When |
|---|---|---|
| 404 | `not_found` | also: the public form isn't available (c8, any reason); an unknown or erased tracking token (c9, also the submitter's second erase); an invalid, expired or spent confirmation token; an idea held for email verification (everyone); a held idea for non-admins (c12); no proposal (section, export, threads); no public submission behind the idea; an unknown image |
| 409 | `proposal_not_available` | proposal write while the idea isn't Shortlisted or in Proposal (c7; existed in the role matrix) |
| 409 | `proposal_exists` | starting a proposal twice |
| 409 | `proposal_conflict` | saving a section from an older version (someone saved it since); a `ProposalConflictProblem` whose `current` is the section as saved now |
| 409 | `too_many_comments` | a 501st thread, or a 201st comment in a thread |
| 409 | `awaiting_moderation` | an idea write (other than delete, approve, reject, erase) on an idea held for moderation (c19) |
| 409 | `not_awaiting_moderation` | approve or reject an idea that isn't held for moderation |
| 409 | `no_email` | turning updates on, or resending the confirmation, without an address on file |
| 409 | `already_verified` | resending the confirmation for a confirmed address |
| 409 | `public_submission_unavailable` | turning the form on while public submission is off for the instance, or for an older project whose slug is reserved |
| 409 | `smtp_not_configured` | also: requiring email verification, or resending a confirmation, while email is off |
| 413 | `content_too_large` | also: an image over `SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES` |
| 415 | `unsupported_media_type` | a `POST` / `PUT` under `/api/v1/public/` without `Content-Type: application/json` |
| 422 | `email_required` | the project requires a confirmed address and none was given |
| 422 | `challenge_failed` | ALTCHA payload invalid, tampered, expired, for another project's form or already used |
| 422 | `invalid_image` | an upload that isn't a PNG or an SVG, is damaged, too large in pixels, or an SVG outside the allow-list or its limits |
| 422 | `invalid_asset` | a branding image id of another profile, another kind, unknown, or deleted by the cleanup during the save |
| 429 | `too_many_attempts` | also: per-IP and per-project submission limits, public throttles, resend limit, export limit, upload quota; with `Retry-After` |
| 503 | `export_busy` | the PDF renderer stayed busy for 30 s, or a render hit its 20 s limit and was killed; with `Retry-After` |

## 5. Decisions

Simpler option chosen each time; the lead may revisit (also logged in
[decisions.md](../decisions.md#2026-10-01--phase-4-contract)).

| Decision | Why |
|---|---|
| A proposal is one Markdown text per fixed section, each with its own version; a save names its base version and conflicts are 409 per section. | SPEC's fixed template; autosave per section; two writers on different sections never collide; nobody overwrites anybody silently (wireframe 05's Reload / Keep mine). |
| No proposal status: starting a proposal moves a Shortlisted idea to Proposal, and the idea's status decides whether it is editable (c7). | One lifecycle, not two; the board shows where the work is. |
| Margin threads anchor to a section, replies are flat, threads resolve and reopen, comments can't be edited, and there are no notifications or @mentions for them in Phase 4. | Wireframe 05; no new `NotificationType` (breaks the SPA's exhaustive maps); simple beats configurable. |
| Exports are two `GET`s (Markdown, PDF) with the aggregate line only for those who may see scores; PDFs use the project's effective branding and a local-only fetcher. | Role matrix E; SSRF and local-file reads are impossible by construction; downloads work as plain links. |
| PDFs render in a child process killed after 20 s, tables beyond 2,000 cells print as source, and Markdown renders as the SPA renders it (raw HTML dropped, images as links). | A hostile or huge proposal can't stall exports or the event loop (measured in the review); the editor's preview is what the PDF shows. |
| Public ideas are ordinary ideas (`submitted_by_id` null) plus a `public_submissions` row; no IP address is stored. | One idea model everywhere; minimal personal data (UK GDPR); in-memory rate limits need no address at rest. |
| `ideas.held_for` (`email_verification` / `moderation`): held ideas are listed nowhere, for anyone; admins use the moderation queue. Writes on a held idea are 409 until approved (c19). | Linear-style triage: no unreviewed spam on boards or in search; no notifications to people who can't see the idea; one rule per surface instead of per-role list logic. |
| Reject deletes the idea. | Moderation is for spam and abuse; deleting keeps no personal data; genuine but unwanted ideas are approved and closed as Rejected. |
| Email verification exists in every project with email: confirming gates status emails; the project setting additionally holds the idea until confirmed (deleted after 3 days otherwise). The confirmation email is fixed text (nothing the submitter typed), at most 3 a day per address with `+tags` folded, and the limit is silent. | The form can't be used to send strangers anything but a short "confirm your idea" note; the setting is the anti-abuse knob SPEC asks for. |
| The honeypot is checked last, accepts any value, and is described neutrally; public writes must be `application/json`. | A filled honeypot gets exactly a real submission's answers; autofill can't trip it; other sites can't post through visitors' browsers. |
| The tracking page and status emails show the title and summary as submitted (a copy erased with the details), and the submitter can erase their details themselves from the tracking page. | Nothing the team writes ever reaches the public; UK GDPR erasure without contacting anyone. |
| Tokens never in server-visible URLs (`#` fragments, POST bodies); tracking tokens hashed and sealed; confirmation tokens signed, not stored. | Ingress logs, traces and `Referer` can't leak them; a database leak alone reveals none; no token table. |
| ALTCHA HMAC key derived from the secret key; replay protection in `altcha_used_challenges` until expiry. | Nothing extra to configure or rotate; the library has no replay protection (research R1 §7). |
| Public settings and branding have their own endpoints instead of new `Project` fields; audit actions land at integration. | Additive contract: Phase 1–3 mocks and tests keep compiling. |
| Branding: global for the signed-in app, project overrides only where the project faces outward (public pages, submitter emails, PDFs). | One consistent product for staff; projects still present themselves to the public in their own colours. |
| Colours hex only, fonts from a bundled enum, footer plain text; no free-form CSS, font names or HTML anywhere in branding. | CSS injection is impossible by type; the database checks the same. |
| Images: PNG or SVG raw-body uploads, PNG re-encoded with Pillow, SVG parsed with expat (no DTD), allow-listed (no `use`, no reference chains, element and reference budgets) and re-serialised, served with nosniff and a sandboxing CSP, immutable by id; no delete endpoint (unreferenced images expire). | No new dependency (Pillow comes with WeasyPrint, expat is standard library, no multipart parser); no metadata, polyglots, ICO/WebP decoders or rendering bombs; SVG XSS blocked twice; cache-busting for free. |
| Reserved slugs for new projects; an older project with one can't turn its form on. | `/{slug}/submit` (SPEC) shares the URL space with the app's own pages. |
| The runtime image moves to Ubuntu 24.04 with its Python 3.12 (ADR 0011). | WeasyPrint needs Pango/HarfBuzz; Debian's mirrors are blocked here, Ubuntu's archive isn't. |

## 6. Room for later phases

- **Phase 5 (API keys, MCP):** `get_proposal` (MCP `get_proposal`) and exports accept
  read keys like other reads; `propose_proposal_section` is `proposal.suggest_section`
  (Phase 6 UI). Public routes stay keyless; moderation and erasure stay session-only
  for erase. MCP `search_ideas` and every other MCP list use `listed_ideas`, and MCP
  `get_idea` goes through c12 like `get_idea` (held ideas never reach an agent; an
  agent's service account is never a project admin by default).
- **Phase 6 (kagent):** "Draft section" (`ai.draft_section`) and member suggestions
  (`proposal.suggest_section`) propose text for a section the owner accepts (saved with
  the section's version like any edit) or discards.
- **Phase 7 / later, if needed:** notifications for margin comments and @mentions in
  them (a new `NotificationType` landed with the SPA's maps); proposal version history;
  a "new public idea waiting" notification for project admins; an email change or
  add-an-address flow on the tracking page; per-project form fields; CJK fonts for PDFs;
  a bulk "reject all waiting" for floods (until then: turn the form off, then reject);
  a configurable privacy-policy link on the public form.

## 7. Changes after the contract

Builders record additive contract changes here (date, change, why), then run
`make gen-api`.

### 2026-10-01 · Contract review applied (before building)

The security and contract review's findings, applied before any builder started
(not additive-only: nothing was built on the replaced parts).

| Finding | Change |
|---|---|
| Confirmation email usable for spam | `submission_received` is fixed text ("Confirm your idea for <project>"), no title or name; the per-address limit counts `outbound_email` (first sends and resends) by `SUBMITTER_ADDRESS_KEY_SQL` (lower-case, `+tag` removed) on the new `ix_outbound_email_submission_address`; `ix_public_submissions_email_lower_created_at` is gone (§3.5, §3.8). |
| SVG rendering bombs, DOCTYPE, recursion, `ns0:` | Upload rules rewritten (§3.11, ADR 0012): expat with DOCTYPE / entity / PI handlers that refuse, 2,000 elements, depth 32, no `use` / `symbol` / `href`, no `url()` inside `clipPath` / `mask` / gradients, a 10,000-element reference budget (mask and clip-path chains and fan-outs measured at 18–73 s), default-namespace serialisation. |
| PDF rendering unbounded | Child process killed after 20 s → 503 `export_busy`; ≤ 2,000 table cells / 200 rows per table as tables; `maxNesting` 20; measured timings (§3.4, ADR 0011). |
| Section text lost whitespace | `ProposalSectionUpdate.body_md` is `SectionText` (`strip_whitespace=False`) (§3.2). |
| 500 on submit with email off | With `asks_for_email` false, `email` and `wants_updates` are both dropped (§3.5). |
| Honeypot gave itself away | Checked last (after email required, ALTCHA with its replay row, the per-project limit); `website` any length, neutral description; DOM name guidance (§3.5). |
| Cross-site submits | Public `POST`/`PUT` need `application/json`, else 415 `unsupported_media_type` (§1). |
| Tracking showed current text | `public_submissions.submitted_title` / `submitted_summary` (erased with the details, `ck_public_submissions_submitted_copy_until_erased`); `TrackedSubmission.description_md` removed; title and summary are as submitted, also in `EmailVerified` and status emails (§3.7). |
| Confirmation needed the form on | `verify_submission_email` is `public.track` (c9: token + instance switch); `/verify` posts on a Confirm click only (§3.7). |
| Erasure could miss emails | `ck_outbound_email_idea_iff_submission_type` replaces `…_idea_only_for_submission_types`: submitter emails must name their idea; `NewEmail.idea_id`; Phase 3's plumbing test passes one; 0007 deletes submitter emails queued before it (§3.8). |
| Idea page while held | Every `IdeaPermissions` flag but `can_delete` false; `IdeaDetail.held_for` / `via_public_form` join the integration step (§3.6, §3.14). |
| Raster uploads | PNG only (`formats=("PNG",)`), bomb warning as error, size before `load()`; ICO and WebP dropped (§3.11). |
| Section save locking and conflict race | Idea `FOR SHARE` after the project's `FOR KEY SHARE`; 409 `proposal_conflict` is a `ProposalConflictProblem` with `current` (§3.2). |
| UK GDPR gaps | `POST /public/track/erase` (`erase_tracked_submission`, c9, 204, audited with `reason: "submitter"`); a fixed privacy notice on the form (§3.5, §3.7, §3.9). |
| Reserved slugs only on create | c8 and `PublicFormSettings.available` exclude reserved slugs; enabling → 409 `public_submission_unavailable` (§2, §3.5). |
| Font fetching | `soundings-font:<font>-<weight>` from a fixed map; `data:` decoded by the fetcher; never `URLFetcher.fetch` (§3.4, §3.10). |
| [consider] taken | ALTCHA challenge bound to the form (`AltchaParameters.data`); `email_sent` no longer reveals the limit; no `history.replaceState` on `/track`; rate-limit WARNING once per key and hour; Markdown aligned with the SPA (HTML dropped, images as links) and headings demoted through the parser; asset FK race → 422 `invalid_asset`; admin outbox ignores held ideas; MCP lists use `listed_ideas` (Phase 5); ICO and WebP cut; resends counted in the per-address limit. |
| [consider] declined | Idea numbers on approval (keys would be null while held, breaking `IdeaRef`; gaps show only to members); submitter name for members only (it is shown like `submitted_by` of internal ideas, which viewers see too); a branding `updated_at` precondition (one admin page, rarely edited; project settings are last-write-wins too); cutting the 20-a-day upload quota (it bounds what one admin account can store); cutting resend (a lost email would otherwise doom an idea held for confirmation); bulk reject (§6, later). |

### 2026-10-01 · Identity: public submission and held ideas (build)

| Change | Why |
|---|---|
| `IdeaDetail.held_for` (`HoldReason \| null`) and `IdeaDetail.via_public_form` (`bool`), both required | The §3.14 integration fields (assigned to identity). `held_for` is `moderation` only for admins opening an idea held for review; `via_public_form` is true when a `public_submissions` row exists. |
| `AuditAction` gains `submission.approve`, `submission.reject`, `submission.erase` and `branding.update` | The §3.14 values, landed together so the SPA's phrases change once. Erasure (admin, submitter, retention) records `submission.erase`. |
| No schema change: `viewable_ideas` is now the same filter as the new `listed_ideas` (both leave out every held idea, for everyone) | Every existing caller of `viewable_ideas` is a list, board, search, count, My work query or the inbox, so they all follow §3.6 without edits. c12 for a single idea (the idea page, its sub-resources, `get_idea_submission`) is in the policy (`load_idea` → `idea.view`), which lets PA and PAd open an idea held for moderation; the moderation queue filters `held_for = 'moderation'` itself. |
| No schema change: c19 is the policy's `FROZEN_WHILE_HELD` (every idea write but `idea.delete`, `idea.moderate` and `public.erase_submitter`, plus `idea.watch`), checked after `project_archived` and before the rule's own 409s | §3.6. Permission flags follow from the same policy, so an admin sees only `can_delete` on a held idea. |
| No schema change: the tracking and confirmation routes count their per-IP throttle (60/min) **before** the token lookup | It bounds load from unknown tokens, which a check after the 404 wouldn't. The form's own per-IP limit stays after c8 (§3.5 step 3). |

### 2026-10-02 · Integration (no schema change)

| Change | Why |
|---|---|
| Font URLs are `soundings-font:<font>-<weight>[-italic][-ext]` (`inter-600`, `inter-400-italic`, `inter-600-ext`), and the `latin-ext` subset is a CSS family of its own; 400 italics and IBM Plex Mono (code) are bundled too | Proposals backend: two subsets under one family name garbled text extraction from the PDF; italics and code need their own faces. Still a fixed name → file map (`app/proposals/fonts.py`). |
| One branding resolver: `app.services.branding` (`effective_branding`, `logo_image`, `email_branding_for`, cached 5 s per process) serves the public pages, `GET /branding`, emails and PDFs; identity's `app/public/branding.py` is removed | Two implementations had grown up in parallel; the public pages now use the cached one (§3.10). |
| The PDF cover's band carries no text (it named the project a third time); tables print at the body size | QA's PDF review. The band is still the primary colour (§3.4: "a band or rule in the primary colour"). |
| Each PDF child process gets its own temporary folder, deleted when the child is stopped or killed | Platform: a killed render left WeasyPrint's font folder (about 700 KB) in `/tmp`; repeated slow exports could fill the pod's `/tmp`. |

### 2026-10-02 · Security review fixes: backend, identity, platform

| Change | Why |
|---|---|
| `get_public_project` documents 429 (additive); the form, challenge and submission routes share a per-IP throttle (`PUBLIC_FORM_THROTTLE`, 120/min) counted **before** the form is looked up; the submission's documented check order gains that step | Review L3: open forms (and private projects' names) could be enumerated at full speed through all three routes, unknown slugs included. `make gen-api` run. |
| The per-address limit on confirmation emails (3 per 24 h) counts the new `confirmation_email_sends` (`address_key` = HMAC-SHA256 of the canonical address, key derived from the secret key; pruned after 24 h by the hourly cleanup), not `outbound_email`; `ix_outbound_email_submission_address` and `SUBMITTER_ADDRESS_KEY_SQL` are gone (migration 0008) | Review M1: erasure, rejection and the retention rules delete outbox rows, so submit → erase reset the count (5 emails to one address in a minute). |
| The canonical address also folds Gmail's dots (`googlemail.com` = `gmail.com`) and Yahoo's `base-keyword` addresses (`yahoo.com`, `ymail.com`, `rocketmail.com`), besides case and `+tag` | Review L1. Over-folding only makes two addresses share a limit. |
| `submission_received` no longer carries the tracking link (§3.8) | Review L2: anyone can put any address in the form; the recipient landed on our domain, in our branding, reading what a stranger typed. The receipt page gives the submitter the link. `EmailVerified.title` stays in the schema (no removal), but the `/verify` page shouldn't show it. |
| PDF export (§3.4): at most `MAX_BOXES` (5,000) boxes per document (`app/proposals/markdown.py` `box_cost`: blocks, list items and links 2, inline elements, hard breaks 2, code lines); a section that goes over is cut there and ends with "The rest of this section is too long for a PDF. Export Markdown for the full text."; a zero-width space after every 32 characters of a run without a break opportunity; text over 1,000 characters prints in `<span>` pieces; sections use `overflow-wrap: normal` | Review H1: ordinary-looking text (5,000 list items, hard breaks, `a*b*` runs, one long word, narrow characters) took 9-25 s and up to 250 MB per section, so every export of it was a 503 and the child could be OOM-killed. The worst mixed document now takes about 6 s and 160 MB on one CPU. |
| The PDF child limits its own `RLIMIT_DATA` to half the container's memory limit (cgroup v2 `memory.max` or v1, at most 1 GiB) and drops every environment variable but locale, fontconfig, `HOME`, `PATH`, `TMPDIR` and `PYTHON*` basics; the chart's default `api.resources.limits.memory` is 1Gi | Review H1 (a runaway render fails with a 500 instead of the pod being OOM-killed) and N4 (no database URL, secret key or OIDC secret in the renderer). |
