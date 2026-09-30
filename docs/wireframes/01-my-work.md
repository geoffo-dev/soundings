# 1. My work (home)

Route `/` · everyone signed in · SPEC 5, screen 1. Answers "what needs me now?" at a
glance: evaluations due, ideas I own, and what changed in my projects.

## Desktop (1440 px)

```
+------------------------+--------------------------------------------------------------+
| [S] Soundings          |  My work                                  [ New idea    N ]  |
|                        |                                                              |
| [ Search...  Cmd+K ]   |  Evaluations due  2                                          |
|                        |  +--------------------------------------------------------+  |
| > My work              |  | CUST-12  Self-serve returns portal     Due tomorrow    |  |
|     Evaluations    2   |  |          Customer Innovation - owner Bob               |  |
|     Ideas I own    5   |  |                                     [## Evaluate ##]   |  |
|                        |  |--------------------------------------------------------|  |
| Projects               |  | TOOL-4   Shared test data service      Due Fri 3 Oct   |  |
|   Customer Innovation  |  |          Internal Tools - owner Carol [  Evaluate  ]   |  |
|   Internal Tools       |  +--------------------------------------------------------+  |
|                        |                                                              |
|                        |  Ideas I own  5                                              |
|                        |  New          CUST-19  Loyalty tiers for B2B    0/0   --     |
|                        |  Evaluating   CUST-15  Returns QR labels        2/3   --     |
|                        |               TOOL-7   Flaky test dashboard     3/3   3.8    |
|                        |  Shortlisted  CUST-9   Partner API              4/4   4.2 !  |
|                        |  Proposal     CUST-3   Subscription boxes       5/5   4.4    |
|                        |                                          Show closed (7) >   |
|                        |                                                              |
|                        |  Recently updated in my projects                             |
|                        |  CUST-21  Carol commented on "Gift cards"          5 min     |
|                        |  TOOL-9   Status New -> Evaluating (Dave)          1 h       |
|                        |  CUST-18  New idea "Chat handover" by Bob          3 h       |
|                        |                                                              |
| [A] Alice Anders   [?] |                                                              |
+------------------------+--------------------------------------------------------------+
```

Legend (all wireframes): `[## Label ##]` is the one primary (accent) button;
`[ Label ]` is secondary; `2/3` is evaluator progress; `!` is the high-disagreement
flag (icon plus text on hover, never colour alone); `--` means no score yet.

## Mobile (390 px)

```
+--------------------------------------+
| [=]  My work                    [+]  |
+--------------------------------------+
| Evaluations due  2                   |
| +----------------------------------+ |
| | CUST-12                          | |
| | Self-serve returns portal        | |
| | Due tomorrow                     | |
| | [########## Evaluate ##########] | |
| +----------------------------------+ |
| | TOOL-4  Shared test data service | |
| | Due Fri 3 Oct       [ Evaluate ] | |
| +----------------------------------+ |
|                                      |
| Ideas I own  5                       |
|  Evaluating                          |
|   CUST-15 Returns QR labels   2/3    |
|  Shortlisted                         |
|   CUST-9  Partner API     4/4  4.2 ! |
|                                      |
| Recently updated                     |
|  CUST-21 Carol commented      5m     |
+--------------------------------------+
```

## Notes

- **Primary action:** "Evaluate" on the most urgent evaluation (overdue first, then
  soonest due). Every other row's Evaluate is secondary. "New idea" is a secondary
  button in the header (`N`).
- **Content rules:** Evaluations due lists ideas where I'm an evaluator and haven't
  submitted, sorted by due date; overdue rows say "Overdue 2 days" with an icon.
  Ideas I own are grouped by status in the fixed order; closed ones are collapsed.
  Recently updated shows the last 20 events in projects I can view.
- **Blind evaluation:** a score is never shown for an idea where I'm a pending
  evaluator; the cell reads "Hidden" (see [role matrix §3](../role-matrix.md)).
- **Sidebar counts:** Evaluations = due and not submitted; Ideas I own = not closed.
  Screen readers hear "Evaluations, 2 due".
- **Loading:** the header renders at once; each section shows 3 skeleton rows of the
  final height. No spinners.
- **Empty:** per section, friendly and actionable. Evaluations: "Nothing to evaluate.
  When someone asks for your view, it appears here." Ideas I own: "You don't own any
  ideas yet. Open a project and volunteer for one you care about." [Browse projects].
  A brand-new user with no projects sees internal projects they can browse and a
  hint to ask a project admin for access.
- **Error:** an inline message with Retry inside the failing section; the other
  sections still render.
- **Keyboard:** `↑`/`↓` move between rows, `Enter` opens the idea, `E` opens the
  evaluate sheet for the focused due row, `N` new idea, `⌘K` palette, `?` shortcuts.
  A skip link jumps past the sidebar.
- **Mobile:** the sidebar becomes a drawer (`[=]`); sections stack; the primary
  Evaluate button is full width; touch targets are at least 44 px.
