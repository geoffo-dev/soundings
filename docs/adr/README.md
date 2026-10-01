# Architecture decision records

One short file per decision that shapes the code: **Context / Decision / Consequences**,
20–40 lines. Product decisions and simplifications that don't change the architecture
go in [../decisions.md](../decisions.md) instead.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-backend-stack.md) | FastAPI + SQLAlchemy 2 async + psycopg 3 + Alembic | Accepted |
| [0003](0003-background-jobs-procrastinate-and-email-outbox.md) | procrastinate on Postgres (no Redis) + transactional email outbox | Accepted |
| [0004](0004-single-image-api-spa-worker.md) | One image: API + SPA, worker entrypoint, migrations as a hook Job | Accepted (runtime base superseded by 0011) |
| [0005](0005-server-side-sessions-oidc-csrf.md) | Server-side sessions, OIDC code flow + PKCE, CSRF double-submit | Accepted |
| [0006](0006-blind-evaluation-and-aggregate-scoring.md) | Blind evaluation and aggregate scoring | Accepted |
| [0007](0007-hand-built-design-system-on-radix.md) | Hand-built design system on Radix | Accepted |
| [0008](0008-contract-first-generated-client-msw.md) | Contract-first build, generated TS client, MSW | Accepted |
| [0009](0009-product-name-and-open-questions.md) | Product name "Soundings" and SPEC section 16 answers | Accepted |
| [0010](0010-central-authorisation-policy.md) | Authorisation in one central policy module, deny by default | Accepted |
| [0011](0011-ubuntu-runtime-image-and-weasyprint.md) | Ubuntu 24.04 runtime image with its Python 3.12, for WeasyPrint (supersedes 0004's runtime base) | Proposed |
| [0012](0012-branding-and-uploaded-images.md) | Branding profiles and uploaded images stored in the database | Proposed |

## Writing a new ADR

1. Copy the shape of an existing one; take the next number; keep it under 40 lines.
2. Status is `Proposed` until the lead accepts it, then `Accepted`. Never rewrite an
   accepted ADR's decision: add a new ADR that supersedes it and mark the old one
   `Superseded by NNNN`.
3. Add it to the table above in the same change.
