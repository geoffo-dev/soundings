import { createRouter } from '@tanstack/react-router'

import { createQueryClient } from '@/api/query'
import { NotFound } from '@/components/not-found'
import { RouteError } from '@/components/route-error'
import { routeTree } from '@/routeTree.gen'

export const queryClient = createQueryClient()

export const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: 'intent',
  // TanStack Query owns caching; let the router always call loaders.
  defaultPreloadStaleTime: 0,
  defaultNotFoundComponent: NotFound,
  defaultErrorComponent: RouteError,
  scrollRestoration: true,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
  interface StaticDataRouteOption {
    /** Breadcrumb label shown in the top bar for this route. */
    crumb?: string
  }
}
