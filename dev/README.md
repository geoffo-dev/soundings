# Dev services

`dev/docker-compose.yml` runs everything Soundings talks to locally: **Postgres 16**,
**Keycloak 26** (realm `soundings`, imported on start) and **Mailpit** (catches all
email). Dev only: fixed passwords, Keycloak in dev mode, no TLS.

```sh
make dev-up       # start and wait until all three are healthy (~40 s the first time)
make dev-logs     # follow logs
make dev-down     # stop (data kept); `docker compose -f dev/docker-compose.yml down -v` wipes it
make dev          # how to run the backend and frontend dev servers against it
```

## URLs

| Service | URL | Credentials |
|---|---|---|
| Postgres | `localhost:5432`, database `soundings` | `soundings` / `soundings` |
| Keycloak admin console | http://localhost:8080/admin/ | `admin` / `admin` |
| Keycloak realm (issuer) | http://localhost:8080/realms/soundings | |
| Mailpit inbox + API | http://localhost:8025 (`/api/v1/messages`) | |
| Mailpit SMTP | `localhost:1025`, no TLS; any username/password is accepted | |
| Fake kagent agent (AI, optional) | http://localhost:8083 (`/api/a2a/<ns>/<name>/`, `/_fake/observations`) | keys in `dev/.fake-agent-keys` |

Ports clash with something else? Change them in `dev/.env` (below), and the URLs that
use them.

## Signing in with Keycloak (the dev flow end to end)

`dev/.env.example` has every setting for this stack: the compose ports, and the
backend's database, dev login, single sign-on against the dev realm and break-glass
admin. The backend reads `SOUNDINGS_*` from its environment, so export the file in
each shell that runs it:

```sh
make dev-up                          # Postgres, Keycloak (realm imported), Mailpit
cp dev/.env.example dev/.env         # once
set -a; . dev/.env; set +a           # every shell that runs the backend
make -C backend install migrate      # once, and after pulling migrations
make seed                            # demo data (below)
make -C backend dev                  # API on http://localhost:8000
npm --prefix frontend run dev        # SPA on http://localhost:5173 (proxies /api to :8000)
```

Open http://localhost:5173, choose **Sign in with SSO**, and sign in at Keycloak as
`alice` / `password`. Back in Soundings you are Alice Anders, platform admin: her
first SSO sign-in linked the seeded account by her external ID (`employee_no`
`E1001`), and group sync made her a synced member of "Innovation admins" and "Tools
team" (the seed's groups are mapped to the realm's groups). Admin → Sign-in (SSO)
shows the effective configuration; Admin → Audit log shows the sign-in (linked by
external ID). The dev login stays available below the SSO
button. Sign out signs you out of Keycloak too (`/login?signed_out=1`).

What makes it work:

- **One issuer for the browser and the API.** Both run on your machine and use
  `http://localhost:8080/realms/soundings`. Keycloak runs with `KC_HOSTNAME_STRICT=false`,
  so its issuer follows the URL used; an API in a container would need the same URL
  (e.g. `KC_HOSTNAME`), which is why the e2e stack and k3s set things up differently.
- **Each origin signs in on itself.** `SOUNDINGS_BASE_URLS` lists `:8000` and `:5173`;
  the redirect URI is `<origin>/api/v1/auth/callback` for the origin you browse, and
  the realm allows both.
- **The same flow without a browser:** `make sso-smoke` (`scripts/sso-smoke.sh
  http://localhost:8000`) signs alice in through Keycloak with curl, then checks the
  acceptance: a managed group mapped to `/tools/members` gives carol a private project;
  removed from that group in Keycloak, she loses it at her next sign-in. It cleans up
  after itself (needs `jq`).
- **Break-glass:** comment out `SOUNDINGS_OIDC_ISSUER` (break-glass works only while SSO
  is not configured), restart the API, and sign in on `/login` with `admin` /
  `dev-break-glass-password`.

## Demo data

`make seed` (or `soundings seed` in `backend/`, or the image's `seed` command) loads a
story told through the real services, backdated over the last two months: 12 people,
three projects and 48 ideas in every status, with owners, blind evaluations (submitted,
drafts, not started), due dates (some overdue), comments, votes and tags. It is the same
every time (people keep their ids), refuses `SOUNDINGS_ENVIRONMENT=production` unless
`--force`, and does nothing once the database has projects: `make seed RESET=1`
(`soundings seed --reset`) wipes all application data and loads it again. `--reset`
also wants `--force` once anyone who is not a demo person has an account (a real
sign-in): a hand-run reset defaults to development mode, so it never wipes a real
database by accident.

| Project | Key | Visibility | Notes |
|---|---|---|---|
| Customer Innovation | `CUST` | internal | 20 ideas, default rubric and proposal template, no research step |
| Internal Tools | `TOOLS` | private | 13 ideas, "Shortlisted" renamed "Next up"; research step **before evaluation** (the default checklist); proposal template Summary, Problem, Solution, Effort & rollout, Risks, The ask |
| Sustainability | `GREEN` | internal | 12 ideas, own rubric (carbon impact counts double), 14-day evaluation window; research step **before the proposal**; the default template plus "Carbon impact" |

Sign in with the dev login as any of them (emails are `<user>@example.com`; alice,
bob, carol, dave, erin and kenji match Keycloak users below, and alice, bob and carol
have the external IDs `employee_no` E1001–E1003):

| User | Name | Roles |
|---|---|---|
| `alice` | Alice Anders | **platform admin**; admin of CUST, member of TOOLS and GREEN. Five evaluations due (two overdue, one draft), owns ideas in five statuses; researches `GREEN-5`, **overdue** (asked by sven) |
| `bob` | Bob Brown | member of CUST and GREEN; **researches `TOOLS-12` as its guest** (not a member of the private Internal Tools: he sees that one idea, its feed and checklist, never its scores or proposal), due in 3 days, asked by dave |
| `carol` | Carol Chen | member of CUST and TOOLS, viewer of GREEN; owns `TOOLS-11`, in Research with its checklist complete |
| `dave` | Dave Davies | admin of TOOLS (edits its research checklist and proposal template; may "Move anyway") |
| `erin` | Erin Evans | viewer of CUST and GREEN (can look, not submit) |
| `farah` | Farah Haddad | member of CUST and GREEN |
| `kenji` | Kenji Watanabe | member of all three; owns `TOOLS-3`, whose proposal uses the TOOLS template and ends with the research appendix |
| `amara` | Amara Okafor | admin of GREEN, member of CUST; owns `GREEN-6`, Shortlisted with its checklist started, and researches it (asked by alice) |
| `mateo` | Mateo Rodríguez | member of CUST and TOOLS |
| `priya` | Priya Raman | admin of CUST, member of TOOLS and GREEN |
| `sven` | Sven Lindqvist | member of TOOLS and GREEN, viewer of CUST; owns `TOOLS-12`, in Research with "Departments or teams consulted" still open (the gate refuses Evaluating; bob researches it) |
| `zanele` | Zanele Dlamini | member of CUST and GREEN, viewer of TOOLS; owns `GREEN-4`, whose proposal has Carbon impact written |

Groups (Admin → Groups), mapped to the Keycloak realm's groups. Manual members
already hold the granted role directly, so the dev login shows the same access as
before; with SSO, sign-in syncs the Keycloak memberships. dave and erin link by
verified email.

| Group | IdP group (sync) | Grants | Manual members |
|---|---|---|---|
| Innovation admins | `/innovation/admins` (managed) | CUST admin | alice, priya |
| Innovation members | `/innovation/members` (managed) | CUST member | none |
| Tools team | `/tools/members` (managed) | TOOLS member | kenji, mateo |
| Viewers | `/viewers` (additive) | GREEN viewer | erin |
| Sustainability champions | not mapped | GREEN member | farah, sven, zanele |

Worth a look: blind evaluation on `CUST-11` (alice still owes her evaluation and sees no
scores; bob, the owner, sees the aggregate and its high-disagreement flag), the
disagreements on `CUST-8`, `TOOLS-2` and `GREEN-6`, and ideas that still need an owner
or more evaluators (`CUST-15`, `GREEN-10`). Phase 8: the TOOLS board's Research column
(`TOOLS-11` complete, its "Similar ideas" finding `CUST-14`; `TOOLS-12` with one required
item open: drag it to Evaluating as sven to see the gate, as dave to "Move anyway"); every TOOLS idea past Research was
researched by its owner first, and GREEN ideas pass through Research between the
shortlist and the proposal; the exports of `TOOLS-3` and `GREEN-4` end with "Research
and consultation". Phase 8b: sign in as bob for a guest researcher (My work's "Research
to do" with `TOOLS-12`, "Asked to research" in his inbox, the idea without its project's
board, scores or proposal; Internal Tools is 404 for him), as alice for an overdue research
assignment (`GREEN-5`), as sven or dave to see "Research: Bob Brown · not in this project"
on `TOOLS-12`. `TOOLS-11` keeps its owner doing the research (nobody assigned). The content
lives in `backend/app/seed/content.py` (Phase 8: `backend/app/seed/research.py`, Phase 8b:
its `ASSIGNMENTS`).

## The whole app from the image

```sh
make demo              # build the image, run Postgres + the app with dev login and demo data
                       # on http://localhost:8000 (DEMO_PORT=8001 for another port)
make demo-down         # remove the containers and their data
```

`make demo` re-run after a change rebuilds the image and restarts the app on it, keeping
the data (`DEMO_RESET=1` reseeds). The app and worker containers run as in Kubernetes:
read-only root filesystem with a writable `/tmp`, no capabilities. The image is Ubuntu
24.04 with its Python 3.12 and the Pango stack, so PDF export works in it (ADR 0011);
an internal Ubuntu mirror goes in `IMAGE_BUILD_ARGS="--build-arg
UBUNTU_MIRROR=http://mirror.internal/ubuntu"`. `make e2e` runs the Playwright suite in
`e2e/` against it.

The public form, branding and proposal export end to end (Customer Innovation's form
is on and moderated in the demo data): `make public-smoke` (default
http://localhost:8000; `PUBLIC_BASE_URL=` for another) sends an anonymous idea with a
solved ALTCHA, approves and shortlists it as Alice, writes and exports its proposal as
PDF and Markdown, and deletes it again. It solves the ALTCHA with `backend/`'s Python
(`ALTCHA_PYTHON=` for another, e.g. `docker exec -i soundings-demo-app python`).
`DEMO_PUBLIC_PER_IP=` raises the form's per-address limit (10 an hour) for `make demo`.

## Keycloak realm `soundings`

Confidential client **`soundings`** (secret `soundings-dev-secret`): standard code flow
only, **PKCE S256 required**, no direct grants. Redirect and post-logout redirect URIs
(`<origin>/*`): `http://localhost:8000`, `http://localhost:5173`,
`http://127.0.0.1:8000`, `http://localhost:8100` and `http://127.0.0.1:8100` (the e2e
stack), `http://localhost:18081` (the local k3s ingress). Another origin? Register it in
*your* Keycloak (the scripts do): `E2E_KC_URL=http://localhost:<kc port> node
e2e/scripts/keycloak.ts add-redirect-origin http://localhost:<app port>`.

Tokens (ID token, access token, userinfo) carry:

- `groups`: full group paths, e.g. `["/innovation/admins", "/tools/members"]`; no
  `groups` claim at all for a user in no groups
- `employee_no`: a user-profile attribute **only admins can edit** (and unmanaged
  attributes are off), as Soundings requires of an external-ID claim; when set
- the usual `sub` (fixed per user: the realm file sets the ids, so linked identities
  survive recreating Keycloak), `email`, `email_verified`, `name`, ...

Groups: `/innovation/admins`, `/innovation/members`, `/tools/members`, `/viewers`. Every
password is `password`.

| User | Email | Groups | `employee_no` | Tests |
|---|---|---|---|---|
| `alice` (Alice Anders) | alice@example.com | `/innovation/admins`, `/tools/members` | `E1001` | external ID (seeded), platform admin |
| `bob` (Bob Brown) | bob@example.com | `/innovation/members` | `E1002` | external ID |
| `carol` (Carol Chen) | carol@example.com | `/innovation/members`, `/tools/members` | `E1003` | the SPEC acceptance (remove her from `/tools/members`) |
| `dave` (Dave Davies) | dave@example.com | `/tools/members` | none | verified email |
| `erin` (Erin Evans) | erin@example.com | `/viewers` | none | verified email, additive group |
| `grace` (Grace Gale) | grace@corp.example | `/tools/members` | `E2001` | **only the external ID** can match: her email is nobody's; pre-create a user with `employee_no` E2001 |
| `mallory` (Mallory Mills) | farah@example.com, **not verified** | `/innovation/admins` | none | an unverified address naming seeded Farah: must be refused (`no_account`, reason `email_not_verified`) |
| `kenji` (Kenji Watanabe) | kenji@example.com | **none** (no claim) | none | in no groups: sync removes his managed synced memberships (`claim_found: false`) |
| `nia` (Nia Lee) | nia@example.org | none | none | verified, but no account: `no_account`, or created with `SOUNDINGS_OIDC_AUTO_CREATE_USERS=true` |

Keycloak's own mail (password reset, if you enable it) goes to Mailpit.

Check the realm end to end (real code + PKCE flow, prints each user's claims):

```sh
python3 dev/keycloak/check_login.py                 # or: ... http://localhost:<port> alice
```

Load the realm into a Keycloak that can't read this directory (a CI service), replacing
it, with extra redirect origins: `python3 dev/keycloak/import_realm.py
http://keycloak:8080 --origin http://testserver`. Change memberships and attributes
from tests or a shell with `e2e/scripts/keycloak.ts` (`group-add`, `group-remove`,
`set-attribute`, `logout`, `reset-realm`; see its header).

**End-to-end tests with SSO:** `E2E_SSO=1 npm --prefix e2e test` starts its own Keycloak
next to the e2e stack (`<E2E_PREFIX>kc` on `E2E_KC_PORT`, default 8180, a fresh realm on
every start) and runs the API with SSO and the dev login (`e2e/scripts/start-stack.sh`).

**Changing the realm:** edit `dev/keycloak/realm-soundings.json`, then
`make dev-down && make dev-up` (Keycloak re-imports only when the realm does not exist
yet; its dev database lives inside the container, so recreating the container is
enough). Changes made in the admin console are lost when the container is recreated.

## Email: Mailpit and the worker

Mailpit catches every email: inbox and API at http://localhost:8025, SMTP on
`localhost:1025` (plain, any credentials). `dev/.env.example` points the backend at it
(`SOUNDINGS_SMTP_HOST=localhost`, `_PORT=1025`, `_SECURITY=none`, `_FROM`) and sets the
time zone of digests and reminders. The API only **queues** email (an outbox row written
in the same transaction as the event); the **worker** sends it, retries it while SMTP is
down, and runs the reminders, daily digests and clean-up. Run it in a third shell:

```sh
set -a; . dev/.env; set +a
make -C backend worker               # soundings worker: email, reminders, digests
```

Then, signed in as Alice, add Bob as an evaluator of an idea: within seconds Mailpit
shows "Please evaluate ..." to bob@example.com, HTML and plain text, with a button that
opens the idea with the evaluate sheet (`/ideas/CUST-n?evaluate=1`). Links in emails use
the first of `SOUNDINGS_BASE_URLS` (`http://localhost:8000`, which serves the SPA once
`npm --prefix frontend run build` has built `frontend/dist`; put
`http://localhost:5173` first to open them in the Vite dev server). Admin → Email
shows the effective configuration, the outbox and **Send test email**; Settings →
Notifications has your own preferences (immediate, daily digest or off per type).

- **No worker running?** Email waits in the outbox (`queued`) and goes out when the
  worker starts; after 15 minutes platform admins see "Some emails aren't going out."
- **SMTP down:** `docker compose -f dev/docker-compose.yml stop mailpit`, trigger an
  email, and Admin → Email shows it queued with "connection refused"; `... start
  mailpit` and it arrives at the next retry (30 s, 1, 2, 4 minutes ... after each
  failure). After five connection failures in a row the worker pauses sending (30 s,
  doubling to 5 minutes): due emails wait without using an attempt, and the first one
  after the pause checks whether the server is back. Mailpit keeps its messages across
  a stop and start (not across `make dev-down`).
- **No email at all:** comment out `SOUNDINGS_SMTP_HOST`: the app works with in-app
  notifications only (the bell) and platform admins see a banner.
- **The same check without a browser:** `make email-smoke` (`scripts/email-smoke.sh`,
  needs `jq`) signs in with the dev login, invites an evaluator, checks the email in
  Mailpit (subject, evaluate link in both parts, `List-Unsubscribe`), then stops
  Mailpit, invites a second one, sees the email queued, starts Mailpit and waits until
  it arrives, once. It removes both evaluators again. Against `make demo`:
  `make email-smoke EMAIL_BASE_URL=http://localhost:8000 MAILPIT_URL=http://localhost:8026
  MAILPIT_CONTAINER=soundings-demo-mailpit`.
- **Preview the templates** without sending: `uv run soundings email-preview` in
  `backend/` writes every email, HTML and text, with sample data to `email-previews/`.

Mailpit's API is handy in scripts: `curl -s localhost:8025/api/v1/messages | jq
'.messages[] | {Subject, To}'`, `GET /api/v1/message/<ID>` (HTML, Text),
`/api/v1/message/<ID>/headers`, and `curl -X DELETE localhost:8025/api/v1/messages`
empties it.

## MCP clients and API keys

The API serves Soundings' MCP server at `/mcp` (streamable HTTP, stateless, JSON): with
`make -C backend dev` or `make demo` that is `http://localhost:8000/mcp`. Clients
authenticate with a personal API key, act as its owner (narrowed by the key's scopes and
projects) and see exactly what the app shows them: a pending evaluator gets no scores.
Every tool call is in Admin → Audit log (`mcp.call`).

**A key.** Sign in (dev login: carol is a member of Customer Innovation and Internal
Tools), open Settings → API keys, create one with the "Read with an assistant" preset (`read`,
`mcp`; "Evaluate with an assistant" adds `evaluate`), optionally restricted to some projects, and copy
it: it is shown once (`sdg_…`). Keys pause after 30 days without a sign-in (signing in
resumes them), and a key made with the dev login stops working when dev login is off.
Scripted, with the dev login:

```sh
api=http://localhost:8000/api/v1
carol=$(curl -s $api/auth/dev/users | jq -r '.[] | select(.email == "carol@example.com") | .id')
curl -s -c /tmp/carol.jar -H 'Content-Type: application/json' -d "{\"user_id\":\"$carol\"}" $api/auth/dev/login >/dev/null
csrf=$(awk '$6 ~ /soundings_csrf$/ {print $7}' /tmp/carol.jar)
export SOUNDINGS_API_KEY=$(curl -s -b /tmp/carol.jar -H "X-CSRF-Token: $csrf" \
  -H 'Content-Type: application/json' -d '{"name": "Claude Code", "scopes": ["evaluate", "mcp"]}' \
  $api/me/api-keys | jq -r .secret)
```

**Claude Code** (an HTTP server with a header; `claude mcp get soundings` checks it):

```sh
claude mcp add --transport http soundings http://localhost:8000/mcp \
  --header "Authorization: Bearer $SOUNDINGS_API_KEY"
```

That stores the key in your `~/.claude.json`. To keep it in the environment instead, a
project's `.mcp.json` expands variables:

```json
{
  "mcpServers": {
    "soundings": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer ${SOUNDINGS_API_KEY}" }
    }
  }
}
```

Then ask, for example, "Which Soundings ideas are waiting for my evaluation?" (Claude
calls `search_ideas` with `awaiting_my_evaluation`, then `get_rubric` and `get_idea`).

**Claude Desktop.** Its custom connectors sign in with OAuth, which Soundings doesn't
offer (keys are issued in the app), so connect through the `mcp-remote` stdio bridge
(npm; needs Node.js) with the key in a header file, which keeps it out of process lists.
`claude_desktop_config.json` (macOS `~/Library/Application Support/Claude/`, Windows
`%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "soundings": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.14.3", "http://localhost:8000/mcp",
               "--header-file", "/Users/you/.config/soundings/mcp-headers.txt"]
    }
  }
}
```

with `mcp-headers.txt` (mode 600) holding one line, `Authorization: Bearer sdg_…`.
`mcp-remote` refuses plain `http://` URLs other than localhost unless you add
`--allow-http`; use https for anything else.

**Checks.** `make mcp-smoke` (`scripts/mcp-smoke.sh`, against `MCP_BASE_URL`, default
:8000, with the demo data and dev login) runs the SPEC acceptance with curl JSON-RPC:
carol's key, `initialize`, the ten tools listed, blind `search_ideas` / `get_idea`,
`submit_evaluation`, `not_found` outside the key's project, `insufficient_scope`
without `write`, a foreign `Origin`, the audit entries, then revoke → 401 at the next
call (it creates and deletes a test idea). Checked on 2026-10-02 against this server:
the key snippet and `claude mcp add` above with Claude Code 2.1.287 (`claude mcp get
soundings`: Connected), `mcp-remote` 0.14.3 over stdio, the Python SDK (`mcp` 2.2) and
the Go SDK that kagent 0.10 uses (`go-sdk` 1.6.1).

## AI: the fake kagent

There is no kagent or model here, so AI assistance (Phase 6) runs against Soundings'
deterministic fake agent ([`fake-agent/README.md`](fake-agent/README.md)): it answers in
kagent v0.10.2's A2A layout and, for each run, calls `/mcp` with the agent's own key
(`get_rubric`, `get_idea`, `submit_evaluation` with a rationale and two sources per
criterion; a research note; a section draft). Everything else is the real app: the
worker's A2A client, deadlines and cancel, the run scope (c22), blind evaluation, SSE.

```sh
# dev/.env (from .env.example) turns AI on and points SOUNDINGS_KAGENT_URL at :8083
make -C backend dev                         # API (other shells: the worker, the SPA)
make -C backend worker                      # AI runs need the worker
make -C dev/fake-agent run                  # the fake on :8083; keys in dev/.fake-agent-keys
#   or: make fake-agent-image && docker compose -f dev/docker-compose.yml --profile ai up -d
#       (then the API must listen beyond loopback: SOUNDINGS_HOST=0.0.0.0 make -C backend dev)
make ai-smoke                               # register an agent (as alice), hand it its key,
                                            # test connection, "Ask AI to evaluate" watched by
                                            # a pending evaluator over SSE, the AI evaluation out
                                            # of the aggregate / included, research, a draft, a
                                            # cancelled slow run, the key refused outside runs
```

By hand: Admin → AI agents → Register agent (namespace `soundings`, any name,
purposes, Customer Innovation), copy the key it shows once and give it to the fake:
`printf 'Bearer %s\n' "$KEY" > dev/.fake-agent-keys/soundings.<name>` (the fake re-reads
it on every request; without a key the agent is "not found"). Test connection shows its
card. Then "Ask AI to evaluate" on a Customer Innovation idea. What the agent does
depends on its name's suffix: `-slow` works until cancelled or the deadline, `-fails`,
`-silent` (finishes without a result), `-asks`, `-rejects`, `-blind-probe`, `-strays`,
`-late`, `-no-cancel`, `-unavailable`, `-drops` (the README). What it saw of a run:
`curl -s localhost:8083/_fake/observations/<run id> | jq`.

The e2e stack does the same with `E2E_AI=1` (fake on :8183, an agent "Idea evaluator",
`soundings/idea-evaluator`, registered after every seed; `e2e/scripts/fake-agent.ts` for
specs), k3s with `make k3s-fake-agent k3s-install AI=1 k3s-smoke AI=1` (the fake as
`kagent/kagent-controller:8083`). kagent's own CRDs (v0.10.2) go into k3s with `make
k3s-kagent-crds`, which also dry-runs every kagent manifest against them
([`../deploy/kagent/README.md`](../deploy/kagent/README.md)).

## Local Kubernetes (k3s in Docker)

```sh
make image              # soundings:dev
make k3s-up             # k3s in a container: API 127.0.0.1:16443, ingress http://localhost:18081
make k3s-install        # import the image, helm upgrade --install with dev/k3s-values.yaml
                        # (dev login on; a post-install hook Job loads the demo data)
make k3s-smoke          # /healthz, /readyz, /, /metrics kept off the ingress, dev login with
                        # CSRF and My work, break-glass with the generated Secret, helm test
make k3s-down
```

**Single sign-on on k3s.** Keycloak runs in the cluster (`dev/k3s/keycloak.yaml`,
namespace `keycloak`, the dev realm) at `http://keycloak.localhost:18081`: browsers and
curl resolve `*.localhost` to your machine, the ingress routes that host to Keycloak,
and inside the cluster CoreDNS rewrites the name to Keycloak's Service, which listens on
the same port. So the issuer is the same for your browser and the app's pods.

```sh
make k3s-keycloak       # Keycloak + realm, the DNS rewrite, Secret soundings-oidc (~30 s)
make k3s-install SSO=1  # + dev/k3s-sso-values.yaml: issuer, client secret via existingSecret,
                        # groups and employee_no claims (dev login stays on)
make k3s-smoke SSO=1    # + scripts/sso-smoke.sh through the ingress: alice's code flow,
                        # carol's project access from her Keycloak group and its removal
                        # at the next sign-in, sign-out at Keycloak, an unverified email refused
scripts/k3s-keycloak.sh down
```

Then sign in at http://localhost:18081 with **Sign in with SSO** (alice / password);
Keycloak's admin console is http://keycloak.localhost:18081/admin/ (admin / admin).

**Email on k3s.** Mailpit runs in the cluster (`dev/k3s/mailpit.yaml`, namespace
`mailpit`) and its inbox is http://mailpit.localhost:18081:

```sh
make k3s-mailpit         # Mailpit (SMTP mailpit.mailpit.svc.cluster.local:1025)
make k3s-install SMTP=1  # + dev/k3s-smtp-values.yaml: SMTP, time zone, egress NetworkPolicies
make k3s-smoke SMTP=1    # + scripts/email-smoke.sh: invite -> email; Mailpit scaled to 0 ->
                         # queued -> scaled back -> delivered once
scripts/k3s-mailpit.sh scale 0|1    # the SMTP outage by hand; `down` removes it
```

**MCP on k3s.** `dev/k3s-mcp-values.yaml` restricts the API's NetworkPolicy to Traefik
and kagent's namespace (`kagent.enabled`), as an install with in-cluster agents would:

```sh
make k3s-install MCP=1   # + dev/k3s-mcp-values.yaml
make k3s-smoke MCP=1     # + scripts/mcp-smoke.sh through the ingress, and
                         # scripts/k3s-mcp-client.sh: the MCP SDK in a pod of namespace
                         # kagent calls http://soundings.soundings.svc.cluster.local/mcp with
                         # the key from a Secret (works; 401 once revoked), a pod in another
                         # namespace can't connect
```

`SSO=1 SMTP=1 MCP=1` combines them (CI does).

`export KUBECONFIG=$PWD/.k3s/soundings-k3s/kubeconfig` for your own kubectl, or use
`docker exec soundings-k3s kubectl ...`. Scripts and their settings: `scripts/k3s-*.sh`.
`make k3s-install` also puts a Traefik rate limit in front of the public form's API
(`dev/k3s/public-ratelimit.yaml`, through the chart's `ingress.publicApi.annotations`),
and `make k3s-smoke` runs `scripts/public-smoke.sh` through the ingress (PDF export in
the api pod) and checks that limit. The kubelet's disk eviction thresholds are 1 GiB
(`K3S_EVICTION_HARD`), not its percentage defaults, which evict every pod on a large
shared disk with gigabytes still free.
