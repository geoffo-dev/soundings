import { createFileRoute, notFound, redirect } from '@tanstack/react-router'

import { findCachedIdea } from '@/api/cache'
import { isApiError } from '@/api/errors'
import { ideaQueryOptions } from '@/api/ideas'
import { retryIfCancelled } from '@/api/query'
import type { IdeaSummary } from '@/api/types'
import { IdeaPage } from '@/features/idea/idea-page'
import { IdeaNotFound, IdeaPageSkeleton } from '@/features/idea/idea-page-states'
import { validateIdeaSearch } from '@/features/idea/idea-search'

/**
 * Project › key. A guest researcher (Phase 8b, `can_view_project` false) sees the
 * project's name as text: project routes are 404 for them, so it is never a link.
 */
function crumbsFor(idea: Pick<IdeaSummary, 'key' | 'title' | 'project' | 'permissions'>) {
  const linked = !('can_view_project' in idea.permissions) || idea.permissions.can_view_project
  return {
    crumbs: [
      linked
        ? { label: idea.project.name, to: `/p/${idea.project.slug}` }
        : { label: idea.project.name },
      { label: idea.key },
    ],
    title: `${idea.key} ${idea.title}`,
  }
}

/** /ideas/$ideaKey?tab=overview|evaluations|proposal&evaluate=1&research=1 */
export const Route = createFileRoute('/_app/ideas/$ideaKey')({
  validateSearch: validateIdeaSearch,
  beforeLoad: ({ params, search }) => {
    // Canonical URLs use the upper-case key (links in emails may not).
    if (params.ideaKey !== params.ideaKey.toUpperCase()) {
      throw redirect({
        to: '/ideas/$ideaKey',
        params: { ideaKey: params.ideaKey.toUpperCase() },
        search,
        replace: true,
      })
    }
  },
  loader: async ({ context, params }) => {
    // Opened from a list, board or My work: paint at once from what they know;
    // the page shows skeletons (or the not-found state) while the detail loads.
    const cached = findCachedIdea(context.queryClient, params.ideaKey)
    if (cached) {
      void context.queryClient.query(ideaQueryOptions(params.ideaKey)).catch(() => undefined)
      return crumbsFor(cached)
    }
    try {
      const idea = await retryIfCancelled(() =>
        context.queryClient.query({ ...ideaQueryOptions(params.ideaKey), staleTime: 'static' }),
      )
      return crumbsFor(idea)
    } catch (error) {
      if (isApiError(error) && (error.status === 404 || error.status === 422)) throw notFound()
      throw error
    }
  },
  // No loader data: the idea wasn't found (or is hidden).
  head: ({ loaderData }) => ({
    meta: [{ title: `${loaderData?.title ?? 'Idea not found'} · Soundings` }],
  }),
  pendingComponent: IdeaPageSkeleton,
  notFoundComponent: IdeaNotFound,
  component: IdeaRoute,
})

function IdeaRoute() {
  const { ideaKey } = Route.useParams()
  const search = Route.useSearch()
  return <IdeaPage ideaKey={ideaKey} search={search} />
}
