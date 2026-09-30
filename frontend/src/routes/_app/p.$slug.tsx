import { createFileRoute, notFound, Outlet } from '@tanstack/react-router'

import { isApiError } from '@/api/errors'
import { projectQueryOptions } from '@/api/projects'
import { retryIfCancelled } from '@/api/query'
import { ProjectNotFound, ProjectRoutePending } from '@/features/project/project-page-states'

/**
 * Layout for /p/$slug and /p/$slug/settings: loads the project once (404 when
 * it doesn't exist or isn't visible), names the breadcrumb and page title.
 */
export const Route = createFileRoute('/_app/p/$slug')({
  loader: async ({ context, params }) => {
    try {
      // Cached data (any age) or a fetch; the page's own query keeps it fresh.
      const project = await retryIfCancelled(() =>
        context.queryClient.query({ ...projectQueryOptions(params.slug), staleTime: 'static' }),
      )
      return { crumb: project.name }
    } catch (error) {
      if (isApiError(error) && (error.status === 404 || error.status === 422)) throw notFound()
      throw error
    }
  },
  head: ({ loaderData }) => ({
    meta: [{ title: `${loaderData?.crumb ?? 'Project'} · Soundings` }],
  }),
  pendingComponent: ProjectRoutePending,
  notFoundComponent: ProjectNotFound,
  component: Outlet,
})
