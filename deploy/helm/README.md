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
checks `/readyz` and the SPA through the Service.

Requirements: Kubernetes 1.27+, an ingress controller or Gateway API implementation, a
default StorageClass for the bundled Postgres (or `externalDatabase.*`).

## Values

Every value is validated by `values.schema.json` (unknown keys, wrong types and invalid
enums are rejected). `values.yaml` has a comment on every setting.

| Key | Default | Description |
|---|---|---|
| `baseUrls` | `[http://localhost:8000]` | Origins the app is served on (`scheme://host[:port]`, no path). First = default for email links. Sign-in redirect URIs and ingress/HTTPRoute hosts derive from these. |
| `nameOverride` / `fullnameOverride` | `""` | Override the chart name / the release-scoped base name (max 50 chars). |
| `global.imageRegistry` | `""` | Registry for **every** image (app + Postgres), for air-gapped mirrors. |
| `image.registry` / `.repository` / `.tag` / `.digest` | `""` / `soundings` / appVersion / `""` | The Soundings image. |
| `image.pullPolicy` / `.pullSecrets` | `IfNotPresent` / `[]` | Pull policy; names of existing registry Secrets. |
| `trustedProxies` | private ranges | IPs/CIDRs whose `X-Forwarded-*` headers are trusted (ingress controller). |
| `logLevel` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. JSON logs, no PII. |
| `devLogin` | `false` | Dev login stub; also switches the app to development mode. Never on shared installs. |
| `secretKey.existingSecret` / `.existingSecretKey` | `""` / `secret-key` | Session/CSRF signing key. Empty: generated once, kept across upgrades. |
| `oidc.issuer` | `""` | OIDC issuer URL. Empty: SSO off (configure later). |
| `oidc.clientId` / `.clientSecret` | `soundings` / `""` | Client credentials (prefer `oidc.existingSecret`, key `oidc.existingSecretKey`, default `client-secret`). |
| `oidc.groupsClaim` / `.externalIdClaim` / `.scopes` | `groups` / `""` / `[openid, profile, email]` | Claims used for group sync and linking pre-created users. |
| `smtp.host` / `.port` / `.security` | `""` / `587` / `starttls` | SMTP server; `security`: `none`, `starttls` or `tls`. Empty host: in-app notifications only. |
| `smtp.existingSecret` | `""` | Secret with optional keys `username`, `password` (or `smtp.username` / `smtp.password` in values). |
| `smtp.from` / `.fromName` / `.replyTo` | `""` / `Soundings` / `""` | Sender; `from` is required when `host` is set. |
| `smtp.caBundle.configMap` / `.key` | `""` / `ca.crt` | Existing ConfigMap with a CA bundle for the SMTP server. |
| `smtp.timeout` | `10` | Connection timeout (seconds). |
| `breakGlass.enabled` / `.existingSecret` | `true` / `""` | Local admin for first sign-in and SSO outages (keys `username`, `password`). Empty secret: user `admin`, random password. |
| `features.publicSubmission` / `.ai` | `true` / `false` | Allow public submission per project; AI assistance via kagent. |
| `kagent.enabled` / `.namespace` / `.examples` | `false` / `kagent` / `false` | Placeholders for Phase 6 (`deploy/kagent/README.md`). |
| `otel.endpoint` | `""` | OTLP/HTTP endpoint for traces. Metrics are always on `/metrics`. |
| `extraEnv` / `extraEnvFrom` | `[]` | Extra env for api, worker and migration containers. |
| `extraVolumes` / `extraVolumeMounts` | `[]` | Extra volumes, e.g. a DB CA for `sslmode=verify-full` (+ `PGSSLROOTCERT`). |
| `api.replicas` / `.resources` | `1` / 100m, 256Mi-512Mi | API size (replicas ignored with autoscaling). |
| `api.startupProbe` / `.livenessProbe` / `.readinessProbe` | `/healthz` / `/healthz` / `/readyz` | Full Probe objects; `{}` disables one. |
| `api.podAnnotations` / `.topologySpreadConstraints` | `{}` / `[]` | |
| `worker.enabled` / `.replicas` / `.concurrency` | `true` / `1` / `4` | Background worker; jobs per pod. |
| `worker.terminationGracePeriodSeconds` / `.resources` / `.livenessProbe` / `.podAnnotations` | `60` / 50m, 192Mi-512Mi / `{}` / `{}` | |
| `migrations.activeDeadlineSeconds` / `.backoffLimit` / `.waitForDatabaseSeconds` / `.resources` | `900` / `2` / `300` / small | Migration Job and init containers. |
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
| `networkPolicy.enabled` / `.ingressFrom` / `.metricsFrom` | `false` / `[]` / `[]` | Ingress-only policies (see below). |
| `serviceMonitor.enabled` / `.interval` / `.scrapeTimeout` / `.labels` | `false` / `30s` / `10s` / `{}` | Prometheus Operator scrape of `/metrics`. |

## Migrations: why two paths

Migrations (`soundings migrate`: app schema and the procrastinate job-queue schema) are
idempotent and serialised by a Postgres advisory lock, so running them more than once
or concurrently is safe.

- **External database** (`postgresql.enabled=false`): a Job annotated
  `helm.sh/hook: pre-install,pre-upgrade` (weight 0, deleted on success and before the
  next run) and `argocd.argoproj.io/hook: PreSync`. The database exists before the
  release, so the schema is migrated before any new pod starts; a failed migration
  stops the upgrade with the old pods still serving. An init container waits up to
  `migrations.waitForDatabaseSeconds` for the database first. Because hooks run before
  the release's own ConfigMap, Secret and ServiceAccount exist, the Job carries its
  settings inline, reads secrets from your `existingSecret`s or from a hook Secret
  (`<release>-soundings-migrate`, weight -10, deleted after success), and runs under the
  namespace's default ServiceAccount without a token.
- **Bundled Postgres** (`postgresql.enabled=true`, the default): a pre-install hook would
  run before the StatefulSet exists and wait forever, and making Postgres itself a hook
  would take it out of normal release management (never upgraded, never uninstalled). So
  instead the api and worker pods run two init containers, `wait-for-db` and `migrate`.
  This works the same with `helm install --wait`, `helm upgrade` and Argo CD, and during
  a rolling upgrade the old pods keep serving until the new ones have migrated and are
  ready.

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
(`postgresql+psycopg://user@host:port/db?sslmode=...`, no password), `WORKER_CONCURRENCY`,
`OTEL_ENDPOINT`, `FEATURE_PUBLIC_SUBMISSION`, `FEATURE_AI`, `BREAK_GLASS_ENABLED`,
`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_GROUPS_CLAIM`, `OIDC_EXTERNAL_ID_CLAIM`,
`OIDC_SCOPES` (comma-separated), `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_FROM`,
`SMTP_FROM_NAME`, `SMTP_REPLY_TO`, `SMTP_TIMEOUT`, `SMTP_CA_BUNDLE` (a file path).
Secrets arrive as env vars from Secrets: `SOUNDINGS_SECRET_KEY`,
`SOUNDINGS_DATABASE_PASSWORD`, `SOUNDINGS_OIDC_CLIENT_SECRET`, `SOUNDINGS_SMTP_USERNAME`,
`SOUNDINGS_SMTP_PASSWORD`, `SOUNDINGS_BREAK_GLASS_USERNAME`,
`SOUNDINGS_BREAK_GLASS_PASSWORD`. Service links are disabled in every pod (a Service
named `soundings` would otherwise inject `SOUNDINGS_PORT=tcp://...`).

## Security

- Every pod meets the **Restricted** Pod Security Standard: non-root (app uid 10001,
  Postgres uid 70), read-only root filesystem with an emptyDir `/tmp`, all capabilities
  dropped, no privilege escalation, seccomp `RuntimeDefault`, no ServiceAccount token.
  `scripts/k3s-install.sh` installs into a namespace that enforces it.
- `networkPolicy.enabled`: the API accepts traffic on its port from `ingressFrom` (+
  `metricsFrom`) peers and this release's pods (any source when `ingressFrom` is empty);
  the worker accepts nothing; the bundled Postgres accepts only this release's api,
  worker and migration pods. Egress is not restricted (IdP, SMTP, kagent and the database
  differ per cluster); add your own egress policy if you need one.
- `/metrics` is served on the app port, so the ingress exposes it too. Block `/metrics`
  at the ingress (or use `networkPolicy`) if that matters to you.

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
SMTP via existingSecret, HPA, NetworkPolicy, ServiceMonitor) and
`ci/gateway-values.yaml` (Gateway API) are linted and rendered in CI.
