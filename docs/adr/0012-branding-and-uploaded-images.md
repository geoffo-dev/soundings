# ADR 0012: Branding profiles and uploaded images stored in the database

- Status: Proposed · Date: 2026-10-01

## Context

SPEC section 10 asks for branding (app name, logo, favicon, primary and accent colour, a
font from a bundled set, email footer) with a global default and per-project overrides,
applied through CSS variables at runtime, in emails, on the public form and in PDFs.
Logos and favicons are the product's only uploads (attachments are a non-goal), the only
stateful dependency is PostgreSQL, and the app runs air-gapped. Branding values reach
CSS, HTML, emails and WeasyPrint, and images are served from the app's own origin, so
both are injection surfaces (CSS injection, SVG XSS, polyglots, SSRF through the PDF
renderer).

## Decision

- **Profiles** in `branding_profiles`: the global row (`project_id` null, one at most)
  and one optional row per project; every field nullable = inherit (project → global →
  built-in default). Colours are only `#rrggbb` (normalised lower-case), fonts only a
  `BrandFont` key, the footer plain text, the app name one line: validated in the API
  and checked again by the database, so no free-form CSS, font name or HTML exists.
- **Where:** the signed-in app always uses the global branding; a project's override
  applies where the project faces outward (public form and tracking pages, submitter
  emails, exported proposals). Runtime theming sets `--brand-primary`, `--brand-accent`
  and `--brand-font` ([ADR 0007](0007-hand-built-design-system-on-radix.md)); the SPA
  derives contrast-safe tokens.
- **Images** in `brand_assets` as `bytea` (≤ 900 KiB uploads, raw request bodies, no
  multipart parser). **PNG and SVG only**, for logos and favicons alike (browsers take
  PNG favicons); ICO and WebP are not accepted, so their decoders (each with a CVE
  history) are never reached by uploads. The bytes decide the type:
  - **PNG** is decoded with Pillow (a WeasyPrint dependency already) restricted to the
    PNG plugin (`Image.open(fp, formats=("PNG",))`), with `MAX_IMAGE_PIXELS` low, the
    decompression-bomb *warning* turned into an error, and the size checked before
    `load()`; then **re-encoded as PNG** (no metadata, no polyglots).
  - **SVG** is parsed with the standard library's expat, refusing any DOCTYPE, entity
    declaration or processing instruction (not `xml.etree`, which expands internal
    entities and can't refuse a DOCTYPE), at most 2,000 elements nested at most 32 deep
    (checked while parsing), and accepted only if every element and attribute is on an
    allow-list: no scripts, event handlers, styles, `href`s, `use` / `symbol` /
    `pattern` / `marker` / `filter`, foreign content or other namespaces. References are
    only `url(#id)` in `fill`, `stroke`, `clip-path` and `mask`; nothing inside a
    `clipPath`, `mask` or gradient may reference anything (no chains), and counting each
    reference as a copy of what it names the drawing stays within 10,000 elements.
    Stored **re-serialised** with the SVG namespace as the default namespace.
  - Stored types are only `image/png` and `image/svg+xml`.
- **Serving** at `/api/v1/branding/assets/{id}`: the stored type, `nosniff`,
  `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`,
  immutable caching by id (a new image is a new id: cache busting for free), ETag = the
  SHA-256. Emails carry no images (Phase 3); PDFs embed the logo as a `data:` URI and
  fetch nothing else (local-only fetcher, ADR 0011).
- No delete endpoint: a profile saved without an image releases it, and unreferenced
  images are deleted 24 hours after upload.

## Consequences

- No object storage, volume or CDN; backups include branding; replicas agree.
- Images live in the main database: fine for a handful of small files per project,
  wrong for anything bigger (attachments would need a new decision).
- The SVG allow-list refuses some legitimate logos (embedded fonts, CSS classes with
  `<style>`, raster images inside SVG, `<use>` reuse, filters); admins export a plain
  SVG or a PNG instead. The sandboxing CSP and `<img>`-only rendering in the SPA are
  defence in depth behind it.
- The reference rules exist because SVG rendering is exponential in reference depth:
  in the contract review a 1.1 KB file of nested `use` took 23.5 s to render at 10⁵
  copies, a 2.6 KB chain of 16 masks 39.5 s, and one mask of 1,000 shapes used 1,000
  times 72.6 s (WeasyPrint 70); a logo is drawn on every PDF export and public page,
  so one bad file would stall them all.
- Admins with an ICO or WebP favicon convert it to PNG once.
- Branding can't express arbitrary styling by design; asks for more get a new key or
  token, not a CSS box.
