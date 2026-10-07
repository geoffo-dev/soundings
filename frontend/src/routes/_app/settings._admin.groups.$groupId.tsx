import { createFileRoute, Link, notFound } from '@tanstack/react-router'
import { UsersRound } from 'lucide-react'

import { adminGroupQueryOptions } from '@/api/admin'
import { isApiError } from '@/api/errors'
import { retryIfCancelled } from '@/api/query'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { GroupPage } from '@/features/admin/groups/group-page'
import { GroupPageSkeleton } from '@/features/admin/groups/group-page-skeleton'

/** /settings/groups/$groupId — one group; 404 when it doesn't exist. */
export const Route = createFileRoute('/_app/settings/_admin/groups/$groupId')({
  loader: async ({ context, params }) => {
    try {
      const group = await retryIfCancelled(() =>
        context.queryClient.query({
          ...adminGroupQueryOptions(params.groupId),
          staleTime: 'static',
        }),
      )
      return {
        crumbs: [{ label: 'Groups', to: '/settings/groups' }, { label: group.name }],
        name: group.name,
      }
    } catch (error) {
      if (isApiError(error) && (error.status === 404 || error.status === 422)) throw notFound()
      throw error
    }
  },
  head: ({ loaderData }) => ({
    meta: [{ title: `${loaderData?.name ?? 'Group'} · Admin · Soundings` }],
  }),
  pendingComponent: GroupPageSkeleton,
  notFoundComponent: GroupNotFound,
  component: GroupRoute,
})

function GroupRoute() {
  const { groupId } = Route.useParams()
  return <GroupPage groupId={groupId} />
}

function GroupNotFound() {
  return (
    <EmptyState
      icon={<UsersRound />}
      title="We couldn’t find that group"
      description="It may have been deleted, or the link is out of date."
      action={
        <Button asChild variant="secondary">
          <Link to="/settings/groups">All groups</Link>
        </Button>
      }
    />
  )
}
