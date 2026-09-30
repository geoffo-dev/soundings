# ADR 0007: Hand-built design system on Radix primitives

- Status: Accepted · Date: 2026-09-30

## Context

SPEC section 5 makes UI quality a headline requirement (calm, fast, Linear-like) and
names shadcn/ui on Radix. shadcn/ui is normally installed with its CLI, which fetches
component source from `ui.shadcn.com`; that host is unreachable from the build
environment, and the product must run air-gapped with no CDN assets. SPEC also asks for
a small internal design system first, shown on a dev-only `/design` page.

## Decision

- We hand-write the components in `frontend/src/components/ui/`, one per file,
  following shadcn/ui conventions (Tailwind classes, `cva` variants, `cn()` helper,
  `forwardRef`-free React 19 props) on top of the unified **`radix-ui`** package for
  behaviour and accessibility (Dialog, Sheet, Popover, DropdownMenu, Tabs, Tooltip…).
  `cmdk` for the command palette, `sonner` for toasts, `lucide-react` for icons.
- **Tokens first:** colours, spacing, radii, type scale, elevation and motion live as
  CSS custom properties in `src/styles/tokens.css`, mapped to Tailwind 4 utilities in
  `theme.css`. Tailwind's default palette and arbitrary values are removed, so
  one-off styling fails lint or doesn't compile.
- Brand: calm neutral greys, one accent (deep ocean blue `#1d5fa8`), status and score
  are the only other colours. Light and dark themes follow the system by default.
  Runtime branding overrides a few variables (`--brand-primary`, `--brand-font`), with a
  contrast check.
- Inter is bundled (`@fontsource-variable/inter`); no web font requests.
- `/design` shows every component in every state; it is dev-only (excluded from
  production builds unless `VITE_ENABLE_DESIGN=true`).
- Screens use only design-system components; a missing variant is added to the
  component, not styled inline.

## Consequences

- We own ~40 small components; updates from upstream shadcn are manual (copy, adapt).
- Radix gives focus management, ARIA and keyboard behaviour we would otherwise get
  wrong; WCAG 2.2 AA is reachable without a heavy UI kit.
- ux-reviewer checks screens against `/design`; drift is a review finding.
