# 4. Evaluate sheet

Opens from the idea page (`E`), from My work, or from the email link
(`/p/{project}/ideas/{key}?evaluate=1`) · assigned evaluators (`evaluation.submit_own`)
· SPEC 5, screen 4. A side sheet over the idea page, so the idea stays readable while
scoring.

## Desktop (1440 px): scoring

```
+--------------------------------------------------+------------------------------------------+
| (idea page, dimmed but readable)                 | Evaluate                             [x] |
|                                                  | CUST-15 Returns QR labels                |
|                                                  | Due Fri 3 Oct - draft saved 10:42        |
|                                                  |------------------------------------------|
|                                                  | Value                          weight 3  |
|                                                  | How much does it help customers or us?   |
|                                                  | ( 1 | 2 | 3 |[4]| 5 )                    |
|                                                  | 4: clear benefit for a large group       |
|                                                  | [ Add a comment (optional)            ]  |
|                                                  |------------------------------------------|
|                                                  | Feasibility                    weight 2  |
|                                                  | ( 1 | 2 | 3 | 4 | 5 )                    |
|                                                  |------------------------------------------|
|                                                  | Effort                         weight 2  |
|                                                  | 1 = very little, 5 = a lot.              |
|                                                  | Lower is better; the score inverts it.   |
|                                                  | ( 1 | 2 |[3]| 4 | 5 )                    |
|                                                  |------------------------------------------|
|                                                  | ... Strategic fit, Risk                  |
|                                                  |------------------------------------------|
|                                                  | Overall recommendation                   |
|                                                  | ( Go | Maybe | No )                      |
|                                                  | [ Overall comment (optional)          ]  |
|                                                  |------------------------------------------|
|                                                  | 3 of 5 scored          [## Submit ##]    |
+--------------------------------------------------+------------------------------------------+
```

## After submitting: the reveal

```
+------------------------------------------+
| Evaluate                             [x] |
| Submitted. You can edit until the owner  |
| closes evaluation.                       |
|------------------------------------------|
| Value         you 4   others 4  4        |
|               mean 4.0                   |
| Feasibility   you 4   others 4  2        |
|               mean 3.3  ! spread 2       |
| Effort*       you 3   others 3  5        |
| ...                                      |
|------------------------------------------|
| Aggregate 3.8 (n=3)   High disagreement  |
| Recommendations  Go 1  Maybe 2  No 0     |
|------------------------------------------|
| [ Edit my evaluation ]      [## Done ##] |
+------------------------------------------+
```

## Mobile (390 px)

```
+--------------------------------------+
| [x]  Evaluate CUST-15     Due 3 Oct  |
|--------------------------------------|
| Value                                |
| How much does it help us?            |
| +------+------+------+------+------+ |
| |  1   |  2   |  3   | [4]  |  5   | |
| +------+------+------+------+------+ |
| 4: clear benefit for a large group   |
| [ Comment (optional) ]               |
|--------------------------------------|
| Feasibility ...                      |
|                                      |
+--------------------------------------+
| 3 of 5 scored     [#### Submit ####] |
+--------------------------------------+
```

## Notes

- **Primary action:** Submit. After submitting: Done.
- **Scoring controls:** one row per active criterion in rubric order: name, weight,
  one-line description, a 1–5 segmented control (a radio group), guidance for the
  hovered/focused score (from the rubric), and an optional comment that expands on
  focus. Inverted criteria say so in words, not only with a mark.
- **Drafts:** every change autosaves as a draft (debounced), with "Saving… / Draft
  saved 10:42". Closing the sheet never loses input. Drafts are private.
- **Validation:** Submit stays enabled; if something is missing it moves focus to the
  first unscored criterion with "Pick a score" (no disabled-button dead ends).
- **Reveal:** on success, other submitted scores fade in per criterion (200 ms,
  staggered; none with reduced motion). Includes AI evaluations only if the viewer can
  see them; the aggregate uses the included set (ADR 0006).
- **Loading:** the sheet opens instantly with skeleton rows while the rubric and draft
  load.
- **Errors:** load failure: inline message with Retry. Submit failure: toast with
  Retry, input kept. Evaluation closed meanwhile (409 `evaluation_closed`): banner
  "Alice closed evaluation; your draft wasn't submitted", controls read-only.
- **Empty:** not applicable (a rubric always has 3–6 criteria). If you're not an
  evaluator, `E` does nothing and the URL param is ignored.
- **Keyboard:** focus starts on the first unscored criterion. `Tab` moves between
  criteria; `←`/`→` or `1`–`5` set the focused score; `G` / `M` / `N` set the
  recommendation when it's focused; `⌘Enter` submits; `Esc` closes (draft kept).
  Focus is trapped in the sheet and returns to the Evaluate button on close.
- **Mobile:** full-height sheet; segments at least 44 px; the footer with the count
  and Submit is sticky.
