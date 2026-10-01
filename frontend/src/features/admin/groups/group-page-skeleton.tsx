import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

/** The group page while it loads (also the route's pending view, so it stays small). */
export function GroupPageSkeleton() {
  return (
    <SkeletonGroup label="Loading group" className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-7 w-24" />
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex flex-col gap-3">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-9 w-full max-w-xl" />
          <Skeleton className="h-9 w-full max-w-md" />
        </div>
      ))}
    </SkeletonGroup>
  )
}
