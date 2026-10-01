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

Open **`/design`** for the living design system (dev only — see below). With `dev:mock` you
sign in at `/login` by picking a fixture user; switch user any time from the user menu
(**Switch user**, dev builds only).

| Script                | What it does                                                                                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev`         | Vite dev server with API proxy                                                                                                                                    |
| `npm run dev:mock`    | Dev server with MSW mocks (`VITE_API_MOCKS=true`)                                                                                                                 |
| `npm run build`       | `tsc -b && vite build` → `dist/`                                                                                                                                  |
| `npm run preview`     | Serve the production build                                                                                                                                        |
| `npm run typecheck`   | `tsc -b`                                                                                                                                                          |
| `npm run lint`        | ESLint (typescript-eslint strict, react-hooks, jsx-a11y) + Prettier check                                                                                         |
| `npm run format`      | Prettier write (also sorts Tailwind classes)                                                                                                                      |
| `npm run test`        | Vitest unit/component tests (jsdom)                                                                                                                               |
| `npm run test:pw`     | Playwright page tests + axe; starts `dev:mock` itself (port `PW_PORT`, 5174)                                                                                      |
| `npm run screenshots` | Every `*screenshots.spec.ts` (mock data) into `../docs/screenshots/phase-1/mock/` (`SCREENSHOT_DIR`); the real-stack set is `npm --prefix ../e2e run screenshots` |
| `npm run gen:api`     | `openapi-typescript src/api/generated/openapi.json -o src/api/generated/schema.d.ts`                                                                              |
| `npm run check`       | typecheck + lint + test + build — must pass before a task is done                                                                                                 |

Environment flags (build time): `VITE_API_MOCKS=true` starts MSW; `VITE_ENABLE_DESIGN=true`
keeps `/design` in a production build (otherwise it 404s and its code is tree-shaken out).
Production builds ship **no source maps**.

## Layout

```
src/
  api/            the data layer (one module per area, below) · client.ts (openapi-fetch + CSRF +
                  ApiError) · query.ts (QueryClient, global error toasts, 401 handling) · keys.ts
                  (query-key factory) · cache.ts (optimistic helpers) · undo.ts · types.ts
  api/generated/  OpenAPI contract + generated types — owned by the lead, never edit by hand
  components/ui/  the design system: one component per file (shadcn/ui conventions on Radix)
  components/layout/  app shell: sidebar, top bar, Page/PageHeader, ⌘K palette, shortcut sheet
  features/<area>/ screens and their pieces: auth, work (My work), new-idea, settings,
                  project (Board/List, settings), idea (idea page, evaluate sheet), design (/design)
  lib/            dates, dialogs, command-registry, list-navigation, search-params, hotkeys +
                  shortcut registry, status/score helpers, theme, branding, utils (cn)
  mocks/          MSW mock backend: db.ts (fixtures) · domain.ts (business rules) · http.ts ·
                  session.ts · handlers/<area>.ts
  routes/         TanStack Router file routes — thin: validate params, load, render a feature
  styles/         tokens.css (values) · theme.css (Tailwind mapping) · base.css · animations.css
tests/            Playwright page tests (support.ts has the fixtures) against dev:mock
```

### Routes

| URL                                                                   | Route file                                                                              | Renders                                  | Owner            |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------- | ---------------- |
| `/login?next=&error=&signed_out=1&expired=1`                          | `routes/login.tsx`                                                                      | `features/auth/login-page`               | frontend-access  |
| `/`                                                                   | `routes/_app/index.tsx`                                                                 | `features/work/my-work-page`             | foundation       |
| `/p/$slug?view=board\|list&status=…`                                  | `routes/_app/p.$slug.tsx` (layout: loads the project, 404, crumb) + `p.$slug.index.tsx` | `features/project/project-page`          | frontend-project |
| `/p/$slug/settings`                                                   | `routes/_app/p.$slug.settings.tsx`                                                      | `features/project/project-settings-page` | frontend-project |
| `/ideas/$ideaKey?tab=overview\|evaluations\|proposal&evaluate=1`      | `routes/_app/ideas.$ideaKey.tsx`                                                        | `features/idea/idea-page`                | frontend-idea    |
| `/settings`                                                           | `routes/_app/settings.tsx` (layout, crumb) + `settings.index.tsx`                       | `features/settings/settings-page`        | foundation       |
| `/settings/users?q=&status=&admins=1&unlinked=1` (+ `/$userId` sheet) | `routes/_app/settings._admin.users.tsx`, `settings._admin.users.$userId.tsx`            | `features/admin/users/*`                 | frontend-admin   |
| `/settings/groups`, `/settings/groups/$groupId`                       | `routes/_app/settings._admin.groups.index.tsx`, `settings._admin.groups.$groupId.tsx`   | `features/admin/groups/*`                | frontend-admin   |
| `/settings/sso`                                                       | `routes/_app/settings._admin.sso.tsx`                                                   | `features/admin/sso/sso-page`            | frontend-admin   |
| `/settings/audit?actor=&action=&project=&from=&to=&target=`           | `routes/_app/settings._admin.audit.tsx`                                                 | `features/admin/audit/*`                 | frontend-admin   |
| `/design`                                                             | `routes/design.tsx`                                                                     | `features/design` (dev only)             | —                |

- **Admin settings** (`settings._admin.tsx`, platform admins): its `beforeLoad` throws `notFound()`
  for anyone else (the ordinary 404, no admin request sent); admin crumbs come from loaders so
  they never show on that 404. Every settings page renders `SettingsFrame`
  (`features/admin/settings-frame.tsx`): the "Settings" heading and, for platform admins only,
  the section row Account · Users · Groups · Sign-in (SSO) · Audit log.
- `_app.tsx` is the signed-in layout: its `beforeLoad` is the **auth guard** (no session →
  `/login?next=<here>`), it renders the shell and mounts the app-wide dialogs. Children read the
  user with `useCurrentUser()` (`features/auth/current-user.ts`).
- **Search params are readable** (`lib/search-params.ts`): arrays are comma lists, flags are
  `1`, defaults are dropped — `?view=list&status=new,evaluating&needs_evaluators=1`. Every route
  validates its own params (`features/project/project-search.ts`, `features/idea/idea-search.ts`);
  unknown values are ignored, never an error. Idea URLs are canonicalised to the upper-case key.
- **Breadcrumbs:** `staticData: { crumb }`, or a loader returning `{ crumb }` or
  `{ crumbs: [{ label, to }] }` (several levels). **Titles:** `head()`.
- **404s** use the same text whether a thing is missing or hidden (no leaks):
  `ProjectNotFound`, `IdeaNotFound`. Each is the page, so its title is the `<h1>`
  (`EmptyState headingLevel={1}`).
- `routeTree.gen.ts` is regenerated by the Vite plugin (`npm run dev` or `npx vite build`);
  commit it.

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
   - borders `border` (default colour) · `border-subtle` (row dividers) · `border-strong` (emphasis) ·
     `border-input` (text fields, ≥ 3:1 per WCAG 1.4.11) · `border-control` (checkboxes, radios)
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
   with `scoreOptions(guidance)` and `guidancePlaceholder={SCORE_GUIDANCE_PLACEHOLDER}` (says
   "Tap" on touch screens); people use `Combobox` with `avatar` options; tags use `TagInput`.
   Forms people fill on a phone use `<DialogContent mobile="fullscreen">`.
9. **Dark mode is automatic** if you only use tokens. Never use `dark:` for colours. The theme
   class can also be applied to a subtree (`<div className="dark">`).
10. **Tables on phones:** `<Table mobile="cards">` turns rows into stacked cards below `md`; give
    cells a `label` and mark the title cell `primary`. `mobile="container-cards"` does the same
    whenever the table's own container is under 48rem (tables beside the sidebar), and makes it
    a CSS container so cells can drop columns with `@3xl:` / `@max-4xl:` variants. Avatar
    stacks: `AvatarGroup on="…"` matches the ring to the background.
11. **Smaller pieces:** `KbdShortcut tone="accent"` for shortcut keys inside a primary button;
    `EmptyState headingLevel={1|2}` when the empty state is the page (h1) or a section (h2);
    `SegmentedControl size="score"` (36px, 44px on touch) for 1–5 scores. The Markdown renderer
    (~47 KB gzip) is imported directly by the idea page, whose route chunk needs it anyway,
    and lazily (`lazy()`) where it is only a preview (New idea).

## Adding a screen

1. Put the screen and its pieces in `src/features/<area>/`; keep the route file thin (validate
   search params, call the loader, render one feature component).
2. Compose with `Page` / `PageHeader` / `PageSection` (`components/layout/page.tsx`;
   `PageSection id="…"` makes an anchor).
3. Data only through the hooks in `src/api/` (next section). Use the API's `permissions`
   booleans to show or hide controls — **never work out roles in the client**.
4. Keyboard: register shortcuts in `src/lib/shortcuts.ts` (the `?` sheet lists them), bind with
   `useShortcut(id, handler)`, and add palette actions with `useCommands()` (below). Lists get
   j/k/↑/↓ navigation with `useListNavigation()` (below).
5. Dates only through `src/lib/dates.ts` / `<RelativeTime>` / `<DueDateLabel>`.

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

## Data layer (`src/api/`)

One module per area, each exporting `…QueryOptions` (for loaders and prefetching) and hooks:

| Module           | Queries                                                                                                                                                                                                                                         | Mutations                                                                                                                                                                                                                                                                                                           |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auth.ts`        | `useMe`, `useAuthConfig`, `useDevUsers`                                                                                                                                                                                                         | `useDevLogin`, `useBreakGlassLogin`, `useLogout` (API clients; the SPA signs out with `features/auth/sso.ts`)                                                                                                                                                                                                       |
| `groups.ts`      | `useGroupSearch(q)` (group picker)                                                                                                                                                                                                              |                                                                                                                                                                                                                                                                                                                     |
| `users.ts`       | `useUserSearch({ q, project })` (people pickers)                                                                                                                                                                                                |                                                                                                                                                                                                                                                                                                                     |
| `projects.ts`    | `useProjects`, `useProject(slug)`, `useProjectMembers`, `useProjectGroupGrants`, `useProjectAccess` (infinite), `useProjectTags`                                                                                                                | `useCreateProject`, `useUpdateProject` (archive → Undo), `useAddProjectMember`, `useUpdateProjectMember` (Undo), `useRemoveProjectMember` (Undo), `useAddProjectGroupGrant`, `useUpdateProjectGroupGrant` (Undo), `useRemoveProjectGroupGrant` (Undo), `useReplaceRubric`                                           |
| `ideas.ts`       | `useIdeaList(slug, filters)` (infinite), `useBoard(slug, filters)`, `useIdea(key)`, `useCachedIdeaSummary(key)`                                                                                                                                 | `useCreateIdea`, `useUpdateIdea` (inline edits), `useDeleteIdea`, `useChangeIdeaStatus` (board move + Undo), `useSetIdeaOwner` (Undo), `useVolunteerAsOwner` (Undo), `useAddEvaluators`, `useRemoveEvaluator` (deferred), `useSetEvaluationDueDate`, `useSetEvaluationClosed` (Undo), `useVoteIdea`, `useWatchIdea` |
| `evaluations.ts` | `useEvaluations(key)`, `useMyEvaluation(key)`                                                                                                                                                                                                   | `useSaveMyEvaluation(key)`                                                                                                                                                                                                                                                                                          |
| `activity.ts`    | `useIdeaActivity(key)` (infinite; `data.items` oldest → newest)                                                                                                                                                                                 | `useCreateComment`, `useUpdateComment`, `useDeleteComment` (deferred)                                                                                                                                                                                                                                               |
| `work.ts`        | `useMyWork`, `useWorkCounts`, `useOwnedIdeas(status, cursor)` ("load more")                                                                                                                                                                     |                                                                                                                                                                                                                                                                                                                     |
| `search.ts`      | `useGlobalSearch(q)` (debounced 150 ms), `useDebouncedValue`                                                                                                                                                                                    |                                                                                                                                                                                                                                                                                                                     |
| `admin.ts`       | `useAdminUsers(filters)` (infinite), `useAdminUser`, `useAdminGroups(q)` (infinite), `useAdminGroup`, `useGroupMembers` (infinite), `useAuditEntries(filters)` (infinite), `useSsoConfig`, `useAdminUserName` / `useAdminGroupName` (audit ids) | `useCreateAdminUser`, `useUpdateAdminUser`, `useReplaceExternalIds`, `useUnlinkIdentity`, `useEndUserSessions`, `useCreateGroup`, `useUpdateGroup`, `useDeleteGroup`, `useReplaceGroupMapping`, `useAddGroupMember`, `useRemoveGroupMember` (Undo for manual members), `useTestGroupMapping`                        |

Conventions:

- **Types** come only from the contract: `import type { IdeaDetail } from '@/api/types'`
  (aliases of `generated/schema.d.ts`). Request paths are typed by openapi-fetch.
- **Keys** come only from `queryKeys` (`keys.ts`). Ideas are cached by their **upper-case key**
  (`queryKeys.ideas.detail('cust-12')` → `['ideas','detail','CUST-12']`); every `/ideas/{idea}`
  endpoint accepts the key, so pass the key from the URL.
- **Filters** (`IdeaFilters`) are normalised (empties dropped, arrays sorted) so equal filters
  share a cache entry. `toIdeaFilters(search)` turns the project URL state into them. Board
  "load more": `useIdeaList(slug, { ...filters, status: [column] }, { initialCursor: column.next_cursor })`.
- **Optimistic updates:** mutations snapshot the affected caches (`cache.ts` `snapshot`),
  patch the idea everywhere it is shown (`patchIdea`, `moveOnBoards`), roll back on error, then
  store the server's answer and invalidate what depends on it. You don't do this in screens.
- **Errors:** a failed mutation shows a toast automatically (friendly copy per error `code`
  from `errors.ts` `describeError`); pass `meta: { silent: true }` when the screen shows the
  error inline (forms: `useCreateIdea`, `useUpdateIdea`, `useSaveMyEvaluation`,
  `useCreateProject`, `useReplaceRubric` are already silent — read `mutation.error`;
  `ApiError.fieldErrors` / `error.problem.errors` have the 422 details).
- **401** from any request (session ended) → `/login?next=<here>&expired=1`, which says so on the
  page (`features/auth/session.ts`); unsent drafts go with the session.
- **Sign-in and sign-out are navigations, never fetches** (contract-phase2 §1): "Sign in with SSO"
  is a link to `GET /api/v1/auth/login?next=…`; "Sign out" posts a plain form to
  `/api/v1/auth/logout/redirect` (`features/auth/sso.ts`), which ends the IdP session too. With
  `dev:mock` (MSW never sees navigations) both run a stand-in IdP from `mocks/sso.ts`.
- **CSRF** is read from `__Host-soundings_csrf` (HTTPS) or `soundings_csrf` (plain HTTP).
- **Break-glass sessions** (`CurrentUser.auth_method === 'break_glass'`) show a banner in the
  shell (`features/auth/break-glass-banner.tsx`).
- **Undo** (contract §3.14, `undo.ts`): hooks with an inverse call show the Undo toast
  themselves (`useChangeIdeaStatus(key)`; pass `{ undo: false }` to opt out). The two deferred
  ones — `useRemoveEvaluator(key)(user)` and `useDeleteComment(key)(commentId)` — hide the item
  immediately (queries filter it via `useHiddenItems`), send the DELETE when the toast closes
  or the page is hidden, and Undo restores it untouched. Deleting an idea has no undo: confirm.
- **Blind evaluation:** render what the API sends. `score_hidden: true` → "Hidden until you
  submit" (`<ScoreBadge hidden>`); never compute or cache scores client-side.

## Mock backend (MSW, `src/mocks/`)

`npm run dev:mock` answers **every operation in the contract** from an in-memory database
(`handlers.test.ts` fails if one is missing). It follows the business rules closely enough to
build and test screens: permissions booleans, blind evaluation (masking in lists, board, sort,
filters, detail and evaluations), the aggregate (§3.8), filters/sorts/cursors (opaque, 400 on a
foreign cursor), board columns and resolution counts, My work, search, Undo inverses, CSRF, and
the documented error codes in the contract's check order. It is not the authority — the
backend and its tests are.

- **Fixtures** (`db.ts`, deterministic): 10 active users + 1 inactive, 3 projects (Customer
  Innovation `CUST` internal; Internal Tools `TOOL` private; Sustainability `GREEN` internal,
  volunteering off, renamed labels "Triage"/"Adopted"), 40 ideas in every status, evaluations,
  drafts, comments, votes and activity. Useful people: **Alice Anders** (default in tests;
  member, admin of Internal Tools, 4 evaluations due incl. 1 overdue and 1 draft, owns ideas in
  every status), **Priya Natarajan** (platform admin), **Emma Lindqvist** (viewer in CUST),
  **Ivan Petrov** (no project roles). Tests import `USERS` from `db.ts` (`tests/support.ts` for
  Playwright).
- **Rules** live in `domain.ts` (unit-tested in `domain.test.ts`); **handlers** in
  `handlers/<area>.ts` use `route(method, path, ({ db, user, url, params, request }) => data)`
  from `http.ts` and throw `fail(status, code)` / `failValidation([...])` for problems.
- **Phase 2 fixtures** (`access-fixtures.ts`, rules in `access.ts`): SSO identities (issuer
  `http://localhost:8080/realms/soundings`), external IDs (`employee_no` E1000–E1012, `gitlab`),
  groups mirroring the Keycloak realm — **Innovation admins** (`innovation/admins` → CUST admin),
  **Innovation members** (`innovation/members` → CUST member), **Tools members**
  (`tools/members` → TOOL member), **Viewers** (`viewers`, additive → GREEN viewer), plus
  **Sustainability champions** (not mapped, manual) and **Contractors** (two values, no members)
  — and ~200 audit entries. Group grants change no Phase 1 user's role; **Kofi Boateng** (CUST and
  TOOL only through groups), **Lena Novak** (pre-created, never signed in, TOOL through a manual
  membership) and the **Break-glass admin** (`break-glass@soundings.invalid`) are new. Ids:
  `GROUPS` in `access-fixtures.ts`, `USERS` in `db.ts`.
- **Session:** every sign-in sets a readable `soundings_mock_session` cookie, its method in
  `soundings_mock_auth_method` (`sso`, `break_glass`, `dev_login`) and `soundings_csrf`. A session
  whose method is switched off answers 401 (§3.9); one without a method cookie (Playwright's
  fixture) always works.
- **Sign-in knobs** (localStorage, then reload): `soundings-mock-auth` = comma list of `sso`,
  `dev_login`, `break_glass` (default `sso,dev_login`; `none` for nothing; break-glass only counts
  without `sso`); `soundings-mock-sso-user` = the fixture user the mock IdP signs in as (default
  `alice`); `soundings-mock-sso-error` = a `/login?error=` code the IdP round trip ends with;
  `soundings-mock-sso-discovery` = `unreachable`, `invalid` or `issuer_mismatch` for Admin → SSO.
  Break-glass credentials: `break-glass` / `correct horse battery staple` (5 failures → 429 with
  `Retry-After`).
- **Knobs** (localStorage, then reload): `soundings-mock-dataset` = `large` adds 10,000 ideas to
  Customer Innovation (also in the user menu → Switch user → Mock data);
  `soundings-mock-latency` = `none` or a number of ms (default realistic 100–400 ms);
  `soundings-mock-fail` = a path fragment (e.g. `/me/work`) that answers 500, to check error
  states.
- **In Vitest:** `server` from `@/mocks/server`, `resetDb()` in `beforeEach`, sign in with
  `api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.alice } })`, override one
  endpoint with `server.use(http.post('*/api/v1/…', () => problemResponse(409, 'code')))`.

The service worker is served from `node_modules/msw` by a Vite plugin in dev/preview only —
nothing MSW-related ends up in `dist/`.

## Command palette, dialogs, keyboard

- **Palette registry** (`lib/command-registry.ts`): pages add context actions while mounted;
  they appear first. Only register what the user may do (API `permissions`).
  ```tsx
  useCommands({
    id: 'idea',
    heading: idea.key,
    actions: [
      { id: 'evaluate', label: 'Evaluate', icon: <Gauge />, shortcut: 'e', onSelect: openSheet },
      { id: 'assign-owner', label: 'Assign owner…', icon: <UserRound />, onSelect: openPicker },
    ],
  })
  ```
  Built-in: jump to idea (server search, exact key first), jump to project, New idea, New
  project (platform admins), My work, Settings, theme, shortcuts, sign out.
- **App dialogs** (`lib/dialogs.ts`): `openNewIdea({ projectSlug })` (project views preselect
  their project; "n" and the palette pass the project in view), `openCreateProject()`.
  `useAppCommands().canCreateIdeas` says whether to show "New idea" at all.
- **Lists:** `const { listRef } = useListNavigation()` on a container, `data-nav-item` on each
  row's link → j/k anywhere, ↑/↓ inside, Enter opens.
- **Shortcuts** in the registry: ⌘K palette, `?` sheet, `[` sidebar, `g m` My work, `j`/`k`,
  `n` new idea, `e` evaluate (bind it on the idea page), ⌘Enter submit.

## Testing

- Vitest: `*.test.ts(x)` next to the code (jsdom). Data hooks: render with a real
  `createQueryClient()` against the mock server (see `api/ideas.test.tsx`).
- Playwright: import `test`/`expect` from `tests/support.ts` — pages start **signed in as
  Alice** with mock latency off; `test.use({ signedInAs: USERS.priya })` or `null` for signed
  out; `seriousViolations(page)` runs axe. Wait for the page's heading before pressing
  shortcuts. `PW_PORT=5191 npm run test:pw` to use another port.
- Two Playwright runs at once share `test-results/` (pass `--output=<own dir>`). The Vite
  dev server reloads open pages whenever someone saves a file; the server `test:pw` starts has
  that off (`VITE_NO_HMR=1`), but one you started yourself and Playwright reuses has not.

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
