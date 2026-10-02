import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

import { PROPOSAL_SECTIONS } from './text'

/** Outline and headings first; section bodies as skeleton lines (wireframe 05). */
export function ProposalSkeleton() {
  return (
    <SkeletonGroup label="Loading proposal" className="flex flex-col">
      <div className="flex items-center justify-between border-b border-subtle pb-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="grid gap-x-10 xl:grid-cols-[12rem_minmax(0,1fr)]">
        <ol className="hidden flex-col gap-1 pt-8 xl:flex">
          {PROPOSAL_SECTIONS.map((section) => (
            <li
              key={section.key}
              className="flex items-center gap-2 px-2 py-1.5 text-sm text-muted"
            >
              <Skeleton className="size-4 rounded-full" />
              {section.title}
            </li>
          ))}
        </ol>
        <div className="flex flex-col">
          {PROPOSAL_SECTIONS.slice(0, 3).map((section, index) => (
            <div key={section.key} className="flex flex-col gap-3 border-b border-subtle py-8">
              <p className="text-lg font-semibold text-primary">
                <span className="text-muted tabular-nums">{index + 1}.</span> {section.title}
              </p>
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
