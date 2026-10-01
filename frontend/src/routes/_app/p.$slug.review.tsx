import { createFileRoute } from '@tanstack/react-router'

import { ModerationPage } from '@/features/moderation/moderation-page'

/** /p/$slug/review — ideas from the public form waiting for review (project admins). */
export const Route = createFileRoute('/_app/p/$slug/review')({
  staticData: { crumb: 'Review' },
  head: () => ({ meta: [{ title: 'Review new ideas · Soundings' }] }),
  component: ModerationRoute,
})

function ModerationRoute() {
  const { slug } = Route.useParams()
  return <ModerationPage slug={slug} />
}
