import { createFileRoute, notFound, redirect } from '@tanstack/react-router'

import { isApiError } from '@/api/errors'
import { ideaQueryOptions } from '@/api/ideas'
import { retryIfCancelled } from '@/api/query'
import { IdeaNotFound, IdeaPage, IdeaPageSkeleton } from '@/features/idea/idea-page'
import { validateIdeaSearch } from '@/features/idea/idea-search'

/** /ideas/$ideaKey?tab=overview|evaluations|proposal&evaluate=1 */
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
    try {
      const idea = await retryIfCancelled(() =>
        context.queryClient.query({ ...ideaQueryOptions(params.ideaKey), staleTime: 'static' }),
      )
      return {
        crumbs: [{ label: idea.project.name, to: `/p/${idea.project.slug}` }, { label: idea.key }],
        title: `${idea.key} ${idea.title}`,
      }
    } catch (error) {
      if (isApiError(error) && (error.status === 404 || error.status === 422)) throw notFound()
      throw error
    }
  },
  head: ({ loaderData }) => ({ meta: [{ title: `${loaderData?.title ?? 'Idea'} · Soundings` }] }),
  pendingComponent: IdeaPageSkeleton,
  notFoundComponent: IdeaNotFound,
  component: IdeaRoute,
})

function IdeaRoute() {
  const { ideaKey } = Route.useParams()
  const search = Route.useSearch()
  return <IdeaPage ideaKey={ideaKey} search={search} />
}
