# Performance check: "10k ideas feels instant" (Phase 7)

SPEC section 12 asks for an app that stays calm and fast with 10,000 ideas. This plan
says how we measure that, what we measured on 2026-10-06, the bottlenecks we found and
who should fix them. Everything here is runnable again; the numbers move by ±20 % on
the shared 4-CPU build machine (other agents were running; load average 1-2).

## 1. Budgets

| What | Budget | Measured with |
|---|---|---|
| API reads, 20 people at once | p95 < 150 ms | `tests/perf/load.py` against a real server |
| API writes | p95 < 250 ms | `load.py`, `test_perf_large.py` |
| Interactions in the browser | < 100 ms from input to the next painted frame (Event Timing, what INP measures) | `e2e/perf/interactions.perf.ts` |
| Largest Contentful Paint, cold load, local | < 1.5 s | `e2e/perf/load.perf.ts` |
| Reference only | TBT < 200 ms (Lighthouse "good"); under 10 % dropped frames while scrolling | the same specs |

The browser runs Chromium at **4x CPU throttling** (`PERF_CPU_THROTTLE`), standing in for
a mid-range laptop. The API runs as shipped: one uvicorn worker, a pool of 5 + 5
connections, PostgreSQL 16 with the image's defaults (128 MB shared buffers) on tmpfs.

## 2. The data set

`backend/tests/perf/seed_large.py` adds, on top of the demo story, in about 40 s of bulk
SQL (deterministic, `hashtext`): 50 people; **Big Ideas** (`/p/big-ideas`, private, key
`BIG`) with **10,000 ideas** and 2,000 more across the demo projects (12,048 in all); tags,
votes (42k), watchers (50k); 3-5 evaluators on every idea past *new* (34.5k assignments);
**30.4k evaluations** (28k submitted, 150k scores); **31k comments** (one idea in a hundred
has 60); **125k feed events**; **23k notifications** (most older ones read); **61k audit
entries**. Pat Pending (`perf01@example.com`) owes 1,000 evaluations in Big Ideas and
submits none, so blind masking is in every query. Aggregates are recomputed through
`app.services.scoring`, then `VACUUM ANALYZE`.

## 3. How to run it

```bash
e2e/perf/stack.sh up           # Postgres p7-perf-pg on 55436 (pg_stat_statements), the e2e
                               # stack on http://localhost:8320 (production SPA build, API,
                               # worker, no SMTP), then the large data set (~2 min cold)
cd backend
uv run python -m tests.perf.load --isolated 30            # service times, one at a time
uv run python -m tests.perf.load --duration 120 --think 2-8 \
  --api-pid ../e2e/perf/.stack/api.pid --worker-pid ../e2e/perf/.stack/worker.pid \
  --pg-container p7-perf-pg --json ../e2e/perf/.stack/results/load.json   # 20 people
uv run python -m tests.perf.load --think 0 --duration 60 --no-fail       # stress
uv run pytest -m slow tests/perf -s                       # N+1, statement budget, p95 (~90 s)
cd ..
npx --prefix e2e playwright test -c e2e/perf/playwright.config.ts        # browser (~1.5 min)
node --experimental-strip-types e2e/perf/bundle-report.ts --build        # bundle analysis
e2e/perf/stack.sh stats        # the statements with the most total time
e2e/perf/stack.sh restart-api  # PERF_API_ENV="SOUNDINGS_WORKERS=2" etc.
e2e/perf/stack.sh down
```

`e2e/perf/README.md` has the details (knobs, the results files under
`e2e/perf/.stack/results/`). `make -C backend test-slow` also runs `tests/perf/` now.

**The load model.** Each virtual person signs in through the dev login and loops over the
screens they would use, weighted: the app shell's cold load, the board, the list (and a
few pages of scrolling), a filter or sort, ⌘K search as you type, an idea page (detail,
feed, AI runs, "mark read", sometimes the evaluations tab), the evaluate sheet, My work,
the inbox, the audit log (admins), the people picker, and one write in ten (comment, vote,
watch, evaluation draft, new idea, edit). The requests of a screen go out together, as
the SPA sends them (captured from the real SPA). Think time between screens is 2-8 s
(`--think`). A `/healthz` probe every 100 ms measures the event loop's lag.

## 4. Results (2026-10-06)

### 4.1 Against the budgets

| Area | Metric | Budget | Result | |
|---|---|---|---|---|
| API, one request at a time | read p95, every endpoint but My work | 150 ms | 8-132 ms (2-letter search 113-132, board by score 93-106) | pass |
| | `GET /me/work` p95 | 150 ms | 150-202 ms | **fail** |
| | write p95 | 250 ms | 20-71 ms | pass |
| API, 20 people, think 2-8 s, 1 worker | read p95, all requests | 150 ms | **262 ms** (11.8 req/s, API 0.18 cores, Postgres 0.21) | **fail** |
| | read p95 of a separate one-at-a-time client during that load | 150 ms | idea 69 ms, board 113 ms | pass |
| | screen p95 (all its requests) | (300 ms) | list 194, board 282, shell 530, idea page 615, evaluate sheet 893 ms | |
| | write p95 | 250 ms | 301 ms | **fail** |
| Same, 2 uvicorn workers | read p95 | 150 ms | 332 ms (same machine minutes later; screen p50 −35 %) | fail |
| Stress, no think time, 1 worker | throughput | | 77 req/s at 0.96 API cores (saturated), reads p95 845 ms | |
| N+1 | statements vs page size | none | none: constant for page 5 vs 50-100 on every list | pass |
| Memory | API / worker RSS | | 195-215 MB / 165 MB (2 workers: 424 MB) | |
| Browser, 4x CPU | LCP, cold `/p/big-ideas` | 1.5 s | 1.01-1.03 s (data shown 1.36-1.65 s) | pass |
| | LCP, cold `/` My work | 1.5 s | 0.91-1.06 s, **but data shown 5.9 s** for Pat (TBT 6.3 s) | pass / **fail in spirit** |
| | TBT, cold list / board | (200 ms) | 270-422 ms / 923 ms | over |
| | list scroll, 80 wheel ticks | (10 % dropped) | 70 % dropped, 112 long tasks = 11.8 s | **fail** |
| | board column scroll | (10 %) | 40 % dropped, 8 long tasks (max 62 ms) | over |
| | sort by score / filter | 100 ms | 224 / 176 ms (result shown 718 / 500 ms) | **fail** |
| | ⌘K open / keystroke / results after last key | 100 ms | 304 / 72 / 160 ms (150 ms is the debounce) | **fail** / pass / ok |
| | open an idea from the list | 100 ms | 88 ms (page shown 551 ms) | pass |
| | open the evaluate sheet | 100 ms | 496 ms (sheet shown 1.08 s) | **fail** |
| Bundle | first-load JS | | 1,026 kB raw / 326 kB gzip in 48 files (browser: 1,236 kB in 72 files, uncompressed on the wire) | see B3, B4 |

### 4.2 Service times (one request at a time, p50 / p95 ms, Pat Pending)

| Endpoint | p50 | p95 | Statements |
|---|---|---|---|
| `GET /me/work` (1,000 due) | 116 | 202 | 12 (17 for an owner with all five groups) |
| `GET /search?q=pr` (two letters, ⌘K while typing) | 94 | 132 | 3 |
| board `sort=-score` / list `sort=-score` / list `sort=title` | 75 / 65 / 61 | 93 / 75 / 87 | 7 |
| `GET /projects/{slug}/tags` | 55 | 78 | 4 |
| board / list (default order) | 59 / 40 | 75 / 49 | 7 |
| list `needs_evaluators` / `q=pricing` / `status=evaluating` | 54 / 45 / 36 | 64 / 52 / 55 | 7 |
| `GET /ideas/{key}` | 33 | 42 | **14** |
| `GET /projects/{slug}` / `GET /projects` | 25 / 24 | 31 / 30 | 6 / 2 |
| feed (60 comments) / AI runs / evaluations / evaluate sheet | 23 / 20 / 18 / 14 | 34 / 26 / 25 / 21 | 7 / 7 / 7 / 6 |
| inbox / audit log (Alice) / people picker / members | 18 / 16 / 14 / 15 | 21 / 20 / 17 / 20 | 3 / 5 / – / 4 |
| `GET /search?q=pricing` / notification summary / `auth/me` / branding | 19 / 12 / 7 / 3 | 25 / 14 / 9 / 4 | 3 / 2 / 1 / – |

Writes, one at a time (p95): comment 59-64 ms, vote 20-22, evaluation draft 35-41, new
idea 51, edit 43-71.

### 4.3 Bundle (production build, `bundle-report.ts`)

134 chunks, 1,681 kB (552 kB gzip). The entry chunk is 344 kB (102 kB gzip) and holds
`src/features/idea` (91 kB), `src/features/ai` (28 kB), the router (58 kB), `src/api`
(36 kB) and cmdk (11 kB); React is its own 214 kB chunk; **react-markdown and micromark
(160 kB) are preloaded on every page**; Radix dialog, tooltip and Sonner add 38 kB each.
No source maps ship; the API serves no compressed variants.

## 5. Bottlenecks and fixes (most impact first)

**B1. My work is heavy and fetched on every page** (backend `app/services/work.py`, lead
for the contract, frontend `components/layout/sidebar.tsx`, `features/work/`). The sidebar's
three counts read the whole `GET /me/work` (`useWorkCounts` shares it): 116 ms of
service time and 240-513 kB of uncompressed JSON on every app load, refetched every two
minutes. `_evaluations_due` loads full `Idea` and `Project` rows (with `description_md`)
for all 1,000 due evaluations. The My work page then renders all of them: for Pat one
4.8 s long task, 17,269 DOM nodes, data shown at 5.9 s (Alice: 1.5 s task, 4,652 nodes).
*Fix:* a cheap counts endpoint for the sidebar (or the counts in
`/me/notifications/summary`, which the bell polls anyway); cap `evaluations_due` at 50
with a "Show all" page (revisits decision F9, which kept it uncapped at 118 ms); select
only the columns the item needs; render the first 50 and page or virtualise the rest.

**B2. The list re-renders every visible row on every scroll event** (frontend
`features/project/list/list-view.tsx`). `useVirtualizer` defaults to `useFlushSync: true`
(a synchronous React render inside each scroll event) and `IdeaTableRow` isn't memoised,
so ~40 rows (each with Radix tooltips, an avatar, a relative time) render per event: 112
long tasks totalling 11.8 s over 80 wheel ticks, frames p95 150 ms. **Measured fix**
(`React.memo` on the row + `useFlushSync: false`, built in a scratch copy): 22 long tasks,
1.4 s, max 99 ms. *Also:* a fixed 44 px row in table mode instead of `measureElement`;
mount tooltips on hover/focus only; `useMemo` the flattened items. The board (6,500 DOM
nodes, TBT 923 ms on load) gains from the same row and tooltip changes.

**B3. The idea page, AI and Markdown load on every first visit** (frontend
`routes/_app/ideas.$ideaKey.tsx`). The route imports `IdeaPageSkeleton` and
`IdeaNotFound` from `features/idea/idea-page`; TanStack's code splitting keeps
`pendingComponent` in the main chunk, so the whole idea page and its imports follow it.
**Measured fix** (scratch build without those two imports): first-load JS 1,026 kB to
622 kB (326 to 204 kB gzip), 48 to 25 files, Markdown no longer preloaded; the cold list
load fetched 914 kB instead of 1,236 kB. Move both into `idea-page-states.tsx`, as
`p.$slug.tsx` does with `project-page-states`.

**B4. Nothing is compressed** (platform `Dockerfile`/build, backend `app/spa.py`,
`app/main.py`, Helm ingress). JSON goes out raw (board 213 kB per page of 50 cards, My work
up to 513 kB, a list page 78 kB) and so do assets (entry 352 kB, which gzips to 102 kB;
CSS 100 kB to 21 kB). Air-gapped installs often have no compressing proxy. *Fix:*
precompressed `.gz`/`.br` assets at image build, served by the SPA handler with
`Vary: Accept-Encoding` (no CPU at request time); gzip for JSON over 1 kB
(`GZipMiddleware`, level 5) or in the chart's ingress annotations; measure the CPU.

**B5. One event loop, bursty screens** (platform Helm `workers`, backend). The SPA sends
5-13 requests per screen; one uvicorn worker interleaves them on one core, so a request's
latency is closer to the whole screen's than its own. At 20 people and 0.18 cores average,
reads p95 is 262 ms, while a separate client making one request at a time during the same
load sees idea p95 69 ms and board 113 ms. Two workers cut screen p50 by a third (+145 MB)
but not the tail; the remaining tail is not fully isolated (see B8). One worker saturates
at about 77 req/s. *Fix:* fewer requests per screen (B1, B7), less CPU per request (B6),
and `workers: 2` as the chart's default with `PROMETHEUS_MULTIPROC_DIR` set; trace a slow
screen with the existing OpenTelemetry hooks before going further.

**B6. Query costs at 10k** (backend; plans in `e2e/perf/.stack/results/auto_explain.log`
when captured, `stack.sh stats`):

- `GET /search` with one or two letters (⌘K as you type): the trigram indexes cannot
  narrow `%pr%`, so 12,248 rows are rechecked and sorted by `similarity()` with
  `description_md` in every row: 130 ms. *Fix:* below three characters match idea keys
  and title prefixes only; select summary columns only.
- `GET /projects/{slug}/tags`: `count(distinct idea_tags.idea_id)` with a nested loop of
  15,121 index probes into `ideas` (the planner expected 2,151): 58-108 ms on every
  project page load. *Fix:* `count(*)` (the primary key makes it distinct) and
  `ideas.project_id = :p` so the planner hashes; or drop the counts (S2).
- Every list page counts its `total` again (13 ms default, 36 ms filtered: a sequential
  scan), cursor pages too, though the SPA reads `total` from the first page only. *Fix:*
  count on the first page only (S3).
- Sorting by score (board and list, 75-106 ms): six correlated subqueries per row
  (evaluators, submitted, my state, comments, voted, tag ids) and the blind
  `score_visible` subplan run over all ~2,000 ideas of a status before the top 50 are
  picked. *Fix:* pick the page's ids first (sort on the cached `aggregate_score` with
  the visibility predicate) and compute the per-row extras for those 50 only.
- `GET /ideas/{key}` sends 14 statements for one idea, the most of any request.

**B7. The shell asks for moderation counts project by project** (frontend sidebar, lead
for the contract). Admins send `GET /projects/{slug}/moderation?limit=1` for every
project they administer, on every load (4 for Alice). *Fix:* a
`pending_moderation_count` on `GET /projects` items for admins.

**B8. Session keep-alive writes inside the request's transaction** (identity
`app/services/sessions.py` `resolve_session`). Once a minute per session the request that
passes the throttle updates `user_sessions.last_seen_at` and `users.last_seen_at` and holds
the row lock until it commits; the screen's other requests, which passed the same check,
wait for it: `UPDATE users` mean 25 ms, max 163 ms (other updates < 1 ms); a forced-touch
burst of 7 requests took 160-318 ms against 129-157 ms without. *Fix:* touch in its own
short transaction with `WHERE last_seen_at < now() - interval '1 minute'` (one winner,
no waiting), as API keys already do for `last_used_at` (`app/api_keys/verify.py`).

**B9. Interactions over 100 ms** (frontend). Sort 224 ms and filter 176 ms to the first
frame (the busy state shows at 250 / 194 ms): render the header's new state first and
the URL navigation in a transition. ⌘K open 304 ms with a 247 ms long task: keep the
first frame of the palette light (mount groups after it opens, prefetch on idle).
Evaluate sheet 496 ms to the first frame and 1.08 s to show: preload its chunk when the
primary action renders or on hover. Opening an idea from the list (88 ms) is in budget.

## 6. Simplifications (SPEC section 15 item 3)

- **S1.** The sidebar's evaluation badge needs one number, not My work. A count (or the
  bell's summary carrying it) removes the heaviest request from every page.
- **S2.** Tag counts in the filter menu cost the second-heaviest read of every project
  page; tags without counts would do (counts could stay in project settings).
- **S3.** `total` on the first list page only.
- **S4.** My work lists the first 50 evaluations due; "Show all" for the rest.

## 7. Regression guards

- `tests/perf/test_perf_large.py` (slow): no N+1 on nine lists and on evaluations
  (3 vs 5 evaluators); `STATEMENT_BUDGET` per request (raise it only with a reason); read
  p95 < 150 ms one at a time (My work is `xfail`, non-strict, until B1); writes < 250 ms.
- `tests/ideas/test_performance.py` (slow, Phase 1): list, board, My work and search p95
  and the keyset index plans at 10k.
- `e2e/perf/*.perf.ts`: soft budgets (LCP, interaction response, dropped frames); every
  run writes `e2e/perf/.stack/results/frontend.json`.

Not covered: real networks (all local; with B4 a 10 Mbit/s link adds ~1 s to a cold
load), Firefox and Safari, phones (390 px layouts render cards: same row components),
the PDF child (measured in Phase 4), MCP and AI runs under load.
