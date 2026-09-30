import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  Archive,
  ArrowUpDown,
  CloudOff,
  FilterX,
  Lightbulb,
  List,
  Plus,
  Settings,
  SquareKanban,
  UserRound,
} from 'lucide-react'
import { useRef, type ReactNode } from 'react'

import { describeError } from '@/api/errors'
import { useProject, useUpdateProject } from '@/api/projects'
import type { IdeaSort, Project, UserRef } from '@/api/types'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { KbdShortcut } from '@/components/ui/kbd'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { WithTooltip } from '@/components/ui/tooltip'
import { BoardView } from '@/features/project/board/board-view'
import { BoardSkeleton } from '@/features/project/board/board-skeleton'
import { ListSkeleton, ListView } from '@/features/project/list/list-view'
import { useCommands } from '@/lib/command-registry'
import { openNewIdea } from '@/lib/dialogs'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import { ProjectPageSkeleton } from './project-page-states'
import { FilterBar } from './project-filters'
import { projectBoardOptions, projectListOptions } from './project-queries'
import {
  clearFilters,
  hasActiveFilters,
  SORT_OPTIONS,
  sortLabel,
  toIdeaFilters,
  withView,
  type ProjectSearch,
  type ProjectView,
} from './project-search'
import { resolveView, writeViewPreference } from './view-preference'

/**
 * The project page (SPEC §5 screen 2, wireframe 02): Board or List of one
 * project's ideas, with filter chips that live in the URL. The route
 * (`/p/$slug`) has already loaded the project (or shown the 404).
 */
export function ProjectPage({ slug, search }: { slug: string; search: ProjectSearch }) {
  const project = useProject(slug)
  if (!project.data) return <ProjectPageSkeleton />
  // Keyed by project: never show one project's ideas while the next one loads.
  return <ProjectPageContent key={slug} project={project.data} search={search} />
}

function ProjectPageContent({ project, search }: { project: Project; search: ProjectSearch }) {
  const navigate = useNavigate()
  const slug = project.slug
  const view = resolveView(slug, search.view)
  const filters = toIdeaFilters(search)
  const filtered = hasActiveFilters(search, view)
  const searchRef = useRef<HTMLInputElement>(null)
  const canCreate = project.permissions.can_create_ideas

  // Keep showing the current results while new filters load (no skeleton flash).
  const board = useQuery({
    ...projectBoardOptions(slug, search),
    placeholderData: keepPreviousData,
    enabled: view === 'board',
  })
  const list = useInfiniteQuery({
    ...projectListOptions(slug, search),
    placeholderData: keepPreviousData,
    enabled: view === 'list',
  })
  const active = view === 'board' ? board : list
  const matching =
    view === 'board'
      ? board.data?.columns.reduce((sum, column) => sum + column.count, 0)
      : list.data?.pages[0]?.total

  const setSearch = (next: ProjectSearch) =>
    void navigate({ to: '/p/$slug', params: { slug }, search: next, replace: true })
  const setView = (next: ProjectView) => {
    writeViewPreference(slug, next)
    setSearch(withView(search, next))
  }
  const setSort = (sort: IdeaSort | undefined) => setSearch({ ...search, sort })
  const newIdea = () => openNewIdea({ projectSlug: slug })

  useShortcut('toggleView', () => setView(view === 'board' ? 'list' : 'board'))
  useShortcut('focusFilters', () => searchRef.current?.focus())

  useCommands({
    id: 'project',
    heading: project.name,
    actions: [
      {
        id: 'project-toggle-view',
        label: view === 'board' ? 'Switch to List' : 'Switch to Board',
        icon: view === 'board' ? <List /> : <SquareKanban />,
        shortcut: SHORTCUTS.toggleView.keys,
        keywords: ['view', 'board', 'list', 'table'],
        onSelect: () => setView(view === 'board' ? 'list' : 'board'),
      },
      {
        id: 'project-mine',
        label: 'Show ideas I own',
        icon: <UserRound />,
        keywords: ['filter', 'owner', 'me', 'mine'],
        onSelect: () => setSearch({ ...search, owner: 'me' }),
      },
      ...(filtered
        ? [
            {
              id: 'project-clear-filters',
              label: 'Clear filters',
              icon: <FilterX />,
              keywords: ['reset', 'filters'],
              onSelect: () => setSearch(clearFilters(search)),
            },
          ]
        : []),
      ...(project.permissions.can_manage
        ? [
            {
              id: 'project-settings',
              label: 'Project settings',
              icon: <Settings />,
              keywords: ['members', 'rubric', 'labels', 'admin'],
              onSelect: () => void navigate({ to: '/p/$slug/settings', params: { slug } }),
            },
          ]
        : []),
    ],
  })

  // Owners on the loaded ideas, so the owner chip can name someone before the members list loads.
  const knownPeople: UserRef[] = (
    view === 'board'
      ? (board.data?.columns.flatMap((column) => column.items) ?? [])
      : (list.data?.pages.flatMap((page) => page.items) ?? [])
  ).flatMap((idea) => (idea.owner ? [idea.owner] : []))

  let content: ReactNode
  if (active.isError && !active.data) {
    content = (
      <Panel>
        <EmptyState
          headingLevel={2}
          role="alert"
          icon={<CloudOff />}
          title="We couldn’t load the ideas"
          description={describeError(active.error).description ?? 'Please try again in a moment.'}
          action={
            <Button
              variant="primary"
              loading={active.isFetching}
              onClick={() => void active.refetch()}
            >
              Try again
            </Button>
          }
        />
      </Panel>
    )
  } else if (matching === undefined) {
    content = view === 'board' ? <BoardSkeleton /> : <ListSkeleton />
  } else if (matching === 0 && filtered) {
    content = (
      <Panel>
        <EmptyState
          headingLevel={2}
          icon={<FilterX />}
          title="No ideas match these filters"
          description="Try fewer filters, or clear them to see every idea."
          action={
            <Button variant="outline" onClick={() => setSearch(clearFilters(search))}>
              Clear filters
            </Button>
          }
        />
      </Panel>
    )
  } else if (matching === 0) {
    content = (
      <Panel>
        <EmptyState
          headingLevel={2}
          icon={<Lightbulb />}
          title="No ideas yet"
          description={
            canCreate
              ? 'Press N to add the first one — start with something you’ve been thinking about.'
              : 'Ideas will appear here once members add them.'
          }
          action={
            canCreate && (
              <Button variant="primary" onClick={newIdea}>
                <Plus /> New idea
              </Button>
            )
          }
        />
      </Panel>
    )
  } else if (view === 'board' && board.data) {
    content = (
      <BoardView
        project={project}
        board={board.data}
        filters={filters}
        stale={board.isPlaceholderData}
      />
    )
  } else {
    content = (
      <ListView
        query={list}
        sort={search.sort}
        onSortChange={setSort}
        resetKey={JSON.stringify(filters)}
      />
    )
  }

  return (
    <Page width="full" className="h-full min-h-0 gap-4 pb-0 sm:gap-5 lg:px-6 lg:py-6">
      <PageHeader
        title={project.name}
        description={project.description || undefined}
        actions={
          <>
            <ViewToggle view={view} onChange={setView} />
            {project.permissions.can_manage && (
              <WithTooltip content="Project settings">
                <Button asChild variant="ghost" size="icon" aria-label="Project settings">
                  <Link to="/p/$slug/settings" params={{ slug }}>
                    <Settings />
                  </Link>
                </Button>
              </WithTooltip>
            )}
            {canCreate && (
              <Button variant="primary" className="max-sm:hidden" onClick={newIdea}>
                <Plus />
                New idea
                <KbdShortcut keys={SHORTCUTS.newIdea.keys} tone="accent" className="ml-1" />
              </Button>
            )}
          </>
        }
      />

      {project.archived_at && <ArchivedNotice project={project} />}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <FilterBar
          project={project}
          search={search}
          view={view}
          onChange={setSearch}
          searchRef={searchRef}
          knownPeople={knownPeople}
        />
        <div className="flex shrink-0 items-center justify-between gap-3 sm:h-7 sm:justify-end">
          <div className="flex items-center gap-2">
            <p className="text-sm text-muted tabular-nums" aria-live="polite">
              {matching === undefined
                ? ' '
                : filtered
                  ? `${matching.toLocaleString()} of ${project.idea_count.toLocaleString()} ideas`
                  : `${matching.toLocaleString()} ${matching === 1 ? 'idea' : 'ideas'}`}
            </p>
            {filtered && (
              <Button
                variant="link"
                size="sm"
                className="sm:hidden"
                onClick={() => setSearch(clearFilters(search))}
              >
                Clear
              </Button>
            )}
          </div>
          <SortMenu sort={search.sort} onChange={setSort} />
        </div>
      </div>

      {content}

      {canCreate && (
        <div className="-mx-4 mt-auto border-t border-subtle bg-surface px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:hidden">
          <Button variant="primary" size="lg" className="w-full" onClick={newIdea}>
            <Plus /> New idea
          </Button>
        </div>
      )}
    </Page>
  )
}

/** Archived projects are read-only; admins can restore them here (with Undo). */
function ArchivedNotice({ project }: { project: Project }) {
  const update = useUpdateProject(project.slug)
  return (
    <div className="-mt-1 flex items-center gap-2 rounded-md bg-subtle px-3 py-1.5 text-sm text-secondary">
      <Archive aria-hidden="true" className="size-4 shrink-0 text-muted" />
      <p className="min-w-0 flex-1">This project is archived. Its ideas are read-only.</p>
      {project.permissions.can_manage && (
        <Button
          variant="ghost"
          size="sm"
          loading={update.isPending}
          onClick={() => update.mutate({ archived: false })}
        >
          Restore
        </Button>
      )}
    </div>
  )
}

function Panel({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border">{children}</div>
}

function ViewToggle({
  view,
  onChange,
}: {
  view: ProjectView
  onChange: (view: ProjectView) => void
}) {
  return (
    <WithTooltip content="Switch view" shortcut={SHORTCUTS.toggleView.keys}>
      <div>
        <SegmentedControl
          size="sm"
          aria-label="View"
          value={view}
          onValueChange={onChange}
          options={[
            {
              value: 'board',
              label: (
                <>
                  <SquareKanban aria-hidden="true" className="size-3.5" />
                  Board
                </>
              ),
              ariaLabel: 'Board',
            },
            {
              value: 'list',
              label: (
                <>
                  <List aria-hidden="true" className="size-3.5" />
                  List
                </>
              ),
              ariaLabel: 'List',
            },
          ]}
        />
      </div>
    </WithTooltip>
  )
}

function SortMenu({
  sort,
  onChange,
}: {
  sort: IdeaSort | undefined
  onChange: (sort: IdeaSort | undefined) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="text-secondary">
          <ArrowUpDown aria-hidden="true" />
          <span className="sr-only">Sort: </span>
          {sortLabel(sort)}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Sort by</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={sort ?? '-updated'}
          onValueChange={(value) =>
            onChange(value === '-updated' ? undefined : (value as IdeaSort))
          }
        >
          {SORT_OPTIONS.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
