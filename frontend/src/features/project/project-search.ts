import type { IdeaFilters, IdeaSort, IdeaStatus, Resolution } from '@/api/types'
import { searchEnum, searchFlag, searchList, searchString } from '@/lib/search-params'

/**
 * URL state of the project page (`/p/$slug?view=list&status=new,evaluating…`).
 * Filters live in the URL so views can be shared (wireframe 02). Defaults are
 * omitted, so a plain `/p/$slug` is the default view.
 */
export interface ProjectSearch {
  view?: ProjectView
  status?: IdeaStatus[]
  resolution?: Resolution[]
  /** A user id, "me" or "none". */
  owner?: string
  tag?: string[]
  needs_evaluators?: true
  high_disagreement?: true
  q?: string
  sort?: IdeaSort
}

export type ProjectView = 'board' | 'list'

export const PROJECT_VIEWS = ['board', 'list'] as const
const STATUSES: IdeaStatus[] = ['new', 'evaluating', 'shortlisted', 'proposal', 'closed']
const RESOLUTIONS: Resolution[] = ['accepted', 'rejected', 'parked']
const SORTS: IdeaSort[] = [
  'score',
  '-score',
  'updated',
  '-updated',
  'created',
  '-created',
  'votes',
  '-votes',
  'title',
  '-title',
]

export function validateProjectSearch(search: Record<string, unknown>): ProjectSearch {
  const owner = searchString(search.owner, 36)
  const sort = searchEnum(search.sort, SORTS)
  return {
    view: searchEnum(search.view, PROJECT_VIEWS),
    status: searchList(search.status, STATUSES),
    resolution: searchList(search.resolution, RESOLUTIONS),
    owner:
      owner === 'me' || owner === 'none' || (owner && /^[0-9a-f-]{36}$/i.test(owner))
        ? owner
        : undefined,
    tag: searchList(search.tag)?.slice(0, 10),
    needs_evaluators: searchFlag(search.needs_evaluators),
    high_disagreement: searchFlag(search.high_disagreement),
    q: searchString(search.q),
    // The default order is left out of the URL.
    sort: sort === DEFAULT_SORT ? undefined : sort,
  }
}

/** The API filters for the list and board queries. */
export function toIdeaFilters(search: ProjectSearch): IdeaFilters {
  return {
    status: search.status,
    resolution: search.resolution,
    owner: search.owner,
    tag: search.tag,
    needs_evaluators: search.needs_evaluators,
    high_disagreement: search.high_disagreement,
    q: search.q,
    sort: search.sort,
  }
}

/* ------------------------------------------------------------------ */
/* Filters                                                             */
/* ------------------------------------------------------------------ */

/** The URL keys that filter ideas (everything except `view` and `sort`). */
export const FILTER_KEYS = [
  'status',
  'resolution',
  'owner',
  'tag',
  'needs_evaluators',
  'high_disagreement',
  'q',
] as const satisfies readonly (keyof ProjectSearch)[]

export type FilterKey = (typeof FILTER_KEYS)[number]

/** Status and resolution only filter the List; the Board always shows every column. */
const LIST_ONLY: readonly FilterKey[] = ['status', 'resolution']

/** Filters that apply in a view (the Board ignores status and resolution). */
export function activeFilters(search: ProjectSearch, view: ProjectView): FilterKey[] {
  return FILTER_KEYS.filter(
    (key) => search[key] !== undefined && (view === 'list' || !LIST_ONLY.includes(key)),
  )
}

export function hasActiveFilters(search: ProjectSearch, view: ProjectView): boolean {
  return activeFilters(search, view).length > 0
}

/** "Clear filters": drops every filter, keeps the view and the sort. */
export function clearFilters(search: ProjectSearch): ProjectSearch {
  return { view: search.view, sort: search.sort }
}

/**
 * Switching views. The Board has no status filter (its columns are the
 * statuses), so going to the Board drops status and resolution rather than
 * keep a filter nobody can see.
 */
export function withView(search: ProjectSearch, view: ProjectView): ProjectSearch {
  if (view === 'list') return { ...search, view }
  const { status: _status, resolution: _resolution, ...rest } = search
  return { ...rest, view }
}

/** Adds or removes one value of a list filter (status, tag…); empty lists are dropped. */
export function toggleValue<T extends string>(values: T[] | undefined, value: T): T[] | undefined {
  const current = values ?? []
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
  return next.length > 0 ? next : undefined
}

/* ------------------------------------------------------------------ */
/* Sort                                                                */
/* ------------------------------------------------------------------ */

/** Contract §3.9: the default order is most recently updated first. */
export const DEFAULT_SORT: IdeaSort = '-updated'

/** Columns the API can sort by (owner, evaluators and status can't be). */
export type SortColumn = 'title' | 'score' | 'votes' | 'updated' | 'created'
export type SortDirection = 'asc' | 'desc'

/** The first click on a header: A→Z for titles, biggest/newest first for the rest. */
const FIRST_DIRECTION: Record<SortColumn, SortDirection> = {
  title: 'asc',
  score: 'desc',
  votes: 'desc',
  updated: 'desc',
  created: 'desc',
}

export function parseSort(sort: IdeaSort | undefined): {
  column: SortColumn
  direction: SortDirection
} {
  const value = sort ?? DEFAULT_SORT
  const descending = value.startsWith('-')
  return {
    column: (descending ? value.slice(1) : value) as SortColumn,
    direction: descending ? 'desc' : 'asc',
  }
}

export function toSort(column: SortColumn, direction: SortDirection): IdeaSort {
  return direction === 'desc' ? `-${column}` : column
}

/** How a header shows its state (`aria-sort`): the direction if sorted by it, else false. */
export function sortDirectionFor(
  sort: IdeaSort | undefined,
  column: SortColumn,
): SortDirection | false {
  const current = parseSort(sort)
  return current.column === column ? current.direction : false
}

/**
 * The sort after clicking a header: a new column starts in its natural
 * direction, the current one flips. Returns `undefined` for the default order
 * so it stays out of the URL.
 */
export function nextSort(sort: IdeaSort | undefined, column: SortColumn): IdeaSort | undefined {
  const current = parseSort(sort)
  const direction =
    current.column === column
      ? current.direction === 'asc'
        ? 'desc'
        : 'asc'
      : FIRST_DIRECTION[column]
  const next = toSort(column, direction)
  return next === DEFAULT_SORT ? undefined : next
}

/** What each sort is called (the menu, and the button when a header chose it). */
const SORT_LABELS: Record<IdeaSort, string> = {
  '-updated': 'Recently updated',
  updated: 'Least recently updated',
  '-score': 'Highest score',
  score: 'Lowest score',
  '-votes': 'Most votes',
  votes: 'Fewest votes',
  '-created': 'Newest',
  created: 'Oldest',
  title: 'Title A–Z',
  '-title': 'Title Z–A',
}

/**
 * The sort menu (Board, and the List where its headers are hidden): the five
 * orders people want. The others are a click on a List header away (it flips
 * the direction), and show up in the menu while they're in use.
 */
const SORT_MENU: IdeaSort[] = ['-updated', '-score', '-votes', '-created', 'title']

export function sortMenuOptions(sort: IdeaSort | undefined): { value: IdeaSort; label: string }[] {
  const values = sort && !SORT_MENU.includes(sort) ? [...SORT_MENU, sort] : SORT_MENU
  return values.map((value) => ({ value, label: SORT_LABELS[value] }))
}

export function sortLabel(sort: IdeaSort | undefined): string {
  return SORT_LABELS[sort ?? DEFAULT_SORT]
}
