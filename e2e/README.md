# End-to-end tests (Playwright)

Browser tests against the **real** Soundings stack: the FastAPI app serving the built
SPA, PostgreSQL and the seeded demo data, signed in with the dev login. No mocks (the
SPA's own page tests with MSW live in `frontend/tests/`). The test plan, with every
case ID and the known failures, is [docs/test-plans/phase-1.md](../docs/test-plans/phase-1.md).

```bash
npm --prefix e2e ci
npm --prefix e2e test                          # starts the stack on :8100, runs, stops it
E2E_KEEP_STACK=1 npm --prefix e2e test         # keep it; the next run only reseeds
E2E_BASE_URL=http://localhost:8000 npm --prefix e2e test   # an app that is already up (CI, make demo)
npm --prefix e2e run screenshots               # docs/screenshots/phase-1/*.png
npm --prefix e2e run check                     # tsc + prettier
npx --prefix e2e playwright test tests/board.spec.ts --headed
```

| Variable                   | Default      | Meaning                                                                                                                    |
| -------------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `E2E_BASE_URL`             | unset        | Test this app as it is: nothing is started or reseeded. It must have the demo data and `SOUNDINGS_DEV_LOGIN_ENABLED=true`. |
| `E2E_PORT` / `E2E_PG_PORT` | 8100 / 55433 | Ports of the local stack.                                                                                                  |
| `E2E_PREFIX`               | `p1-qa-`     | Docker name prefix (the Postgres container is `<prefix>pg`).                                                               |
| `E2E_KEEP_STACK`           | unset        | `1`: don't stop the local stack after the run.                                                                             |
| `E2E_SKIP_BUILD`           | unset        | `1`: reuse the last SPA build in `e2e/.stack/dist`.                                                                        |
| `E2E_WORKERS`              | 2            | Parallel browsers.                                                                                                         |
| `SCREENSHOTS`              | unset        | Set by `npm run screenshots`: runs only the screenshots project.                                                           |

**The local stack** (`scripts/start-stack.sh`, run by `global-setup.ts`): Postgres 16 in
Docker on tmpfs, `soundings migrate`, `soundings seed --reset`, `vite build` into
`e2e/.stack/dist` (the frontend's own `dist/` is left alone), then `soundings api` in
the background (pid and log in `e2e/.stack/`). `scripts/stop-stack.sh` stops only what
it started. CI tests the container image instead (`make demo`, the GitLab `e2e` job).

**Writing tests**

- Import `test`, `expect` and helpers from `tests/support/fixtures.ts`.
  `signIn(page, 'alice')` signs the browser in through the API; `switchUserInUi` uses
  the login page.
- Read-only tests may use the seeded story (`backend/app/seed/content.py`). Anything
  that changes data creates its own project with `createTeamProject(...)`; the `api`
  fixture archives it afterwards, so tests run in parallel and rerun on one database.
- Locate by role and accessible name, as a screen reader would; wait for state, never
  for time.
- `@playwright/test` is pinned to 1.56.1 (the CI image); never run `playwright install`
  here, Chromium comes from `PLAYWRIGHT_BROWSERS_PATH`.
