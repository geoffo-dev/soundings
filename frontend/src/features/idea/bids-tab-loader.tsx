import { lazy, Suspense } from 'react'

import { BidsTabSkeleton } from '@/features/bids/bids-tab-skeleton'

// The Bids tab loads with the tab, not with the idea page: most visits never open it.
const BidsTab = lazy(() =>
  import('@/features/bids/bids-tab').then((module) => ({ default: module.BidsTab })),
)

/** The Bids tab (Phase 10): the idea's call for bids (features/bids). */
export function BidsTabLoader() {
  return (
    <Suspense fallback={<BidsTabSkeleton />}>
      <BidsTab />
    </Suspense>
  )
}
