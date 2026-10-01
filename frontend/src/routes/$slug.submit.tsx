import { createFileRoute } from '@tanstack/react-router'

import { publicProjectQueryOptions } from '@/api/public'
import { PublicSubmitPage } from '@/features/public/submit-page'

/**
 * /{slug}/submit — a project's public form (SPEC §10; contract-phase4 §3.5).
 * Public: no sign-in and no app shell, like /login. The app's own top-level
 * paths are static routes and reserved slugs (`RESERVED_SLUGS`), so they never
 * reach this route. The loader fetches the project first so the page renders
 * in its branding at once; it never fails (the page shows the error states).
 */
export const Route = createFileRoute('/$slug/submit')({
  loader: async ({ context, params }) => {
    try {
      const project = await context.queryClient.query(publicProjectQueryOptions(params.slug))
      return { title: `Share an idea with ${project.name}` }
    } catch {
      return { title: 'Share an idea' }
    }
  },
  head: ({ loaderData }) => ({
    meta: [
      { title: `${loaderData?.title ?? 'Share an idea'} · Soundings` },
      { name: 'referrer', content: 'no-referrer' },
    ],
  }),
  component: PublicSubmitRoute,
})

function PublicSubmitRoute() {
  const { slug } = Route.useParams()
  return <PublicSubmitPage slug={slug} />
}
