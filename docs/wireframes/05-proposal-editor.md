# 5. Proposal editor

Route `/p/{project}/ideas/{key}/proposal` (the idea page's Proposal tab) · readers:
`proposal.view`; writers: `proposal.write` (owner, admins) · SPEC 5, screen 5. A calm
Markdown editor over the fixed template, with the outline on the left and comment
threads in the right margin.

## Desktop (1440 px), owner editing

```
+-----------------------------------------------------------------------------------------+
| CUST-3 Subscription boxes / Proposal          Saved 10:42        [## Export v ##]       |
|-----------------------------------------------------------------------------------------|
| OUTLINE            | 1. Summary                    [Write | Preview] | Comments (3)     |
| (*) Summary        | [B] [I] [Link] [List] [Draft with AI]           |                  |
| (*) Problem        | +---------------------------------------------+ | Summary          |
| ( ) Solution       | | A monthly curated box for existing          | | (C) Carol  2 h   |
| ( ) Market & users | | customers, starting with coffee and tea.    | | Can we quantify  |
| ( ) Cost & effort  | |                                             | | churn impact?    |
| ( ) Benefits       | +---------------------------------------------+ | [Reply][Resolve] |
| ( ) Risks          |                                                 |                  |
| ( ) Next steps     | 2. Problem                                      | Problem          |
|     / the ask      | +---------------------------------------------+ | (B) Bob    1 h   |
|                    | | Repeat purchase rate dropped 8% ...         | | Source for 8%?   |
|  (*) has content   | +---------------------------------------------+ | [Reply][Resolve] |
|                    |                                                 |                  |
|                    | 3. Solution                                     |                  |
|                    | +---------------------------------------------+ | [+ Comment on    |
|                    | | (empty: "Describe what we'd build...")      | |    this section] |
|                    | +---------------------------------------------+ |                  |
+-----------------------------------------------------------------------------------------+
```

## Suggested text (member suggestion or "Draft with AI", Phase 6)

```
| 3. Solution                                                         |
| +---------------------------------------------------------------+   |
| | Suggested by [AI] Research agent - 3 sources          [v]     |   |
| | We would partner with two local roasters and ...              |   |
| |                                    [ Discard ]  [## Accept ##]|   |
| +---------------------------------------------------------------+   |
```

## Mobile (390 px)

```
+--------------------------------------+
| <  Proposal - CUST-3      [Export v] |
| Section: [ 1. Summary            v ] |
|--------------------------------------|
| [Write | Preview]                    |
| +----------------------------------+ |
| | A monthly curated box for ...    | |
| +----------------------------------+ |
|                                      |
| [ Comments (3) ]  opens bottom sheet |
+--------------------------------------+
```

## Notes

- **Primary action:** Export (menu: PDF, Markdown). Saving is automatic. Before a
  proposal exists, the Proposal tab's primary action is "Start proposal" (owner, once
  shortlisted); others see "The owner will write a proposal once this idea is
  shortlisted."
- **Editor:** one auto-growing native `<textarea>` per template section with a
  Write/Preview toggle (react-markdown), a small toolbar (bold, italic, link, list)
  and native spellcheck. No editor library (research R2). Sections are fixed: Summary,
  Problem, Solution, Market & users, Cost & effort, Benefits/revenue, Risks, Next steps
  / the ask. The outline marks which have content.
- **Comments:** threads attach to a section (not character ranges), with Reply and
  Resolve; resolved threads collapse. Members and evaluators comment
  (`proposal.comment`); viewers read.
- **Saving:** debounced autosave with "Saving… / Saved 10:42". If someone else saved
  the same section meanwhile, a banner offers "Reload" or "Keep mine" (no silent
  overwrite).
- **Loading:** outline and headings render first; section bodies show skeleton lines.
- **Empty:** each empty section shows a one-line prompt as placeholder ("Who has this
  problem, and how do we know?").
- **Errors:** save failure keeps the text, shows an inline "Not saved. Retry" by the
  section and a warning if you try to leave. Export failure: toast with Retry.
- **Keyboard:** `⌘B` / `⌘I` / `⌘K` (link, inside the editor only), `⌘⇧P` toggles
  preview, `⌘⌥M` comments on the current section, `⌘S` saves now. The outline is a
  list of links that move focus to the section.
- **Mobile:** readable and commentable; editing works but isn't the target. The
  outline becomes a section picker; comments open in a bottom sheet.
