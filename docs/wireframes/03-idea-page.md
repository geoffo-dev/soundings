# 3. Idea page

Route `/p/{project}/ideas/{key}` (e.g. `CUST-15`) · anyone who passes `idea.view` ·
SPEC 5, screen 3. The single place for an idea: content and conversation on the left,
state and people on the right. Tabs only for Overview / Evaluations / Proposal.

## Desktop (1440 px), viewed by the owner

```
+------------------------+----------------------------------------------------------------------+
| (sidebar)              | Customer Innovation / CUST-15                [Watch] [Vote 12] [...] |
|                        | Returns QR labels                           [## Close evaluation ##] |
|                        | Print-free returns: customers show a QR code at the drop-off point.  |
|                        | [Overview]  Evaluations 2/3   Proposal                               |
|                        |---------------------------------------------+------------------------|
|                        | Description                                 | Status  [Evaluating v] |
|                        | Today customers print a label, which ...    | Owner   (A) Alice      |
|                        | - works with the carrier's existing API     |                        |
|                        | - no printer needed                         | Evaluators        2/3  |
|                        |                                             |  (B) Bob        [v]    |
|                        | Activity                                    |  (C) Carol      [v]    |
|                        | (B) Bob submitted an evaluation      2 h    |  (D) Dave       [ ]    |
|                        | (C) Carol                            1 h    |  [+ Invite evaluator]  |
|                        |     Have we checked the carrier API         | Due     Fri 3 Oct      |
|                        |     limits?                     [Reply]     |                        |
|                        | --- Alice moved New -> Evaluating   1 d     | Score   3.8   n=2   !  |
|                        |                                             |  Value      ####-  4.0 |
|                        | +-----------------------------------------+ |  Feasibil.  ###--  3.0 |
|                        | | Write a comment, @ to mention           | |  Effort*    ####-  4.0 |
|                        | |                            [ Comment ]  | |  Strat. fit ####-  3.5 |
|                        | +-----------------------------------------+ |  Risk*      ####-  4.5 |
|                        |                                             |  * inverted            |
|                        |                                             | Tags  returns  +       |
|                        |                                             |                        |
|                        |                                             |                        |
+------------------------+---------------------------------------------+------------------------+
```

## Sidebar for a pending evaluator (blind)

```
| Evaluators        2/3  |
|  (B) Bob        [v]    |
|  (C) Carol      [v]    |
|  (D) You        [ ]    |
| Due     Fri 3 Oct      |
|                        |
| Score   Hidden until   |
|         you submit     |
| [##### Evaluate #####] |
```

## Evaluations tab

```
| Evaluations  2 submitted of 3                  Aggregate 3.8 (n=2)  High disagreement |
|---------------------------------------------------------------------------------------|
| (B) Bob       Go      Value 4  Feas. 4  Effort 3  Fit 4  Risk 4   "Solid, cheap..."   |
| (C) Carol     Maybe   Value 4  Feas. 2  Effort 5  Fit 3  Risk 5   "Carrier API..."    |
| [AI] Evaluator agent  Maybe  Value 3 ...   Excluded from score  [ Include ]  Sources >|
| (D) Dave      not submitted yet                                                       |
```

## Mobile (390 px)

```
+--------------------------------------+
| <  CUST-15             [Watch] [...] |
| Returns QR labels                    |
| Print-free returns: customers ...    |
| Evaluating - (A) Alice - Due 3 Oct   |
| [Details v]  (status, evaluators,    |
|              score, tags)            |
| [Overview] Evaluations  Proposal     |
|--------------------------------------|
| Description ...                      |
| Activity ...                         |
| [Write a comment...]                 |
+--------------------------------------+
| [############ Evaluate ############] |
+--------------------------------------+
```

## Notes

- **Primary action (one per view, top right, depends on who is looking):** pending evaluator:
  "Evaluate" (`E`). Owner: the next step for the status: "Invite evaluators" when there
  are none, "Close evaluation" when all are in, "Start proposal" when shortlisted.
  Everyone else: none; "Comment" is secondary.
- **Inline editing:** title, summary, description and tags are click-to-edit for
  people allowed to (`idea.edit_own` / `idea.edit_any`), with Save/Cancel and `Esc`.
  Status is a dropdown for owner and admins, a plain badge for others. Owner shows
  "I'll own this" when unowned and volunteering is allowed.
- **Score panel:** aggregate with `n`, per-criterion bars (inverted criteria marked),
  and the disagreement flag with an explanation on hover/focus ("Scores for Effort
  differ by 2 or more"). Hidden entirely for pending evaluators (role matrix §3).
- **Activity:** comments and events in one feed, newest last, with the composer at the
  bottom. Markdown with a preview; `@` opens a member picker. AI research notes appear
  here with an AI badge and sources (Phase 6).
- **Loading:** title and tabs render from the list cache immediately; description,
  activity and sidebar show skeletons.
- **Empty:** no description: "No details yet" (owner/submitter see "Add details").
  No activity: "No comments yet. Ask a question or share a thought." No evaluators
  (owner): "Invite 2–4 people to evaluate this idea."
- **Error / not found:** 404 shows "This idea doesn't exist or you don't have access"
  (same text for both, to avoid leaking). Failed saves keep the edit open with an
  inline error.
- **Keyboard:** `E` evaluate, `C` focus comment box, `S` status menu (owner/admin),
  `A` assign owner (admin), `1`/`2`/`3` switch tabs, `⌘Enter` posts a comment.
- **Mobile:** one column; the sidebar collapses into "Details"; the primary action is
  a sticky bottom bar.
