# Soundings — frontend

React 19 + TypeScript (strict) SPA with a small internal design system. Calm, fast,
obvious — think Linear. Everything is bundled (Inter font included, no CDNs, no
telemetry) so it runs air-gapped. In production the FastAPI app serves `dist/`.

## Run it

Node 22.12+ and npm.

```bash
npm install
npm run dev:mock          # UI only, API mocked with MSW → http://localhost:5173
npm run dev               # against a backend: proxies /api, /mcp, /metrics to
                          # $SOUNDINGS_API_URL (default http://localhost:8000)
npm run dev -- --port 5174   # any Vite flag works after `--`
```

Open **`/design`** for the living design system (dev only — see below).

| Script                | What it does                                                                         |
| --------------------- | ------------------------------------------------------------------------------------ |
| `npm run dev`         | Vite dev server with API proxy                                                       |
| `npm run dev:mock`    | Dev server with MSW mocks (`VITE_API_MOCKS=true`)                                    |
| `npm run build`       | `tsc -b && vite build` → `dist/`                                                     |
| `npm run preview`     | Serve the production build                                                           |
| `npm run typecheck`   | `tsc -b`                                                                             |
| `npm run lint`        | ESLint (typescript-eslint strict, react-hooks, jsx-a11y) + Prettier check            |
| `npm run format`      | Prettier write (also sorts Tailwind classes)                                         |
| `npm run test`        | Vitest unit/component tests (jsdom)                                                  |
| `npm run test:pw`     | Playwright page tests + axe; starts `dev:mock` itself (port `PW_PORT`, 5174)         |
| `npm run screenshots` | Light/dark/mobile screenshots into `../docs/screenshots/phase-0/` (`SCREENSHOT_DIR`) |
| `npm run gen:api`     | `openapi-typescript src/api/generated/openapi.json -o src/api/generated/schema.d.ts` |
| `npm run check`       | typecheck + lint + test + build — must pass before a task is done                    |

Environment flags (build time): `VITE_API_MOCKS=true` starts MSW; `VITE_ENABLE_DESIGN=true`
keeps `/design` in a production build (otherwise it 404s and its code is tree-shaken out).

## Layout

```
src/
  api/            client.ts (openapi-fetch + CSRF + ApiError), query.ts (QueryClient), errors.ts
  api/generated/  OpenAPI contract + generated types — owned by the lead, never edit by hand
  components/ui/  the design system: one component per file (shadcn/ui conventions on Radix)
  components/layout/  app shell: sidebar, top bar, Page/PageHeader, ⌘K palette, shortcut sheet
  features/       feature code (screens' building blocks); features/design = the /design page
  lib/            theme, branding, hotkeys + shortcut registry, status/score helpers, utils (cn)
  mocks/          MSW: browser.ts, server.ts (vitest), handlers/<feature>.ts
  routes/         TanStack Router file routes (routeTree.gen.ts is generated — commit it)
  styles/         tokens.css (values) · theme.css (Tailwind mapping) · base.css · animations.css
tests/            Playwright page tests (a11y, keyboard, shell) against dev:mock
```

## Design-system rules (read before building a screen)

1. **Build from `src/components/ui` and the tokens only.** No hex/rgb/hsl values, no
   `style={{ color }}`, no arbitrary Tailwind values for colour, spacing or type
   (`p-[13px]`, `text-[15px]`, `bg-[#…]`). Tailwind's default palette, font sizes, weights,
   radii and shadows are _removed_ in `theme.css` — if a utility doesn't exist, it isn't in the
   system. Need something new? Add it to `components/ui` (or a token), show it on `/design`,
   and mention it in your report.
2. **Colour is for meaning.** Neutrals do the work. `bg-accent` marks the one primary action
   per view and selected states; `text-accent` is for links. Otherwise colour only for idea
   status (`StatusBadge`) and scores (`ScoreBadge`, `ScoreBar`). Status is always dot _and_ label.
3. **Tokens** (full list with light/dark swatches on `/design`):
   - surfaces `bg-background` (canvas/sidebar) · `bg-surface` (panels, cards, inputs) ·
     `bg-elevated` (overlays) · `bg-subtle` / `bg-subtle-hover` (quiet fills, hover, selected)
   - text `text-primary` · `text-secondary` · `text-muted` · `text-accent` · `text-danger|warning|success|info`
   - borders `border` (default colour) · `border-subtle` (row dividers) · `border-strong` (inputs) · `border-control`
   - feedback `bg-danger` / `bg-danger-subtle` (same for warning, success, info)
   - status `bg-status-{new,evaluating,shortlisted,proposal,accepted,rejected,parked}` · scores `bg-score-{1..5}`
   - elevation `shadow-overlay` (menus, popovers, toasts) · `shadow-dialog` · `shadow-raised` (dragging).
     **Content never has shadows** — cards are `border bg-surface`.
4. **Type:** 14px base. `text-2xl` page titles (use `PageHeader`), `text-xl` section/dialog
   titles, `text-lg` card titles/emphasis, `text-base` body, `text-sm` buttons/tables/secondary,
   `text-xs` meta. Weights: `font-normal` 400, `font-medium` 500 (labels, buttons), `font-semibold` 600
   (titles, numbers). `tabular-nums` for numbers in columns.
5. **Spacing:** 4px grid (Tailwind default scale). Inside controls `1.5–2`, between related
   controls `2–3`, between groups `4–6`, between page sections `8`. Radii: `rounded-md` controls,
   `rounded-lg` cards/menus, `rounded-xl` dialogs, `rounded-full` avatars/dots.
6. **Motion:** 120–200ms, `ease-out`. Use the provided `animate-*` utilities; everything is
   collapsed to ~0ms for `prefers-reduced-motion`.
7. **Icons:** `lucide-react`, default `size-4` (buttons size them automatically). Decorative
   icons get `aria-hidden`; icon-only buttons need `aria-label` (and usually `WithTooltip`).
8. **Forms:** wrap every control in `<Field label description error>` — ids, `aria-describedby`
   and `aria-invalid` are wired automatically. Scores use `SegmentedControl variant="accent"`
   with `scoreOptions(guidance)`; people use `Combobox` with `avatar` options.
9. **Dark mode is automatic** if you only use tokens. Never use `dark:` for colours. The theme
   class can also be applied to a subtree (`<div className="dark">`).

## Adding a screen

1. Create a route file under `src/routes/_app/` (inside the app shell), e.g.
   `src/routes/_app/projects.$projectId.tsx` → `/projects/:projectId`. Routes outside the shell
   (public submit page) go directly in `src/routes/`. The router plugin regenerates
   `routeTree.gen.ts` when the dev server or build runs.
2. Breadcrumb: `staticData: { crumb: 'Settings' }`, or return `{ crumb }` from the loader for
   dynamic titles. Page title: `head: () => ({ meta: [{ title: 'X · Soundings' }] })`.
3. Compose with `Page` / `PageHeader` / `PageSection` from `components/layout/page.tsx`.
4. Data: TanStack Query + the typed client:
   ```ts
   const ideas = useQuery({
     queryKey: ['projects', projectId, 'ideas'],
     queryFn: () =>
       unwrap(
         api.GET('/api/v1/projects/{project_id}/ideas', {
           params: { path: { project_id: projectId } },
         }),
       ),
   })
   ```
   Non-2xx responses throw `ApiError` (`status`, `code`, `title`, `detail`); 4xx are never
   retried. Mutations: update optimistically, then `toast.success(...)` or `toastUndo(...)` for
   destructive-ish actions. Unsafe requests carry `X-CSRF-Token` from the `soundings_csrf` cookie.
5. Keyboard: register shortcuts in `src/lib/shortcuts.ts` (the `?` sheet lists them) and bind
   with `useShortcut(id, handler)`. Add palette actions in `components/layout/app-commands.tsx`.
6. Put reusable pieces in `src/features/<feature>/`; keep route files thin.

### Every screen must have (review checklist)

- [ ] **Loading:** skeletons shaped like the content (`SkeletonListRow`, `SkeletonBoardCard`,
      `SkeletonIdeaPage`, or `Skeleton`) inside `SkeletonGroup`. No page spinners.
- [ ] **Empty:** `EmptyState` saying what the place is for and the next step (one action).
- [ ] **Error:** friendly message + retry (`RouteError` for loaders; inline `EmptyState role="alert"`).
- [ ] **Dark mode** checked; **390px mobile** checked (evaluate/submit must be comfortable).
- [ ] **Keyboard:** everything reachable with Tab, visible focus, Esc closes overlays,
      shortcuts registered. **Screen reader:** labels, headings in order, status never colour-only.
- [ ] One primary button per view; toasts for feedback; Undo instead of confirm dialogs where possible.
- [ ] Page test in `tests/` (axe: zero serious/critical in light and dark) + unit tests for logic.

## Mock API (MSW)

1. Add `src/mocks/handlers/<feature>.ts`:
   ```ts
   import { http, HttpResponse } from 'msw'
   import type { components } from '@/api/generated/schema'
   type Idea = components['schemas']['Idea']
   export const ideaHandlers = [
     http.get('/api/v1/ideas/:id', ({ params }) => HttpResponse.json<Idea>({/* … */})),
   ]
   ```
2. Spread it into `handlers` in `src/mocks/handlers/index.ts`.
3. `npm run dev:mock` uses them in the browser; in Vitest use `server` from `@/mocks/server`
   (`server.listen()` / `server.use(...)` — see `src/api/client.test.ts`). Problem responses
   should be `application/problem+json` like the real API.

The service worker is served from `node_modules/msw` by a Vite plugin in dev/preview only —
nothing MSW-related ends up in `dist/`.

## Theme, branding and fonts

- `ThemeProvider` / `useTheme()` → `preference` (`light | dark | system`, default system),
  `resolvedTheme`, `setPreference`. Stored in `localStorage["soundings-theme"]`; the inline
  script in `index.html` applies the class before first paint (keep both in sync).
- `applyBranding({ primary, accent, font })` (`src/lib/branding.ts`) overrides `--brand-primary`,
  `--brand-accent`, `--brand-font` and derives hover/foreground/tint/text/focus variants in
  OKLCH so text stays ≥ 4.5:1 in both themes. Only hex colours and plain family names are
  accepted. Fonts must be bundled (`@fontsource-variable/*`) — never load from a CDN.

## Content Security Policy

`index.html` has one inline script (theme bootstrap). With a strict CSP, allow it by hash:
`script-src 'self' 'sha256-Lky9V5/caBkqQQFiI9bOL/8ZyoNp80/ww3I30xQrBDY='`. If you change that
script, recompute: `node -e "const h=require('fs').readFileSync('dist/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];console.log(require('crypto').createHash('sha256').update(h).digest('base64'))"`.
Sonner injects its CSS at runtime, so `style-src` needs `'unsafe-inline'` (as do Radix's
positioning styles).
