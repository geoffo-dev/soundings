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
make demo                        # build soundings:dev, run it with Postgres, the worker,
                                 # Mailpit and demo data
open http://localhost:8000       # pick a person on the sign-in page (Alice is the admin)
open http://localhost:8026       # Mailpit: every email the demo sends
make demo-down                   # remove the containers and their data
```

`make demo` (`scripts/demo.sh`) runs the same image as the cluster, in development mode
with the dev login and the demo story (12 people, three projects, 45 ideas; who's who
in [dev/README.md](../dev/README.md#demo-data)), plus `soundings worker` and Mailpit as
its SMTP server, so invitations, mentions and the rest arrive in Mailpit's inbox.
`DEMO_PORT` changes the app's port and `DEMO_MAILPIT_PORT` Mailpit's, `DEMO_SMTP=0`
runs without email (in-app notifications only), `DEMO_TIMEZONE` sets the instance time
zone, `DEMO_RESET=1` reloads fresh demo data, and running it again after `make image`
swaps the app and worker containers and keeps the data. Without a Debian mirror, build with
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
  existingSecret: soundings-smtp  # optional keys: username, password
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

Credentials come from the Secret (or `smtp.username` / `smtp.password` in values, not
both); both keys are optional, for relays that accept your cluster without
authentication. The api and worker pods get the same settings (the api queues mail and
shows the configuration, the worker sends it). Changing a value rolls both
Deployments; a new password in the Secret or a new CA needs `kubectl -n soundings
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
providers expect from automated mail.

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
and **replaces** the system trust store for SMTP only (sign-in uses the image's trust
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
that is still current. Mail older than **3 days** (digests: **2 days**) is never sent
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
Message-ID. An outage longer than about 5 hours leaves emails Failed: use **Retry all
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
  daily cleanup (old notifications and outbox rows) runs in the digest hour's run.

### Running without SMTP

Leave `smtp.host` empty (the default). The app works with in-app notifications only:
the bell and inbox are unchanged, preferences can still be set (the page says email
isn't set up), nothing is written to the outbox, and platform admins see a dismissible
banner "Email isn't set up" linking to Settings → Email, which lists the setup steps.
Test email and retry answer 409. Configure SMTP later and email starts with the next
notification; nothing from before is sent late.

### Worker and scaling

The worker (`soundings worker`, Deployment `worker`) runs every background job: sending
email, the per-minute outbox sweep, the hourly schedule and the daily job cleanup. Keep
`worker.enabled` on whenever SMTP is configured. One replica with `worker.concurrency`
4 is plenty for most organisations; more replicas are safe (each email is claimed by
exactly one worker with a 5-minute lease, and periodic jobs are queued once however
many workers run), and give you continuity during node drains. Each attempt must finish
within 4 minutes; a worker that dies mid-send leaves the email to the sweep, which
retries it after the lease (the recipient may then, rarely, get it twice, with the
same Message-ID). The worker serves no HTTP and needs no Service; shutdown waits
`worker.terminationGracePeriodSeconds` for running jobs.

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
### Troubleshooting

## Data protection [Phase 4, 7]

### Erasing a public submitter's personal data
### What is stored about users
