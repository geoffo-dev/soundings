# Performance kit (Phase 7)

Measures "10k ideas feels instant" against a real stack. Results, budgets and the
bottlenecks found: [docs/test-plans/performance.md](../../docs/test-plans/performance.md).
Not part of the e2e suite (`playwright.config.ts` there only runs `tests/`).

## The stack

```bash
e2e/perf/stack.sh up      # ~2 min cold: Postgres + e2e stack + demo story + large data set
e2e/perf/stack.sh seed    # reseed only (after load tests added comments and ideas)
e2e/perf/stack.sh stats   # pg_stat_statements: statements by total time (PERF_STATS_LIMIT)
e2e/perf/stack.sh restart-api              # PERF_API_ENV="SOUNDINGS_WORKERS=2 ..."
e2e/perf/stack.sh down
```

It reuses `e2e/scripts/start-stack.sh` with its own ports and names: the app on
http://localhost:8320 (`PERF_PORT`), Postgres `p7-perf-pg` on 127.0.0.1:55436
(`PERF_PG_PORT`, started first with `pg_stat_statements`), state in `e2e/perf/.stack/`
(SPA build, logs, pid files, `results/`; git-ignored), no SMTP (the worker runs).
`PERF_SCALE=0.1` seeds a tenth of the ideas. The data set is
`backend/tests/perf/seed_large.py`; people sign in through the dev login: Pat Pending
`perf01@example.com` (owes 1,000 evaluations, blind), Alice (admin), `perf02`-`perf50`.

## API load (`backend/tests/perf/load.py`)

From `backend/`:

```bash
uv run python -m tests.perf.load --isolated 30                       # service times
uv run python -m tests.perf.load --duration 120 --think 2-8 \
  --api-pid ../e2e/perf/.stack/api.pid --worker-pid ../e2e/perf/.stack/worker.pid \
  --pg-container p7-perf-pg --json ../e2e/perf/.stack/results/load.json
uv run python -m tests.perf.load --think 0 --duration 60 --no-fail   # stress
```

20 people (`--users`) loop over screens with 2-8 s between them; the table lists p50,
p95, p99 and max per operation and per screen (all of a screen's requests), the
`/healthz` probe (event-loop lag), throughput, the API's and worker's memory and the CPU
of the API and Postgres. Exit 1 when a read p95 ≥ 150 ms or a write p95 ≥ 250 ms
(`--no-fail` to report only).

In-process checks (N+1, statements per request, p95 one at a time) seed their own test
database: `uv run pytest -m slow tests/perf -s` (~90 s; part of `make -C backend
test-slow`).

**Query plans:** turn on `auto_explain` for a run, then turn it off again (it times
every statement):

```bash
docker exec p7-perf-pg psql -U soundings -c "LOAD 'auto_explain'" \
  -c "ALTER SYSTEM SET session_preload_libraries = 'auto_explain'" \
  -c "ALTER SYSTEM SET auto_explain.log_min_duration = '25ms'" \
  -c "ALTER SYSTEM SET auto_explain.log_analyze = on" -c "SELECT pg_reload_conf()"
e2e/perf/stack.sh restart-api && (cd backend && uv run python -m tests.perf.load --isolated 3)
docker logs --since 5m p7-perf-pg > e2e/perf/.stack/results/auto_explain.log 2>&1
docker exec p7-perf-pg psql -U soundings -c "ALTER SYSTEM RESET ALL" -c "SELECT pg_reload_conf()"
e2e/perf/stack.sh restart-api
```

## Browser (`*.perf.ts`)

```bash
npx --prefix e2e playwright test -c e2e/perf/playwright.config.ts [load|interactions]
```

Chromium at 4x CPU throttling (`PERF_CPU_THROTTLE`), 1440 × 900, one test at a time,
against `PERF_BASE_URL` (default http://localhost:8320, the production build).

- `load.perf.ts`: cold loads (a fresh context: empty HTTP cache) of the list, the board
  and My work as Pat and as Alice, and a warm reload: FCP, LCP (and its element), when
  the content first shows, TBT after FCP, long tasks, JS/CSS/font/API bytes over the
  network, DOM size.
- `interactions.perf.ts`: wheel-scrolling the list (infinite loading) and a board column
  (frames from `requestAnimationFrame`, dropped frames, long tasks, heap), sort and
  filter, ⌘K open and search, opening an idea from the list and opening the evaluate
  sheet. "Response" is the Event Timing duration (input to the next frame painted, as
  INP measures it), "result" when the new content first shows.

Budgets are soft assertions (`expect.soft`): every metric is recorded and the misses
are listed. Each run merges its numbers into `e2e/perf/.stack/results/frontend.json`
(`PERF_RESULTS` to write elsewhere); the list reporter prints a `[perf]` line per
measurement. Type-check with `npx --prefix e2e tsc --noEmit -p e2e/perf`.

## Bundle

```bash
node --experimental-strip-types e2e/perf/bundle-report.ts --build [--json out.json]
node --experimental-strip-types e2e/perf/bundle-report.ts --dir <build with source maps>
```

`--build` builds `frontend/` with source maps into `e2e/perf/.stack/bundle` (the
production config plus `--sourcemap`; `frontend/dist` is untouched). For each chunk: raw
and gzip size, `*` when index.html preloads it (first load), and the packages and source
folders its minified bytes come from (through the source map). `BUNDLE_TOP` sets how many
chunks are listed (15).
