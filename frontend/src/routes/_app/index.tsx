import { createFileRoute } from '@tanstack/react-router'
import { CircleCheckBig, Plus } from 'lucide-react'

import { useAppCommands } from '@/components/layout/app-commands'
import { Page, PageHeader, PageSection } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { KbdShortcut } from '@/components/ui/kbd'
import { SkeletonGroup, SkeletonListRow } from '@/components/ui/skeleton'
import { SHORTCUTS } from '@/lib/shortcuts'

export const Route = createFileRoute('/_app/')({
  staticData: { crumb: 'My work' },
  head: () => ({ meta: [{ title: 'My work · Soundings' }] }),
  component: MyWorkPage,
})

/**
 * PHASE 0 PLACEHOLDER for "My work" (SPEC §5 screen 1). Phase 1 replaces the
 * skeletons with real queries; the layout and states are the reference.
 */
function MyWorkPage() {
  const { newIdea } = useAppCommands()
  return (
    <Page>
      <PageHeader
        title="My work"
        description="Evaluations waiting for you, ideas you own and what changed recently."
        actions={
          <Button variant="primary" onClick={newIdea}>
            <Plus />
            New idea
            <KbdShortcut
              keys={SHORTCUTS.newIdea.keys}
              className="ml-1 hidden sm:inline-flex [&_kbd]:border-white/25 [&_kbd]:bg-white/15 [&_kbd]:text-accent-foreground [&_kbd]:shadow-none"
            />
          </Button>
        }
      />

      <PageSection title="Evaluations due">
        <div className="rounded-lg border">
          <EmptyState
            size="compact"
            icon={<CircleCheckBig />}
            title="You’re all caught up"
            description="When an idea owner asks you to evaluate, it shows up here with its due date."
          />
        </div>
      </PageSection>

      <PageSection title="Ideas I own">
        <SkeletonGroup label="Loading your ideas" className="overflow-hidden rounded-lg border">
          <SkeletonListRow />
          <SkeletonListRow />
          <SkeletonListRow className="border-b-0" />
        </SkeletonGroup>
      </PageSection>

      <PageSection title="Recently updated in my projects">
        <SkeletonGroup
          label="Loading recent activity"
          className="overflow-hidden rounded-lg border"
        >
          <SkeletonListRow />
          <SkeletonListRow />
          <SkeletonListRow />
          <SkeletonListRow className="border-b-0" />
        </SkeletonGroup>
      </PageSection>
    </Page>
  )
}
