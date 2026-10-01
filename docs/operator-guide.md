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
only stateful dependency; an SMTP server and an OIDC provider come with Phases 3 and 2.
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

Until single sign-on arrives in Phase 2, `devLogin=true` (`SOUNDINGS_DEV_LOGIN_ENABLED`)
shows a "who are you?" list instead of a password and switches the app to development
mode. Anyone who can reach the app can then act as anyone, so use it only on your own
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
cookie that the SPA echoes in a header on every write. A session ends after
`sessions.idleTimeout` without a request (default `PT12H`) or `sessions.maxAge` after
sign-in (default `P7D`), whichever comes first; signing in again always issues a new
token. The cookies are `Secure` in production; `SOUNDINGS_COOKIE_SECURE` (in
`extraEnv`) overrides that for unusual setups, but `false` is refused in production.

## Sign-in and access [Phase 2]

### Configuring OIDC: Keycloak, Entra ID, Google
### Redirect URIs for each hostname
### Login matching and external IDs
### Groups and IdP group mappings (managed vs additive)
### Break-glass admin

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
### Audit log
### Troubleshooting

## Data protection [Phase 4, 7]

### Erasing a public submitter's personal data
### What is stored about users
