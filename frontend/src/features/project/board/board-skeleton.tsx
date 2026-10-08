import { SkeletonBoardCard, SkeletonGroup } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** Five skeleton columns while the board loads. */
export function BoardSkeleton() {
  return (
    <SkeletonGroup label="Loading the board" className="flex min-h-0 flex-1 gap-3 overflow-hidden">
      {[3, 4, 2, 1, 1].map((cards, index) => (
        <div
          key={index}
          className={cn(
            'flex w-11/12 shrink-0 flex-col gap-2 rounded-lg bg-background p-2',
            index === 4 ? 'sm:w-40' : 'sm:w-auto sm:max-w-sm sm:min-w-44 sm:flex-1',
          )}
        >
          <div className="flex h-8 items-center gap-2 px-1.5">
            <span className="size-2 rounded-full bg-subtle-hover" />
            <span className="h-3 w-20 animate-pulse rounded-sm bg-subtle-hover" />
          </div>
          {Array.from({ length: cards }, (_, card) => (
            <SkeletonBoardCard key={card} />
          ))}
        </div>
      ))}
    </SkeletonGroup>
  )
}
