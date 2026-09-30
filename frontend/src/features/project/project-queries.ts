import type { QueryClient } from '@tanstack/react-query'

import { boardQueryOptions, ideaListInfiniteOptions } from '@/api/ideas'

import { toIdeaFilters, type ProjectSearch, type ProjectView } from './project-search'
import { resolveView } from './view-preference'

/** List page size: large pages keep scrolling through 10k ideas to a few requests. */
export const LIST_PAGE_SIZE = 100

export const projectBoardOptions = (slug: string, search: ProjectSearch) =>
  boardQueryOptions(slug, toIdeaFilters(search))

export const projectListOptions = (slug: string, search: ProjectSearch) =>
  ideaListInfiniteOptions(slug, toIdeaFilters(search), { pageSize: LIST_PAGE_SIZE })

/**
 * Starts loading the board or list for a project URL without waiting for it
 * (route loader, hover preloads): the page shows skeletons if it is slow.
 */
export function prefetchProjectView(
  queryClient: QueryClient,
  slug: string,
  search: ProjectSearch,
): ProjectView {
  const view = resolveView(slug, search.view)
  // Errors are the page's business (it shows them with a retry); ignore them here.
  const ignore = () => undefined
  if (view === 'board') queryClient.query(projectBoardOptions(slug, search)).catch(ignore)
  else queryClient.infiniteQuery(projectListOptions(slug, search)).catch(ignore)
  return view
}
