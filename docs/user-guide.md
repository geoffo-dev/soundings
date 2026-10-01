# Soundings user guide

> Each section is filled in by the phase that ships the feature (noted in brackets). Keep
> it short and task-based: SPEC section 1 says every feature should be usable without
> reading docs, so this guide is for the "why" and the edge cases.

## Getting started [Phase 1–2]

### Signing in

Choose **Sign in with SSO**. You sign in on your organisation's page (Keycloak,
Microsoft Entra ID, Google…) and come straight back to the page you were opening.
Soundings never sees your password; your browser only holds a session cookie.

The first time, Soundings finds your account in this order and links it to your
organisation sign-in for good: an employee number (or similar ID) an administrator
entered for you, then your email address if your organisation has verified it, then,
only where the instance allows it, a new account with no access of its own. If none of
that works you see "You don't have a Soundings account yet": ask an administrator to
add you, then sign in again.

What you can see comes from your project roles: the ones given to you directly and the
ones your **groups** grant. Groups that come from your organisation's directory are
refreshed **each time you sign in**, so after a change there (a new team, say), sign
out and in again to pick it up.

| The sign-in page says | What to do |
|---|---|
| "That sign-in took too long or was already used" | Start again; the link from the sign-in page is single-use and lasts 10 minutes. |
| "Sign-in was cancelled" | You declined at your organisation's page; sign in again when ready. |
| "Single sign-on isn't available right now" / "We couldn't verify your sign-in" | Try again in a few minutes; if it persists, tell an administrator (the details are in the audit log). |
| "Your account is deactivated" / "…needs an administrator to finish linking it" | Contact an administrator. |
| "Too many sign-in attempts from your network" | Wait a minute. |

A session lasts up to 7 days and ends after 12 hours without activity; then the app
says "Your session has ended" and takes you back to where you were after you sign in.
**Signing out** (account menu, or "Sign out" in the palette) also signs you out of your
organisation's sign-in page, so the next sign-in asks for your password again, and it
clears the drafts this browser kept for you.

Two other ways in exist for administrators: the **break-glass** account (an emergency
platform admin, available only while single sign-on is not configured; a banner stays
on screen while you use it and everything it does is in the audit log), and on
development installs a **development login** that lists everyone ("who are you?").

### Finding your way: My work, projects, the command palette (⌘K)

- **My work** (`G` then `M`, or the logo) is your home page:
  - **Evaluations due**: ideas waiting for your scores, overdue first. The most urgent
    one has the page's only blue button; "Continue" means you have a saved draft.
  - **Ideas I own**, grouped by status (Closed is folded away).
  - **Recently updated in my projects**: the ten ideas with the latest activity.
  The sidebar repeats the counts and shows a red dot when an evaluation is overdue.
- **Projects** are listed in the sidebar. A project page has two views of the same
  ideas: a **Board** (a column per status) and a **List** (sortable columns); `V`
  switches between them and the app remembers your choice. Filters (owner, tag,
  "Needs evaluators", "High disagreement") and the sort live in the page address, so a
  filtered view can be bookmarked or shared. `F` jumps to the search box.
- **⌘K** (Ctrl+K on Windows and Linux) opens the command palette: type an idea key
  (`cust-12`) or words from a title to jump to an idea, a project name to open it, or
  a command ("New idea", "Switch to dark theme", "Sign out"). What is highlighted is
  what Enter opens: results that arrive while you type never move the highlight away
  from something you can already see. On an idea page the palette also offers that
  idea's actions (evaluate, change status, assign owner, invite evaluators…).

### Keyboard shortcuts (`?`)

`?` shows every shortcut. They work anywhere except while you are typing in a field.

| Where | Keys |
|---|---|
| Everywhere | `⌘K` palette · `?` shortcuts · `[` sidebar · `G` `M` My work · `N` new idea · `⌘↵` submit a form or comment |
| Lists (My work, project list, board) | `J` / `K` or `↓` / `↑` move · `Enter` opens · in My work `E` evaluates the focused idea (or the most urgent one) |
| Project page | `V` board/list · `F` search and filter · on the board `←` / `→` move between columns; on a focused card `Space` picks it up, arrows move it, `Space` drops it (`Esc` puts it back) |
| Idea page | `E` evaluate · `S` change status · `A` assign owner · `C` comment · `1` `2` `3` Overview / Evaluations / Proposal |
| Evaluate sheet | `1`–`5` score the focused criterion · `Tab` next criterion · `⌘↵` submit · `Esc` close (your draft is kept) |
| Pickers (owner, evaluators, members, filters) | type to filter · `↑` / `↓` · `Enter` picks the highlighted entry (the best match is highlighted as you type) · in Invite evaluators `⌘↵` sends the invitation |
| Project settings | `⌘S` saves the section you are editing |

On macOS `⌘` is Command; elsewhere it is Ctrl. When a dialog, sheet or menu closes,
focus goes back to where you were, so you can carry on with the keyboard.

### Light and dark mode

The app follows your system setting. To choose, use **Settings → Appearance** (System,
Light or Dark), the account menu (your name at the bottom of the sidebar) or type
"theme" in the palette. The choice is remembered on this device.

### Your settings page

**Settings** in the sidebar shows your account (name and email, from sign-in), the
theme, and links to the settings of every project you manage. Platform admins also see
the sections described in [Platform administration](#platform-administration-phase-2).

## Ideas [Phase 1]

### Submitting an idea (`N`)

Press `N` or "New idea". Only a **title** and a one-line **summary** are required; add a
description (Markdown, with a preview) and tags if you like. In a project the dialog
picks that project for you. If you close the dialog, what you typed is kept in this
browser, for you only, until you submit or sign out. The idea gets a key such as `CUST-12` that never changes, and
you start watching it.

### Statuses: New, Evaluating, Shortlisted, Proposal, Closed

The five statuses are fixed (project admins may rename them). The owner or a project
admin moves an idea to any status: from the status picker (`S`), by dragging its card on
the board, or with the keyboard on a board card. Closing asks for a resolution:
Accepted, Rejected or Parked. A status change has no side effects, so "Undo" in the
toast puts it back exactly.

### Comments, @mentions, votes and watching

- **Comments** use Markdown. `C` jumps to the comment box and `⌘↵` posts. You can edit
  or delete your own comments; a deleted comment can be restored with "Undo" for a few
  seconds. Comments are flat in Phase 1; @mentions come with notifications in Phase 3.
- **Votes** show support (one per person, any status). They don't affect the score.
- **Watching** an idea will send you its updates once notifications arrive (Phase 3).
  You watch ideas you submit, own, evaluate or comment on; the Watch button stops or
  starts it.

### Editing an idea

Click the title or summary to edit it in place (Enter saves, Esc cancels); the pencil
beside Description opens the Markdown editor. The submitter can edit while the idea is New, the owner until it is Closed,
and project admins always. Only admins can delete an idea (after a confirmation; there
is no undo).

## Owning an idea [Phase 1]

### Volunteering ("I'll own this") and being assigned

Every idea has one accountable owner. A project admin assigns one (`A`), or, when the
project allows it, any member can volunteer with "I'll own this" on an unowned idea.
An owner can step down from the owner menu. Owners and evaluators must be project
members with the member or admin role.

### Inviting evaluators and setting a due date

The owner (or an admin) invites evaluators from the Evaluators section of the idea page:
pick several people at once and, optionally, a due date. The first invitation sets a
due date by itself when there is none: 7 days later by default (a project setting).
Change or clear the date at any time while evaluation is open. Removing an evaluator who
hasn't submitted takes effect when the "Undo" toast disappears; nobody can remove
themselves, and submitted evaluations are never removed.

### Moving an idea between statuses

See [Statuses](#statuses-new-evaluating-shortlisted-proposal-closed). Moving to
Evaluating doesn't invite anyone or set a date: invite evaluators when you are ready.
Due dates can be up to five years ahead.

### Closing and reopening evaluation

"Close evaluation" stops further scoring (the page suggests it once everyone has
submitted); "Reopen" undoes it. Closing does **not** reveal scores to evaluators who
never submitted. Closing the idea itself also ends evaluation.

## Evaluating [Phase 1]

### The evaluate sheet (`E`): criteria, scores, recommendation

"Evaluate" (or `E`, or the button in My work) opens a sheet beside the idea, so you can
read while you score. Score each criterion from 1 to 5; the hint under the scale says
what the score you're on means for this project. Criteria marked "lower is better"
(such as Effort or Risk) count against the idea when they score high. Add an optional
comment per criterion and choose a recommendation: Go, Maybe or No. Your draft saves as
you go (and when you close the sheet); only you can see it. "Submit" needs every
criterion scored and a recommendation, and points you to anything missing. On a phone
the sheet fills the screen and the scores are easy to tap.

### Why you can't see other scores yet (blind evaluation)

Until you submit, you can't see anyone's scores for that idea, anywhere: the idea page,
lists, the board, sorting and filters, search or email. You do see how many people have
submitted. This keeps first opinions independent. It applies to everyone, including
project admins and the owner when they are evaluators, and closing evaluation doesn't
lift it. The moment you submit, the sheet shows how your scores compare with everyone
else's.

### Editing your evaluation

After submitting, "Edit my evaluation" lets you change your scores until evaluation
closes; the change is marked "Edited after submission" for everyone to see.

### Reading the aggregate score and the "high disagreement" flag

The score (for example **3.7 / 5 · 3 evaluations**) is a weighted average of the
criteria: each criterion's average across the submitted evaluations, weighted as the
project's rubric says (inverted criteria turned round first), rounded to one decimal.
The per-criterion bars show each average and the range of scores (hover a range mark
for the lowest and highest). **High disagreement** means that on some criterion two
evaluators are 2 or more points apart: worth a conversation before deciding. The
Evaluations tab (`2`) shows every score side by side in one table, with each
evaluator's recommendation, and their comments below it.
In a project, sort by "Highest score" to rank ideas; ideas without a score (or whose
score is hidden from you) come last.

## Proposals [Phase 4]

### Writing a proposal from the template
### Comments in the margin
### Exporting to PDF or Markdown

## Public submission and tracking links [Phase 4]

## Notifications and email preferences [Phase 3]

### Immediate, daily digest or off
### Unsubscribing

## API keys and MCP [Phase 5]

### Creating and revoking a personal API key
### Connecting an MCP client

## AI assistance [Phase 6]

### "Ask AI to evaluate" and the AI badge
### "Research this" and "Draft section"

## For project admins [Phase 1–4]

Project settings are behind the gear icon on the project page (or Settings → Projects
you manage). Members see them read-only. Each section saves on its own (`⌘S`); if you
try to leave with unsaved changes, the app asks first.

### Members and groups

Members settings has three lists.

- **People**: add someone by name or email and give them a role: **viewer** (reads and
  votes), **member** (also submits, comments, owns and evaluates) or **admin** (also
  manages the project).
- **Groups**: switch the add form to *Group* to give a whole group a role. Everyone in
  the group has it for as long as they are in the group; when single sign-on maps the
  group to your organisation's directory, that follows the directory (see
  [Groups](#groups-and-identity-provider-mappings)).
- **Everyone with access**: each person's effective role and why, for example
  "via Tools members" or "Direct (viewer) · via Innovation admins". When someone has a
  role directly and through groups, the highest one counts.

Role changes and removals offer "Undo" for a few seconds. Every project keeps at least
one admin, counting admins through groups; the app explains when a change would leave
none. Removing someone keeps their owner and evaluator assignments, but they grant
nothing without a member role. Only platform admins create projects; the creator
becomes its first admin.

### Editing the rubric

A rubric has 3 to 6 criteria, each with a weight (relative: 2 counts twice as much as
1), an optional "inverted" switch for criteria where a high score is bad, and optional
guidance for each score. Saving recalculates every idea's score in the project;
submitted evaluations stay submitted, and a new criterion is scored the next time
someone edits their evaluation.

### Renaming status labels

Rename any status or resolution (for example "Shortlisted" → "Next up"); the board,
lists and filters use the new names at once. The reset button next to a name restores
the default.

### Project settings and branding

General settings: name, description, visibility (private: members only; internal:
everyone who can sign in can read it), whether members may volunteer to own ideas, and
the evaluation window in days. **Archive** makes a project read-only and hides it from
lists, search and My work; restore it from the archived notice or the settings. Branding
comes in Phase 4.

### Moderating public submissions and erasing submitter details

## Platform administration [Phase 2]

Platform admins get four more sections in **Settings** (also in the palette: "Users",
"Groups", "Sign-in (SSO)", "Audit log"). Everyone else sees a plain "Page not found" at
those addresses.

### Users

Search by name or email and filter by status, platform admins or "Not signed in yet".
**Add user** pre-creates someone before their first sign-in: email, name, and ideally an
**external ID** (for example their `employee_no`), which links their organisation
sign-in more safely than email. Give platform admin rights sparingly.

Opening a user shows their profile, their project access and where it comes from
(direct or via a group), their groups (Manual or Synced), their linked sign-in accounts
and external IDs, and a link to the audit log about them. From there you can:

- **Unlink** a sign-in account, so the next sign-in matches the account again (it also
  ends their single sign-on sessions);
- **Sign out everywhere**;
- **Deactivate** (or reactivate): they can't sign in, their sessions end at once, and
  they count nowhere. **This is how you offboard someone**: removing them from your
  organisation's directory alone leaves a running session and their memberships until
  they next sign in.

You can't deactivate yourself or remove your own platform admin rights, and the
instance always keeps one active platform admin besides break-glass.

### Groups and identity provider mappings

A group is a set of people that projects can give a role to. People join a group in
two ways, and the member list badges each one:

- **Manual**: an admin added them (Add member on the group's page). Sign-in never
  touches a manual membership.
- **Synced**: the group is mapped to one or more **identity provider groups** (such as
  `/innovation/members` from Keycloak, or a group's object id from Entra ID), and the
  person's sign-in said they are in one. Values are matched without leading or trailing
  slashes and ignoring case; the editor shows how each value is saved.

Each mapping has a **sync** mode:

- **Managed** (the default): the synced membership follows the identity provider at
  every sign-in, joining and leaving. Use it for groups that grant access.
- **Additive**: sign-in only adds. People stay until an admin removes them ("Remove
  until next sign-in" on a synced member). Use it for broad groups where losing access
  by surprise would hurt more than lingering in the group.

Changes to a mapping apply to each person at their **next sign-in**. To cut someone's
access now, remove them from the group (roles are checked on every request) or
deactivate them.

**Test mapping** (on the Groups list and each group's page) shows what a sign-in would
do: paste a decoded ID token as JSON ("Insert an example" shows the shape) and,
optionally, pick a person to compare with their current groups. The result reads like
a diff: **+ Joins**, **− Leaves** and **= Stays**, each with the reason, followed by the
project roles they would end up with. Nothing is saved or logged.

Deleting a group removes its members, mapping and project roles; people keep what they
have directly or through other groups.

### Sign-in (SSO)

A read-only view of how people sign in, as set by the deployment (the Helm values; see
the [operator guide](operator-guide.md#sign-in-and-access-phase-2)): whether the
identity provider answers, the client, the redirect and sign-out URIs to register for
each address the app is served on (with copy buttons), the order sign-in uses to find
an account, group sync, and whether break-glass and the development login are on.
Secrets are never shown.

### Audit log

Every sign-in (and refused sign-in, with the reason), admin change, project membership
and group grant change, owner and evaluator assignment, submitted evaluation, status
change and idea deletion, newest first, one sentence each, for example "Priya Natarajan
added Lena Novak to group Tools members". Filter by who did it, what kind of action,
project, dates, or "About" a user or group; "Details" shows the raw fields. Entries
name ids, never emails, tokens or claims, and each records how the person had signed in
(single sign-on, break-glass or the development login). The log is kept indefinitely.

## Who can do what

See [role-matrix.md](role-matrix.md) for the full table; a plain-language summary goes
here in Phase 7.
