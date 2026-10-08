import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

/** Outline, headings and section bodies as skeleton lines (wireframe 05). */
export function ProposalSkeleton() {
  return (
    <SkeletonGroup label="Loading proposal" className="flex flex-col">
      <div className="flex items-center justify-between border-b border-subtle pb-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="grid gap-x-10 xl:grid-cols-[12rem_minmax(0,1fr)]">
        <ol className="hidden flex-col gap-1 pt-8 xl:flex">
          {['w-20', 'w-16', 'w-24', 'w-28', 'w-20', 'w-24'].map((width, index) => (
            <li key={index} className="flex items-center gap-2 px-2 py-1.5">
              <Skeleton className="size-4 rounded-full" />
              <Skeleton className={`h-3.5 ${width}`} />
            </li>
          ))}
        </ol>
        <div className="flex flex-col">
          {['w-32', 'w-24', 'w-28'].map((width, index) => (
            <div key={index} className="flex flex-col gap-3 border-b border-subtle py-8">
              <Skeleton className={`h-5 ${width}`} />
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-11/12" />
              <Skeleton className="h-3.5 w-3/5" />
            </div>
          ))}
        </div>
      </div>
    </SkeletonGroup>
  )
}
