import { createFileRoute } from '@tanstack/react-router'
import { LayoutGrid } from 'lucide-react'

import { useAppCommands } from '@/components/layout/app-commands'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'

/** PHASE 0 PLACEHOLDER for the project Board/List (SPEC §5 screen 2). */
export const Route = createFileRoute('/_app/projects/$projectId')({
  loader: ({ params }) => ({ crumb: titleFromSlug(params.projectId) }),
  head: ({ loaderData }) => ({
    meta: [{ title: `${loaderData?.crumb ?? 'Project'} · Soundings` }],
  }),
  component: ProjectPage,
})

function titleFromSlug(slug: string): string {
  return slug
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function ProjectPage() {
  const { crumb } = Route.useLoaderData()
  const { newIdea } = useAppCommands()
  return (
    <Page width="wide">
      <PageHeader title={crumb} />
      <div className="rounded-lg border">
        <EmptyState
          icon={<LayoutGrid />}
          title="No ideas in this project yet"
          description="Ideas submitted here appear on the board, grouped by status. Start with the first one."
          action={
            <Button variant="primary" onClick={newIdea}>
              Submit an idea
            </Button>
          }
        />
      </div>
    </Page>
  )
}
