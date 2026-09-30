# Soundings user guide

> Each section is filled in by the phase that ships the feature (noted in brackets). Keep
> it short and task-based: SPEC section 1 says every feature should be usable without
> reading docs, so this guide is for the "why" and the edge cases.

## Getting started [Phase 1–2]

### Signing in

Phase 1 has a development sign-in only: pick who you are from the list (type to filter)
and you're in. Single sign-on (Keycloak or Microsoft Entra ID) replaces it in Phase 2.
A session lasts up to 7 days and ends after 12 hours without activity; after that the
app takes you back to the sign-in page and then to where you were.

### Finding your way: My work, projects, the command palette (⌘K)

- **My work** (`G` then `M`, or the logo) is your home page:
  - **Evaluations due**: ideas waiting for your scores, overdue first. The most urgent
    one has the page's only blue button; "Continue" means you have a saved draft.
  - **Ideas I own**, grouped by status (Closed is folded away).
  - **Recent activity** in your projects.
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
| Lists (My work, project list) | `J` / `K` or `↓` / `↑` move · `Enter` opens · in My work `E` evaluates the focused idea (or the most urgent one) |
| Project page | `V` board/list · `F` search and filter · on a focused board card `Space` picks it up, arrows move it, `Space` drops it |
| Idea page | `E` evaluate · `S` change status · `A` assign owner · `C` comment · `1` `2` `3` Overview / Evaluations / Proposal |
| Evaluate sheet | `1`–`5` score the focused criterion · `Tab` next criterion · `⌘↵` submit · `Esc` close (your draft is kept) |

On macOS `⌘` is Command; elsewhere it is Ctrl.

### Light and dark mode

The app follows your system setting. To choose, open the account menu (your name at the
bottom of the sidebar) or type "theme" in the palette. The choice is remembered on this
device.

## Ideas [Phase 1]

### Submitting an idea (`N`)

Press `N` or "New idea". Only a **title** and a one-line **summary** are required; add a
description (Markdown, with a preview) and tags if you like. In a project the dialog
picks that project for you. If you close the dialog, what you typed is kept on this
device until you submit. The idea gets a key such as `CUST-12` that never changes, and
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
  You watch ideas you submit, own, evaluate or comment on.

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
The per-criterion bars show each average and the range of scores. **High disagreement**
means that on some criterion two evaluators are 2 or more points apart: worth a
conversation before deciding. The Evaluations tab shows every evaluation side by side.
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

Project settings are behind the gear icon on the project page. Members see them
read-only.

### Members and groups

Add people by name or email and give them a role: **viewer** (reads and votes),
**member** (also submits, comments, owns and evaluates) or **admin** (also manages the
project). Every project keeps at least one admin. Removing someone keeps their owner
and evaluator assignments, but they grant nothing without a member role. Groups from
single sign-on come in Phase 2. Only platform admins create projects; the creator
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

## Who can do what

See [role-matrix.md](role-matrix.md) for the full table; a plain-language summary goes
here in Phase 7.
