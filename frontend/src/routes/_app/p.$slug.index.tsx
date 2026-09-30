import { createFileRoute } from '@tanstack/react-router'

import { ProjectPage } from '@/features/project/project-page'
import { prefetchProjectView } from '@/features/project/project-queries'
import { validateProjectSearch } from '@/features/project/project-search'

/** /p/$slug?view=board|list&status=…&owner=…&tag=…&needs_evaluators=1&high_disagreement=1&q=…&sort=… */
export const Route = createFileRoute('/_app/p/$slug/')({
  validateSearch: validateProjectSearch,
  loaderDeps: ({ search }) => search,
  // Start loading the ideas alongside the project (also on hover preloads); don't wait.
  loader: ({ context, params, deps }) => {
    prefetchProjectView(context.queryClient, params.slug, deps)
  },
  component: ProjectRoute,
})

function ProjectRoute() {
  const { slug } = Route.useParams()
  const search = Route.useSearch()
  return <ProjectPage slug={slug} search={search} />
}
