# Performance check: "10k ideas feels instant" (Phase 7)

SPEC section 12 asks for an app that stays calm and fast with 10,000 ideas. This plan
says how we measure that, what we measured on 2026-10-06, the bottlenecks we found and
who should fix them. Everything here is runnable again; the numbers move by ±20 % on
the shared 4-CPU build machine (other agents were running; load average 1-2).
**Section 8 has the same measurements after the Phase 7 fixes (2026-10-07), taken side
by side with the code from before them.**

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
  p95 < 150 ms one at a time, My work (Pat's and an owner's) and its counts included
  since Phase 7 (the `xfail` is gone); writes < 250 ms. The timings freeze the test
  process's heap first (`frozen_heap`), as the API does after startup: otherwise one
  full garbage collection over the earlier tests' objects lands on a single sample.
- `tests/ideas/test_performance.py` (slow, Phase 1): list, board, My work and search p95
  and the keyset index plans at 10k.
- `e2e/perf/*.perf.ts`: soft budgets (LCP, interaction response, dropped frames); every
  run writes `e2e/perf/.stack/results/frontend.json`.

Not covered: real networks (all local; with B4 a 10 Mbit/s link adds ~1 s to a cold
load), Firefox and Safari, phones (390 px layouts render cards: same row components),
the PDF child (measured in Phase 4), MCP and AI runs under load.

## 8. After the Phase 7 fixes (2026-10-07)

**How.** Side by side on one data set (`e2e/perf/stack.sh up` on :8400, Postgres
`p7-fixb-pg`, reseeded before the browser runs): the code from before the fixes (commit
`fd32366`: its API on :8401 and its SPA build, driven by its own `load.py`, which sends
what that SPA sent: all of My work on every page, one moderation request per project)
and the fixed tree (API on :8400, the SPA with the image's `.br`/`.gz` twins, today's
`load.py`). Each pair ran back to back; load average 1-2 (other agents). Raw results:
`e2e/perf/.stack/results/p7-ab-*.json`. What changed, by bottleneck: B1 (C1 work counts,
50 evaluations due a page, the owned groups and due counts in one statement each), B2
(memoised list rows, no `flushSync`, fixed row heights, tooltips on hover), B3 (the idea
page out of the first load), B4 (Brotli/gzip twins, gzip for JSON), B6 (short searches,
tag counts, no parallel workers, fewer statements on the idea page), B7 (C2 moderation
counts in `GET /projects`), B8 (the keep-alive after the response), B9 (palette list a
frame later, idea and evaluate chunks preloaded when idle). Declined: B5 (2 workers).

### 8.1 One request at a time (`load.py --isolated 30`, p50 / p95 ms)

| Endpoint | Before | After |
|---|---|---|
| `GET /me/work`, Pat (1,000 due) | 134 / 180 | **55 / 67** |
| `GET /me/work`, Alice (owns 225 ideas in five groups) | 192 / 264 | **103 / 129** |
| `GET /me/work/counts` (the sidebar, new) | – | 22 / 29 |
| `GET /me/evaluations-due` (a page of 50, new) | – | 28 / 36 |
| `GET /search?q=pr` (two letters) | 129 / 162 | **14 / 17** |
| `GET /projects/{slug}/tags`, Alice / Pat | 105 / 143, 66 / 81 | **39 / 47, 33 / 43** |
| list `sort=-score`, Alice / Pat | 137 / 225, 98 / 133 | 77 / 86, 75 / 90 |
| list `sort=title`, Alice | 104 / 130 | 86 / 97 |
| board, Alice / Pat | 97 / 158, 69 / 91 | 82 / 99, 67 / 85 |
| board `sort=-score`, Alice / Pat | 111 / 155, 96 / 123 | 115 / 143, 93 / 120 |
| `GET /ideas/{key}`, Pat | 32 / 42 (14 statements) | 25 / 32 (10-11) |
| `GET /projects` (now with `pending_moderation_count`) | 28 / 33 | 32 / 37 |
| all reads, p95 over every operation: Alice / Pat | 153 / 128 | **101 / 83** |

Every read is now under 150 ms one at a time; the closest are the board by score
(120-143 ms: five sorted pages of 51 cards, about 45 ms of SQL and 50 ms of building 255
summaries) and an owner's My work. In-process (`make -C backend test-perf`, quiet
machine): board by score 142, an owner's My work 139, Pat's My work 71-74, everything
else ≤ 97 ms; writes ≤ 97 ms. A/B of the My work statements alone, in-process with
identical bodies: Alice 141 / 166 → 108 / 122, Pat 78 / 96 → 66 / 81.

### 8.2 Twenty people (`--think 2-8`, 120 s, two rounds each) and stress

| | Before (rounds 1, 2) | After (rounds 1, 2) |
|---|---|---|
| reads p95, all requests | 294, 268 ms | **255, 206 ms** |
| writes p95 (n = 50-60, noisy) | 196, 240 ms | 249, 167 ms |
| screen p50 / p95: app shell (cold load) | 227-232 / 639-722 | **56-59 / 429-468** |
| list | 109-120 / 256-296 | 93-97 / 194-213 |
| idea page | 93-106 / 282-292 | 77-89 / 203-341 |
| board | 123-133 / 242-371 | 118-129 / 226-299 |
| evaluate sheet | 47-51 / 1,066-1,095 | 40 / 891-957 |
| throughput, API CPU | 11.7 req/s | 11.6 req/s, 0.2 cores |
| stress (`--think 0`, 60 s): throughput, reads p95 | 59 req/s, 1,145 ms | **67 req/s**, 959 ms |
| API resident memory | 182 MB | 180-211 MB |

**Still over budget at 20 people** (reads p95 206-255 ms against 150). The medians are
well inside it; the tail is requests of overlapping screens sharing the one event loop
(B5, declined: scale with replicas, each pod has its own loop). A board of 255 cards or
an owner's My work costs 50-100 ms of Python, and the requests queued behind it wait.
The connection pool isn't it (a pool of 20 changed nothing, §4.1), nor garbage
collection (the startup heap is frozen; with collection off a board took the same).
Next steps if it matters: lighter summaries (the board builds 255 per call), a narrower
sort for the board by score (ids and the masked score first, the rest for 51 rows:
about 30 % less SQL in a hand-written trial), or two replicas.

### 8.3 Browser (4x CPU throttling; one cold-load run, two interaction runs)

| Metric | Before | After |
|---|---|---|
| My work cold, Pat: data shown / TBT / DOM nodes | 10.97 s / 9.5 s / 17,269 | **1.96 s / 0.25 s / 1,043** |
| My work cold, Alice: data shown / TBT | 3.14 s / 2.4 s | 3.31 s / 2.0 s (her 186 owned ideas still render) |
| List cold, Pat: FCP = LCP / data shown | 1.55 / 2.20 s | 1.40 / 2.07 s |
| Board cold, Pat: LCP / data shown / TBT | 1.69 / 3.39 / 1.85 s | 1.83 / 2.43 / 1.44 s |
| List cold, Alice: LCP / data shown | 1.36 / 1.81 s | 2.14 / 2.09 s (one run) |
| Bytes on a cold list load: JS / CSS / API | 1,236 / 98 / 609 kB | **400 / 14 / 19 kB** |
| First-load JS (`bundle-report.ts`) | 1,026 kB (326 gzip), 48 files | **636 kB (209 gzip), 28 files** |
| List scroll, 80 wheel ticks: long tasks / dropped frames / p95 frame | 147-157 (18-20 s) / 84-85 % / 267 ms | **55-71 (3.6-4.7 s)** / 75-77 % / 150-167 ms |
| Board column scroll: dropped frames | 49-56 % | 48-51 % |
| Sort by score: response / result shown | 256-360 / 790-973 ms | 224-232 / 746-874 ms |
| Filter "Needs evaluators": response | 256-264 ms | 168-208 ms |
| ⌘K open: response | 472-568 ms | 296-408 ms |
| Evaluate sheet: response / shown | 632-760 / 1,055-1,520 ms | 640 / 954-1,070 ms |
| Open an idea from the list: response / page shown | 128-136 / 760-879 ms | **248-264** / 700-720 ms |

The browser now fetches 101-110 JS files in all on a cold load (63-72 before): the
first load is smaller, and the idea page and evaluate sheet chunks follow when the
browser is idle (B9), so they show up in a load that waits for the network to settle.

**Still over the 100 ms interaction budget:** sort and filter (168-232 ms), ⌘K open
(296-408 ms), the evaluate sheet (640 ms), and opening an idea from the list, which got
**slower** to its first frame (128-136 → 248-264 ms) although the page shows sooner:
something now renders synchronously on that click (cause found in the final
verification: the idle preload paints the idea page in the click's frame, §9.2). List scrolling still drops three frames in four at 4x
throttling. LCP on Alice's cold list was 2.1 s in one run (1.4 s before); repeat it
before reading much into it.

### 8.4 Against the budgets now

| Area | Budget | After | |
|---|---|---|---|
| API reads one at a time, all (My work included) | p95 < 150 ms | 17-143 ms | pass |
| API writes one at a time | p95 < 250 ms | 25-97 ms | pass |
| 20 people, reads | p95 < 150 ms | 206-255 ms | **fail** (B5) |
| 20 people, writes | p95 < 250 ms | 167-249 ms | pass, barely |
| N+1 | none | none | pass |
| Cold LCP | < 1.5 s | 1.3-1.4 s (board 1.8, Alice's list 2.1 in one run) | mostly |
| Interactions | < 100 ms | 168-640 ms | **fail** |
| My work for 1,000 evaluations due | (instant) | data at 2.0 s cold, TBT 0.25 s | fixed |

## 9. Final verification (2026-10-07)

**How.** The perf stack on its own ports (:8100, Postgres `p7-final-perf-pg`), the final
tree's API, 4x CPU throttling, load average under 1. A/B by swapping only the SPA build
(with its `.br`/`.gz` twins) under the same API and data: the committed tree (`b5923e4`,
"HEAD"), the final tree, and the final tree with the idle preload of the idea route
turned off ("no preload", a scratch build). Three cold loads or four clicks per variant;
raw lines in the final verification's report.

### 9.1 My work: 10 ideas per owned group (lead decision 3)

My work now shows the first 10 ideas of each owned group with "Show N more" (50 at a
time: first from the up to 50 the response already holds, then through the group's
cursor, `GET /me/owned-ideas?status=`); no contract change.

| Alice (owns 186 open ideas in five groups), cold | HEAD (all rendered) | Final (10 per group) |
|---|---|---|
| data shown | 3.15-3.58 s | **2.48-2.83 s** |
| TBT after FCP | 1.98-2.10 s | **1.18-1.39 s** |
| longest task | 1.53-1.72 s | 0.90-1.18 s |
| DOM nodes | 3,560 | 1,854-1,893 |

Pat (1,000 evaluations due, owns nothing) is unchanged: data at 1.78 s, TBT 0.69 s,
1,043 nodes. Alice's remaining long task is the app's first render with its data (the
sidebar, the 50 evaluations due and five groups), not the groups.

### 9.2 Opening an idea from the list (lead decision 4)

| Variant | Response (input to next paint) | Page shown |
|---|---|---|
| Final tree (idle preload of the idea route, B9) | 200-216 ms (one run 312) | 684-924 ms |
| HEAD (the same code path) | 192-248 ms | 633-752 ms |
| Final tree without the preload | **152-176 ms** | 891-1,068 ms |

**Cause:** with the idea route's chunk already loaded, the router paints the idea page
(the list's cached summary and skeletons) in the click's own frame, so that frame
carries unmounting the list and mounting the page. Without the preload the click's frame
only starts the chunk download and the page appears about 250 ms later. §8.3's 128-136
ms "before" was that empty first frame. **Kept** as the better trade (the page shows
sooner); no cheap way to have both was found, since the router's store update renders
synchronously. Listed as a known issue in the release notes.

### 9.3 The final tree against the budgets (one run each)

| Interaction (4x throttling) | Response | Shown | Budget |
|---|---|---|---|
| List: sort by score | 200 ms | 782 ms | 100 ms: **miss** |
| List: filter "Needs evaluators" | 160 ms | 557 ms | **miss** |
| ⌘K open | 272 ms | 358 ms | **miss** |
| ⌘K, worst keystroke | 96 ms | results 172 ms after the last key | pass |
| Open an idea from the list | 208 ms | 684 ms | **miss** (9.2) |
| Evaluate sheet | 592 ms | 887 ms | **miss** |
| List scroll, 80 wheel ticks | p95 frame 133 ms; 70 % of frames dropped; 38 long tasks (2.4 s) | | **miss** (better than §8.3: 55-71 long tasks, 75-77 %) |
| Board column scroll | p95 frame 83 ms; 50 % dropped | | **miss** |

| Cold load (4x throttling) | LCP | Data shown | TBT |
|---|---|---|---|
| List, Pat / Alice | 1.34 / 1.54 s | 1.98 / 1.94 s | 0.36 / 0.33 s |
| Board, Pat | 1.37 s | 2.20 s | 1.31 s |
| My work, Pat / Alice | 1.13 / 1.23 s | 1.78 / 2.48 s | 0.69 / 1.23 s |
| Warm list, Pat | 0.75 s | 1.14 s | 0.23 s |

`make -C backend test-slow` (the in-process budgets, `tests/perf` included) passed on an
idle machine (6 tests, 160 s). The API was unchanged since §8, so §8.1-8.2 stand: every
read under 150 ms one at a time; at 20 people at once reads p95 206-255 ms (**miss**,
scale with `api.replicas`). These misses are the release notes' known issues.

## 10. Phase 8 review: My work for an owner, and this machine's baseline (2026-10-08)

The lead asked for the owner's My work (`me.work (owner)` in `tests/perf`, `my work
(owner)` in `tests/ideas/test_performance.py`) to fit the 150 ms read budget, and for the
budget to be raised only if 0.1.0's code also misses on an idle machine.

**Profile** (alice at 10k ideas: 50 evaluations due, 187 owned cards in six groups, 20
recent; in-process, warm): about 110-120 ms per request, of which SQL execution about 25
ms (owned groups 14.5, evaluations due 7, recent 5) and Python about 55-70 ms CPU, spread
over 14 statements (SQLAlchemy statement building, compile-cache keys and row handling
about a third of it), 260 cards' summaries and 225 KB of JSON (gzip 2.5 ms).

**Fixes** (contract-phase8 §10 R6, no response change): migration 0014's
`ix_ideas_owner_id_status_last_activity_at` (each owned group one range scan that stops
after the page; the groups' statement 14.5 → 8.9 ms), `ix_evaluations_idea_id_status` and
`ix_comments_idea_id_live` (the cards' submitted and comment counts index-only; 8.9 → 7.0
ms, every list and board gains the same per card; a partial index on `status =
'submitted'` was useless because prepared statements' generic plans bind the status); the
people of the page (due evaluations' owners, cards' owners, the latest activity's actors)
and the projects with your roles each in one statement (14 → 11 statements); page rows
read positionally. A/B on the same database, alternating runs (60 requests each, p50 /
p95 ms): 0.1.0-era code on the old indexes 118-141 / 139-166, the new code 107-111 /
127-139; the score-sorted board 117-125 / 135-160 → 110-115 / 131-135 (search unchanged).

**This machine, idle** (4 vCPUs, no other agent running, steal ≈ 0): one request's time
spreads widely (one run of the same My work: 93-190 ms, p50 118), so a round's p95 moves
by 20-40 ms between identical runs. **0.1.0's own code misses too**: `tests/perf` me.work
(owner) 161.1 and board -score 161.2; `test_performance` my work (owner) 142.4 then 185.6,
board -score 140.2 then 152.3 (`git archive 0046a9a`, same venv, same machine, the same
hour). The new code in the same hour: my work (owner) 134.9-170.7, me.work (owner)
143.5-174.4 per round.

**So the guards now** (lead's rule): reads keep the 150 ms budget; a read over it is
measured again, up to three rounds, and judged by its best (`best_p95`; a regression is
over in every round, and every round is printed); and the two heaviest reads, an owner's
My work (~260 cards) and the score-sorted board (masks and sorts every column), have 200
ms (`HEAVY_READ_BUDGET_MS` / `HEAVY_BUDGET_MS`). `make -C backend test-slow` passed with
them on the idle machine (6 tests, 214 s). `STATEMENT_BUDGET["me.work"]` (Pat) is
lowered from 12 to the 9 it now takes.

**The real fix for the owner's My work** is fewer cards per group in the response (the SPA
shows 10 per group and asks for more 50 at a time, §9.1): returning 10 instead of 50 would
cut its cards from about 260 to about 110. That changes `WorkOwnedGroup.ideas` ("the first
50"), so it is the lead's decision, not done here.
