# Soundings Helm chart

One image, two Deployments (`api` serves the REST API and the SPA; `worker` runs
background jobs), PostgreSQL as the only stateful dependency.

```sh
# Try it (bundled Postgres, sign in with the generated break-glass admin):
helm install soundings ./deploy/helm -n soundings --create-namespace \
  --set 'baseUrls[0]=https://ideas.example.com' --set ingress.enabled=true

# Production-shaped example: ci/production-values.yaml
helm upgrade --install soundings ./deploy/helm -n soundings -f my-values.yaml
```

`NOTES.txt` prints the URL and the first sign-in steps. `helm test soundings -n soundings`
checks `/readyz` and the SPA through the Service (with the first base URL's `Host`).

```sh
# A demo with sample data and the dev login (development mode; never on a shared install):
helm install soundings ./deploy/helm -n soundings --create-namespace \
  --set 'baseUrls[0]=http://localhost:8000' --set devLogin=true --set demo.seed=true
kubectl -n soundings port-forward svc/soundings 8000:80   # then open http://localhost:8000
```

Requirements: Kubernetes 1.27+, an ingress controller or Gateway API implementation, a
default StorageClass for the bundled Postgres (or `externalDatabase.*`).

## Values

Every value is validated by `values.schema.json` (unknown keys, wrong types and invalid
enums are rejected). `values.yaml` has a comment on every setting.

| Key | Default | Description |
|---|---|---|
| `baseUrls` | `[http://localhost:8000]` | Origins the app is served on (`scheme://host[:port]`, no path). First = default for email links. Sign-in redirect URIs and ingress/HTTPRoute hosts derive from these. The app answers **only** these hosts (400 `invalid_host` otherwise, except `/healthz` and `/readyz`): list every public host, and call it from inside the cluster with one of them as `Host`. |
| `nameOverride` / `fullnameOverride` | `""` | Override the chart name / the release-scoped base name (max 50 chars). |
| `global.imageRegistry` | `""` | Registry for **every** image (app + Postgres), for air-gapped mirrors. |
| `image.registry` / `.repository` / `.tag` / `.digest` | `""` / `soundings` / appVersion / `""` | The Soundings image. |
| `image.pullPolicy` / `.pullSecrets` | `IfNotPresent` / `[]` | Pull policy; names of existing registry Secrets. |
| `trustedProxies` | private ranges | IPs/CIDRs of the proxies (ingress controller, gateway) whose `X-Forwarded-For`/`-Proto` are believed. Narrow to your ingress controller's pods (see [Security](#security)). |
| `trustedProxyHops` | `1` | How many trusted proxies append to `X-Forwarded-For` (2 with an L7 load balancer in front of the ingress controller that also appends). |
| `logLevel` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. JSON logs, no PII. |
| `devLogin` | `false` | Dev login stub; also switches the app to development mode. Never on shared installs. |
| `demo.seed` | `false` | Load the demo data after install and upgrades (hook Job, see [Demo data](#demo-data)). Needs `devLogin`. |
| `sessions.idleTimeout` / `.maxAge` | `PT12H` / `P7D` | A session ends after this long without a request / this long after sign-in. ISO 8601 durations or seconds. |
| `metrics.port` | `9090` | Port of Prometheus `/metrics` (container and Service port `metrics`); never the app port. |
| `secretKey.existingSecret` / `.existingSecretKey` | `""` / `secret-key` | Session/CSRF signing key. Empty: generated once, kept across upgrades. |
| `oidc.issuer` | `""` | OIDC issuer URL, exactly the provider's `issuer` (https unless `devLogin`). Empty: SSO off; the break-glass admin works instead. See [Single sign-on](#single-sign-on). |
| `oidc.clientId` / `.clientSecret` | `soundings` / `""` | Confidential client (code flow + PKCE). Prefer `oidc.existingSecret` with the secret under `oidc.existingSecretKey` (default `client-secret`); one of the two is required with an issuer. |
| `oidc.scopes` | `[openid, profile, email]` | Requested scopes (`openid` required). |
| `oidc.groupsClaim` | `groups` | Claim (name or dotted path such as `realm_access.roles`) with the IdP groups that group mappings match. Empty: no group sync. |
| `oidc.externalIdClaim` / `.externalIdKind` | `""` / `""` | Claim that links pre-created users by external ID (e.g. `employee_no`, Entra ID `oid`) and the external-ID kind it is compared with (default: the claim path's last segment). **Must be an attribute only IdP admins can set.** |
| `oidc.matchVerifiedEmail` | `true` | Link an existing user by email when the token says `email_verified: true`. |
| `oidc.autoCreateUsers` | `false` | Create an account (no roles; access only through groups) for an unmatched person with a verified email. |
| `smtp.host` / `.port` / `.security` | `""` / `587` / `starttls` | SMTP server; `security`: `none`, `starttls` or `tls`. Empty host: in-app notifications only. |
| `smtp.existingSecret` | `""` | Secret with optional keys `username`, `password` (or `smtp.username` / `smtp.password` in values). |
| `smtp.from` / `.fromName` / `.replyTo` | `""` / `Soundings` / `""` | Sender; `from` is required when `host` is set. |
| `smtp.caBundle.configMap` / `.key` | `""` / `ca.crt` | Existing ConfigMap with a CA bundle for the SMTP server. |
| `smtp.timeout` | `10` | Connection timeout (seconds). |
| `breakGlass.enabled` / `.existingSecret` | `true` / `""` | Local platform admin for the first sign-in and SSO outages, available only while `oidc.issuer` is empty (keys `username`, `password`, 16+ characters). Empty secret: user `admin`, random 24-character password. |
| `features.publicSubmission` / `.ai` | `true` / `false` | Allow public submission per project; AI assistance via kagent. |
| `kagent.enabled` / `.namespace` / `.examples` | `false` / `kagent` / `false` | Placeholders for Phase 6 (`deploy/kagent/README.md`). |
| `otel.endpoint` | `""` | OTLP/HTTP endpoint for traces. Metrics are always on `/metrics` (`metrics.port`). |
| `extraEnv` / `extraEnvFrom` | `[]` | Extra env for api, worker and migration containers. |
| `extraVolumes` / `extraVolumeMounts` | `[]` | Extra volumes, e.g. a DB CA for `sslmode=verify-full` (+ `PGSSLROOTCERT`). |
| `api.replicas` / `.resources` | `1` / 100m, 256Mi-512Mi | API size (replicas ignored with autoscaling). |
| `api.startupProbe` / `.livenessProbe` / `.readinessProbe` | `/healthz` / `/healthz` / `/readyz` | Full Probe objects; `{}` disables one. |
| `api.podAnnotations` / `.topologySpreadConstraints` | `{}` / `[]` | |
| `worker.enabled` / `.replicas` / `.concurrency` | `true` / `1` / `4` | Background worker; jobs per pod. |
| `worker.terminationGracePeriodSeconds` / `.resources` / `.livenessProbe` / `.podAnnotations` | `60` / 50m, 192Mi-512Mi / `{}` / `{}` | |
| `migrations.activeDeadlineSeconds` / `.backoffLimit` / `.waitForDatabaseSeconds` / `.resources` | `900` / `2` / `300` / small | Migration Job, init containers and the demo seed Job. |
| `autoscaling.enabled` / `.minReplicas` / `.maxReplicas` / `.targetCPUUtilizationPercentage` | `false` / `2` / `6` / `75` | HPA for the API. |
| `podDisruptionBudget.enabled` / `.maxUnavailable` | `true` / `1` | PDB for the API (never blocks drains). |
| `service.type` / `.port` / `.annotations` | `ClusterIP` / `80` / `{}` | |
| `ingress.enabled` / `.className` / `.annotations` | `false` / `""` / `{}` | |
| `ingress.hosts` / `.tls` | `[]` (hosts of `baseUrls`) / `[]` | TLS entries: `{secretName, hosts}`. |
| `httpRoute.enabled` / `.parentRefs` / `.hostnames` / `.annotations` | `false` / `[]` / `[]` (hosts of `baseUrls`) / `{}` | Gateway API `HTTPRoute` (v1). `parentRefs` required when enabled. |
| `serviceAccount.create` / `.name` / `.annotations` | `true` / `""` / `{}` | No API token is mounted. |
| `podSecurityContext` / `securityContext` | Restricted | uid/gid 10001, non-root, seccomp `RuntimeDefault`, read-only root FS, no capabilities, no privilege escalation. |
| `tmpSizeLimit` | `256Mi` | The writable `/tmp` emptyDir. |
| `podLabels` / `nodeSelector` / `tolerations` / `affinity` | empty | Applied to every app pod (and Postgres). |
| `postgresql.enabled` | `true` | Bundled single-replica Postgres (dev/small installs). |
| `postgresql.image.*` | `docker.io/library/postgres:16-alpine` | |
| `postgresql.auth.database` / `.username` / `.password` | `soundings` / `soundings` / `""` | Empty password: generated and kept. Only applied at first initialisation. |
| `postgresql.auth.existingSecret` / `.existingSecretKey` | `""` / `password` | |
| `postgresql.persistence.enabled` / `.storageClass` / `.size` / `.accessModes` | `true` / `""` / `8Gi` / `[ReadWriteOnce]` | The PVC is kept on uninstall. |
| `postgresql.resources` / `.podSecurityContext` | 100m, 256Mi-1Gi / uid 70 | |
| `externalDatabase.host` / `.port` / `.database` / `.user` | `""` / `5432` / `soundings` / `soundings` | Used when `postgresql.enabled=false` (host required). |
| `externalDatabase.password` / `.existingSecret` / `.existingSecretPasswordKey` | `""` / `""` / `password` | E.g. CloudNativePG's `<cluster>-app` Secret. |
| `externalDatabase.sslmode` | `require` | `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full`. |
| `networkPolicy.enabled` / `.ingressFrom` / `.metricsFrom` | `true` / `[]` / `[]` | Ingress-only policies: peers for the HTTP port / the metrics port (see below). Set `ingressFrom` to your ingress controller's namespace. |
| `serviceMonitor.enabled` / `.interval` / `.scrapeTimeout` / `.labels` | `false` / `30s` / `10s` / `{}` | Prometheus Operator scrape of the Service's `metrics` port. |

## Migrations: why two paths

Migrations (`soundings migrate`: app schema and the procrastinate job-queue schema) are
idempotent and serialised by a Postgres advisory lock, so running them more than once
or concurrently is safe.

- **External database** (`postgresql.enabled=false`): a Job annotated
  `helm.sh/hook: pre-install,pre-upgrade` (weight 0, deleted on success and before the
  next run) and `argocd.argoproj.io/hook: PreSync`. The database exists before the
  release, so the schema is migrated before any new pod starts; a failed migration
  stops the upgrade with the old pods still serving. An init container
  (`soundings wait-for-db`) waits up to `migrations.waitForDatabaseSeconds` for the
  database first. Because hooks run before the release's own ConfigMap, Secret and
  ServiceAccount exist, the Job carries its settings inline, reads the database password
  from `externalDatabase.existingSecret` or from a hook Secret
  (`<release>-soundings-migrate`, weight -10, deleted after success; only when the
  password is in values), and runs under the namespace's default ServiceAccount without a
  token. Migrations need no other secret (no `SOUNDINGS_SECRET_KEY`).
- **Bundled Postgres** (`postgresql.enabled=true`, the default): a pre-install hook would
  run before the StatefulSet exists and wait forever, and making Postgres itself a hook
  would take it out of normal release management (never upgraded, never uninstalled). So
  instead the api and worker pods run two init containers, `wait-for-db` and `migrate`
  (with only the database password, not the app's other secrets).
  This works the same with `helm install --wait`, `helm upgrade` and Argo CD, and during
  a rolling upgrade the old pods keep serving until the new ones have migrated and are
  ready.

## Demo data

`devLogin=true` plus `demo.seed=true` adds a Job (`<release>-soundings-seed`,
`helm.sh/hook: post-install,post-upgrade`, `argocd.argoproj.io/hook: PostSync`, deleted
after success) that runs `soundings wait-for-db`, `soundings migrate` and
`soundings seed`: 12 people (Alice Anders is the platform admin), three projects and 45
ideas in every status, with owners, blind evaluations, comments and votes over the last
few weeks. It migrates itself, so it does not depend on the api pods' init containers,
and it does nothing once the database has projects, so upgrades keep what people
changed. To start over: `kubectl -n <ns> exec deploy/<release>-soundings-api -- soundings
seed --reset` (add `--force` once people other than the demo ones have signed in). The
chart refuses `demo.seed` without `devLogin` (the app refuses to seed in production mode).

## Secrets

The chart's Secret `<release>-soundings` holds whatever you did not supply via an
`existingSecret`:

| Key | When |
|---|---|
| `secret-key` | `secretKey.existingSecret` empty (random, kept across upgrades) |
| `database-password` | external DB with `externalDatabase.password` |
| `oidc-client-secret` | `oidc.clientSecret` set |
| `smtp-username`, `smtp-password` | `smtp.username` / `smtp.password` set |
| `break-glass-username`, `break-glass-password` | `breakGlass.enabled` without `existingSecret` (`admin`, random, kept) |

The bundled Postgres password lives in `<release>-soundings-postgresql` (key `password`).

Generated values survive upgrades through Helm's `lookup`. **Argo CD, Flux with
`helm template`, or `--dry-run` cannot use `lookup`**: generated values would change on
every render, so there set `secretKey.existingSecret`, `breakGlass.existingSecret` and
`postgresql.auth.existingSecret` (or use an external database).

## Settings passed to the app

Non-secret settings go into the ConfigMap `<release>-soundings` as `SOUNDINGS_*`
variables: `ENVIRONMENT` (`production`, or `development` with `devLogin`),
`DEV_LOGIN_ENABLED`, `BASE_URLS`, `TRUSTED_PROXIES`, `LOG_LEVEL`, `DATABASE_URL`
(`postgresql+psycopg://user@host:port/db?sslmode=...`, no password), `METRICS_PORT`,
`SESSION_IDLE_TIMEOUT`, `SESSION_MAX_AGE`, `WORKER_CONCURRENCY`,
`OTEL_ENDPOINT`, `FEATURE_PUBLIC_SUBMISSION`, `FEATURE_AI`, `BREAK_GLASS_ENABLED`,
`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_GROUPS_CLAIM`, `OIDC_EXTERNAL_ID_CLAIM`,
`OIDC_EXTERNAL_ID_KIND`, `OIDC_MATCH_VERIFIED_EMAIL`, `OIDC_AUTO_CREATE_USERS`,
`OIDC_SCOPES` (comma-separated; all `OIDC_*` only when `oidc.issuer` is set), `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_FROM`,
`SMTP_FROM_NAME`, `SMTP_REPLY_TO`, `SMTP_TIMEOUT`, `SMTP_CA_BUNDLE` (a file path).
Secrets arrive as env vars from Secrets: `SOUNDINGS_SECRET_KEY`,
`SOUNDINGS_DATABASE_PASSWORD`, `SOUNDINGS_SMTP_USERNAME`, `SOUNDINGS_SMTP_PASSWORD`, and
in the **api pods only** (the worker signs nobody in) `SOUNDINGS_OIDC_CLIENT_SECRET`,
`SOUNDINGS_BREAK_GLASS_USERNAME` and `SOUNDINGS_BREAK_GLASS_PASSWORD`. Service links are disabled in every pod (a Service
named `soundings` would otherwise inject `SOUNDINGS_PORT=tcp://...`). The session
cookies' `Secure` flag is automatic (always set in production); `SOUNDINGS_COOKIE_SECURE`
in `extraEnv` overrides it (`false` is refused in production).

## Single sign-on

One OpenID Connect provider per instance (Keycloak, Entra ID, Google, ...), configured
here and nowhere else: Settings > Sign-in (SSO) shows the effective settings read-only,
with secrets masked, the URIs to register and whether the provider's discovery
document can be fetched. The flow is the server-side authorization code flow with PKCE
(S256), `state` and `nonce`; the browser only ever holds an HttpOnly session cookie.

**The IdP client.** A confidential OIDC client with the standard (authorization code)
flow only, PKCE S256, and for every entry of `baseUrls` (each host signs in on itself):

| Register | Value |
|---|---|
| Valid redirect URI | `<base URL>/api/v1/auth/callback` |
| Valid post-logout redirect URI | `<base URL>/login?signed_out=1` |

`NOTES.txt` prints the exact list after every install. Put in the **ID token**: `sub`,
`email`, `email_verified`, `name` (scopes `openid profile email`), the groups claim
(`oidc.groupsClaim`) and, if you use one, the external-ID claim. Keycloak: a "Group
Membership" mapper with full group path (`/innovation/admins`; leading slashes are
ignored when matching) and a "User Attribute" mapper; the dev realm
`dev/keycloak/realm-soundings.json` is a working example. Entra ID: the `groups` claim
(object ids, "groups assigned to the application" so a user never has more than 200:
a token with the group overage marker is refused) and `oid` as external ID. Google: no
groups claim (`oidc.groupsClaim: ""`), no external ID.

**Who gets in (login matching).** At each sign-in Soundings looks for the user linked
to the token's issuer and `sub`; at the first sign-in it links a user found by external
ID (`oidc.externalIdClaim`), then by verified email (`oidc.matchVerifiedEmail`), then
creates one (`oidc.autoCreateUsers`), else refuses ("ask an admin to add you").
Everyone else is pre-created by an admin (Settings > Users).

- **The external-ID claim must come from an attribute only IdP admins can set.**
  Whoever can choose its value signs in as the pre-created user who has it, platform
  admins included. Keycloak: declare the attribute in the realm's user profile with edit
  permission `admin` only and keep "Unmanaged attributes" disabled. Entra ID: `oid` or
  `employeeid`, never `upn`, `preferred_username` or `email`.
- **Email matching trusts the IdP's `email_verified`.** Keep `matchVerifiedEmail` on
  only for an IdP that verifies addresses (Keycloak does; Entra ID sends no
  `email_verified`, so pre-create users with the `oid` external ID there).
- Profile fields are not synced: after the first sign-in, names and emails are
  Soundings' own.

**Groups.** Settings > Groups maps internal groups to IdP group values; projects grant
roles to groups. A *managed* mapping follows the IdP at every sign-in (adds and
removes the synced membership); an *additive* one only adds. Memberships an admin
added by hand are never touched. Sync runs only at sign-in, so changes in the IdP
apply at the person's next sign-in.

**Offboarding = deactivate** (Settings > Users). Removing someone from the IdP stops new
sign-ins, but a running session lasts until it ends (`sessions.idleTimeout`, at most
`sessions.maxAge`, 7 days by default) and their synced memberships stay until they
sign in again. Deactivating ends their sessions at once; "Sign out everywhere" (same
page) ends them without deactivating, so a removed IdP group applies at the next
sign-in. For IdP changes to apply sooner on their own, shorten `sessions.maxAge` (e.g.
`P1D`). There is no back-channel logout.

**Production** (`devLogin: false`) requires an https issuer and https `baseUrls` once
SSO is configured (the chart refuses otherwise, and so would the app): the redirect
carries the authorization code, and the session cookies are `Secure` with the
`__Host-` prefix.

### Break-glass admin and the bootstrap order

The break-glass admin is a local platform admin whose credentials live in a Secret
(`breakGlass.existingSecret`, or generated by the chart: user `admin`, 24 random
characters; `NOTES.txt` shows how to read it). It exists for the first sign-in and for
SSO outages, **works only while `oidc.issuer` is empty**, and every sign-in and every
action taken with it is audited. It is throttled (5 failures per address per 15
minutes), its sessions last at most 8 hours (1 hour idle) and end as soon as SSO is
configured. In production the password needs 16+ characters.

1. Install without `oidc.issuer`. Sign in as the break-glass admin.
2. Settings > Users: pre-create the real platform admins, with an external ID from an
   admin-only attribute where the IdP has one, and/or their email. Optionally create
   groups and their IdP mappings, and grant them project roles.
3. Register the redirect URIs (Settings > Sign-in (SSO) lists them) on the IdP client.
4. `helm upgrade` with `oidc.issuer`, `oidc.clientId` and `oidc.existingSecret`.
   Break-glass switches off; the admins from step 2 are linked at their first SSO
   sign-in. SSO users are never platform admins by default.

**SSO outage:** `helm upgrade <release> <chart> --reuse-values --set oidc.issuer=`
brings break-glass back (with the same generated password: the Secret keeps it), and
setting the issuer again turns it off. That takes cluster access, the right bar for an
emergency account. The credentials stay wired into the api pods while SSO is on; the
app ignores them until the issuer is unset.

## Security

- Every pod meets the **Restricted** Pod Security Standard: non-root (app uid 10001,
  Postgres uid 70), read-only root filesystem with an emptyDir `/tmp`, all capabilities
  dropped, no privilege escalation, seccomp `RuntimeDefault`, no ServiceAccount token.
  `scripts/k3s-install.sh` installs into a namespace that enforces it.
- `networkPolicy.enabled` (default on): the API accepts traffic on its HTTP port from
  `ingressFrom` peers and on its metrics port from `metricsFrom` peers, plus this
  release's pods (each port: any source when its list is empty); the worker accepts
  nothing; the bundled Postgres accepts only this release's api, worker, migration and
  seed pods. Egress is not restricted (IdP, SMTP, kagent and the database differ per
  cluster); add your own egress policy if you need one.
- **Client addresses behind the ingress.** The sign-in throttles (60 SSO starts a
  minute, 5 failed break-glass sign-ins per 15 minutes) count per client address. The
  app believes `X-Forwarded-For` only from `trustedProxies`, and only the
  `trustedProxyHops` entries they appended, read from the right; whatever a client
  puts further left is ignored, private-looking or not. A pod that can reach the API
  directly is a "proxy" in a trusted range and can choose that entry, so set
  `networkPolicy.ingressFrom` to your ingress controller's namespace and narrow
  `trustedProxies` to its pod CIDR (or node IPs for a host-network controller). If
  every request seems to come from one address (the load balancer or a node after
  SNAT), give the ingress controller's Service `externalTrafficPolicy: Local` or let
  it trust the load balancer's headers, and raise `trustedProxyHops` if that load
  balancer appends its own entry.
- `/metrics` is served only on `metrics.port` (Service port `metrics`), never on the app
  port, so the ingress and HTTPRoute (which route `http` only) do not expose it.
- The app refuses requests for hosts that are not in `baseUrls`, so a spoofed `Host`
  cannot steer links or sign-in redirects.
- **Request bodies over 1 MiB** get 413 `content_too_large` from the app itself, before
  authentication and without reading them into memory (a too-large `Content-Length` is
  refused at once; chunked bodies are counted as they stream in), so no ingress setting
  is needed to keep the API pod under its memory limit. To refuse them at the edge as
  well: ingress-nginx does by default (`nginx.ingress.kubernetes.io/proxy-body-size`
  defaults to `1m`; keep it at `1m` if you set it); Traefik (k3s's default) has no limit
  unless you reference a `buffering` Middleware with `maxRequestBodyBytes: 1048576`
  through the `traefik.ingress.kubernetes.io/router.middlewares:
  <namespace>-<name>@kubernetescrd` annotation; Gateway API has no standard body limit.
  `scripts/k3s-smoke.sh` checks the 413 through the ingress.

## Air-gapped installs

Mirror `soundings:<tag>` and `postgres:16-alpine` into your registry and set
`global.imageRegistry` (plus `image.repository` / `postgresql.image.repository` if the
paths differ, and `image.pullSecrets`). Nothing is fetched at runtime: fonts, Swagger UI
and the SPA are in the image. The Helm test uses the app image.

## Develop and test

```sh
scripts/check-task.sh helm        # helm lint --strict + template for defaults and ci/*-values.yaml
make k3s-up image k3s-install k3s-smoke   # local k3s: install with dev/k3s-values.yaml, smoke test
scripts/k3s-test-external-db.sh   # hook-Job path against a second database
make k3s-down
```

`ci/default-values.yaml`, `ci/production-values.yaml` (external DB, ingress + TLS, SSO,
SMTP via existingSecret, HPA, NetworkPolicy, ServiceMonitor), `ci/sso-values.yaml`
(Entra ID-shaped SSO: `oid` external ID, no email matching, two hostnames, generated
break-glass), `ci/gateway-values.yaml` (Gateway API) and `ci/demo-values.yaml` (dev
login + demo seed Job with NetworkPolicies) are linted and rendered in CI.
`scripts/k3s-smoke.sh` also signs in through the ingress when the dev login is on
(session + CSRF) and reads My work, and when break-glass is available signs in with the
credentials from its Secret (as `NOTES.txt` says) after a wrong password is refused.

Single sign-on end to end on k3s, with Keycloak in the cluster (`dev/k3s/keycloak.yaml`,
the dev realm, issuer `http://keycloak.localhost:18081/realms/soundings`):

```sh
make k3s-up image k3s-keycloak          # Keycloak into the cluster (namespace keycloak)
make k3s-install SSO=1                  # + dev/k3s-sso-values.yaml (OIDC via existingSecret)
make k3s-smoke SSO=1                    # + code flow through the ingress, groups → access
make k3s-down
```
