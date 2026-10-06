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
  these apply to the next request on every replica. The break-glass account can't create
  keys. "Sign out everywhere" ends sessions, not keys.
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

### Rate limits

All three are counted **in each API pod's memory** (like the sign-in throttles), so with
N replicas a client spread across them gets up to N times as much; they bound floods and
runaway agents, not determined attackers.

| Limit | Over it |
|---|---|
| 30 failed key authentications a minute per client address (IPv6: per /64) | failing keys from that address get 429 `too_many_attempts` with `Retry-After` instead of 401; **valid** keys from the same address still work, so one broken script behind a NAT can't lock out its neighbours |
| 300 requests a minute per key (REST and `/mcp` together) | 429 `too_many_attempts` |
| 30 writes a minute per key (REST `POST`/`PUT`/`PATCH`/`DELETE`, MCP tools that change something) | 429, or the tool error `too_many_attempts`; reads still work |

The client address comes from the trusted proxies (`trustedProxies`, `trustedProxyHops`;
see [Security](#security-pod-security-restricted-networkpolicy-secrets)): get those right or
every client looks like the ingress controller and shares one failure budget.

### Audit and logs

- `api_key.create` and `api_key.revoke` (with the key's id and prefix; `reason:
  deactivated` when deactivation revoked it) are kept like every other audit entry.
- **Every MCP tool call** is one `mcp.call` entry: the tool, its rule, `allow` or `deny`,
  the error code, the key's id, and the idea or project it was about; never the arguments
  (queries, comments and idea text can hold personal data). A call refused for lack of the
  `mcp` scope is recorded too; `initialize` and `tools/list` aren't. What a call changed has
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
runs the acceptance with curl: a key, `initialize`, the nine tools, blind results,
`not_found` outside the key's projects, `insufficient_scope`, a foreign `Origin`, the
audit entries, then revoke and 401 on the next call. On k3s, `make k3s-install MCP=1` and
`make k3s-smoke MCP=1` also run an MCP client in a pod of another namespace with its key in
a Secret, as kagent will (`scripts/k3s-mcp-client.sh`).

## kagent integration [Phase 6]

Phase 5 prepares it; Phase 6 adds the agents, their UI and the A2A runs. Agents use the
MCP server above with a **service account's** key, under the same rules as people (blind
evaluation, the key's projects and scopes, every call audited); a service account never
owns an idea or holds the admin role, and its evaluations are left out of the aggregate by
default. Details and what has been verified: [`deploy/kagent/README.md`](../deploy/kagent/README.md).

### Checking the installed kagent version

The manifests target kagent **0.10.x** (`kagent.dev/v1alpha2`); the 1.0 line changes the
API group version and the Agent kinds. Check what is installed before enabling them:

```sh
kubectl get crd | grep kagent
kubectl explain remotemcpservers.kagent.dev.spec --recursive | head -40
kubectl -n kagent get agents,rmcps
```

### Registering agents and service-account API keys

Phase 6's Admin → AI agents creates the service account and its key (scopes `read`,
`evaluate`, `mcp`, plus `write` for suggestions and comments), restricted to the projects
the agent serves: one agent account shared by projects that must not see each other is a
path for prompt injection, so register one agent per project there. Project admins add the
agent as a member (never admin). Put the key in a Secret as the whole header value,
`Bearer sdg_…` (kagent sends it as is). Revoking the key, or deactivating the account,
cuts the agent off at its next call.

### Example manifests (`deploy/kagent/`)

`deploy/kagent/remote-mcp-server.yaml` (apply by hand) and the chart's `kagent.examples`
render a `RemoteMCPServer` pointing at the release's Service URL, reading the header from
`kagent.mcp.keySecret` / `.keySecretKey` (both need `kagent.enabled`, which also admits
kagent's namespace through the NetworkPolicy):

```sh
kubectl -n soundings create secret generic soundings-agent-key \
  --from-literal=authorization="Bearer sdg_..."
helm upgrade soundings ./deploy/helm -n soundings --reuse-values \
  --set kagent.enabled=true --set kagent.examples=true \
  --set kagent.mcp.keySecret=soundings-agent-key
```

The example `Agent` manifests (evaluator and researcher) come with Phase 6.

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

The worker's scaling is described under [Worker and scaling](#worker-and-scaling).
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

Settings → Audit log (platform admins) records sign-ins, admin and access changes,
assignments, evaluations, status changes, deletions, public-submission decisions,
branding, API keys and every MCP tool call, with ids and outcome codes only. Entries are
kept indefinitely except `mcp.call`, which the worker deletes after 90 days
([above](#audit-and-logs)).

### Troubleshooting

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
### What is stored about users
