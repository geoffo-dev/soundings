# 2. Project: Board and List

Route `/p/{project}` (`?view=board|list`, filters in the query string) · anyone who
passes `project.view` · SPEC 5, screen 2. One project's ideas, as a board by status or
a sortable table. The view choice is remembered per user.

## Desktop, List view (1440 px)

```
+------------------------+-------------------------------------------------------------------+
| (sidebar as My work)   |  Customer Innovation       [Board | List]  [## New idea ##]       |
|                        |                                                                   |
|                        |  [Status v] [Owner v] [Tag v] [Needs evaluators] [High disagr.]   |
|                        |  42 ideas                                Sort: Score (high) v     |
|                        |  +-------------------------------------------------------------+  |
|                        |  | Idea                    Owner Evals Score  Status      Upd. |  |
|                        |  |-------------------------------------------------------------|  |
|                        |  | CUST-3  Subscription    (C)   5/5   4.4    Proposal     1 d |  |
|                        |  | CUST-9  Partner API     (B)   4/4   4.2 !  Shortlisted  2 h |  |
|                        |  | TOOL-7  Flaky tests     (A)   3/3   3.8    Evaluating   4 h |  |
|                        |  | CUST-15 QR returns      (A)   2/3   Hidden Evaluating   3 h |  |
|                        |  | CUST-19 Loyalty tiers   --    0/0   --     New          5 m |  |
|                        |  | ...  (virtualised: 10k rows scroll smoothly)                |  |
|                        |  +-------------------------------------------------------------+  |
+------------------------+-------------------------------------------------------------------+
```

## Desktop, Board view

```
+------------------------------------------------------------------------------------------+
|  Customer Innovation                              [Board | List]  [## New idea ##]       |
|  [Status v] [Owner v] [Tag v] [Needs evaluators] [High disagreement]                     |
|                                                                                          |
|  New  6            Evaluating  9      Shortlisted  4     Proposal  2       Closed  21 >  |
|  +--------------+  +--------------+   +--------------+   +--------------+                |
|  | CUST-19      |  | CUST-15      |   | CUST-9       |   | CUST-3       |                |
|  | Loyalty tiers|  | Returns QR   |   | Partner API  |   | Subscription |                |
|  | for B2B      |  | labels       |   |              |   | boxes        |                |
|  | --   0/0  -- |  | (A)  2/3 Hid.|   | (B) 4/4 4.2 !|   | (C) 5/5 4.4  |                |
|  +--------------+  +--------------+   +--------------+   +--------------+                |
|  +--------------+  +--------------+   +--------------+                                   |
|  | CUST-21 ...  |  | TOOL-7 ...   |   | CUST-11 ...  |                                   |
|  +--------------+  +--------------+   +--------------+                                   |
+------------------------------------------------------------------------------------------+
```

## Mobile (390 px)

```
+--------------------------------------+
| [=] Customer Innov.     [Board|List] |
| [Filters (2)]            Sort: Score |
+--------------------------------------+
| CUST-3  Subscription boxes           |
| Proposal - (C) - 5/5 - 4.4      1 d  |
|--------------------------------------|
| CUST-9  Partner API                  |
| Shortlisted - (B) - 4/4 - 4.2 !  2 h |
|--------------------------------------|
| CUST-15 Returns QR labels            |
| Evaluating - (A) - 2/3 - Hidden  3 h |
+--------------------------------------+
|              [+ New idea]            |
+--------------------------------------+
```

Board on mobile: one column at a time, with status tabs across the top.

## Notes

- **Primary action:** "New idea" (pre-selects this project). Moving cards and sorting
  are direct manipulation, not buttons.
- **Board:** columns are the five fixed statuses with the project's labels. Closed is
  collapsed to a count and expands to Accepted / Rejected / Parked. Owners and admins
  can drag (`idea.change_status`); for everyone else cards have no drag handle.
  Dropping on Closed opens a small resolution picker. Moves are optimistic with an
  Undo toast; a failed move snaps back with an error toast.
- **List:** sortable headers (`aria-sort`), default sort by last update; the score
  sort follows the blind rule (hidden ideas sort as unscored). Rows are virtualised.
- **Filters:** chips for status, owner, tag, "Needs evaluators" (not closed, no
  evaluators yet) and "High disagreement". Filters live in the URL so views can be
  shared; "Clear" appears when any chip is active.
- **Loading:** skeleton rows (list) or skeleton cards (board) of final size.
- **Empty:** new project: "No ideas yet. Start with one you've been thinking about."
  [New idea] (or, for viewers, "Ideas will appear here"). Filtered empty: "No ideas
  match these filters" [Clear filters].
- **Error:** inline panel with Retry in place of the list; filters stay usable.
- **Keyboard:** `↑`/`↓` rows, `Enter` open, `N` new idea, `F` focuses filters, `V`
  toggles Board/List. Board moves with the keyboard: focus a card, `Space` to lift,
  arrow keys to move between columns, `Space` to drop, `Esc` to cancel; each step is
  announced to screen readers.
- **Mobile:** list is the default; the board shows one status at a time. Filters open
  in a bottom sheet. "New idea" is a sticky footer button.
