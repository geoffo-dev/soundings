# Soundings operator guide

> Filled in phase by phase (noted in brackets) and completed in Phase 7.
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

### The image: Ubuntu 24.04, Python 3.12 and the PDF libraries [Phase 4]

Since Phase 4 the runtime image is based on `ubuntu:24.04` with Ubuntu's own Python 3.12
(no downloaded interpreter) and the libraries WeasyPrint needs for PDF export: Pango,
HarfBuzz (with its subsetter), fontconfig, DejaVu fonts as the glyph fallback, plus
`ca-certificates` and `tzdata` ([ADR 0011](adr/0011-ubuntu-runtime-image-and-weasyprint.md)).
It is about 40 MB larger than the Debian-based Phase 3 image (about 500 MB, 118 MB
compressed). It still runs as user 10001 with a read-only root filesystem: fontconfig
and WeasyPrint write only under `/tmp` (the chart's `emptyDir`; `XDG_CACHE_HOME=/tmp/cache`).
The build fails if WeasyPrint can't render a test page, so an image that built can
export PDFs.

Building it yourself (`make image`, or `docker build .`): packages come from Ubuntu's
archive; for an internal mirror pass `--build-arg UBUNTU_MIRROR=http://mirror.internal/ubuntu`
(replaces `archive`, `security` and `ports.ubuntu.com`) and override the base with
`UBUNTU_IMAGE` (CI pins it by digest). `RUNTIME_APT_PACKAGES` only *adds* packages (a
mirror's keyring, debugging tools). Behind a TLS-intercepting proxy, pass its CA as the
`build_ca` BuildKit secret (`BUILD_CA=` with `make image`); it never lands in a layer.
Rebuild regularly: the Ubuntu packages are not version-pinned, so a rebuild picks up
security fixes.

**Fonts.** The four branding fonts (Inter, IBM Plex Sans, Source Serif 4, Atkinson
Hyperlegible) and IBM Plex Mono for code ship inside the app (`app/assets/fonts/`,
`woff2`, latin and latin-ext, about 750 KB with their SIL Open Font License texts) and
in the SPA bundle; PDFs embed subsets of them, and emails name them first in a system
font stack (mail clients use their own fonts; nothing is downloaded). There is no way to
add a font: the set is fixed so that every surface can render it offline.

### Running the image without Helm [Phase 7]

The image starts in **production** mode (`SOUNDINGS_ENVIRONMENT=production` is set in
it): no dev login, `Secure` `__Host-` cookies, exception messages redacted from logs,
`/metrics` only on its own port, the API's OpenAPI document and Swagger UI only for
signed-in callers, and a refusal to start with a weak or missing signing key. Outside
Kubernetes (Docker, Compose, Nomad, a VM) give it at least:

| Variable | What |
|---|---|
| `SOUNDINGS_DATABASE_URL` | `postgresql://user@host:5432/db` (and `SOUNDINGS_DATABASE_PASSWORD`, so the password needn't be URL-encoded). The role should own its database and not be a superuser. |
| `SOUNDINGS_SECRET_KEY` | 32+ random characters (`openssl rand -base64 48`): signs sessions' sealed cookies, unsubscribe and tracking links, ALTCHA challenges. Keep it stable: changing it invalidates outstanding links. |
| `SOUNDINGS_BASE_URLS` | Every origin people use, comma-separated (`https://ideas.example.com`); other `Host`s get 400. |
| `SOUNDINGS_TRUSTED_PROXIES` | Your reverse proxy's address(es); the default trusts the private ranges, which is only safe if nothing else can reach the container. |
| sign-in | `SOUNDINGS_OIDC_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET`, or the break-glass admin (`SOUNDINGS_BREAK_GLASS_ENABLED=true`, `_USERNAME`, `_PASSWORD` of 16+ characters). |
| `SOUNDINGS_SMTP_*` | Optional: email (worker only). |

Run `soundings migrate` once per upgrade (or `wait-for-db --timeout 120 && migrate`
before the API), then `soundings api` and `soundings worker` (the same image, the
same variables). Run them like the chart does: `--read-only --tmpfs /tmp`, as the
image's user 10001, with no added capabilities. `soundings api` and `soundings worker`
refuse to start when `SOUNDINGS_ENVIRONMENT` is unset and the signing key is the
built-in development one (only a hand-built environment without the image's setting can
get there). Development mode (the dev login, demo data with `soundings seed`) must be
asked for with `SOUNDINGS_ENVIRONMENT=development`, as `make demo` does: never on a
shared or reachable machine.

## Trying it out [Phase 1]

### `make demo`: the image on your machine

```sh
make demo                        # build soundings:dev, run it with Postgres, the worker,
                                 # Mailpit and demo data
open http://localhost:8000       # pick a person on the sign-in page (Alice is the admin)
open http://localhost:8026       # Mailpit: every email the demo sends
make demo-down                   # remove the containers and their data
```

`make demo` (`scripts/demo.sh`) runs the same image as the cluster, in development mode
with the dev login and the demo story (12 people, three projects, 48 ideas, three of them
from Customer Innovation's public form; who's who
in [dev/README.md](../dev/README.md#demo-data)), plus `soundings worker` and Mailpit as
its SMTP server, so invitations, mentions and the rest arrive in Mailpit's inbox.
`DEMO_PORT` changes the app's port and `DEMO_MAILPIT_PORT` Mailpit's, `DEMO_SMTP=0`
runs without email (in-app notifications only), `DEMO_TIMEZONE` sets the instance time
zone, `DEMO_PUBLIC_PER_IP` the public form's per-address limit, `DEMO_RESET=1` reloads
fresh demo data, and running it again after `make image` swaps the app and worker
containers and keeps the data. The containers run as in a cluster: read-only root
filesystem, a `/tmp` tmpfs, no capabilities. `make public-smoke` then checks the public
form, an anonymous submission and a branded PDF export against it.

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

**The app's database role is not a superuser** [Phase 7]. On a fresh volume the bundled
Postgres creates the bootstrap superuser `postgres` (password under `admin-password` in
its Secret, for maintenance with `kubectl exec ... psql -U postgres`; the app never uses
it) and the app's login role `postgresql.auth.username` (default `soundings`), which owns
the database and its `public` schema. That is all migrations, the job queue's schema and
the `pg_trgm` extension (a trusted extension) need; `COPY ... PROGRAM` and other
superuser powers are out of the app's reach. A volume initialised by an earlier chart
keeps its roles (the app's role stays the bootstrap superuser, which PostgreSQL can't
demote): to harden one, dump the database, reinstall with a new volume and restore as
the new owner. With an external database, give the app a role of the same kind: owner
of its database, not a superuser, and `CREATE` on the `public` schema.

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

### Client addresses behind the ingress [Phase 7]

Every throttle (sign-in and break-glass attempts, the public form, ALTCHA challenges,
tracking and confirmation links, refused API keys) keys on the client's address. The app
takes it from `X-Forwarded-For`, but only from a peer listed in `trustedProxies`, and
only `trustedProxyHops` entries from the right. So two settings must agree:

- `trustedProxies` names who may vouch for an address (default: the private ranges
  pods usually get, so any ingress controller works out of the box);
- `networkPolicy.ingressFrom` says who may reach the API at all.

While `ingressFrom` is empty, **any pod in the cluster** can connect to the API directly,
and with the default `trustedProxies` it counts as a proxy: it can put any address in
`X-Forwarded-For` and get a fresh throttle budget with every request. `NOTES.txt` warns
whenever that is the case. Set `ingressFrom` to your ingress controller's namespace (as
in `deploy/helm/ci/production-values.yaml`) and, if you can, narrow `trustedProxies` to
its pod range. The two stay separate settings on purpose: a NetworkPolicy peer is a
selector, `trustedProxies` an address range, and neither can be derived from the other.

### Compression [Phase 7]

The app compresses on its own: the image carries Brotli and gzip copies of the SPA's
files (made at build time, served with `Content-Encoding` and `Vary: Accept-Encoding`;
the 1 MB of JavaScript goes out as about 300 kB), and `GET` JSON responses of 1 KB or
more are gzipped for clients that accept it (the board of a 10k-idea project: 213 kB
raw). A response the app marks `Cache-Control: no-store` *by itself* (a new API key or
an agent's key, shown once) is never compressed, so a secret is never in a compressed
body next to text an attacker chose (BREACH); session and CSRF tokens are cookies, never
in a body. You don't need compression at the ingress; if you turn it on (ingress-nginx
`use-gzip`, Traefik's `Compress` middleware), exclude `text/event-stream`, which the AI
run progress streams.

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

A signed-in person may make at most 120 changes a minute (posts, edits, votes, moves),
per API pod, across their sessions; past that the API answers 429 `rate_limited` with
`Retry-After` and the SPA asks them to wait [Phase 7]. Reads are not limited. API keys
have their own limit (30 changes a minute). `SOUNDINGS_SESSION_WRITES_PER_MINUTE` (in
`extraEnv`) changes it; the e2e stack raises it because its specs set up data through the
API. Expired sessions are deleted every hour.

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

Soundings emails people when they are made owner, asked to evaluate, reminded of a due
evaluation, when all evaluations are in, and (by default in a daily digest) about
status changes and comments; @mentions too. Every notification also lands in the
in-app inbox, so email is optional. Mail goes through **any SMTP server**: your
organisation's relay, Microsoft 365, Google Workspace or a sending service. Nothing else
is needed (no queue service: the outbox is a PostgreSQL table, sent by the worker).

### SMTP settings and `existingSecret`

Configured only through Helm values (environment variables `SOUNDINGS_SMTP_*`); there
is no settings screen. Settings → Email shows the values in effect, read-only.

```yaml
smtp:
  host: smtp.example.com          # empty: no email (in-app notifications only)
  port: ""                        # empty: 587, or 465 with security: tls
  security: starttls              # none | starttls | tls
  existingSecret: soundings-smtp  # keys username and password (worker pods only)
  from: ideas@example.com         # required with host; one plain address
  fromName: Example Ideas         # default "Soundings"
  replyTo: innovation@example.com # optional
  timeout: 10                     # seconds, per connection and command (max 120)
  caBundle:
    configMap: ""                 # a ConfigMap with your CA (PEM), key ca.crt
baseUrls: [https://ideas.example.com]   # the first one is used in email links
timezone: Europe/London
notifications:
  digestHour: 8
  reminderDays: [2, 0]
```

```sh
kubectl -n soundings create secret generic soundings-smtp \
  --from-literal=username=soundings@example.com --from-literal=password='…'
```

Credentials come from the Secret, which must have both keys `username` and
`password` (or set `smtp.username` / `smtp.password` in values, not both). For a relay
that accepts your cluster without authentication, set neither. The chart refuses
`existingSecret` and `smtp.password` with `security: none` (except with `devLogin`).
**Only the worker pods get the credentials** (they send the mail); the api pods get
every other SMTP setting, so they can queue mail and show the configuration, plus
`SOUNDINGS_SMTP_USERNAME_SET` / `_PASSWORD_SET`, so Settings → Email can say a user
name and password are set without the api ever holding them. Changing a value rolls
both Deployments; a new password in the Secret or a new CA needs `kubectl -n soundings
rollout restart deploy`. Links in emails use the first of `baseUrls`, so list the
address people use first.

**Common providers** (check your provider's current documentation; these are the usual
settings):

| Provider | `host` | `security` (port) | Username / password | Notes |
|---|---|---|---|---|
| Your organisation's relay (Postfix, Exchange connector) | the relay | `starttls` (587) or `none` (25) | often none | `none` only inside your network; production refuses a password with `none`. A relay with a private CA needs `caBundle`. |
| Microsoft 365 | `smtp.office365.com` | `starttls` (587) | a licensed mailbox and its password | SMTP AUTH must be enabled for that mailbox; `from` must be the mailbox or one it may send as. Otherwise use an Exchange connector as a relay (row above). |
| Google Workspace | `smtp.gmail.com`, or `smtp-relay.gmail.com` | `starttls` (587) or `tls` (465) | an app password; the relay can allow your egress IPs instead | `from` must be the account or an alias. |
| Amazon SES | `email-smtp.<region>.amazonaws.com` | `starttls` (587) or `tls` (465) | the SES SMTP credentials (not the IAM keys) | Verify the `from` domain; leave the sandbox. |
| SendGrid, Mailgun, Postmark… | the service's SMTP host | `starttls` (587) | the service's SMTP credentials (SendGrid: `apikey` and the API key) | Verify the sender domain (SPF/DKIM) so mail isn't marked as spam. |

Whatever the provider, publish SPF and DKIM for the `from` domain; mail arrives with
`List-Unsubscribe` and one-click unsubscribe headers (RFC 8058), which large mailbox
providers expect from automated mail. The one-click header and the footer's
"Unsubscribe from <type>" link turn off only that kind of email (or the digest); the
footer's separate "Unsubscribe from all email" link turns off everything. The links are
signed with a key derived from `secretKey` and don't expire; rotating the secret key
breaks every link in mail already sent (people then sign in to their preferences).

### Security modes (`none`, `starttls`, `tls`) and custom CA bundles

- `starttls` (default, port 587): connects in plain text and upgrades with STARTTLS; a
  server that doesn't offer it fails ("server doesn't support STARTTLS or AUTH").
- `tls` (port 465): TLS from the first byte ("implicit TLS", SMTPS).
- `none`: plain SMTP, for a relay or Mailpit inside your network. No STARTTLS is
  attempted. Production refuses a password with it (it would cross the network in
  clear text), and so does the chart for `smtp.password`.

TLS always verifies the server's certificate and host name. For a server whose
certificate comes from a private or corporate CA, put the CA (PEM, the whole chain's
roots) in a ConfigMap and name it:

```sh
kubectl -n soundings create configmap smtp-ca --from-file=ca.crt=./corporate-ca.pem
helm upgrade … --set smtp.caBundle.configMap=smtp-ca   # key: smtp.caBundle.key (ca.crt)
```

It is mounted read-only (`/etc/soundings/smtp-ca/ca.crt`, `SOUNDINGS_SMTP_CA_BUNDLE`)
and **replaces** the system trust store for SMTP only; the pods refuse to start when
the file holds no PEM certificate (a wrong key or an empty ConfigMap) (sign-in uses the image's trust
store, or `SSL_CERT_FILE`). A certificate that fails verification (an unknown CA, or
issued for another host name) shows as "TLS certificate not trusted" in the outbox and
the test email's result; other TLS problems (no common protocol, a plain-text server on
a TLS port) as "TLS handshake failed". There is no setting to skip verification.

With `networkPolicy.egress.enabled`, only the worker may open connections to the SMTP
port; narrow it with `networkPolicy.egress.smtp.to` (the relay's CIDR). See the
[chart README](../deploy/helm/README.md#security).

### Sending a test email; failed sends and retries

**Settings → Email → Send test email** (platform admins) sends a real email to yourself
or one address through the outbox and the worker, and shows the result within about 30
seconds: "Sent to …" when the server accepted it, or the reason it didn't, with a hint
(host and port, TLS, credentials). A test email has one attempt, so a failure shows at
once. If it stays "Queued", the worker isn't running or can't reach the database.

**How sending works.** Each email is a row in `outbound_email`, written in the same
database transaction as the event that causes it (an invitation, a comment), together
with its `send_email` job; the worker sends it. Content is rendered when it is sent, so
an email never shows what the recipient may no longer see, and no message bodies are
stored. If the server doesn't accept it, the email goes back in the queue:

- **Transient** (connection refused or timed out, TLS problems, any 4xx reply such as
  greylisting, authentication failures): retried after 30 s, 1, 2, 4, 8, 16, 32 minutes
  and then hourly, 12 attempts over about 5 hours, then **Failed**.
- **Permanent** (a 5xx reply other than authentication, for example an unknown
  recipient or a refused sender): **Failed** at once.

The outbox on Settings → Email lists every email with its recipient's name (never the
address), type, status, attempts and the last error, in our own words ("connection
refused", "SMTP 535: authentication failed", "TLS certificate not trusted"; the server's
reply text is never stored, since it can contain addresses). **Retry** sends a failed
email again with fresh attempts; **Retry all failed** does that for every failed email
that is still current. Test emails are limited to 5 per admin per 10 minutes, and
retrying a failed test email counts toward that limit. Mail older than **3 days** (digests: **2 days**) is never sent
late: it is cancelled as "Not sent: out of date", as are emails whose recipient lost
access, turned that type off, or has an unusable address. Platform admins see a banner,
"Some emails aren't going out", while an email failed in the last 24 hours or one has
waited more than 15 minutes; it clears by itself.

Sent and cancelled rows are kept 30 days, failed ones 90 days; in-app notifications 90
days. Test emails and retries are in the audit log (without the address). The worker
logs outbox ids, types, attempt numbers and error classes, never addresses, subjects,
bodies, tokens or the server's replies. Its counters are `soundings_emails_sent_total`,
`soundings_email_attempts_failed_total` (by type and kind: transient, permanent,
internal), `soundings_emails_cancelled_total` and the gauge `soundings_emails_queued`;
in Phase 3 the worker doesn't serve them on a port yet, so watch the banner, the outbox
and the logs.

**When the SMTP server is down**, nothing is lost: email waits in the outbox and goes out
when the server is back (the next retry, at most an hour later), once, with the same
Message-ID. After **five connection failures in a row** (refused, timed out, cut off) a
worker **pauses sending** for 30 seconds, doubling up to 5 minutes while the server
stays unreachable: due emails are postponed to the end of the pause **without using an
attempt**, and the first one after it probes the server. So an unreachable server costs
one timeout per pause rather than one per email, and the minute sweep, reminders,
digests and in-app notifications never wait behind a backlog of sends (their jobs run
first). Test emails are always tried. Each worker process pauses on its own; the log
says "SMTP server unreachable: pausing sends" and "SMTP server reachable again". An outage longer than about 5 hours leaves emails Failed: use **Retry all
failed** within three days. **When the worker is down** (or scaled to 0), email,
reminders and digests wait; when it starts, queued email goes out, a missed digest hour
is caught up that day, and a reminder day that passed is skipped (people still see due
evaluations on My work).

### Digests, reminders and the time zone

Everything time-based follows **one time zone for the whole installation**, `timezone`
(IANA name, default `UTC`); emails show dates with its name ("Fri 9 Oct, 17:00
(Europe/London)"). There are no per-user time zones.

- **Daily digest:** once a day, at `notifications.digestHour` (default 8) local time or
  in the first hourly run after it, each person who has notifications set to "Daily
  digest" and not yet read in the app gets one email with them, grouped by idea (at most
  the last 7 days). Nobody gets two digests a day.
- **Evaluation reminders:** `notifications.reminderDays` (default `[2, 0]`: two days
  before the due date and on the day), sent at the digest hour to evaluators who
  haven't submitted, only on that local day: never for overdue evaluations, never
  twice, and a changed due date reschedules them. `[]` turns reminders off; people can
  also turn them off for themselves.
- The schedule runs in the worker every hour and handles daylight-saving changes; the
  cleanup (old notifications and outbox rows) runs at the end of every hourly run.

### Running without SMTP

Leave `smtp.host` empty (the default). The app works with in-app notifications only:
the bell and inbox are unchanged, preferences can still be set (the page says email
isn't set up), nothing is written to the outbox, and platform admins see a dismissible
banner "Email isn't set up" linking to Settings → Email, which lists the setup steps.
Test email and retry answer 409. Configure SMTP later and email starts with the next
notification; nothing from before is sent late.

### Worker and scaling

The worker (`soundings worker`, Deployment `worker`) runs every background job: sending
email, the per-minute outbox sweep, the hourly schedule, the daily job cleanup, and the
in-app notifications of very large events: a status change or comment that would notify
**more than 500 people** is handed to the worker (a `notify_event` job written in the
same transaction), so those inbox items, and their emails, appear only once the worker
runs it. Smaller events notify people within the request. Keep
`worker.enabled` on whenever SMTP is configured. One replica with `worker.concurrency`
4 is plenty for most organisations; more replicas are safe (each email is claimed by
exactly one worker with a 5-minute lease, and periodic jobs are queued once however
many workers run), and give you continuity during node drains. Each attempt must finish
within 4 minutes; a worker that dies mid-send leaves the email to the sweep, which
retries it after the lease (the recipient may then, rarely, get it twice, with the
same Message-ID); jobs of a worker without a heartbeat for 2 minutes are marked failed
by the sweep, so they don't stay "doing" for ever. The worker serves no HTTP and needs no Service; shutdown waits
`worker.terminationGracePeriodSeconds` for running jobs.

## Public submission and anti-abuse [Phase 4]

A project admin can open a **public form** for their project (project settings → Public
form): anyone can then send an idea at `<baseUrl>/<project-slug>/submit` without an
account and follow it through a private tracking link. This is the only part of
Soundings that anonymous visitors can write to, so it is worth knowing what is exposed
and which knobs exist. The chart README's
[Public submission](../deploy/helm/README.md#public-submission) section has the ingress
details.

**What is exposed.** The form, `/track` and `/verify` are pages of the SPA. Their API is
under `/api/v1/public/` (the form's project, an ALTCHA challenge, submit, tracking,
status-email opt-in and out, resend, "Delete my details", confirm), plus the public
`GET /api/v1/branding` and `/api/v1/branding/assets/<id>` (logos and favicons). Nothing
there returns private data: a closed or unknown form is the same 404, the form shows only
the project's name, intro and branding, and a tracking link shows only the title and
summary as sent, the status and its dates, never people, comments, scores or the team's
edits. Tracking and confirmation tokens travel after `#`, so they never reach the server,
a proxy or an access log in a URL.

**Turning it off.** `features.publicSubmission: false` (`SOUNDINGS_PUBLIC_SUBMISSION_ENABLED`)
closes every form and makes every tracking and confirmation link answer 404, without
touching project settings; turning it back on restores them. Use it to stop intake in
an incident. Project slugs that clash with the app's own paths (`settings`, `track`,
`verify`, `api`, …) can't be used for new projects, and older projects with one can't
turn their form on.

| Helm value | Environment | Default | What it does |
|---|---|---|---|
| `features.publicSubmission` | `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` | `true` | The instance switch above |
| `publicSubmission.perIpPerHour` | `SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP` | `10` | Submissions per client address (IPv6: per /64) per hour, across projects, **per API pod** (1–1,000) |
| `publicSubmission.perProjectPerHour` | `SOUNDINGS_PUBLIC_SUBMISSIONS_PER_PROJECT` | `100` | Submissions per project per hour from everyone, counted in the database (across pods; 1–10,000) |
| `publicSubmission.altcha.cost` | `SOUNDINGS_ALTCHA_COST` | `5000` | Proof-of-work iterations per attempt (1,000–1,000,000) |
| `publicSubmission.altcha.expiry` | `SOUNDINGS_ALTCHA_EXPIRY` | `PT30M` | How long a challenge stays valid (1 minute to 1 day) |
| `branding.maxUploadBytes` | `SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES` | `524288` | Largest logo or favicon (16 KiB to 900 KiB) |

Everything else is fixed: tracking and confirmation pages share a limit of 60 requests a
minute per address, loading a form, its challenge and the submission together 120 a
minute per address (counted before the form is looked up, so unknown names count too),
challenges 30 a minute, confirmation emails 3 a day per address (an address is compared
lower-cased with any `+tag` removed, Gmail's dots and Yahoo's `-keyword` folded;
counted in the database by a keyed hash of the address, so erasing a submission doesn't
reset it) and per submission, and the confirmation email contains no text the visitor
typed and no tracking link, so the form can't be used to send anyone spam.

### Rate limits behind a proxy (trusted proxies)

The per-address limit keys on the client address the app derives from `X-Forwarded-For`
through `trustedProxies` and `trustedProxyHops`, exactly as the sign-in throttles do
(see [Security](#security-pod-security-restricted-networkpolicy-secrets)). Get this right
before publishing a form:

- If every request seems to come from one address (the load balancer, or a node after
  SNAT), the whole internet shares one budget of `perIpPerHour` submissions. The first
  refusal for an address in an hour is logged at **WARNING** (`public submission
  refused`, `reason=rate_limited`, the project id, never the address): a burst of those
  right after a launch usually means a wrong `trustedProxyHops` or an ingress that
  doesn't pass the client address.
- If the app trusts too much (a wide `trustedProxies` with pods able to reach the API
  directly), a client can choose its own address. Keep `networkPolicy.ingressFrom` set
  to your ingress controller's namespace.
- The per-address submission limit is in memory, per pod, and forgets on restart (the
  confirmation-email limit above is in the database); the per-project
  limit (`perProjectPerHour`, counted in the database) is the real backstop against
  address rotation such as IPv6 /64s.
- For an edge limit on anonymous traffic only, `ingress.publicApi.annotations` renders a
  second Ingress for `/api/v1/public` (ingress-nginx `limit-rpm`, a Traefik `RateLimit`
  middleware; `dev/k3s/public-ratelimit.yaml` is the k3s example). Keep any edge body
  limit at `1m` or more: the app refuses bodies over 1 MiB itself.
- Don't let a CDN or proxy cache `/api/` (responses are `no-store`) except
  `/api/v1/branding/assets/<id>` (immutable), and don't add a CSP at the edge.

### ALTCHA, moderation and email verification

Three layers in the app, in this order, so that a bot learns nothing from the answers:

1. **ALTCHA proof of work.** The visitor's browser solves a small PBKDF2 puzzle while
   they type (under a second on a phone at the default cost) and sends the solution with
   the idea. The app checks it locally: no third-party service, works air-gapped, no
   cookies. Challenges are signed with a key derived from `SOUNDINGS_SECRET_KEY` (all
   pods agree; rotating the secret key invalidates challenges in flight), bound to one
   project's form, valid for `altcha.expiry`, and accepted once (solved challenges are
   remembered in the database until they expire, so a replay fails on any pod). Raise
   `altcha.cost` if bots get through; test the form on a slow phone after changing it.
2. **A honeypot field**, checked last: a submission that filled it gets a normal-looking
   receipt whose link tracks nothing, and nothing is stored (logged at INFO as
   `public submission dropped (honeypot)`).
3. **Per-address and per-project limits** (above): 429 with `Retry-After`.

Writes must be `application/json` (415 otherwise), so other sites can't post the form
through their visitors' browsers.

Per project, admins choose **moderation** (on by default for a new form: public ideas
wait in a queue, invisible everywhere, until an admin approves or rejects them) and
**email verification** (the idea reaches the team only after its sender confirms their
address; needs SMTP; ideas never confirmed are deleted after 3 days). Without SMTP the
form asks for no address at all. Submitters' confirmation and status emails go through
the normal outbox and worker ([Email](#email-phase-3)) in the project's branding; there
is no unsubscribe header because the tracking page is where people stop them ("Stop
these emails" in every status email's footer). Confirmation links have the form
`<publicBaseUrl>/<project slug>/verify#<token>` (links sent before 2 October 2026 as
`/verify#<token>` keep working); the token stays after `#`, so it never reaches a log.

The hourly cleanup (the worker) deletes expired ALTCHA records, ideas held for
confirmation for more than 3 days, unconfirmed addresses after 3 days, contact details
of closed ideas idle for 180 days, and unused uploaded images after 24 hours.

## Branding [Phase 4]

Platform admins set the instance's branding in Settings → Branding (app name, logo,
favicon, primary and accent colours, one of the four bundled fonts, an email footer);
project admins can override any of them for their project. The
signed-in app always uses the global branding; a project's override applies to its
public pages, the emails its public submitters get and its exported PDFs. A project that
uploads its own logo but leaves the app name empty is its own brand: its name is the
wordmark in those emails, the PDF's running header and the public pages' title. Global
changes are audited as `branding.update`, project ones as `project.update`.

- **Applied at runtime**, no restart or rebuild: the SPA sets CSS variables, the page
  title and the favicon; emails and PDFs read the branding when they are produced.
  Each API pod caches resolved branding for 5 seconds, so after a save other replicas
  follow within 5 seconds.
- **Safe by construction:** colours are `#rrggbb` only and fonts a fixed key (both also
  checked by the database), so nothing typed reaches CSS; the app name and footer are
  plain text.
- **Uploads** are the only files Soundings accepts: logos and favicons, PNG or SVG, at
  most `branding.maxUploadBytes` (512 KiB by default, 900 KiB at most so an upload
  always fits the 1 MiB request limit), at most 2048 × 2048 pixels (favicons 512 × 512)
  and 20 uploads per profile per day. They are stored in PostgreSQL (no volume or object
  storage to provision; back up the database and you have them). PNGs are decoded with
  Pillow's PNG reader only and re-encoded (metadata and trailing data stripped); SVGs
  are parsed without DTDs or entities, checked against an allow-list of drawing elements
  and attributes (no scripts, links, `use`, embedded images, styles or external
  references; size and reference budgets against rendering bombs) and re-serialised
  ([ADR 0012](adr/0012-branding-and-uploaded-images.md)). They are served by id with
  `nosniff`, a sandboxing `Content-Security-Policy` and year-long immutable caching
  (a new image gets a new id), and the SPA shows them only as images. Emails carry no
  images. An image no profile uses is deleted 24 hours after upload.
- **PDF export** renders in a child process of each API pod (about 100–190 MiB while
  warm, one render at a time per pod, killed after 20 seconds with a 503) and fetches
  nothing: only the embedded logo and the bundled fonts. No egress rule is needed. The
  layout is bounded (at most 5,000 layout boxes per document; a longer section is cut
  in the PDF with a note pointing to the Markdown export), and the renderer limits its
  own memory to half the container's limit (at most 1 GiB) and restarts when it grows
  past that, so a hostile proposal can't get the pod OOM-killed. The chart's default
  `api.resources.limits.memory` is **1Gi**; don't go below 768Mi. The renderer starts
  with no secrets in its environment.

## API keys and MCP [Phase 5]

People create personal API keys in Settings → API keys and use them with the REST API
(`/api/v1`) or the MCP server (`/mcp`). How to connect a client and the tool catalogue:
[mcp.md](mcp.md); the contract: [contract-phase5.md](api/contract-phase5.md); the design:
[ADR 0013](adr/0013-api-keys-and-mcp-server.md). Nothing needs configuring: keys and
`/mcp` are always on, and every limit below is a constant (simple beats configurable).

### Keys

- **Format and storage:** `sdg_` + a 12-character lookup id + `_` + a 40-character secret
  (`sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}`: add it to GitHub push protection or gitleaks as
  a custom pattern). The database holds the lookup id and a SHA-256 of the whole key, never
  the key; the key is shown once. Rotating `SOUNDINGS_SECRET_KEY` doesn't affect keys.
- **What a key can do:** its owner's permissions **at each request** (roles, groups,
  platform-admin flag), narrowed by its scopes (`read`, `write`, `evaluate`, `mcp`) and an
  optional project restriction. Deleting and moderating ideas, project and admin settings,
  the inbox and key management are session only. Platform admins' keys are narrowed the
  same way and can't reach any admin page.
- **When a key stops:** revoked (by its owner, or any key in Settings → All API keys),
  expired, its owner deactivated (that revokes every key of theirs; reactivating doesn't
  bring them back), its owner hasn't signed in for 30 days (**dormant**: it works again
  after their next sign-in, which also refreshes their groups; service accounts are exempt),
  or the sign-in method of the session that created it is no longer available (a key made
  with the development login stops when `devLogin` is off; a key made through SSO while
  `oidc.issuer` is empty). Authentication reads the key's row on every request, so all of
  these apply to the next request on every replica, and each MCP tool call reads the key
  and its owner again inside its own transaction (a call let in just before a revoke
  runs nothing after it: the tool error `unauthorized`). The break-glass account can't
  create keys. "Sign out everywhere" ends sessions, not keys.
- **Lost project access shows:** a restricted key whose owner can no longer open one of
  its projects stops reaching it at once; Settings → API keys says "+1 project you can no
  longer open", and Settings → All API keys strikes that project through.
- **AI agents' keys** (service accounts, Phase 6): an agent without a role in a project is
  treated as a private non-member there (404), internal projects included; it never owns
  an idea or holds the admin role; its evaluations are left out of the aggregate; and its
  people search (`GET /api/v1/users`) finds only people who share a project with it,
  inside its key's projects.
- **A leaked key:** paste it into Settings → All API keys' search (only its first 16
  characters are sent and matched exactly), revoke it, and look for its id in the audit
  log (`api_key_id`).

### Exposing `/mcp`

- `/mcp` is served by the API pods on the app's port, `POST` only (other methods 405),
  stateless JSON responses (no SSE, no sessions), so proxies need no buffering or timeout
  changes. The chart's ingress (or HTTPRoute) already routes it with the rest of the app.
  To restrict who may reach it from outside, set `ingress.mcp.annotations` (for example an
  allow-list middleware): it adds an Ingress `<release>-soundings-mcp` for `/mcp` only, a
  Prefix path so it outranks `/` on Traefik too.
- **In the cluster** (kagent, Phase 6), clients call the Service:
  `http://<fullname>.<namespace>.svc.cluster.local/mcp`. `/mcp` is exempt from the app's
  Host check (like the probes), so that host needn't be in `baseUrls`. Every request still
  needs a bearer key, and an `Origin` header, when a client sends one, must be one of the
  `baseUrls` origins (403 `invalid_origin`), which stops DNS rebinding from browsers. With
  `networkPolicy.ingressFrom` set, add the namespaces of in-cluster clients to it
  (`kagent.enabled` adds kagent's).
- `/mcp` never accepts session cookies and sends no CORS headers. `/.well-known/*` answers
  404 problem+json: there is no OAuth for MCP (keys are issued in the app), and clients
  that probe for it report the key error instead.
- **No `Authorization: Bearer` header from a proxy.** The app reads every `Authorization:
  Bearer …` header as an API key (a bad one is 401, never a fall-through to the session
  cookie), so a forward-auth or OAuth2 proxy in front of the app that adds its own bearer
  token (oauth2-proxy's `--pass-authorization-header` or `--set-authorization-header`, an
  ingress `auth-response-headers: Authorization`, an identity-aware proxy injecting an ID
  token) makes every browser request 401 and counts the proxy's address towards the
  failed-key throttle. Don't forward such a header upstream; `Basic` and other schemes are
  ignored. Sign-in to Soundings is OIDC itself: it needs no auth proxy.
- **Text for agents:** request bodies refuse invisible Unicode tag characters (hidden
  instructions for AI models), and MCP results have every invisible character stripped;
  ideas from the public form say `via_public_form`, and every people-written field is
  described as untrusted in the tools' output schemas.

### Rate limits

All three are counted **in each API pod's memory** (like the sign-in throttles), so with
N replicas a client spread across them gets up to N times as much; they bound floods and
runaway agents, not determined attackers.

| Limit | Over it |
|---|---|
| 30 failed key authentications a minute per client address (IPv6: per /64) | failing keys from that address get 429 `too_many_attempts` with `Retry-After` instead of 401; **valid** keys from the same address still work, so one broken script behind a NAT can't lock out its neighbours |
| 300 requests a minute per key (REST and `/mcp` together, refused ones included) | 429 `too_many_attempts` |
| 30 writes a minute per key (REST `POST`/`PUT`/`PATCH`/`DELETE`, MCP tools that change something) | 429, or the tool error `too_many_attempts`; reads still work |

The client address comes from the trusted proxies (`trustedProxies`, `trustedProxyHops`;
see [Security](#security-pod-security-restricted-networkpolicy-secrets)): get those right or
every client looks like the ingress controller and shares one failure budget.

### Audit and logs

- `api_key.create` and `api_key.revoke` (with the key's id and prefix; `reason:
  deactivated` when deactivation revoked it) are kept like every other audit entry.
- **Every MCP tool call** is one `mcp.call` entry: the tool, its rule, `allow` or `deny`,
  the error code, the key's id, and the idea or project it was about; never the arguments
  (queries, comments and idea text can hold personal data). A request refused for lack of
  the `mcp` scope, or over the key's request budget, is recorded too, at most once a
  minute per key; a cancelled call (`cancelled`) and a crash (`internal_error`) are
  recorded; `initialize`, `tools/list` and requests the SDK refuses before a tool runs
  (415, 406, 400) aren't. What a call changed has
  its own entry as in the app (`evaluation.submit`, with `auth: api_key` and the key id).
  The worker's hourly job deletes `mcp.call` entries older than **90 days**; other entries
  are kept for good. Audit log → "API keys and MCP" shows them.
- Refused key authentications are **not** audited (a flood must not fill the audit log):
  they are logged at INFO as `api key refused` with a `reason` (`malformed`, `unknown`,
  `mismatch`, `revoked`, `expired`, `inactive_owner`, `method_unavailable`,
  `dormant_owner`) and the key id when known; the first throttled refusal of an address in
  a minute is a WARNING. Logs never contain a key, the `Authorization` header or tool
  arguments; the MCP SDK's own loggers are held at WARNING for that reason.

### Checking it

`make mcp-smoke` (`scripts/mcp-smoke.sh <base URL>`, needs dev login and the demo data)
runs the acceptance with curl: a key, `initialize`, the ten tools listed, blind results,
`not_found` outside the key's projects, `insufficient_scope`, a foreign `Origin`, the
audit entries, then revoke and 401 on the next call. On k3s, `make k3s-install MCP=1` and
`make k3s-smoke MCP=1` also run an MCP client in a pod of another namespace with its key in
a Secret, as kagent will (`scripts/k3s-mcp-client.sh`).

## kagent integration [Phase 6]

AI assistance (SPEC section 9) uses [kagent](https://kagent.dev) agents for two jobs: the
**AI evaluator** ("Ask AI to evaluate": a cited evaluation with an AI badge, left out of
the aggregate unless the idea's owner or an admin includes it) and the **research and
drafting assistant** ("Research this": a cited research note; "Draft section": a proposal
suggestion the owner accepts or discards). It is **off by default** and optional: without
it nothing in Soundings needs kagent.

How a run works: a person asks on the idea page; the API writes a run row and a job on the
worker's `ai` queue; the worker sends **one A2A message** to kagent's controller at
`<controllerUrl>/api/a2a/<namespace>/<name>/` (kagent 0.10, A2A 0.3) or
`/agents/<namespace>/<name>` (kagent 1.0, `A2A-Version: 1.0`), streams the task's status,
and ends the run when the task does, at the deadline (`ai.runTimeout`, then A2A
`tasks/cancel`) or when someone cancels. The agent does the work through Soundings'
**MCP server** (`/mcp`) with **its own service account's key**: `get_rubric`, `get_idea`,
then `submit_evaluation`, `add_research_note` or `propose_proposal_section`. Soundings
attaches that result to the run; A2A text is ignored. Progress reaches browsers over
Server-Sent Events from the API (falls back to polling). Design: ADR 0014; contract:
`docs/api/contract-phase6.md`; manifests and the full walkthrough:
[`deploy/kagent/README.md`](../deploy/kagent/README.md).

Security properties to rely on:

- **URLs are built, never given.** Soundings calls only `SOUNDINGS_KAGENT_URL` (Helm
  `kagent.controllerUrl`, an origin validated at start-up) + a fixed path + the agent's
  namespace and name (DNS labels, always limited to the allowed namespaces:
  `kagent.agentNamespaces`, else the release namespace).
  Nothing typed in the UI, sent by an agent or found in an agent card can make it call
  another host; redirects are never followed and proxy variables are ignored.
- **Prompts carry no secrets:** the message holds the run id, kind, idea key, section and
  the agent's name, never a key, URL or idea text.
- **An agent's key works only inside its runs (c22):** only on `/mcp` (every REST route
  answers 403), and every call must name its open run (`run_id`, from the run's message):
  it then reaches only that run's idea, writing only that run's result. Two runs of one
  agent open at once can't reach each other. After a run ends (done, cancelled, timed
  out, worker restart) calls naming it do nothing, even while a newer run is open.
- **Agents are blind:** they never see other evaluators' scores or comments, before or
  after submitting, and see their own evaluation only in their evaluate run. Everything
  an agent writes is shown labelled AI and treated as untrusted text (sanitised
  Markdown, http/https links only, sources "Cited by AI, not checked").

### Enabling AI assistance

```sh
helm upgrade soundings ./deploy/helm -n soundings --reuse-values \
  --set features.ai=true --set kagent.enabled=true
```

| Value (env) | Default | Meaning |
|---|---|---|
| `features.ai` (`SOUNDINGS_AI_ENABLED`) | `false` | The switch. Off: no run starts (409 `ai_unavailable`), queued runs fail, the idea page hides the AI actions; Admin settings → AI agents still works |
| `kagent.controllerUrl` (`SOUNDINGS_KAGENT_URL`) | `http://kagent-controller.<kagent.namespace>:8083` | kagent's controller, an http(s) origin without a path |
| `kagent.existingTokenSecret` / `tokenSecretKey` (`SOUNDINGS_KAGENT_TOKEN`) | empty | Bearer token for kagent's `trusted-proxy` auth mode (api and worker pods) |
| `kagent.agentNamespaces` (`SOUNDINGS_AI_AGENT_NAMESPACES`) | the release namespace (the app's own default without the chart: `soundings`) | Where agents may be registered, at least one (an empty list is refused at start-up, never "any"); keeps runs away from kagent's built-in agents in kagent's own namespace |
| `ai.runTimeout` (`SOUNDINGS_AI_RUN_TIMEOUT`) | `PT5M` | Deadline once a run has started (30 s to 1 h) |
| `ai.maxConcurrentRuns` (`SOUNDINGS_AI_MAX_CONCURRENT_RUNS`) | `4` | Runs at once per worker pod, in a pool of their own (email and the schedules never wait behind them); the worker's database pool grows by this many |
| `ai.defaultProtocol` (`SOUNDINGS_AI_DEFAULT_PROTOCOL`) | `kagent_v0_10` | Protocol of a new agent unless the admin picks one |
| `ai.mcpUrl` (`SOUNDINGS_AI_MCP_URL`) | the release's Service URL + `/mcp` | Shown to admins for the agents' `RemoteMCPServer`; never sent to agents |

AI runs need the **worker** (`soundings worker`): without it runs stay queued and expire
after 30 minutes. Each person may ask for 20 runs an hour; one run is active per idea,
agent and kind (a repeated request returns it). A worker that stops mid-run ends its runs
`worker_lost` and tells the agent to cancel.

### Checking the installed kagent version

The manifests target kagent **0.10.x** (`kagent.dev/v1alpha2`; kagent-adk 0.10.2 speaks
A2A 0.3 only, so register agents with protocol `kagent_v0_10`). kagent 1.0 (pre-release)
moves to `api.kagent.dev/v1alpha3`, new Agent kinds and the `/agents/<ns>/<name>` A2A
path. Check before enabling anything:

```sh
kubectl get crd | grep kagent           # agents.kagent.dev: 0.10; agents.api.kagent.dev: 1.0
kubectl explain agents.spec.declarative --api-version=kagent.dev/v1alpha2
kubectl -n soundings get agents,rmcps
```

### Registering agents, service accounts and their Secret

1. **Create the kagent Agent** (below) in an allowed namespace, with a `ModelConfig`.
2. **Register it** in Soundings: Admin settings → AI agents → Register agent (platform
   admins, signed in; not the break-glass account): display name, the Agent's namespace
   and name, protocol, purposes (evaluate, research, draft sections) and projects. This
   creates the agent's **service account** (`agent-<id>@soundings.invalid`, never signs
   in, never owns ideas, never a project admin), makes it a member of those projects and
   creates **one key** whose scopes follow the purposes and whose projects follow the
   agent (no expiry; changing the agent changes the key, no new Secret needed).
3. **Apply the Secret** it shows once (`soundings-agent-<name>`, key `authorization`, the
   whole header `Bearer sdg_…`) in the agent's namespace, and point the Agent's
   `RemoteMCPServer` at it (the dialog also shows that manifest, with the MCP URL in
   effect). The key is never shown again; Soundings keeps only a fingerprint.
4. **Test connection** fetches the agent card through the controller (10 a minute per
   admin) and shows the agent's name, skills and A2A versions, or the HTTP status.

**Rotate key** issues a new key and revokes the old one at once (apply the new Secret;
runs fail until you do). **Disable** revokes the key and cancels the agent's runs;
enabling it again needs a rotation. Deactivating the service account (Admin → Users) also
revokes its key. Agents are never deleted. Every registration, change (with the new
purposes, projects and key scopes), rotation, run request, cancel, "include in score" and
research-note deletion is in the audit log (category "AI agents and runs"), and every MCP
call an agent makes is an `mcp.call` entry with its key.

**Reach:** an agent's key can act only inside its runs, but while a run is open, anyone
who can message that kagent agent directly could steer it on that idea. Keep kagent's UI
and A2A endpoint inside the cluster (kagent's default auth mode, `unsecure`, trusts every
caller; use `trusted-proxy` with `kagent.existingTokenSecret` where you can), and register
separate agents for projects that must not share one.

**kagent keeps what its agents read.** kagent stores each run's session (the task, its
messages and tool calls, so the idea text and comments the agent read through MCP) in
its own database. That copy is outside Soundings: deleting an idea, erasing a public
submitter's details and Soundings' retention schedules don't reach it. Apply kagent's own
retention (or clean its database) if your data rules need it, and keep its database as
protected as Soundings'.

### Example manifests (`deploy/kagent/`)

- `deploy/kagent/agents.yaml`: by hand, for kagent 0.10 in namespace `soundings`: a
  `ModelConfig`, and for `idea-evaluator` and `idea-researcher` each a placeholder key
  Secret (replace it with the one registration shows), a `RemoteMCPServer` reading it and
  a Declarative, streaming `Agent` with its Soundings tools and standing rules.
- The chart's `kagent.examples=true` (needs `kagent.enabled` and kagent's CRDs) renders
  the same two agents as `<fullname>-evaluator` and `<fullname>-researcher`, each with its
  own `RemoteMCPServer` reading `soundings-agent-<fullname>-evaluator` / `-researcher`,
  the names registration's Secret uses; set `kagent.agents.modelConfig`:

  ```sh
  helm upgrade soundings ./deploy/helm -n soundings --reuse-values \
    --set kagent.examples=true --set kagent.agents.modelConfig=soundings-model
  ```

- `deploy/kagent/remote-mcp-server.yaml` (Phase 5, `kagent.mcp.keySecret`): a shared
  `RemoteMCPServer` with one **person's** key for their own kagent agents. An AI agent's
  key doesn't work there outside its runs.
- `deploy/kagent/fake-agent-byo.yaml`: Soundings' deterministic test agent as a `type:
  BYO` Agent, for a test cluster that has kagent but no model.

### NetworkPolicy

With `networkPolicy.ingressFrom` set (recommended), `kagent.enabled` admits kagent's
namespace and, in `kagent.agentNamespaces`, pods labelled
`app.kubernetes.io/managed-by: kagent` (kagent's agent pods) to the API; other pods there
are dropped. With `networkPolicy.egress.enabled`, the api (Test connection) and the
worker (runs) may also reach kagent's controller port (`networkPolicy.egress.kagent.to`
narrows the peers, `.port` overrides 8083). The agents reach `/mcp` through the Service
URL (`http://<fullname>.<namespace>.svc.cluster.local:<port>/mcp`); exposing `/mcp`
through the ingress is not needed for them.

### What is verified against kagent, and what isn't (2026-10-06)

| | Against | Status |
|---|---|---|
| Every manifest in `deploy/kagent/` and the chart's `kagent.examples` resources | kagent **v0.10.2**'s real CRDs (git tag v0.10.2) in k3s v1.31: `make k3s-kagent-crds` (server-side dry run), created for real by `make k3s-install AI=1` | **verified** (the API server applied defaults and refused invalid fields) |
| kagent's MCP client (go-sdk v1.6.1) against `/mcp` | the library kagent pins | **verified** (Phase 5) |
| The whole loop: register, Test connection, A2A 0.3 and 1.0 streaming, `tasks/get` polling, cancel, deadline, worker shutdown, results through `/mcp`, c22, blind agents, SSE through Traefik, NetworkPolicies, two API replicas | Soundings' **fake agent** (`dev/fake-agent`, on a2a-sdk 1.2.1's server; its 0.3 wire format checked with a2a-sdk 0.3.23's client, kagent-adk 0.10.2's library) standing in for kagent's controller: backend acceptance, `E2E_AI=1` e2e, `make demo DEMO_AI=1`, `make ai-smoke`, `make k3s-smoke AI=1` | **verified against the fake** |
| kagent's controller proxying A2A to agent pods, its task store for `tasks/get`, its handling of `A2A-Version`, `RemoteMCPServer` `headersFrom` resolution at runtime, kagent 1.0's layout | kagent's source and docs only (its chart can't be pulled on our build network) | **not verified live** |
| A model following the run message (tool order, real citations, no scores in notes) | no LLM here | **assumed**; the server enforces the rules (c22, blind, limits, result matching) regardless |

To close the gap on your cluster: install kagent 0.10.x, apply `fake-agent-byo.yaml`
(the fake behind kagent's real controller, no model needed), register it and run "Ask AI
to evaluate"; then swap in a Declarative agent with your `ModelConfig`.

### Troubleshooting runs

A run's row on the idea page says why it ended in plain words with a next step (its
**Steps** show Soundings' fixed sentence, including the A2A state where there is one);
`GET /api/v1/ideas/{idea}/ai-runs/{id}` has the code and that sentence:
`agent_unreachable` (no connection to the controller, or 5xx / 404, after two retries: check `kagent.controllerUrl`, the egress policy, the
Agent's namespace and name), `agent_unavailable` (the agent was disabled, lost the
project or purpose, or has no usable key when the run started), `agent_protocol_error`
(the controller answered something other than A2A: wrong protocol for the kagent
version?), `agent_rejected`, `agent_failed` and `agent_needs_input` (the agent's task
ended so: its logs are in kagent), `no_result` (the task completed without recording its
result through MCP: often a missing or stale key Secret, or a model that ignored its
instructions), `timed_out` (raise `ai.runTimeout` or use a faster model),
`queue_timeout` (no worker picked it up for 30 minutes), `worker_lost` (the worker
stopped mid-run), `ai_disabled` and `internal_error` (logged with its traceback). Worker
logs carry run ids, error classes and HTTP statuses, never prompts, keys or agent text.

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
the scraper with `networkPolicy.metricsFrom` when network policies are on: since Phase 7
nobody else may connect to the metrics port by default (route counts and timings say
how the app is used).
`otel.endpoint` sends OTLP/HTTP traces.

### Logs (JSON, no PII)

One JSON object per line on stdout. Every response carries an `X-Request-ID` (an
incoming well-formed one is reused), which is also in the log line and in problem
responses, so a user's error report can be matched to the log.

### Backups and restore

Everything Soundings keeps is in PostgreSQL: ideas, evaluations, proposals, the audit
log, the email outbox and the job queue, and the branding images. Back up the database
and the chart's Secret (`<release>-soundings`: the signing key; without it sealed
values, unsubscribe and tracking links stop working, and people sign in again).

- External or CloudNativePG database: use its backups (point-in-time recovery).
- Bundled Postgres: a nightly `pg_dump` is enough for its size, e.g.
  `kubectl -n soundings exec sts/soundings-postgresql -- pg_dump -U postgres -Fc soundings > soundings.dump`;
  restore into an empty database with `pg_restore -U postgres --no-owner --role=soundings -d soundings`.

Restore with the API and worker scaled to 0, then start them: `soundings migrate` (the
init containers or the hook) brings an older dump's schema up to date. Erased data (a
public submitter's details, an anonymised account) is in backups until they expire.

### Scaling: replicas, HPA, PodDisruptionBudget

Each API pod runs **one** uvicorn worker (an event loop plus a warm PDF renderer of
about 190 MB): scale with `api.replicas` or `autoscaling.enabled` (CPU, 2 to 6 replicas
by default), not with more workers per pod [Phase 7: measured at 10k ideas, two workers
per pod cut the median screen time by a third but not the tail, and doubled memory].
One pod served 20 people at once with reads at p95 under 150 ms one at a time and 262
ms under load (docs/test-plans/performance.md). The throttles (sign-in, public form,
keys, writes) are per pod, so with N replicas they allow N times as much.
`podDisruptionBudget` (on, `maxUnavailable: 1`) keeps one API pod during node drains
without ever blocking them. The worker's scaling is described under
[Worker and scaling](#worker-and-scaling).
### Security: Pod Security `restricted`, NetworkPolicy, secrets

`networkPolicy.enabled` is **on by default**: the bundled Postgres accepts only this
release's pods, the worker accepts nothing, and the API's HTTP port accepts this
release's pods plus `networkPolicy.ingressFrom` (any source while that is empty; the
NOTES warn you, see [Client addresses behind the ingress](#client-addresses-behind-the-ingress-phase-7)).
Set `ingressFrom` to your ingress controller's namespace so other
pods can't reach the API directly with an `X-Forwarded-For` of their choosing, and
`metricsFrom` to your Prometheus: while it is empty only this release's own pods may
scrape the metrics port [Phase 7]. The policies are ignored on a CNI without
NetworkPolicy support (k3s's default flannel enforces them through its network policy
controller).

**Client addresses behind proxies.** The sign-in throttles key on the client IP. The app
believes `X-Forwarded-For` only from a peer in `trustedProxies` (default: the private
ranges, where ingress controllers live) and only its `trustedProxyHops` rightmost
entries (default 1: the ingress controller's; set 2 when an L7 load balancer in front
of the ingress also appends). Entries further left are whatever the client sent and are
ignored. Narrow `trustedProxies` to your ingress pods' range where you can.
### Audit log

Settings → Audit log (platform admins) records sign-ins, admin and access changes,
assignments, evaluations, status changes, deletions, public-submission decisions,
branding, API keys and every MCP tool call, with ids and outcome codes only. Entries are
kept indefinitely except `mcp.call`, which the worker deletes after 90 days
([above](#audit-and-logs)).

### Troubleshooting

| Symptom | Look at |
|---|---|
| A pod won't start: `SOUNDINGS_SECRET_KEY must be set to 32+ random characters` | Production refuses the development key: set `secretKey.existingSecret`, or let the chart generate one (not with `--dry-run`, Argo CD or Flux: [Upgrades](#upgrades-and-migrations-pre-upgrade-hook-argo-cd-presync)). |
| `soundings: refusing to start. SOUNDINGS_ENVIRONMENT is not set ...` | A hand-built environment without the image's setting: set `SOUNDINGS_ENVIRONMENT` ([Running the image without Helm](#running-the-image-without-helm-phase-7)). |
| 400 `invalid_host` | The host isn't in `baseUrls`. |
| Everyone shares one rate limit, or a limit never applies | `trustedProxies` / `trustedProxyHops` ([Client addresses behind the ingress](#client-addresses-behind-the-ingress-phase-7)). |
| 429 `rate_limited` for a person | More than 120 changes a minute ([Sessions](#sessions)). |
| Sign-in loops or `login_expired` | The issuer URL must be the same for browsers and pods; cookies need `https` in production. |
| No email | Admin settings → Email (settings in effect, the outbox, test email); a running worker. |
| AI runs fail | [Troubleshooting runs](#troubleshooting-runs). |
| Anything else | The response's `request_id` is in the API's log line for that request. |

## Data protection [Phase 4, 7]

### Erasing a public submitter's personal data

What Soundings keeps about someone who used a public form (UK GDPR, data minimisation):
the idea they wrote, and only if they gave them their name and email address, whether
the address is confirmed and whether they want status emails, plus a copy of the title
and summary as sent and a hashed and an encrypted copy of their tracking token. **No IP
address, user agent or cookie is stored**: rate limits are counted in memory, and
logs and the audit log hold ids and outcome codes only, never names, addresses, tokens
or idea text. The form shows a fixed privacy notice saying this.

Erasure removes the name, address, confirmation, update preference, the copy of what was
sent and the tracking link (which stops working at once), and deletes every email queued
or sent to that person; the idea and its history stay. It happens three ways, each
recorded as `submission.erase` in the audit log:

- a project or platform admin clicks **Erase submitter details** in the idea's
  submission panel (a request by email or phone ends here);
- the submitter clicks **Delete my details** on their tracking page (no actor);
- the retention rules, hourly (no actor, reason `retention`): contact details of closed
  ideas idle for 180 days; unconfirmed addresses are dropped after 3 days, and ideas
  still waiting for confirmation then are deleted.

Personal data someone typed into the idea's own text is removed by editing the idea;
rejecting a held idea deletes it entirely. The retention periods are constants. Database
backups keep erased data until they expire, so set your backup retention accordingly.

### What is stored about users [Phase 7]

About the people who sign in (staff accounts), Soundings keeps what it needs to show who
did what and to let them in, and nothing it doesn't (UK GDPR, data minimisation). No IP
address is stored anywhere; logs carry ids and outcome codes, never names, addresses,
tokens or text.

| Where | What | Kept |
|---|---|---|
| `users` | email address, display name, platform-admin and active flags, when last seen | until anonymised (deactivating keeps it, so their work still names them) |
| `user_identities` | the IdP's issuer and subject (`sub`), last SSO sign-in | until unlinked (Admin settings → Users) or anonymised |
| `user_external_ids` | ids from an IdP claim (an employee number) | until changed or anonymised |
| `user_sessions` | SHA-256 of the session token, the CSRF token, the sign-in method, the ID token sealed with the signing key (for the IdP's sign-out), a browser and OS summary ("Firefox on Linux") | until sign-out; once expired (12 h idle, 24 h at most) deleted hourly |
| `group_memberships`, `project_members` | groups (synced from the IdP or added by hand) and project roles | while they apply |
| `api_keys` | key name, lookup id, SHA-256 of the key, scopes, last use; revoked keys stay for the audit trail | for good (revoked at deactivation) |
| `notifications`, `notification_preferences` | their inbox and email choices | inbox 90 days; preferences until anonymised |
| `outbound_email` | emails to them, by user id (the address is read when sending, not stored) | sent 30 days, failed 90 days |
| ideas, comments, evaluations, votes, watches, proposals, suggestions, `activity_events`, `ai_runs` | what they wrote and did, by user id; @mentions of them carry their name in the comment text | the organisation's record: kept with the idea (deleted with it) |
| `audit_log` | the actor's and target's ids, the action, ids and field names (never names, emails, tokens or claims) | for good, except `mcp.call` entries (90 days) |

**When someone leaves:** deactivate them in Admin settings → Users (signs them out,
revokes their keys, stops their notifications; their work keeps their name). To erase
their personal data (an erasure request, or your retention policy), run, once
deactivated:

```bash
kubectl -n soundings exec deploy/soundings-api -- soundings anonymise-user lee@example.com
```

It renames the account "Former user <8 characters>" with an undeliverable placeholder
address, deletes their sign-in identities, external ids, sessions, inbox, email
preferences and outbox rows, revokes any key still active, and renames @mentions of
them in comments; ideas, evaluations, comments and audit entries stay, under the
placeholder. It records one `user.anonymise` audit entry (counts only, no actor) and
can't be undone. It refuses an active account, the break-glass account and AI agents'
service accounts (disable or delete the agent instead). Remove the person from your IdP
too: with `oidc.autoCreateUsers` on, their next SSO sign-in would create a new account.
Text they typed into ideas or comments that names them is edited like any other text;
backups keep the old rows until they expire.

**Right of access:** Admin settings → Users shows the account, its identities, groups,
projects and keys; Admin settings → Audit log, filtered by the person, shows what they
did as an administrator.
