# Soundings operator guide

> Filled in phase by phase (noted in brackets) and completed in Phase 7; headings without
> text are still to come.
> Audience: whoever installs and runs Soundings on Kubernetes. The Helm chart's own
> reference is `deploy/helm/README.md` and `values.yaml`; this guide explains choices
> and procedures.

## Overview [Phase 0–1]

### What gets deployed: one image, `api` and `worker` Deployments, migration Job

One container image serves the REST API and the single-page app (`soundings api`) and
runs background jobs (`soundings worker`). The Helm chart (`deploy/helm/`) deploys it as
two Deployments, `api` and `worker`, plus PostgreSQL (bundled for small installs, or
your own). Migrations run before new pods serve: in init containers with the bundled
database, in a `pre-install,pre-upgrade` hook Job (Argo CD `PreSync`) with an external
one; why there are two paths is in the [chart README](../deploy/helm/README.md#migrations-why-two-paths).
The full values reference is that README and `values.yaml`; this guide explains the
choices.

### Requirements: Kubernetes version, PostgreSQL 16, ingress or Gateway API

Kubernetes 1.27 or later, an ingress controller (or a Gateway API implementation for
`httpRoute`), and a default StorageClass for the bundled Postgres. PostgreSQL 16 is the
only stateful dependency; an OIDC provider (Phase 2) is needed for single sign-on and an
SMTP server (Phase 3) for email.
Every pod meets the **Restricted** Pod Security Standard.

### Air-gapped installs: image registry override, no runtime downloads

Mirror `soundings:<tag>` and `postgres:16-alpine`, set `global.imageRegistry` (and
`image.pullSecrets`). Nothing is downloaded at runtime: fonts, Swagger UI and the SPA
are in the image; there is no telemetry.

## Trying it out [Phase 1]

### `make demo`: the image on your machine

```sh
make demo                        # build soundings:dev, run it with Postgres and demo data
open http://localhost:8000       # pick a person on the sign-in page (Alice is the admin)
make demo-down                   # remove the containers and their data
```

`make demo` (`scripts/demo.sh`) runs the same image as the cluster, in development mode
with the dev login and the demo story (12 people, three projects, 45 ideas; who's who
in [dev/README.md](../dev/README.md#demo-data)). `DEMO_PORT` changes the port,
`DEMO_RESET=1` reloads fresh demo data, and running it again after `make image` swaps
the app container and keeps the data. Without a Debian mirror, build with
`IMAGE_BUILD_ARGS="--build-arg RUNTIME_APT_PACKAGES="` (PDF export, a Phase 4 feature,
then has no system libraries).

### The dev login

`devLogin=true` (`SOUNDINGS_DEV_LOGIN_ENABLED`) shows a "who are you?" list on the
sign-in page (next to single sign-on when that is configured) and switches the app to
development mode. Anyone who can reach the app can then act as anyone, so use it only on your own
machine or a throwaway cluster. Production mode refuses it.

## Installing with Helm [Phase 0–1]

### Quick start on k3s/k3d

```sh
helm install soundings ./deploy/helm -n soundings --create-namespace \
  --set 'baseUrls[0]=https://ideas.example.com' --set ingress.enabled=true
helm test soundings -n soundings      # /readyz and the SPA through the Service
```

`NOTES.txt` prints the URL and the first sign-in steps. For a local cluster in Docker,
`make k3s-up`, `make k3s-install IMAGE=soundings:<tag>`, `make k3s-smoke` and
`make k3s-down` do the whole loop (`dev/k3s-values.yaml`: dev login and demo data, in a
namespace that enforces the Restricted policy).

### Demo data on a cluster

```sh
helm install soundings ./deploy/helm -n soundings --create-namespace \
  --set 'baseUrls[0]=http://localhost:8000' --set devLogin=true --set demo.seed=true
kubectl -n soundings port-forward svc/soundings 8000:80
```

`demo.seed` adds a post-install/post-upgrade hook Job that migrates and runs
`soundings seed`. It does nothing once the database has projects, so upgrades keep what
people changed; the chart refuses it without `devLogin`. To start over:
`kubectl -n soundings exec deploy/soundings-api -- soundings seed --reset`
(add `--force` once anyone other than the demo people has an account).

### Bundled Postgres vs external or CloudNativePG database

The bundled single-replica Postgres suits trials and small installs; its PVC is kept on
uninstall. For anything you back up, set `postgresql.enabled=false` and
`externalDatabase.*` (for CloudNativePG, point `existingSecret` at the cluster's
`<cluster>-app` Secret; `sslmode` defaults to `require`).

### Ingress, TLS and multiple hostnames

`baseUrls` lists every origin people use (`scheme://host[:port]`, no path); the first
is the canonical one for links in emails. The ingress (or `httpRoute`) hostnames default
to their hosts. **The app answers only those hosts**: any other `Host` gets 400
`invalid_host` (`/healthz` and `/readyz` excepted, so probes work), which stops a
spoofed `Host` header steering links or sign-in redirects. So list every public host,
and have in-cluster callers send one of them as `Host`. `trustedProxies` (default: the
private ranges) names the proxies whose `X-Forwarded-For`/`-Proto` headers are believed;
narrow it to your ingress controller's pod range if you can.

Request bodies over 1 MiB get 413 `content_too_large` from the app itself, before
authentication and without buffering them. ingress-nginx enforces the same 1 MiB by
default; Traefik and Gateway API need their own limit if you want one at the edge (the
[chart README](../deploy/helm/README.md#security) shows how).

### `values.schema.json` validation and `NOTES.txt`

Every value is validated: an unknown key, a wrong type or an invalid enum fails the
install before anything is applied.

### Upgrades and migrations (pre-upgrade hook, Argo CD PreSync)

`helm upgrade` migrates first (hook Job or init containers), then rolls the pods; old
pods keep serving until new ones are ready. Migrations are idempotent and serialised by
an advisory lock. Generated secrets (signing key, break-glass password, bundled
database password) survive upgrades through Helm's `lookup`; with Argo CD, Flux or
`--dry-run`, which can't use `lookup`, supply them as `existingSecret`s.

### Sessions

Signing in creates a server-side session: an HttpOnly, `SameSite=Lax` cookie holding a
random token, of which the database stores only a SHA-256 hash, plus a readable CSRF
cookie that the SPA echoes in a header on every write. Both are named
`__Host-soundings_*` whenever they are `Secure`. A session ends after
`sessions.idleTimeout` without a request (default `PT12H`) or `sessions.maxAge` after
sign-in (default `PT24H`; Phase 1 had `P7D`), whichever comes first (break-glass: 1
hour and 8 hours), and
as soon as its sign-in method stops being available; signing in again always issues a
new token. The cookies are `Secure` in production; `SOUNDINGS_COOKIE_SECURE` (in
`extraEnv`) overrides that for unusual setups, but `false` is refused in production.

## Sign-in and access [Phase 2]

One OpenID Connect provider per instance, configured only by Helm values (`oidc.*`, or
`SOUNDINGS_OIDC_*` for the bare image). **Settings → Sign-in (SSO)** shows the effective
configuration read-only, with secrets masked, the URIs to register for every base URL
and whether the provider's discovery document can be fetched. The values reference and
the IdP client checklist are in the chart README's
[Single sign-on](../deploy/helm/README.md#single-sign-on) section; this section is the
how-to.

The flow is the server-side authorization code flow with PKCE (S256), `state` and
`nonce`. Nothing is stored while a sign-in is in progress: the attempt (state, nonce,
PKCE verifier, where to go next; 10 minutes) travels in an HttpOnly cookie, encrypted
and authenticated with a key derived from the app's secret key (`secretKey`), so the
browser can neither read nor change it. **Rotating the secret key** therefore restarts
sign-ins in progress (and sign-out then goes without `id_token_hint`, so Keycloak asks
to confirm it once). The ID token is validated (signature with the provider's keys,
refetched hourly, `iss`, `aud`/`azp`, `exp`, `nonce`), and the browser only ever holds
the HttpOnly session cookie. Sign-out ends the session and then the provider's session
(RP-initiated logout with `id_token_hint`, stored encrypted) when the provider has an
end-session endpoint. In production every endpoint in the provider's discovery
document must be https.

People who signed in with the wrong account get "Use a different account" on the
sign-in page, which sends `prompt=select_account` and `max_age=0` to the provider:
Entra ID and Google show their account picker; Keycloak asks to re-authenticate, and
its "Restart login" button (next to the username) lets the person sign in as someone
else.

**Sessions and IdP changes.** Sessions last at most `sessions.maxAge` (24 hours by
default) and end after `sessions.idleTimeout` (12 hours) without a request. Group sync
and login matching run only at sign-in, so a removal or group change in the IdP applies
within a day on its own; deactivate the person (Settings → Users), or use "Sign out
everywhere", to apply it at once.

### Configuring OIDC: Keycloak, Entra ID, Google

Every provider needs a **confidential web client** using the authorization code flow
(no implicit or password grants), and for **each** entry of `baseUrls`:

| Register | Value |
|---|---|
| Redirect URI | `<base URL>/api/v1/auth/callback` |
| Post-logout redirect URI | `<base URL>/login?signed_out=1` |

The ID token must carry `sub`, `email`, `email_verified` and `name` (scopes
`openid profile email`), plus the groups claim and, if you use one, the external-ID
claim. Put the client secret in a Secret and point `oidc.existingSecret` at it.

**Keycloak** (the dev realm `dev/keycloak/realm-soundings.json` is a working example):

```yaml
oidc:
  issuer: https://keycloak.example.com/realms/soundings   # exactly the realm's issuer
  clientId: soundings
  existingSecret: soundings-oidc        # key client-secret
  groupsClaim: groups                   # "Group Membership" mapper, full group path on
  externalIdClaim: employee_no          # "User Attribute" mapper, added to the ID token
  matchVerifiedEmail: true              # Keycloak verifies addresses
```

Client: *Client authentication* on, *Standard flow* only, *PKCE method* S256, *Valid
redirect URIs* and *Valid post logout redirect URIs* as above. Group values arrive as
full paths (`/innovation/members`); mappings may be typed with or without the slashes.
Declare the external-ID attribute in the realm's **User profile** with edit permission
`admin` only and keep *Unmanaged attributes* disabled, or users could set it themselves.
Realm roles instead of groups: `groupsClaim: realm_access.roles`.

**Microsoft Entra ID** (`deploy/helm/ci/sso-values.yaml` is this shape):

```yaml
oidc:
  issuer: https://login.microsoftonline.com/<tenant-id>/v2.0
  clientId: <application (client) id>
  existingSecret: soundings-oidc
  groupsClaim: groups                   # group object ids
  externalIdClaim: oid                  # the user's immutable object id
  externalIdKind: entra_oid
  matchVerifiedEmail: false             # Entra ID sends no email_verified
```

App registration: platform *Web* with both URIs above as redirect URIs, a client secret
(*Certificates & secrets*). *Token configuration*: add the **groups** claim with "Groups
assigned to the application" (so the token lists object ids of assigned groups only,
and nobody exceeds the 200-group limit) and the optional `email` claim. A token in
which the groups claim was replaced by the overage marker (`_claim_names`) is refused
rather than read as "no groups", which would remove every managed membership. Since
email matching is off, pre-create users with the `entra_oid` external ID (their *Object
ID* in the Entra admin center); never use `upn`, `preferred_username` or `email` as the
external-ID claim. Group mappings take the group's *Object ID*.

**Google** (Workspace):

```yaml
oidc:
  issuer: https://accounts.google.com
  clientId: <id>.apps.googleusercontent.com
  existingSecret: soundings-oidc
  groupsClaim: ""                       # Google sends no groups: no sync
  externalIdClaim: ""
  matchVerifiedEmail: true
  autoCreateUsers: false
```

OAuth client of type *Web application* with the redirect URIs above (Google has no
end-session endpoint, so sign-out ends only the Soundings session). Without a groups
claim, access comes from manual group memberships and direct project roles. **Any
Google account can authenticate**: keep `autoCreateUsers` off (pre-create people, who
then link by verified email), or set the OAuth consent screen to *Internal* first.

**A private CA.** The app fetches the discovery document, keys and tokens with the
system trust store replaced by `SSL_CERT_FILE` when that is set. For an IdP behind an
internal CA, mount a bundle holding that CA (plus any public roots you still need) with
`extraVolumes` / `extraVolumeMounts` and set `SSL_CERT_FILE` in `extraEnv`. Outbound
proxies are read from `HTTPS_PROXY` / `NO_PROXY`.

**Checking it.** After `helm upgrade`, Settings → Sign-in (SSO) should say the provider
answers. If not, it says which of the three failures it is (unreachable, not a
discovery document, issuer mismatch). Production refuses an http issuer and, once SSO
is configured, http base URLs.

### Redirect URIs for each hostname

Each base URL signs in on itself: someone who opened `https://ideas.example.net` comes
back to that host, so register both URIs above for **every** entry of `baseUrls`
(`NOTES.txt` and the SSO page list them). A sign-in started on a host the app doesn't
know is sent to the first base URL first. The cookies are named `__Host-soundings_*`
whenever they are `Secure`, so a sibling subdomain can't plant one.

### Login matching and external IDs

At every sign-in the app looks for the user linked to the token's issuer and `sub`. At
the first sign-in it tries, in order, and stops at the first user found:

1. the **external ID**: `oidc.externalIdClaim` against users' external IDs of kind
   `oidc.externalIdKind` (Settings → Users → Add user, or a user's External IDs);
2. the **verified email** (`oidc.matchVerifiedEmail`, only when `email_verified` is
   true; a user who has an external ID of the configured kind links only by it);
3. **auto-create** (`oidc.autoCreateUsers`, verified email only, an account with no
   roles: access then comes only through groups);
4. otherwise the sign-in is refused (`no_account`, "ask an administrator to add you").

A match that is deactivated, a service account, the break-glass account or already
linked to another identity refuses rather than falling through. Every refusal is in the
audit log with its reason and the issuer/subject, never the email or claims. Admins
unlink an identity (Settings → Users) to let an account match again.

**The external-ID claim must come from an attribute only IdP admins can set**: whoever
can choose its value signs in as the pre-created user who has it, platform admins
included. Names and emails are not synced from claims after the first sign-in.

### Groups and IdP group mappings (managed vs additive)

Internal groups (Settings → Groups) are what projects grant roles to. A group can be
mapped to one or more IdP group values, matched after trimming, stripping `/` at both
ends and lower-casing (inner path segments count: `admins` does not match
`/innovation/admins`). At each sign-in the user's **synced** memberships are updated
from `oidc.groupsClaim`:

- **managed**: synced memberships become exactly the matched groups (joins and leaves);
- **additive**: sign-in only adds;
- **manual** memberships (added by an admin) are never touched by sync;
- a token **without** the groups claim means "no groups": managed memberships go.

A strategy that works:

- Map **access-granting** groups (project admins, members) as *managed*, so removing
  someone in the IdP removes their access at their next sign-in.
- Use *additive* only for broad, low-risk groups (viewers, a whole department) where a
  flaky IdP group must not lock people out; admins prune them by hand.
- Grant project roles to groups, not people, and keep direct roles for exceptions.
  Projects show "Everyone with access" with the source of each role.
- Before changing a mapping, paste a real ID token into **Test mapping** to see who
  joins, leaves and stays, and the resulting project roles.
- Sync only runs at sign-in. **Offboard by deactivating** the user (their sessions end
  at once); removing them in the IdP alone leaves a running session for up to
  `sessions.maxAge` and their memberships until they come back.

### Break-glass admin

A local platform admin whose credentials come from a Secret (`breakGlass.existingSecret`
with keys `username` and `password` of 16+ characters, or generated by the chart: user
`admin`, 24 random characters; `NOTES.txt` shows how to read it). It **works only while
`oidc.issuer` is empty**, is throttled (5 failures per address per 15 minutes, then 429
with `Retry-After`), its sessions last at most 8 hours (1 hour idle) and end as soon as
SSO is configured, and every sign-in and every action is audited as
`auth_method: break_glass`. A banner stays on screen while it is used.

Bootstrap order:

1. Install without `oidc.issuer` and sign in as the break-glass admin.
2. Settings → Users: pre-create the real platform admins (external ID from an
   admin-only attribute, and/or email). Optionally create groups, their mappings and
   project grants.
3. Register the redirect URIs from Settings → Sign-in (SSO) on the IdP client.
4. `helm upgrade` with `oidc.issuer`, `oidc.clientId` and `oidc.existingSecret`.
   Break-glass switches off; the admins from step 2 link at their first SSO sign-in.

**SSO outage:** `helm upgrade <release> <chart> --reuse-values --set oidc.issuer=`
brings break-glass back with the same password; setting the issuer again switches it
off. That needs cluster access, the right bar for an emergency account.

## Email [Phase 3]

### SMTP settings and `existingSecret`
### Security modes (`none`, `starttls`, `tls`) and custom CA bundles
### Sending a test email; failed sends and retries
### Running without SMTP

## Public submission and anti-abuse [Phase 4]

### Rate limits behind a proxy (trusted proxies)
### ALTCHA, moderation and email verification

## Branding [Phase 4]

## API keys and MCP [Phase 5]

## kagent integration [Phase 6]

### Checking the installed kagent version
### Registering agents and service-account API keys
### Example manifests (`deploy/kagent/`)

## Operations [Phase 1, 7]

### Health probes: `/healthz`, `/readyz`

`/healthz` (liveness and startup) answers as long as the process serves requests and
never touches the database. `/readyz` (readiness) runs `SELECT 1` and answers 503
`not_ready` when the database doesn't respond in time, so a pod drops out of the Service
instead of failing requests. Both skip the host check, and their access-log lines
are DEBUG only.

### Metrics (`/metrics`), ServiceMonitor, OTel tracing

Prometheus metrics are served **only on their own port**, `metrics.port` (default
9090; `SOUNDINGS_METRICS_PORT`), exposed as the Service port `metrics`. The ingress and
HTTPRoute route the `http` port only, so metrics are never public. Scrape them with
`serviceMonitor.enabled=true` (Prometheus Operator) or your own scrape config, and allow
the scraper with `networkPolicy.metricsFrom` when network policies are on.
`otel.endpoint` sends OTLP/HTTP traces.

### Logs (JSON, no PII)

One JSON object per line on stdout. Every response carries an `X-Request-ID` (an
incoming well-formed one is reused), which is also in the log line and in problem
responses, so a user's error report can be matched to the log.

### Backups and restore
### Scaling: replicas, HPA, PodDisruptionBudget
### Security: Pod Security `restricted`, NetworkPolicy, secrets

`networkPolicy.enabled` is **on by default**: the bundled Postgres accepts only this
release's pods, the worker accepts nothing, and the API's HTTP port accepts this
release's pods plus `networkPolicy.ingressFrom` (any source while that is empty; the
NOTES remind you). Set `ingressFrom` to your ingress controller's namespace so other
pods can't reach the API directly with an `X-Forwarded-For` of their choosing, and
`metricsFrom` to your Prometheus. The policies are ignored on a CNI without
NetworkPolicy support (k3s's default flannel enforces them through its network policy
controller).

**Client addresses behind proxies.** The sign-in throttles key on the client IP. The app
believes `X-Forwarded-For` only from a peer in `trustedProxies` (default: the private
ranges, where ingress controllers live) and only its `trustedProxyHops` rightmost
entries (default 1: the ingress controller's; set 2 when an L7 load balancer in front
of the ingress also appends). Entries further left are whatever the client sent and are
ignored. Narrow `trustedProxies` to your ingress pods' range where you can.
### Audit log
### Troubleshooting

## Data protection [Phase 4, 7]

### Erasing a public submitter's personal data
### What is stored about users
