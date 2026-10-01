# End-to-end tests (Playwright)

Browser tests against the **real** Soundings stack: the FastAPI app serving the built
SPA, PostgreSQL and the seeded demo data, signed in with the dev login, and (Phase 2,
`E2E_SSO=1`) a real Keycloak 26 with the dev realm. No mocks (the SPA's own page tests
with MSW live in `frontend/tests/`). The test plans, with every case ID and the known
failures: [phase-1.md](../docs/test-plans/phase-1.md),
[phase-2.md](../docs/test-plans/phase-2.md).

```bash
npm --prefix e2e ci
npm --prefix e2e test                          # starts the stack on :8100, runs, stops it
E2E_KEEP_STACK=1 npm --prefix e2e test         # keep it; the next run only reseeds
E2E_BASE_URL=http://localhost:8000 npm --prefix e2e test   # an app that is already up (CI, make demo)
E2E_SSO=1 npm --prefix e2e test                # + Keycloak: the @sso specs run too
E2E_SSO=1 npm --prefix e2e test -- --grep @sso  # only the SSO specs (as CI's SSO jobs)
npm --prefix e2e run screenshots               # docs/screenshots/phase-1/*.png
npm --prefix e2e run screenshots:phase2        # docs/screenshots/phase-2/*.png (SSO, then break-glass)
npm --prefix e2e run check                     # tsc + prettier
npx --prefix e2e playwright test tests/board.spec.ts --headed
```

| Variable                     | Default      | Meaning                                                                                                                            |
| ---------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `E2E_BASE_URL`               | unset        | Test this app as it is: nothing is started or reseeded. It must have the demo data and `SOUNDINGS_DEV_LOGIN_ENABLED=true`.         |
| `E2E_PORT` / `E2E_PG_PORT`   | 8100 / 55433 | Ports of the local stack.                                                                                                          |
| `E2E_PREFIX`                 | `p1-qa-`     | Docker name prefix (the Postgres container is `<prefix>pg`, Keycloak `<prefix>kc`).                                                |
| `E2E_SSO`                    | `0`          | `1`: also Keycloak (fresh dev realm on every start) and the API with SSO next to the dev login. Break-glass is then off.           |
| `E2E_KC_PORT` / `E2E_KC_URL` | 8180 / unset | Keycloak's port for the local stack; `E2E_KC_URL` points the specs at another Keycloak (CI). Admin `admin`/`admin`.                |
| `E2E_BREAK_GLASS`            | `1`          | `0`: no break-glass admin. On (without SSO) it is `E2E_BREAK_GLASS_USERNAME` / `_PASSWORD` (`admin` / `e2e-break-glass-password`). |
| `E2E_KEEP_STACK`             | unset        | `1`: don't stop the local stack after the run.                                                                                     |
| `E2E_SKIP_BUILD`             | unset        | `1`: reuse the last SPA build in `e2e/.stack/dist`.                                                                                |
| `E2E_WORKERS`                | 2            | Parallel browsers.                                                                                                                 |
| `E2E_STATE_DIR`              | `e2e/.stack` | SPA build, API pid and log of the local stack. Give each stack run in parallel its own, with its own ports and prefix.             |
| `SCREENSHOTS`                | unset        | Set by the screenshot scripts: `phase-1` (or `1`) / `phase-2` runs only that screenshots spec.                                     |

**The local stack** (`scripts/start-stack.sh`, run by `global-setup.ts`): Postgres 16 in
Docker on tmpfs, `soundings migrate`, `soundings seed --reset --force`, `vite build` into
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
- **SSO specs** (Phase 2) are tagged `@sso` and start with `await requireSso()`, so they
  skip against an app without SSO. `tests/support/sso.ts` signs in through Keycloak's
  form in the browser (`ssoSignInAs(page, 'carol')`), signs out through the account
  menu, and changes Keycloak memberships with `withoutKeycloakGroup(user, path, body)`,
  which always puts the user back. Each sign-in needs a browser without a Keycloak
  session (a fresh context, `context.clearCookies()`, or after signing out).
- Some SSO specs need a fresh seed and realm (an identity links once): the local stack
  resets both on start, and so do CI's jobs.
- `@playwright/test` is pinned to 1.56.1 (the CI image); never run `playwright install`
  here, Chromium comes from `PLAYWRIGHT_BROWSERS_PATH`.
