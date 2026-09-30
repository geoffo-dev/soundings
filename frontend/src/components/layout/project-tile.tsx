import { cn } from '@/lib/utils'

/** Neutral letter tile for a project — projects don't get colours (colour is for status and scores). */
export function ProjectTile({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex size-4.5 shrink-0 items-center justify-center rounded-[4px] border border-strong bg-surface text-[0.625rem] font-semibold text-secondary',
        className,
      )}
    >
      {name.trim()[0]?.toUpperCase()}
    </span>
  )
}
