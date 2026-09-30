# Soundings operator guide

> Skeleton. Filled in phase by phase (noted in brackets) and completed in Phase 7.
> Audience: whoever installs and runs Soundings on Kubernetes. The Helm chart's own
> reference is `deploy/helm/README.md` and `values.yaml`; this guide explains choices
> and procedures.

## Overview [Phase 0]

### What gets deployed: one image, `api` and `worker` Deployments, migration Job
### Requirements: Kubernetes version, PostgreSQL 16, ingress or Gateway API
### Air-gapped installs: image registry override, no runtime downloads

## Installing with Helm [Phase 0–1]

### Quick start on k3s/k3d
### Bundled Postgres vs external or CloudNativePG database
### Ingress, TLS and multiple hostnames
### `values.schema.json` validation and `NOTES.txt`
### Upgrades and migrations (pre-upgrade hook, Argo CD PreSync)

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

## Operations [Phase 7]

### Health probes: `/healthz`, `/readyz`
### Metrics (`/metrics`), ServiceMonitor, OTel tracing
### Logs (JSON, no PII)
### Backups and restore
### Scaling: replicas, HPA, PodDisruptionBudget
### Security: Pod Security `restricted`, NetworkPolicy, secrets
### Audit log
### Troubleshooting

## Data protection [Phase 4, 7]

### Erasing a public submitter's personal data
### What is stored about users
