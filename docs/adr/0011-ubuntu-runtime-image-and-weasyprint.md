# ADR 0011: Ubuntu 24.04 runtime image with its Python 3.12, for WeasyPrint

- Status: Accepted (built and verified in Phase 4 integration, 2026-10-02) · Date: 2026-10-01 · Supersedes the runtime base of [ADR 0004](0004-single-image-api-spa-worker.md)

## Context

Phase 4 exports proposals to PDF with WeasyPrint 70 (SPEC section 4), which `dlopen`s
Pango, HarfBuzz (with subsetting), fontconfig and GLib at runtime (research R1 §4).
`python:3.12-slim` (Debian 13) has none of them, and Debian's mirrors are unreachable
from this build environment, so the image has been built with
`RUNTIME_APT_PACKAGES=""` and PDF export could never work in it. Ubuntu's archive is
reachable: the lead verified `apt-get install python3.12 python3.12-venv libpango-1.0-0
libpangoft2-1.0-0 libharfbuzz-subset0` in `ubuntu:24.04` here. The image must stay
air-gapped at runtime, non-root, read-only-root compatible and scannable.

## Decision

- The **build** stage for the backend virtualenv and the **runtime** stage both use
  `ubuntu:24.04` with Ubuntu's `python3.12` (`/usr/bin/python3.12`), so the venv's
  interpreter path is the same in both; uv runs with `UV_PYTHON=/usr/bin/python3.12` and
  `UV_PYTHON_DOWNLOADS=never`. Wheels (psycopg, cryptography, pydantic-core, Pillow) are
  manylinux and work unchanged. The Node stage is unchanged.
- Runtime packages (`--no-install-recommends`): `python3.12`, `libpango-1.0-0`,
  `libpangoft2-1.0-0`, `libharfbuzz-subset0` (pulling GLib, HarfBuzz, fontconfig),
  `ca-certificates`, `tzdata` (`SOUNDINGS_TIMEZONE` needs the zone database) and
  `fonts-dejavu-core` as the fallback for glyphs the bundled fonts lack (Greek,
  Cyrillic, symbols). `python3.12-venv` only in the build stage. `apt` lists are removed.
  Build args `UBUNTU_IMAGE` (default `ubuntu:24.04`, pinned by digest in CI) and
  `UBUNTU_MIRROR` replace `PYTHON_IMAGE` / `DEBIAN_MIRROR`; `RUNTIME_APT_PACKAGES` now
  only **adds** packages (default empty: an internal mirror's keyring, debugging tools).
- The **bundled fonts** (Inter, IBM Plex Sans, Source Serif 4, Atkinson Hyperlegible;
  latin + latin-ext `woff2`, 400/600/700, with their OFL texts) ship inside the backend
  package (`app/assets/fonts/`) and are the only fonts the PDF stylesheet names, as
  `soundings-font:<font>-<weight>` URLs. WeasyPrint gets a URL fetcher that answers
  those names from a fixed map built at import (name → bytes, so no URL ever becomes a
  file path) and `data:` URIs (decoded by the fetcher itself), and raises for
  everything else; it never calls WeasyPrint's default `URLFetcher.fetch`, which
  follows `HTTP(S)_PROXY` and redirects.
- **Rendering runs in a child process** (`multiprocessing` with the `spawn` context;
  never `fork` from the threaded API process), one at a time per API process, killed
  after 20 seconds (503 `export_busy`). WeasyPrint holds the GIL (the contract review
  measured 448 ms event-loop pauses with a render in a thread) and some inputs are slow
  (large tables), so neither the event loop nor other exports may wait on a render.
- `XDG_CACHE_HOME=/tmp/cache` (the chart mounts an `emptyDir` at `/tmp`), so fontconfig
  can cache with a read-only root filesystem; the image runs as UID 10001 as before.
- `import weasyprint` happens inside the export, so the API starts (and everything but
  PDF export works) even where the libraries are missing.

## Consequences

- PDF export works in the shipped image and in `make demo`; CLAUDE.md's
  `IMAGE_BUILD_ARGS="--build-arg RUNTIME_APT_PACKAGES="` workaround is gone (Phase 4
  integration: `make image` builds without it and `make public-smoke` exports a PDF
  rendered inside the container).
- The image grows by roughly 60 MB (Python from Ubuntu, Pango stack, fonts) and follows
  Ubuntu's security updates (USNs) for Python and the libraries; Trivy scans them.
  *Measured in Phase 4 (same dependencies, only the base changed): 461 MB → 504 MB
  (+43 MB; 105 MB → 117 MB compressed). The Phase 3 image was 365 MB; most of the growth
  since is WeasyPrint's Python dependencies (fontTools, Pillow, pyphen).*
- Ubuntu's Python 3.12 is a patch release behind python.org's (3.12.3 in 24.04); the
  backend must not rely on newer 3.12.x behaviour (GitLab's `backend:test` runs on the
  Ubuntu image's interpreter; GitHub installs Pango next to its own Python).
- *Measured:* a render takes 1.4 s cold and 0.5 s warm in a hardened container (read-only
  root, `/tmp` tmpfs, no capabilities, no network); the warm child keeps about 100–190 MB.
  Each child writes WeasyPrint's temporary font folder in its own directory, which the
  API deletes when the child goes (a killed render left about 700 KB in `/tmp` before).
- Rendering is CPU-bound and holds the GIL: one render at a time per API process, in
  its own process with a hard time limit (contract-phase4 §3.4). Starting a fresh
  interpreter costs about a second per export, acceptable for a rare action; a warm
  child replaced after each kill is an optimisation, not a requirement.
