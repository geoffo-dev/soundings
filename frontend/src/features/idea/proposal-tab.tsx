import { lazy, Suspense } from 'react'

import { ProposalSkeleton } from '@/features/proposal/proposal-skeleton'

import { useIdeaPage } from './idea-context'

// The editor loads with the tab, not with the app: most visits never open it.
const ProposalPanel = lazy(() =>
  import('@/features/proposal/proposal-panel').then((module) => ({
    default: module.ProposalPanel,
  })),
)

/** The Proposal tab: the proposal editor (features/proposal) for the idea in view. */
export function ProposalTab() {
  const { ideaKey, idea, me, archived, setTab } = useIdeaPage()
  return (
    <Suspense fallback={<ProposalSkeleton />}>
      <ProposalPanel
        ideaKey={ideaKey}
        idea={idea}
        me={me}
        archived={archived}
        onOpenResearch={() => setTab('overview')}
      />
    </Suspense>
  )
}
