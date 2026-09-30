# ADR 0004: One image serves the API and SPA; the worker is a second entrypoint

- Status: Accepted · Date: 2026-09-30

## Context

SPEC section 11 asks for one container image, two Deployments (`api`, `worker`) and
database migrations as a pre-install/pre-upgrade hook Job, installable with one
`helm install`, runnable air-gapped. A separate static-file server for the SPA would
mean a second image, a second Deployment and cross-origin cookie handling.

## Decision

- One multi-stage `Dockerfile`: a Node stage builds `frontend/dist`; a Python stage
  builds a self-contained virtualenv; the runtime stage (`python:3.12-slim`, non-root
  UID 10001, read-only root filesystem compatible) contains both.
- `ENTRYPOINT ["soundings"]`, default `CMD ["api"]`. Subcommands: `api` (uvicorn),
  `worker` (procrastinate), `migrate` (`alembic upgrade head`, idempotent), `openapi`.
- FastAPI serves the SPA: hashed files under `/assets/*` with immutable caching, and any
  other unknown `GET` that isn't `/api`, `/mcp`, `/healthz`, `/readyz` or `/metrics`
  returns `index.html` (client-side routing). Same origin, so session cookies stay
  `SameSite=Lax` and there is no CORS.
- Migrations run as a Helm `pre-install,pre-upgrade` hook Job (also annotated as an
  Argo CD `PreSync` hook) when the database is external. With the bundled Postgres
  StatefulSet the hook would run before the database exists, so the pods run
  `soundings migrate` in an init container instead (see `deploy/helm/README.md`).
- The image contains every asset it needs (fonts, Swagger UI, email templates): no
  runtime downloads. Registry and base images are overridable build args.

## Consequences

- One artefact to build, scan (Trivy) and promote; API and SPA versions can't drift.
- Frontend-only changes still rebuild the whole image. Acceptable at our size.
- Worker and API scale independently via two Deployments of the same image.
- The API must never shadow SPA routes with backend routes outside `/api` and `/mcp`;
  new top-level backend paths need the lead's approval.
