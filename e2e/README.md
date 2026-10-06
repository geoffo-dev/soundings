# End-to-end tests (Playwright)

Browser tests against the **real** Soundings stack: the FastAPI app serving the built
SPA, PostgreSQL and the seeded demo data, signed in with the dev login, (Phase 2,
`E2E_SSO=1`) a real Keycloak 26 with the dev realm, and (Phase 3) `soundings worker`
with Mailpit as the SMTP server, (Phase 4) the public form with the real ALTCHA proof
of work and PDF export through the API's WeasyPrint child, (Phase 5) API keys used
against `/api/v1` and the MCP server at `/mcp` exactly as a script or an MCP client would,
and (Phase 6, `E2E_AI=1`) AI runs through the worker to Soundings' fake kagent agent
(`dev/fake-agent`), which calls `/mcp` back with its service-account key.
No mocks (the SPA's own page
tests with MSW live in `frontend/tests/`). The test plans, with every case ID and the
known failures: [phase-1.md](../docs/test-plans/phase-1.md),
[phase-2.md](../docs/test-plans/phase-2.md), [phase-3.md](../docs/test-plans/phase-3.md),
[phase-4.md](../docs/test-plans/phase-4.md), [phase-5.md](../docs/test-plans/phase-5.md),
[phase-6.md](../docs/test-plans/phase-6.md).

```bash
npm --prefix e2e ci
npm --prefix e2e test                          # starts the stack on :8100, runs, stops it
E2E_KEEP_STACK=1 npm --prefix e2e test         # keep it; the next run only reseeds
E2E_BASE_URL=http://localhost:8000 npm --prefix e2e test   # an app that is already up (CI, make demo)
E2E_SSO=1 npm --prefix e2e test                # + Keycloak: the @sso specs run too
E2E_SSO=1 npm --prefix e2e test -- --grep @sso  # only the SSO specs (as CI's SSO jobs)
npm --prefix e2e run screenshots               # docs/screenshots/phase-1/*.png
npm --prefix e2e run screenshots:phase2        # docs/screenshots/phase-2/*.png (SSO, then break-glass)
npm --prefix e2e run screenshots:phase3        # docs/screenshots/phase-3/ (+ emails/), then E2E_SMTP=0
npm --prefix e2e run screenshots:phase4        # docs/screenshots/phase-4/ (+ pdf/, emails/)
npm --prefix e2e run screenshots:phase5        # docs/screenshots/phase-5/ (API keys, admin keys, suggestions)
npm --prefix e2e run screenshots:phase6        # docs/screenshots/phase-6/ (AI runs, evaluations, notes, agents; E2E_AI=1)
E2E_AI=1 npm --prefix e2e test                 # + the fake kagent agent: the @ai specs run too
E2E_AI=1 npm --prefix e2e test -- --grep @ai   # only the AI specs (as CI's e2e-ai job)
E2E_SMTP=0 npm --prefix e2e test               # no SMTP: in-app notifications only, admin banner
npx --prefix e2e playwright test --project=smtp-outage --no-deps   # only the Mailpit-outage specs
npx --prefix e2e playwright test --project=serial --no-deps        # only the @serial specs (global branding)
E2E_PUBLIC_PER_IP=5 npx --prefix e2e playwright test public-abuse --grep PA-06   # the per-address limit
npm --prefix e2e run check                     # tsc + prettier
npx --prefix e2e playwright test tests/board.spec.ts --headed
```

| Variable                           | Default         | Meaning                                                                                                                                      |
| ---------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `E2E_BASE_URL`                     | unset           | Test this app as it is: nothing is started or reseeded. It must have the demo data and `SOUNDINGS_DEV_LOGIN_ENABLED=true`.                   |
| `E2E_PORT` / `E2E_PG_PORT`         | 8100 / 55433    | Ports of the local stack.                                                                                                                    |
| `E2E_PREFIX`                       | `p1-qa-`        | Docker name prefix (the Postgres container is `<prefix>pg`, Keycloak `<prefix>kc`).                                                          |
| `E2E_SSO`                          | `0`             | `1`: also Keycloak (fresh dev realm on every start) and the API with SSO next to the dev login. Break-glass is then off.                     |
| `E2E_KC_PORT` / `E2E_KC_URL`       | 8180 / unset    | Keycloak's port for the local stack; `E2E_KC_URL` points the specs at another Keycloak (CI). Admin `admin`/`admin`.                          |
| `E2E_BREAK_GLASS`                  | `1`             | `0`: no break-glass admin. On (without SSO) it is `E2E_BREAK_GLASS_USERNAME` / `_PASSWORD` (`admin` / `e2e-break-glass-password`).           |
| `E2E_KEEP_STACK`                   | unset           | `1`: don't stop the local stack after the run.                                                                                               |
| `E2E_SKIP_BUILD`                   | unset           | `1`: reuse the last SPA build in `e2e/.stack/dist`.                                                                                          |
| `E2E_WORKERS`                      | 2               | Parallel browsers.                                                                                                                           |
| `E2E_STATE_DIR`                    | `e2e/.stack`    | SPA build, API pid and log of the local stack. Give each stack run in parallel its own, with its own ports and prefix.                       |
| `SCREENSHOTS`                      | unset           | Set by the screenshot scripts: `phase-1` (or `1`) / `phase-2` / `phase-3` / `phase-4` runs only that screenshots spec.                       |
| `E2E_SMTP`                         | `1`             | `0`: the stack runs without SMTP (in-app notifications only; platform admins see a banner). The email specs skip.                            |
| `E2E_MAILPIT_PORT` / `_SMTP_PORT`  | 8125 / 1125     | Mailpit's web/API and SMTP ports of the local stack (container `<prefix>mailpit`, emptied on every start).                                   |
| `E2E_MAILPIT_URL`                  | unset           | Mailpit's web/API URL for an app given with `E2E_BASE_URL` (the local stack's otherwise).                                                    |
| `E2E_MAILPIT_CONTAINER`            | unset           | The Mailpit container the outage specs may stop and start (needed with `E2E_BASE_URL`; GitHub CI sets it, GitLab can't).                     |
| `E2E_TIMEZONE`                     | `Europe/London` | The instance time zone of the local stack (dates in emails, digests, reminders).                                                             |
| `E2E_PUBLIC_PER_IP`                | `1000`          | Public submissions per client address and hour (the app's default is 10; every spec submits from 127.0.0.1). Changing it restarts the API.   |
| `E2E_ALTCHA_COST`                  | unset           | The ALTCHA proof-of-work cost (unset: the app's 5,000). Changing it restarts the API.                                                        |
| `E2E_TRUSTS_FORWARDED`             | unset           | `1`: the app given with `E2E_BASE_URL` trusts this runner's `X-Forwarded-For` (PA-05 runs; the local stack always does).                     |
| `E2E_AI`                           | `0`             | `1`: the fake kagent agent on `E2E_FAKE_AGENT_PORT` (8183), AI on, runs limited to `E2E_AI_RUN_TIMEOUT` (PT1M), "Idea evaluator" registered. |
| `E2E_FAKE_AGENT_URL` / `_KEYS_DIR` | unset           | The fake agent of an app given with `E2E_BASE_URL` and where it reads keys (`make demo DEMO_AI=1`: :8027, `dev/.fake-agent-keys`).           |

**The local stack** (`scripts/start-stack.sh`, run by `global-setup.ts`): Postgres 16 in
Docker on tmpfs, `soundings migrate`, `soundings seed --reset --force`, `vite build` into
`e2e/.stack/dist` (the frontend's own `dist/` is left alone), then `soundings api` and `soundings worker` in
the background (pids and logs in `e2e/.stack/`), with Mailpit `<prefix>mailpit` as their
SMTP server (emptied on every start; `node e2e/scripts/mailpit.ts list` shows what arrived). `scripts/stop-stack.sh` stops only what
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
- **Email specs** (Phase 3) read mail from Mailpit through `tests/support/email.ts` (on top
  of `scripts/mailpit.ts`): `requireEmail(api)` skips without SMTP;
  `newPeople(alice, ['nora', 'theo'])` creates people with run-unique addresses (the
  inbox is shared by the whole run, preferences are per person);
  `emailTo(person, /subject/, since)` waits for a message. Always filter by recipient and
  `since`. `links(mail)`, `visibleText(mail.HTML)` and `expectNoScoreData(...)` help with
  the checks.
- **Stopping Mailpit** (`stopMailpit()` / `startMailpit()`, always in `finally`): only in
  specs tagged `@smtp-outage`. They run in the `smtp-outage` project after every other
  spec, one at a time, and skip unless `canControlMailpit()` (a container this run may
  stop: the local stack's, or `E2E_MAILPIT_CONTAINER`). The worker retries 30 s after a
  failure, then 1, 2, 4… minutes: allow about 2.5 minutes after the restart. By
  Playwright's dependency rule a failing spec in `e2e` skips them (rerun them alone with
  `--project=smtp-outage --no-deps`), and naming a file that holds one
  (`email-acceptance`, `admin-email`) runs the whole `e2e` project first (add
  `--project=e2e` to run just that file's other tests).
- **Public form specs** (Phase 4) use `tests/support/public.ts`: `projectWithPublicForm(alice,
name, members, { form, branding })` (a fresh project, form on and moderated unless said
  otherwise), `Visitor` (no account, no session: the public API as the pages use it) and
  `solveAltcha` (the widget's PBKDF2 proof of work in Node), `fillPublicForm` and
  `humanCheckDone` for the browser (the SPA solves with its own worker). Every request comes
  from 127.0.0.1, which the stack trusts as its proxy: a spec that exhausts a per-address
  throttle claims an address of its own with `X-Forwarded-For` (`Visitor.open(url, address)`,
  `extraHTTPHeaders`), so the rest of the run isn't throttled. Challenges are limited to 30
  a minute per address: fetch one per submission.
- **Global state** (Phase 4): a spec that changes the global branding is tagged `@serial`
  and runs in the `serial` project (after `e2e`, before `smtp-outage`, one at a time), and
  puts the profile back in `finally`. A project's branding override is per project: no tag.
- **PDFs** are read with `tests/support/pdf.ts`: `readPdf` (pdf.js text per page and
  metadata), `pdfColours` (RGB colours in the content streams), `embedsFont` (an embedded
  font program's own name), `pdfImageCount`, and `renderPdfPages` (pdf.js in Chromium, for
  screenshots). `pdfjs-dist` is a dev dependency here; there is no poppler on the machine.
- **API keys and MCP** (Phase 5) use `tests/support/mcp.ts`: `KeyClient.open(url, secret)` is
  a client with the key only (`Authorization: Bearer`, no cookie, no CSRF header): `rest()`
  for `/api/v1`, `rpc()` / `connect()` / `toolNames()` / `call()` / `ok()` / `fails()` for
  `/mcp` JSON-RPC (stateless, so one POST per call), and `expectRefusedKey` for the one 401
  every refused key gets. Each client claims an address of its own with `X-Forwarded-For`:
  refused keys count towards 30 a minute per address, and the run shares 127.0.0.1. Keys are
  made with `api.createApiKey(...)` (the session API; the secret is only in that result) and
  revoked when the spec ends (25 keys per user). Specs that end someone's sessions or
  deactivate them create that person (`admin-api-keys.spec.ts` `newPerson`). Tests for
  contract rules that aren't built yet are `test.fail(true, …)`: they pass while the defect
  stands and fail once it is fixed (then drop the mark; none are left).
- **AI assistance** (Phase 6) uses `tests/support/ai.ts`: `aiTeam(alice)` (a project of the
  spec's own: Alice owns the ideas, Bob and Carol score, Farah is pending; `idea({status:
'shortlisted'})` starts a proposal), `registerAgent(admin, {projectIds, purposes, name})`
  (through the admin API; the key goes to the fake with `FakeAgent.giveKey`; the name's
  suffix picks the fake's behaviour: `agentName('slow')`, `-lingers`, `-fails`, `-asks`,
  `-blind-probe`, …), `askAgent` / `requestRun`, `waitRun`, `readEvents` (the run's SSE
  stream read to its end) and `retireAgents` (disables them: runs stop, keys revoked).
  `e2e/scripts/fake-agent.ts` reads what the fake saw of a run (`observations`, `waitFor`).
  AI specs are tagged `@ai` and skip (`skipWithoutAi`) unless AI is on and the fake
  answers. The stack's own "Idea evaluator" is left to the screenshots and `make ai-smoke`.
- `@playwright/test` is pinned to 1.56.1 (the CI image); never run `playwright install`
  here, Chromium comes from `PLAYWRIGHT_BROWSERS_PATH`.
