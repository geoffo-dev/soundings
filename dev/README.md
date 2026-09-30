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

Ports clash with something else? `cp dev/.env.example dev/.env` and change them there.

Backend settings for this stack:

```sh
export SOUNDINGS_DATABASE_URL=postgresql+psycopg://soundings:soundings@localhost:5432/soundings
export SOUNDINGS_DEV_LOGIN_ENABLED=true          # Phase 1 login stub
```

OIDC and SMTP settings (`SOUNDINGS_OIDC_*`, `SOUNDINGS_SMTP_*`) are listed in
`dev/.env.example`; the backend reads them from Phase 2 / Phase 3 on.

## Keycloak realm `soundings`

Confidential client **`soundings`** (secret `soundings-dev-secret`): standard code flow
only, **PKCE S256 required**, no direct grants. Redirect and post-logout redirect URIs:
`http://localhost:8000/*`, `http://localhost:5173/*`, `http://127.0.0.1:8000/*`,
`http://localhost:18081/*` (the local k3s ingress).

Tokens (ID token, access token, userinfo) carry:

- `groups`: full group paths, e.g. `["/innovation/admins", "/tools/members"]`
- `employee_no`: a managed user-profile attribute (editable by admins only), when set
- the usual `sub`, `email`, `email_verified` (all test users are verified), `name`, ...

Groups: `/innovation/admins`, `/innovation/members`, `/tools/members`, `/viewers`.

| User | Password | Groups | `employee_no` |
|---|---|---|---|
| `alice` (Alice Anders) | `password` | `/innovation/admins`, `/tools/members` | `E1001` |
| `bob` (Bob Brown) | `password` | `/innovation/members` | `E1002` |
| `carol` (Carol Chen) | `password` | `/innovation/members`, `/tools/members` | `E1003` |
| `dave` (Dave Davies) | `password` | `/tools/members` | none |
| `erin` (Erin Evans) | `password` | `/viewers` | none |

Emails are `<user>@example.com`. Keycloak's own mail (password reset, if you enable it)
goes to Mailpit.

Check the realm end to end (real code + PKCE flow, prints each user's claims):

```sh
python3 dev/keycloak/check_login.py                 # or: ... http://localhost:<port> alice
```

**Changing the realm:** edit `dev/keycloak/realm-soundings.json`, then
`make dev-down && make dev-up` (Keycloak re-imports only when the realm does not exist
yet; its dev database lives inside the container, so recreating the container is
enough). Changes made in the admin console are lost when the container is recreated.

## Sending a test email to Mailpit

```sh
python3 - <<'EOF'
import smtplib
from email.message import EmailMessage
m = EmailMessage(); m["From"] = "soundings@example.com"; m["To"] = "alice@example.com"
m["Subject"] = "Hello"; m.set_content("It works")
with smtplib.SMTP("localhost", 1025) as s: s.send_message(m)
EOF
```

Then open http://localhost:8025.

## Local Kubernetes (k3s in Docker)

```sh
make image              # soundings:dev
make k3s-up             # k3s in a container: API 127.0.0.1:16443, ingress http://localhost:18081
make k3s-install        # import the image, helm upgrade --install with dev/k3s-values.yaml
make k3s-smoke          # /healthz, /readyz, / through the ingress + helm test
make k3s-down
```

`export KUBECONFIG=$PWD/.k3s/soundings-k3s/kubeconfig` for your own kubectl, or use
`docker exec soundings-k3s kubectl ...`. Scripts and their settings: `scripts/k3s-*.sh`.
No Debian mirror reachable (e.g. a locked-down sandbox)? Build without the PDF libraries:
`make image IMAGE_BUILD_ARGS="--build-arg RUNTIME_APT_PACKAGES="` (PDF export then fails).
