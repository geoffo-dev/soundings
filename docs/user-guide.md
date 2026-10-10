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
add you, then sign in again. Signed in with the wrong account (a personal one, say)?
Choose **Use a different account** under the sign-in button: your organisation's page
then lets you pick or enter another account instead of reusing the one it remembers
(on Keycloak's page, use the restart button next to your username).

What you can see comes from your project roles: the ones given to you directly and the
ones your **groups** grant. Groups that come from your organisation's directory are
refreshed **each time you sign in**, so after a change there (a new team, say), sign
out and in again to pick it up.

| The sign-in page says | What to do |
|---|---|
| "That sign-in took too long or was already used" | Start again; the link from the sign-in page is single-use and lasts 10 minutes. |
| "Sign-in was cancelled" | You declined at your organisation's page; sign in again when ready. |
| "Single sign-on isn't available right now" / "We couldn't verify your sign-in" | Try again in a few minutes; if it persists, tell an administrator (the details are in the audit log). |
| "Your account is deactivated" / "…needs an administrator to finish linking it" | Contact an administrator. For the second one, "Use a different account" helps if you simply signed in as the wrong person. |
| "Too many sign-in attempts from your network" | Wait a minute. |

A session lasts up to 24 hours and ends after 12 hours without activity; then the app
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
    one has the page's only blue button; "Continue" means you have a saved draft. The
    first 50 are listed; **Show more** loads the rest, a hundred at a time.
  - **Research to do** [Phase 8b] (only when you have some): ideas whose research
    checklist you answer, as their researcher or as their owner when nobody else was
    asked, with a required item still open. Overdue first, then the soonest due, then
    those without a due date; each row says how many required items are open ("2
    open") and **Answer** opens the checklist. "As owner" marks the ones you do as owner.
    With nothing to evaluate, this section comes first and the empty **Evaluations due**
    box isn't shown.
  - **Ideas I own**, grouped by status (Closed is folded away). Each group shows its
    first 10 ideas; **Show more** adds 50 at a time. Viewers, who can't own ideas, don't
    see this section.
  - **Recently updated in my projects**: the ten ideas with the latest activity.
  The sidebar repeats the counts and shows a red dot when an evaluation (or research)
  is overdue; **Research** appears under My work only while you have research to do.
  Project admins see how many public-form ideas wait for review in the sidebar, next to
  the project, and in a notice above its board. On a brand-new install, or before anyone
  has added you to a project, My work says how to start instead: platform admins get
  **Create a project** (and `N` opens New project while there is none).
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

**Single-key shortcuts** (letters, digits and symbols on their own, like `N` or `G` `M`)
can be turned off with the switch at the top of the `?` sheet, for example if you use
speech input or press keys by accident. Shortcuts with `⌘`/Ctrl keep working, and so do
keys that only act inside a focused control (arrows in a list, `1`–`5` on a score). The
choice is kept in this browser for you; with it off, the key hints on buttons go too.

| Where | Keys |
|---|---|
| Everywhere | `⌘K` palette · `?` shortcuts · `[` sidebar · `G` `M` My work · `G` `I` notifications · `N` new idea · `⌘↵` submit a form or comment · `Alt`+`T` go to the messages (an Undo, for instance) |
| Lists (My work, project list, board, notifications) | `J` / `K` or `↓` / `↑` move · `Enter` opens · in My work `E` evaluates the focused idea (or the most urgent one) |
| Project page | `V` board/list · `F` search and filter · on the board `←` / `→` move between columns; on a focused card `Space` picks it up, arrows move it, `Space` drops it (`Esc` puts it back) |
| Idea page | `E` evaluate · `S` change status · `A` assign owner · `C` comment · `1` `2` `3` Overview / Evaluations / Proposal |
| Evaluate sheet | `1`–`5` score the focused criterion · `Tab` next criterion · `⌘↵` submit · `Esc` close (your draft is kept) |
| Pickers (owner, evaluators, members, filters) | type to filter · `↑` / `↓` · `Enter` picks the highlighted entry (the best match is highlighted as you type) · in Invite evaluators `⌘↵` sends the invitation |
| Comment box | `@` opens the people list · `↑` / `↓` · `Enter` or `Tab` inserts the mention · `Esc` closes the list |
| Project settings | `⌘S` saves the section you are editing |

On macOS `⌘` is Command; elsewhere it is Ctrl. When a dialog, sheet or menu closes,
focus goes back to where you were, so you can carry on with the keyboard. After you
follow a link, focus starts at the new page's title.

**Undo** messages (after moving, closing or deleting something) stay for 10 seconds, and
for as long as the pointer or keyboard focus is on them.

### Light and dark mode

The app follows your system setting. To choose, use **Settings → Account** (Appearance) (System,
Light or Dark), the account menu (your name at the bottom of the sidebar) or type
"theme" in the palette. The choice is remembered on this device.

### Your settings page

**Settings** in the sidebar is about you, in three tabs: **Account** (name and email,
from sign-in, the theme, and links to the settings of every project you manage),
**Notifications** (your email preferences,
[below](#notifications-and-email-preferences-phase-3)) and **API keys** (your keys for
scripts and MCP clients, [below](#api-keys-and-mcp-phase-5)). Platform admins also have
**Admin** in the sidebar, with its own sections
([Platform administration](#platform-administration-phase-2)); old links to admin pages
under /settings still work.

## Ideas [Phase 1]

### Submitting an idea (`N`)

Press `N` or "New idea". Only a **title** and a one-line **summary** are required; add a
description (Markdown, with a preview) and tags if you like. In a project the dialog
picks that project for you. If you close the dialog, what you typed is kept in this
browser, for you only, until you submit or sign out. The idea gets a key such as `CUST-12` that never changes, and
you start watching it.

### Statuses: New, Evaluating, Shortlisted, Proposal, Closed

The five statuses are fixed (project admins may rename them). A project may add one
more, **Research**, before evaluation or before the proposal (see
[The research step](#the-research-step-phase-8)); the board then has a Research column
in that place. The owner or a project
admin moves an idea to any status: from the status picker (`S`), by dragging its card on
the board, or with the keyboard on a board card. Closing asks for a resolution:
Accepted, Rejected or Parked. A status change has no side effects, so "Undo" in the
toast puts it back exactly. In a project with a research step, moving an idea past
Research waits for its research checklist (below).

### Comments, @mentions, votes and watching

- **Comments** use Markdown. `C` jumps to the comment box and `⌘↵` posts. You can edit
  or delete your own comments; a deleted comment can be restored with "Undo" for a few
  seconds. Comments are flat (no threads).
- **@mentions:** type `@` in the comment box and pick a person from the list (people
  with a role in the project: admins, members and viewers, never yourself). The mention
  shows as "@Name" with a light tint, in the comment box too, and always points at that
  person, even if their name changes. Typing inside a name turns it into plain text;
  Backspace right after it removes the whole mention. They get a notification, and an email unless they turned mentions off
  ([Notifications](#notifications-and-email-preferences-phase-3)); people who can't see
  the idea are not told. Up to 20 people per comment. Adding someone by editing a
  comment notifies only the newly mentioned people.
- **Votes** show support (one per person, any status). They don't affect the score.
- **Watching** an idea sends you its new comments and status changes. You watch ideas
  you submit, own, evaluate or comment on; the Watch button stops or starts it. The
  owner and evaluators hear about status changes even when they don't watch.

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

### The next step on the idea page

The blue button at the top of an idea is its next step for you, and it follows the
status. **Evaluate** (or **Continue evaluation**) while you owe a score comes first. For
the owner and admins it is then **Assign owner** (or **I'll own this**) on an unowned
idea, **Invite evaluators** while nobody is invited, **Close evaluation** while evaluation
is open, **Change status** once it is closed (shortlist or close the idea), **Start
proposal** on a Shortlisted idea and **Open proposal** once there is one. In a project
with a research step, the button also walks the idea through it: **Start research** on
the status before Research (New or Shortlisted) while the checklist is open, **Finish
research** while required items are unanswered (it takes you to the first one), then
**Start evaluation** (or **Start proposal**) once it is done. **Start evaluation** opens
**Invite evaluators** when nobody is invited yet: inviting starts evaluation and moves the
idea to Evaluating with it. A closed idea, or one with nothing for you to do, has no blue
button.

## The research step [Phase 8]

Before the team invests in an idea, its owner checks that it isn't already being done
somewhere else in the company, and that the right departments or teams have been
consulted. A project admin turns this on per project (Project settings → Research),
**before evaluation** (New → Research → Evaluating …) or **before the proposal**
(… Shortlisted → Research → Proposal). Projects without it work exactly as before.

### The Research panel

On the idea's Overview tab, the **Research** panel lists the project's checklist, for
example "Not already being done elsewhere", "Departments or teams consulted" and "Data
protection considered". The idea's owner, its researcher (see below) and project admins
answer each item in a few lines of plain text, such as "Legal (contracts team), 3 Oct: fine if we keep the
standard terms"; the hint under each item's title says what to write. **Save answer** (or
`⌘↵`) saves it and records who answered and when; edit it later the same way, or
**Clear** it ("Undo" in the toast brings it back). An answer you typed but didn't save is
kept in this browser: leave the page and come back, and it is still there ("Unsaved draft
restored"), until you save it or press **Discard**. `Esc` only leaves the box. Required
items are marked **Required**; the line at the top says how many are answered and how
many required items are left ("1 required item left before Evaluating", or "Research
complete"). The panel opens by itself while the idea is in Research, and for the owner
and admins also in the status just before it; otherwise it starts folded (click
**Research** to open it).

Everyone who can open the idea reads the checklist and the answers, evaluators included
(there are no scores in it). Under the checklist:

- **Similar ideas**: up to five ideas with a similar title or summary in every project
  you can see (archived ones too), with their project, status and owner, so you know
  whom to ask. Ideas waiting for moderation never appear.
- **Ask AI to research** (where AI assistance is on, the same as in the AI menu): an AI
  agent looks for similar work and writes a research note in the activity feed; the
  panel then says "Note from <agent>" with **Read it**, which takes you to the note.

On the board, in the list and in My work, ideas in Research show the checklist at a
glance: **2 open** (required items left) or **Ready** (nothing holds the move). Ideas in
the status just before Research show it too once something is answered.

### Who does the research [Phase 8b]

By default the idea's owner does the research. The owner, project admins and platform
admins can ask **one person** to do it instead, the idea's **researcher**, with an
optional **research due date**. The Research panel says who it is: "Research: Bob Chen ·
due Fri 9 Oct", or "Research: Sven Lindqvist (owner)" when nobody else was asked (the
idea's details then just say **Owner**). An overdue date says "overdue" in words, in the
warning colour.

- **Start research**: in the status just before Research, the owner's blue button asks
  who does the research (you, the owner, unless you pick someone) and an optional due
  date, then moves the idea into Research. The confirmation says who does it and by when.
- **Change** (in the Research panel, the details' **Research** value or ⌘K "Change
  researcher…") picks a person and a due date. To take the research away from someone,
  choose the owner there: the dialog says when that person will no longer see the idea.
  The due date stays when the researcher changes. A date already past stays as it is
  until you pick another ("Was due Wed 7 Oct (overdue)"), so the dialog still saves. The
  activity feed records a change as one line ("asked Bob Chen to research, due Fri 9 Oct").
- The researcher can **Hand back** the research (after confirming); their answers stay
  and the owner does it again. An owner asked by name has nothing to hand back.
- Anyone with an active Soundings account can be the researcher, inside the project or
  not (never an AI agent or the break-glass account). The picker lists the project's
  people first and everyone else under **Not in this project**, and choosing one says
  what they will see (below). In a **private** project only project and platform admins
  can ask someone outside it; owners pick from the project's people. Everyone who sees
  the idea sees "not in this project" next to an outside researcher, and above the
  comment box members read "Bob Chen (researching, not in this project) can read
  comments."
- The researcher answers the checklist, comments (and can be @mentioned: the mention list
  calls them "researcher") and is told about status changes. They can't move the idea or
  use **Move anyway**: when the checklist is complete, the owner moves it on.
- **Once the idea has moved past Research**, the research is done: the researcher reads
  the answers but can no longer change them ("The idea has moved past Research, so only
  its owner or an admin can change these answers now."), and nobody new can be asked: the
  panel offers **Remove** instead of **Change** (it asks first and says why). Moving the
  idea back into Research lets the owner ask someone again. An answer the researcher
  typed but hadn't saved when this happened stays under its item with **Copy** and
  **Discard**, so it can be passed on.
- Asking someone sends them **Asked to research** (with the due date and a link to the
  checklist) and puts the idea in their My work, under **Research to do**. With a due
  date, a **Research reminder** goes out 2 days before and on the day, at the usual
  reminder hour, while a required item is still open: to the researcher, or to the owner
  when nobody else was asked. Reminders stop as soon as the required items are answered
  or the idea moves on.
- Closing the idea, or turning the project's research step off, ends the assignment
  (reopening doesn't bring it back); in an archived project it is paused. If a
  researcher leaves a private project, or their account is deactivated, it ends too, and
  so does the research of everyone outside the project when an internal project is made
  private (its admin is asked first: "2 people researching ideas here aren't in the
  project and will lose access."). Answers already written always stay.

On the board and in the list (phones too), ideas in Research show the researcher's
avatar inside the checklist badge ("Researched by Bob Chen") when someone other than the
owner was asked.

### Researching an idea outside your projects [Phase 8b]

If you're asked to research an idea in a **private** project you aren't in, you see
**that one idea** and nothing else of the project: its title, summary, description,
tags, status and owner, the activity feed and comments, the research checklist (which
you answer) and Similar ideas you could see anyway. You never see its scores,
evaluations, evaluators, proposal or AI actions, and the project shows by name only (no
link). The idea page says "You can see this idea because you're researching it." The
idea is in your My work (first, when you have nothing to evaluate), inbox and search; if
you're in no project at all, My work is just your **Research to do**. In the comment box,
**@** offers only the people on the idea (its owner and whoever wrote in its activity).
When you hand it back, someone else is asked, the idea is closed or the project's
research step is turned off, the idea disappears for you at once: a page you still have
open says "You're no longer researching TOOLS-12" (and that what you typed is kept on
this device, should it come back to you). In an **internal** project, which everyone can
already read, being its researcher only adds answering, commenting and **Hand back**.

### Moving past Research

While a required item has no answer, an idea can't move past Research: dragging its
card to a later column, picking a later status, inviting its first evaluator or asking
AI to evaluate it (before evaluation), or starting its proposal (before the proposal).
The card snaps back and a dialog lists the open items, with **Open research**. Moving an
idea back, or closing it, is never held up, and an optional item never holds anything
up. Changing the checklist or turning the step on never moves an idea: ideas already
past Research stay where they are. Moving an idea back into Research while required
items are open offers no **Undo** (undoing would take it past Research again); the
toast says to finish the checklist first. Once an idea is past Research, a required
item's answer can be changed but not cleared, so the answers that let it through stay
on record.

**Move anyway** (also **Invite anyway**, **Ask anyway**, **Start anyway**): project
and platform admins can take an idea past Research with items open, after an optional
one-line reason. It is recorded in the audit log, and the activity feed says the idea
was moved "without finishing research". Owners who aren't admins finish the checklist
first.

Someone who sent the idea through the public form never sees Research: their tracking
page keeps showing the stage before it ("With the team").

### Closing and reopening evaluation

"Close evaluation" stops further scoring (the page suggests it once everyone has
submitted); "Reopen" undoes it. Closing does **not** reveal scores to evaluators who
never submitted. Closing the idea itself also ends evaluation. Both are recorded in the
platform's audit log.

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

A strong idea becomes a commercial proposal on its **Proposal** tab (`3`).

### Writing a proposal from the template

Once an idea is **Shortlisted**, its owner (or a project or platform admin) sees **Start
proposal** on the Proposal tab (also in ⌘K). Starting it moves the idea to **Proposal**,
like any status change: watchers are notified and a public submitter who asked for
updates gets an email. Everyone else sees "The owner will write the proposal" until then.

Every proposal follows its project's **template**: by default eight sections (Summary,
Problem, Solution, Market & users, Cost & effort, Benefits / revenue, Risks, and Next
steps / the ask), which a project admin can rename, reorder, add to or trim (see
[Proposal template](#proposal-template)). Each section's hint is the grey line under its
heading. Summary starts with the idea's summary; the rest start empty. When the template
changes, every proposal follows at once; a section removed from it is hidden, with its
text kept, and comes back if an admin restores it. If a section is removed while you
are typing in it, your text is kept in this browser at the end of the proposal, with
**Copy text** and **Discard**. Each section is a plain Markdown box that grows
as you type, with **Write** and **Preview** (`⌘↵` switches), a small toolbar (bold,
italic, link, list; `⌘B`, `⌘I`) and a word count. The outline on the left shows which
sections are written and how many open comments each has; on narrow screens it becomes a
"Jump to section" list. `j` / `k` move between sections and `⌘S` saves at once.

Sections save by themselves a moment after you stop typing ("Saving…", then "Saved
10:42"). Two people can write different sections at the same time. If someone else saved
the **same** section since you started, you see both versions side by side with the
changes marked: **Use Carol's version**, or **Keep your version** to save yours over
it (for your own other tab: **Use the saved version** / **Keep this version**). A save that fails
keeps your text and shows "Not saved" with **Retry**; the app asks before you leave with
unsaved text. A section holds up to 20,000 characters.

In a project with a research step before the proposal, a Shortlisted idea goes to
Research first, and starting its proposal waits for the checklist
([Moving past Research](#moving-past-research)); the proposal can also be written while
the idea is in Research. In any project with a research step, the proposal ends with
**Research and consultation**: the answered checklist items, as the exports print them
(the outline's last link goes there).

The proposal can be edited while the idea is Shortlisted or in Proposal. Moving the idea
anywhere else makes it read-only (it can still be read, commented on and exported);
moving it back makes it editable again. Viewers and evaluators read the rendered text.

### Comments in the margin

Members and admins can comment on a section (`c` comments on the section in view): the
thread sits beside the section on a wide screen and opens in a sheet on a phone. Anyone
who may comment can reply, **Resolve** a thread (it collapses to one line) or **Reopen**
it; replying to a resolved thread reopens it. You can delete your own comments (admins
any). Margin comments don't notify anyone in this version and don't take @mentions;
they never appear in exports.

### Suggestions [Phase 5]

An AI assistant connected with someone's key (or, from Phase 6, an AI agent) can
**suggest** the whole new text of a section; it doesn't change the proposal. Pending
suggestions appear under their section ("1 suggestion", and a count in the outline and
the editor's top bar) with who suggested it ("via assistant", or an AI badge for an
agent, with "Written by an AI agent: check the facts"), when, and the changes against the
current text (**Changes**, with the changed words highlighted inside each line) or the
text alone (**Suggested text**). Each card says who decides ("Ada decides whether to use
it."). If the section was saved since, it says "The section has changed since this was
suggested". Everyone who can read the proposal sees suggestions; the owner and admins
**Accept** (the text is saved as a normal section save, with Undo; any edit still being
saved is saved first, and it asks only if your edits couldn't be saved; a conflicting save
offers **Accept anyway**) or **Discard** (with Undo); focus then moves to the next pending
suggestion. For the owner and admins the idea's **Proposal** tab shows how many
suggestions wait for a decision ("3 to review" on phones). A newer suggestion from the
same person for the same section replaces their earlier one; nobody is notified of
suggestions in this version.

### Exporting to PDF or Markdown

**Export** (top right of the Proposal tab) downloads the proposal as **PDF** or
**Markdown**; anyone who can see the idea can export it. Both start with the title and a
details block (project, idea key, status, owner, "Exported 2 October 2026 by …") and
list the template's sections in order; an empty one reads "Not written yet". While the
project's research step is on, they end with **Research and consultation**: each
answered checklist item with its answer and who answered it when. The aggregate
score line is included only if you are allowed to see scores (never for an evaluator who
hasn't submitted yet). Comments are never exported.

The Export menu warns when sections are still empty ("3 of 8 sections are still
empty"). The PDF is A4 in the project's branding: a cover with the logo (or the app
name), the title and the details, the contents with page numbers (on the cover for a
short proposal, else on their own page; empty sections are marked "Not written yet"),
the app name and idea key at the top of every page and "Page X of Y" at the bottom, in
the project's font and colours. Headings keep the levels the editor's preview shows.
Links stay links, in the primary colour, with their address printed after them in
brackets (paper can't be clicked); pictures in the Markdown become links (a proposal
never loads anything from the internet). A very long section (thousands of list items,
say) is cut in the PDF with a note to export Markdown for the full text. You can export 10 times a minute. One PDF prints at a
time, and printing stops after 20 seconds (only a huge proposal, such as one full of
long tables, gets near that): the app then says "The PDF export is busy", so try again a
few seconds later.

## Public submission and tracking links [Phase 4]

A project can accept ideas from anyone, without an account, through its **public form**
at `https://<your Soundings>/<project-slug>/submit` (a project admin turns it on, see
[below](#public-form-moderation-and-erasing-submitter-details)). The form shows the
project's name, an introduction and the project's branding, nothing else about it.

**Sending an idea.** Fill in a title and a summary, and optionally a description
(Markdown), your name and your email address. With an address you can tick "Email me
when the status changes". A quiet "Verifying you're human" line works in the background
while you type (a small proof-of-work puzzle your browser solves; no images to click, no
third party). `⌘↵` sends. The fixed privacy notice under the form says what is kept:
what you write, plus your name and address only if you give them; never your IP
address.

**Your private tracking link.** After sending, the page shows a private link
(`…/track#…`) once, with **Copy** (and **Share** on phones): keep it, it's the only way
back to your idea without an account. It is not in the confirmation email (anyone can
type any address into the form); status emails carry it once your address is
confirmed. The tracking page shows the title and summary as you sent them, what the
status means in plain words, and its history: Sent, **With the team** (the date the
team got it) and every status change since (dates only, no names). It lets you:

- turn status emails on or off ("Email me when the status changes");
- **resend** the confirmation email if you haven't confirmed your address;
- **Delete my details**: erases your name, address and the link itself; the idea stays
  with the team, and the link stops working at once.

Anyone who has the link can do these things, so don't share it.

**Confirming your address.** The confirmation email ("Confirm your idea for <project>")
contains no text you typed. Its button opens a page in the project's look
(`…/<project>/verify#…`) where you click **Confirm my email address** (nothing happens
just by opening the link, so mail scanners can't confirm for you). Only confirmed addresses get status emails. Some projects also hold an idea until
its address is confirmed: then the team sees nothing until you click. Confirmation links
last 3 days; an unconfirmed address is forgotten after 3 days, and an idea still waiting
for confirmation then is deleted.

**What happens next.** Most projects review public ideas first ("The team reviews new
ideas first"): the idea waits until a project admin approves it, then appears in New
like any other idea and follows the normal flow. Status emails say only "Your idea "…"
is now Evaluating" and link to the tracking page, which is also where you stop them
("Stop these emails" at the bottom of every status email).

**Limits.** To keep the form usable, each address can send a handful of ideas an hour,
and a project takes at most 100 public ideas an hour; "You've sent several ideas in a
short time" means try again in a few minutes.

## Notifications and email preferences [Phase 3]

### The bell and your inbox (`G` `I`)

The bell at the top of every page shows how many notifications you haven't read. It
opens your latest ones (on a phone, a full-height panel); **See all notifications**, or
`G` then `I`, opens the inbox page, grouped by day, with **All** and **Unread** and
**Mark all read** (with **Undo** for a few seconds). Each notification says who did
what on which idea, in one sentence:

| You're told when | Opens |
|---|---|
| someone makes you the **owner** of an idea | the idea |
| someone **asks you to evaluate** (with the due date) | the evaluate sheet of that idea |
| your **evaluation is due**: 2 days before the due date and on the day, while you haven't submitted | the evaluate sheet |
| someone **asks you to research** an idea (with the due date) [Phase 8b] | the idea's research checklist |
| your **research is due**: 2 days before the research due date and on the day, while a required item is open [Phase 8b] | the research checklist |
| **all evaluations are in** on an idea you own | the idea |
| an idea you own, evaluate or watch **changes status** | the idea |
| someone **comments** on an idea you watch | the comment |
| someone **@mentions** you | the comment |

Opening a notification marks it read, and so does opening the idea it's about. You're
never told about your own actions, and you only see notifications about ideas you can
still open: if you lose access to a project, its notifications disappear from your
inbox.

**Blind evaluation holds here too:** no notification or email ever contains scores,
recommendations, the aggregate or anyone's evaluation comments. "All evaluations are
in" only says how many came in; open the idea to see the results.

### Immediate, daily digest or off

Everything always shows up in your inbox. **Settings → Notifications** chooses, for each
kind of notification, whether it is also **emailed**:

- **Immediate**: one email as it happens. The default for things you need to act on:
  being made owner, being asked to evaluate or to research, reminders, all evaluations
  in, mentions.
- **Daily digest**: one email a day with everything set to "Daily digest" that you
  haven't already read in the app. The default for things you follow: status changes
  and new comments. The page says when it arrives (for example "08:00
  (Europe/London)"); the time and the reminder days are set by your administrator for
  everyone.
- **Off**: no email; the inbox still shows it.

Changes save as you choose. **Reset** puts one type back to its default, and **Turn off
all email** switches everything to Off (with Undo). Turning a type off also stops
emails of that type that are already waiting to go out. If the page says "Email isn't
set up on this server yet", you get in-app notifications only until an administrator
configures email; your choices are kept for then.

Every email has a button to the right place (the evaluate button opens the evaluate
sheet, signing you in first if needed), the idea's key and title in the subject, and a
footer that says why you got it.

### Unsubscribing

Every notification email ends with three links: **Email preferences** (sign in and
choose per type), **Unsubscribe from …** that kind of email (from the digest: everything
you get as a digest) and **Unsubscribe from all email**. Each unsubscribe link opens a
page that shows what will stop and for which address (partly hidden), and changes
nothing until you press **Unsubscribe**. A link only stops what it says: the "…
evaluation requests" link can't turn off your other emails, so to stop everything use
**Unsubscribe from all email** or your preferences. You don't need to sign in, and the
links in old emails keep working. Mail apps that show their own "Unsubscribe" button
next to the sender use the first link: one click there turns that kind of email off.
Unsubscribing never affects the in-app inbox; to get emails again, change the type back
in Settings → Notifications.

## API keys and MCP [Phase 5]

A personal API key lets a script or an AI assistant use Soundings **as you**: the REST
API at `/api/v1`, or the MCP server at `/mcp`. It never does more than you can do in the
app, and only what its scopes allow.

### Creating and revoking a personal API key

**Settings → API keys** (also in ⌘K) lists your keys: name, the start of the key
(`sdg_…`; hover it for when it was created), what it **can** do in plain words ("Read
and evaluate", "Also through AI assistants"), projects, expiry ("in 3 days" stands out in
the last week; expired keys are listed last, quieter, with **Remove**) and when it was
last used. If you lose access to a project a key is restricted to, the key stops reaching
it and the row says "+1 project you can no longer open". **Create key** asks for:

- **A name** that says what it's for ("Claude Desktop", "Weekly report"); each of your
  keys needs a different one.
- **What it can do**: one of four presets, **Read only** (scripts and reports that look),
  **Read with an assistant** (an AI assistant that searches and reads), **Evaluate with an
  assistant** (it also submits evaluations as you: they count as yours) and **Full
  access**, or **Custom** to tick the scopes yourself. *Read* sees what you see; *Write* creates and changes ideas, comments, owners,
  evaluators, statuses and proposals; *Evaluate* saves and submits your own evaluations,
  blind as in the app; *AI assistants (MCP)* lets an AI assistant connect (its tools also
  need Read, Write or Evaluate). Write and Evaluate include Read. Under the form, "This
  key can …" says in plain words what the key will be able to do.
- **Expiry**: 30 days, 90 days, a year, a date, or never.
- **Projects**: all the projects you can access (now and later), or only some.

The key is shown **once**, with Copy and ready-made examples: store it somewhere safe,
because Soundings keeps only a fingerprint of it ("Treat it like a password"), then
choose **I've copied it**; closing without copying asks once more. After that the list
shows only its start. A key can't be changed later: create a new one and revoke the old.

**Revoke** asks first, then the key stops at once: whatever uses it gets "unauthorized"
on its next request. Signing out doesn't stop keys. A key also pauses when you haven't
signed in to Soundings for 30 days (signing in resumes it), and a platform admin can
revoke any key (Settings → API keys → Everyone's keys); deactivating an account revokes all
its keys.
Some things always need you signed in, so no key can do them: deleting or moderating
ideas, project and admin settings, your inbox, and managing keys. You can have up to 25
keys. The break-glass admin account can't create keys.

### Connecting an AI assistant (MCP client)

Below your keys, **For developers and AI assistants** (folded; open it) shows the server
URL (`<this address>/mcp`), the header (`Authorization: Bearer <your key>`), a link to
the API reference and examples for Claude Code, Claude Desktop, other clients that take
an `mcpServers` config, and curl. Create a key with the **Read with an assistant** or
**Evaluate with an assistant** preset and paste it in; then ask the assistant something like
"Which Soundings ideas are waiting for my evaluation?". The client can list projects,
search and read ideas, rubrics and proposals, create ideas, comment, submit your
evaluations and suggest proposal text, within the key's scopes and projects. It sees what
you see: no scores before you have submitted your own evaluation. Every call it makes is
recorded in the audit log. Step-by-step setup, the tool list and safety notes for power
users: [mcp.md](mcp.md).

## AI assistance [Phase 6]

When your platform admin has registered AI agents (kagent) for a project, an idea's owner
and the admins can ask one for help. Agents can do three things: **evaluate** an idea
against the rubric, **research** it, and **draft** a proposal section. Whatever an agent
writes carries an **AI** badge, and it is shown as text from outside Soundings: links
only to web pages, opened in a new tab, and every source it cites is labelled **"Cited by
AI, not checked"** (it may have invented it). Check the facts before you rely on them.

An agent works only on the idea you asked about, and only while its run lasts: once the
run ends (done, cancelled or out of time) it can't read or change anything, and two runs
of the same agent can't reach each other's ideas. It never sees anyone else's scores or
evaluation comments, not even after it has submitted its own, and it sees its own
evaluation only while it is evaluating (so a research note or a draft can't repeat its
scores).

### "Ask AI to evaluate" and the AI badge

On an idea you own (or as an admin), open the **AI** menu next to the main action (also in
⌘K): it is the one place to ask an agent to evaluate, research or draft. The agent joins
the evaluators with an AI badge, and a row appears on the Overview tab under **AI runs**
while it works: the current step ("Read the rubric", "Read the idea", "Saved its
evaluation"), how long it has taken and about how long it has left, and **Cancel**.
**Steps** opens who asked, when it will be stopped and every step so far. A run that did
its job folds under **History (N)** once you leave the page (its evaluation or note is on
the page already); a run that stopped short keeps its row, with **Try again**.
Everyone who can see the idea can watch, but a run never shows scores, so pending
evaluators stay blind. The row updates live and falls back to refreshing on its own if
live updates aren't available. When a run ends, your focus stays where you left it (a
screen reader announces how it ended).

When it is done, the row reads "Evaluation submitted · not in the score yet" and **View
the evaluation** opens the agent's card on the Evaluations tab: a score per criterion,
each with its **rationale** and the **sources** it cited, its recommendation and a
summary. A run that fails, times out or is cancelled says why in plain words with what
to do next ("The agent didn't finish within 5 minutes. Try again: it may have been
busy."), and the latest row offers **Try again** (Soundings' own record of what happened
stays under Steps). If it ended without an evaluation, the agent is taken off the
evaluators again (the activity feed says so). Asking again while a run is working just
shows that run. Once the agent has submitted, the button reads **Ask AI to evaluate
again**: a new evaluation replaces its old one, and its card says "Re-evaluated". Each
person can ask for 20 runs an hour; past that, Soundings says when you can ask again.

**"Not in score": what excluded means.** An AI evaluation is **left out of the score** by
default: the aggregate, the number of evaluations, the per-criterion means, the
disagreement flag and the board's ranking count people only. Under the score, "1 AI
evaluation not counted · Review" says so and takes you to it. The agent's scores still
show in the comparison table (its column muted, with dashed score chips; the Mean column
says "counted") and on its card, marked "not in score", so you can read and compare
them. If you find its evaluation sound, switch **Include in score** on its card
(owner and admins): the aggregate then counts it like a person's, and you can switch it
off again at any time (Undo is offered). If the agent re-evaluates and changes any score
or its recommendation, it is left out again until someone includes it again.

### "Ask AI to research" and "Draft section"

**Ask AI to research** (the AI menu, ⌘K, or the Research panel in a project with a
research step) asks an agent for a short research note: what it
found about the idea, open questions and numbered sources. The note appears in the
activity feed with the AI badge, in a box of its own, readable by everyone who can see
the idea. The owner and admins can **Delete** it (after confirming; there is no undo):
the feed then shows that a research note was deleted, and the audit log records who
deleted it.

In the proposal editor, **Draft with AI** (on phones **Draft**) on the section you are
working on (other sections show it when you point at them or tab to them), or **Draft a
section…** in the AI menu, asks an agent to suggest text for that section. While it works, the section shows its progress with
Cancel; when it is done, its text arrives as a **suggestion** under the section (focus
moves to it), with the AI badge and the changes highlighted, like any other suggestion (see
[Suggestions](#suggestions-phase-5)): **Accept** puts it into the section, **Discard**
drops it. Drafting works while the idea is Shortlisted or In proposal and its proposal
has been started.

When an AI action is greyed out, it says why: AI assistance is off, no agent serves this
project, the idea or its evaluation is closed, the project is archived, the idea is
waiting for moderation, or the proposal hasn't been started.

## For project admins [Phase 1–4]

Project settings are behind the gear icon on the project page (or Settings → Account →
Projects you manage), in six tabs: **General** (with the status labels), **Members**,
**Rubric**, **Research** (the research step and its checklist), **Proposal template**
and **Public form** (with the project's branding); on a phone the tabs wrap onto two
lines. Members see them read-only. Each form
has its own Save (`⌘S` saves the tab you are on); if you try to leave with unsaved
changes, the app asks first. Forms whose fields belong together keep an explicit Save;
single preferences (notifications) and documents (proposals) save as you go.

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
becomes its first admin. The break-glass account can't run projects, so it chooses the
first admin when it creates one (on a fresh install, add that person in Admin → Users
first).

### Editing the rubric

A rubric has 3 to 6 criteria, each with a weight (relative: 2 counts twice as much as
1), an optional "inverted" switch for criteria where a high score is bad, and optional
guidance for each score. Reorder criteria by dragging the handle, with Alt+↑/↓ in any of
their fields, or from their **Move** menu (Move up, Move down). Saving recalculates every idea's score in the project;
submitted evaluations stay submitted, and a new criterion is scored the next time
someone edits their evaluation.

### Research step and checklist

Project settings → **Research** chooses where the Research stage goes: **Off** (the
default), **Before evaluation** or **Before proposal**; each option shows the stages it
gives. Turning it on with no checklist yet fills in the default three items (change them
as you like; nothing is saved until **Save research step**). The checklist is edited like
the rubric: 1 to 10 items, each with a title, a one-line hint (what to write) and a
**Required** switch; reorder by dragging, Alt+↑/↓ or **Move**. Removing an item that
ideas answered keeps their answers, hidden, under **Removed items**, and **Restore**
brings them back to where they were (at the end if the checklist is shorter now). Saving
only the checklist says "Checklist saved".

The step can't be moved or turned off while ideas are in Research: a line under the
choice says how many ("Can't change while 2 ideas are in Research · Show them") and links
to them, so you can move them first. Turning the step off hides the
Research column, the checklist and every answer, and keeps them for when you turn it on
again. Turning it on, moving it or changing the checklist never moves an idea; the next
move past Research checks the required items.

### Proposal template

Project settings → **Proposal template** lists the sections every proposal in the project
has, 1 to 12, each with a title and a one-line hint shown in the editor (under the
section's heading). Rename a section,
change its hint, reorder (drag, Alt+↑/↓ or **Move**), **Add section**, or remove one (at
least one stays). Renaming or reordering keeps each section's text; a new section starts
empty in every proposal. Removing a section loses nothing (so it doesn't ask): until you
save, **Discard** brings it back; once saved, its text is kept, hidden from the editor and
the exports, under **Removed sections** ("Text in 3 proposals"), and **Restore** brings
it back with its text, comments and suggestions, to where it was (at the end if the
template is shorter now). Saving changes every proposal in the project at once.

### Renaming status labels

On the General tab, rename any status or resolution (for example "Shortlisted" → "Next up"); the board,
lists and filters use the new names at once. Research is listed while the project's
research step is on. The reset button next to a name restores
the default.

### Project settings and branding

General settings: name, description, visibility (private: members only; internal:
everyone who can sign in can read it), whether members may volunteer to own ideas, and
the evaluation window in days. Making an internal project **private** ends the research
of anyone researching one of its ideas without a role in the project; when there are
such people, Save asks first ("Make this project private?") and says how many lose
access. **Archive** makes a project read-only and hides it from
lists, search and My work; restore it from the archived notice or the settings.

**Branding** (project settings → Public form, below the form's settings) overrides the global branding for this
project's **public pages, emails to its public submitters and exported proposals**; the
signed-in app keeps the global look for everyone. Every field says "Use the global one"
until you set it: app name, logo, favicon, primary and accent colour, font and email
footer. A project that sets its own logo but no app name is its own brand: its emails,
PDF header and public pages name the **project** rather than the instance. The preview
shows the public form and an email to a submitter, in light and dark, as you type (on a
phone, **Preview** in the save bar opens it); nothing changes until you save. See
[Branding](#branding) for the rules on colours, fonts and images.

### Public form, moderation and erasing submitter details

**Turning the form on** (project settings → Public form): switch "Accept ideas through
the public form", then choose:

- **Review new ideas before the team sees them** (on by default): public ideas wait in a
  moderation queue instead of appearing in New.
- **Ask people to confirm their email address**: the address becomes required and the
  idea reaches the team only once its sender clicks the confirmation link (needs email
  set up; ideas never confirmed are deleted after 3 days).
- An **intro** (Markdown) shown above the form: what kind of ideas you're after.

The page shows the form's link to copy. Changes apply to new submissions only. The form
isn't available in an archived project, when a platform operator has turned public
submission off for the whole instance, or for a project whose address clashes with one
of the app's own pages. A private project's form shows only its name, introduction and
branding.

**Moderating.** While ideas wait, the board shows "3 ideas waiting for review" (on a
phone, a one-line link) and the sidebar a **Review 3** link under the project (admins
only); each opens the queue (`/p/<project>/review`), oldest first: title, summary, description and
the sender's name if they gave one. **Approve** puts the idea in New (at the top) with no
email to anyone; **Reject** deletes it for good, for spam, abuse or off-topic posts. Both
offer Undo for a few seconds. A genuine idea you don't want to pursue is better approved
and later closed as Rejected: its sender then sees an honest status on their tracking
page. A held idea is invisible everywhere else (board, lists, search, My work,
notifications) and read-only for admins who open it by link, apart from approve, reject,
erase and delete.

**Who sent it.** A public idea says "Submitted by Jo via the public form" (or just "via
the public form") to everyone who can see it; its activity starts with "A visitor sent
it through the public form". Project and platform admins also see the address, whether
it is confirmed and whether the sender wants status emails, in the idea's submission
panel.

**Erasing submitter details** (UK GDPR): "Erase submitter details" in the submission
panel removes the sender's name, email address, confirmation, update preference, the
copy of what they sent and their private link, and deletes the emails queued or sent to
them; the idea and its history stay. It asks first and can't be undone. Senders can do
the same themselves with "Delete my details" on their tracking page. Personal data they
typed into the idea itself is removed by editing the idea. Automatically, unconfirmed
addresses are forgotten after 3 days, and contact details of closed ideas with no
activity for 180 days are erased.

## Platform administration [Phase 2]

Platform admins get **Admin** in the sidebar: Users, Groups, Sign-in (SSO), Email,
Branding, AI agents and the Audit log. **Admin** opens a list of them; on an admin page
they are listed under Admin in the sidebar (on a phone, each page has "All admin
settings" to go back to the list). They are also in the palette. The pages keep their
addresses under /settings. Everyone else sees a plain "Page not found" there.

### Users

Search by name or email and filter by status, platform admins or "Not signed in yet".
Each person's row says Active or Deactivated, with "Platform admin" or "Break-glass" by
their name. AI agents' accounts aren't listed here: they live in AI agents.
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

### Branding

**Admin → Branding** (platform admins) sets the instance's look: app name (up to 40
characters, shown in the sidebar, page titles and emails), logo, favicon, primary and
accent colours, font, and an email footer (plain text, up to 5 lines, for example your
company name and address). The app, the sign-in page, every email to staff, and every
project without its own override use it. The preview shows the app, a public form and
an email in light and dark before you save; **Reset** goes back to the built-in
Soundings branding. Saves are recorded in the audit log (field names only).

- **Colours** are hex values (`#0b6e4f`). The app keeps text readable whatever you pick:
  it derives the shades it needs and the preview warns when a colour has low contrast.
- **Fonts** come from a bundled set: Inter (default), IBM Plex Sans, Source Serif 4 and
  Atkinson Hyperlegible. They are part of the app, so nothing is downloaded from the
  internet. Public pages, emails and PDFs use the font throughout; inside the app it is
  used for the wordmark and page titles, while the dense working text stays in Inter.
  An invalid colour says "Use a hex colour such as #1d5fa8." when you leave the field.
- **Logo and favicon**: PNG or SVG, up to 512 KiB by default (your operator can change
  it), logos at most 2048 × 2048 pixels and favicons 512 × 512. Drop a file or choose
  one. PNGs are re-saved without their metadata; SVGs must be simple drawings (shapes,
  gradients, text; no scripts, links, embedded images, styles or external references),
  and the app explains what it refused. Design the logo for a light background: emails
  and PDFs are always light, and in dark mode the app shows the logo on a light plate.
  A logo you replace keeps working at its old address for a day, then is deleted.

### Email

Shows the email settings in effect, read-only (they come from the deployment's
configuration; the [operator guide](operator-guide.md#email-phase-3) explains them): the
server and port, the security mode, the sender, the address links in emails point to,
whether a username and password are set (never their values), and when digests and
reminders go out. Without a mail server it lists the setup steps instead, and you see a
quiet banner "Email isn't set up" across the app (dismiss it for the session).

- **Send test email** sends a real email through the outbox to yourself, or to one
  address you type, and shows whether it arrived at the mail server, with a hint when
  it didn't (wrong host or port, TLS certificate, password). Five per admin every 10
  minutes.
- **Outbox**: every email with its recipient's name (never the address), type, status
  and attempts. Mail the server didn't accept is retried by itself, 12 times over about
  5 hours. **Failed** email (after the last attempt, or refused for good) has a
  **Retry** button, and **Retry all failed** retries every one that is still current.
  Emails more than three days old (digests: two) are not sent late; they show as "Not
  sent". When something failed in the last day, or mail has been waiting more than 15
  minutes, platform admins see the banner "Some emails aren't going out", which links
  here and clears by itself once mail flows again.

Sending a test email and retrying are recorded in the audit log, without the address.

### Everyone's API keys [Phase 5]

**Settings → API keys → Everyone's keys** (platform admins; the old "All API keys"
address leads there) lists every key people and AI agents have that isn't revoked:
the key's name and start (`sdg_` and 12 characters), the owner (an AI agent's avatar says
so) with a **Dormant** badge when they haven't signed in for 30 days, scopes, projects
(a project the owner can no longer open is struck through: the key no longer reaches
it), when it was last used, and expiry (or **Expired**). Search by name, owner, or a
key's start: pasting a whole leaked key works, and only its start is ever searched for.
Filter by state; a user's admin page links to their keys. **Revoke** stops a key at once.
"Sign out everywhere" ends a person's sessions but not their keys; deactivating them
revokes those too.

### AI agents [Phase 6]

**Admin → AI agents** (platform admins) registers kagent agents and shows the AI
settings in effect (read-only, from the deployment: whether AI is on, the kagent
controller's address, the run time limit, the default protocol, the namespaces agents may
run in and the MCP address agents use). **Register agent** asks for a name people will see
("Idea evaluator"), an optional description, the kagent Agent's **namespace** (one of
those in effect) and **name** (as in Kubernetes, lower case: mistakes show as you type), the
protocol (kagent 0.10 or 1.0), **what it does** (evaluate, research, draft proposal
sections) and **which projects** it serves. Under the fields, "Soundings will call …"
shows the one address runs go to: it is built from the controller address in effect and
the namespace and name, never typed.

Registering creates the agent's account (it shows with an AI badge, never signs in, can't
own ideas or be a project admin) and its **key**, shown **once** with the Kubernetes
Secret to apply and the agent's MCP server entry: hand them to whoever runs kagent, then
choose **I've copied it** (the dialog's last step is to test the connection). The key only
works while one of the agent's runs is open, on that run's idea. **Test connection**
fetches the agent's card through the controller and shows its name, skills and A2A
versions, or why it didn't answer with a list of what to check, most likely first (a
404 means the controller answered but has no ready agent by that name). **Change** edits the
name, description, protocol, purposes and projects (taking a purpose or project away
cancels its runs there; the key follows without a new Secret); **Rotate key** replaces the
key (the old one stops at once: apply the new Secret); **Disable** revokes the key and
cancels its runs (enabling it again needs a new key; a disabled agent's key reads "Revoked
when disabled"). The break-glass account may rename, narrow or disable an agent, but not
give it more purposes or projects. Agents are never deleted, so their
evaluations and notes keep their author. Each row shows the agent's runs in progress and
when its key was last used; **Runs and changes in the audit log** opens the log filtered to
AI. Project admins can remove an agent from their project (Members) and add it back.

### Audit log

Every sign-in (and refused sign-in, with the reason), admin change, project membership
and group grant change, owner and evaluator assignment, submitted evaluation, closing
and reopening of evaluation, status change, idea deletion, test email and email retry,
approval, rejection and erasure of public submissions (an erasure by the sender or by the
retention rules has no actor), branding changes, API keys created and revoked, every
MCP tool call (under "API keys and MCP": the tool, allowed or denied, and the key, never
what was asked; these entries are kept for 90 days), and AI agents registered and
changed, AI runs asked for and cancelled, AI evaluations counted or left out and research
notes deleted (under "AI agents and runs", naming the agent), newest first, one sentence each, for
example "Priya Natarajan added Lena Novak to group Tools members". Filter by who did it, what kind of action,
project, dates, or "About" a user or group; "Details" shows the raw fields. Entries
name ids, never emails, tokens or claims, and each records how the person had signed in
(single sign-on, break-glass or the development login) or which API key they used. The
log is kept indefinitely (MCP calls: 90 days).

## Who can do what

In plain words; [role-matrix.md](role-matrix.md) has every rule and its exceptions. A
project's **viewers**, **members** and **admins** come from its Members tab (directly or
through a group); **platform admins** act as an admin of every project. Being an idea's
**owner**, **evaluator** or **researcher** adds to your role on that idea only.

| | Viewer | Member | Idea owner | Researcher | Project admin | Platform admin |
|---|---|---|---|---|---|---|
| Read the project's ideas (internal projects: everyone signed in) | yes | yes | yes | that idea (also from outside a private project) | yes | yes |
| Submit ideas, comment, vote | watch only | yes | yes | comment on that idea | yes | yes |
| Volunteer to own an idea ("I'll own this") | | yes (where the project allows it) | | | yes | yes |
| Invite evaluators, set the due date, move the idea, close or reopen evaluation | | | yes | | yes | yes |
| Evaluate (evaluators are members or admins of the project) | | when invited | | | when invited | when invited |
| See the scores | unless you are a pending evaluator | same | same | never from outside a private project | same | same |
| Answer the research checklist | | | yes | yes, while the idea is in Research or before it | yes | yes |
| Ask someone to research, change the research due date | | | yes (in a private project: only people with a role there) | hand it back | yes | yes |
| **Move anyway** past Research with items open | | | | | yes | yes |
| Write the proposal, accept suggestions | | suggest text | yes | | yes | yes |
| Project settings: members, rubric, research step, proposal template, public form | | | | | yes | yes |
| Create projects; Admin (users, groups, sign-in, branding, email, API keys, AI agents, audit log) | | | | | | yes |

Pending evaluators never see anyone's scores, anywhere, until they submit their own.
