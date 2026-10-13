import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

/** While the call (or the tab's code) loads: its header, then rows. */
export function BidsTabSkeleton() {
  return (
    <SkeletonGroup label="Loading the call for bids" className="flex flex-col gap-6 pt-2">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-6 w-72" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <div className="flex flex-col divide-y divide-subtle rounded-lg border">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="ml-auto h-4 w-24" />
          </div>
        ))}
      </div>
    </SkeletonGroup>
  )
}
