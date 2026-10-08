import { Link } from '@tanstack/react-router'
import { CloudOff, Search } from 'lucide-react'
import { useId } from 'react'

import { useSimilarIdeas } from '@/api/research'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status-badge'

/**
 * "Similar ideas" (contract-phase8 §3.7): up to five ideas with a similar title or
 * summary in every project you can see (archived ones too), most similar first, so
 * the owner can check it isn't already being done and knows whom to ask. Held ideas
 * never appear; there is no score data, so blind evaluation is unaffected.
 */
export function SimilarIdeas({ ideaKey }: { ideaKey: string }) {
  const similar = useSimilarIdeas(ideaKey)
  const headingId = useId()
  const items = similar.data?.items ?? []
  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-2 border-t border-subtle pt-4"
    >
      <h3 id={headingId} className="text-sm font-medium text-primary">
        Similar ideas
      </h3>
      {similar.isPending ? (
        <SkeletonGroup label="Looking for similar ideas" className="flex flex-col gap-2">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </SkeletonGroup>
      ) : similar.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-secondary">
          <CloudOff aria-hidden="true" className="size-4 text-muted" />
          We couldn’t look for similar ideas.
          <Button size="sm" variant="outline" onClick={() => void similar.refetch()}>
            Try again
          </Button>
        </div>
      ) : items.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Search aria-hidden="true" className="size-4 shrink-0" />
          No similar ideas found in the projects you can see.
        </p>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {items.map((idea) => (
            <li key={idea.id}>
              <Link
                to="/ideas/$ideaKey"
                params={{ ideaKey: idea.key }}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-2 transition-colors hover:bg-subtle focus-visible:bg-subtle focus-visible:-outline-offset-2"
              >
                <span className="flex min-w-0 flex-1 items-baseline gap-2">
                  <span className="shrink-0 text-xs whitespace-nowrap text-muted tabular-nums">
                    {idea.key}
                  </span>
                  <span className="min-w-0 truncate text-sm font-medium text-primary">
                    {idea.title}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-3 text-sm text-muted">
                  <span className="max-w-40 truncate">{idea.project.name}</span>
                  <StatusBadge
                    variant="plain"
                    status={idea.status}
                    resolution={idea.resolution}
                    label={idea.status_label}
                  />
                  {idea.owner ? (
                    <span className="flex items-center gap-1.5">
                      <Avatar
                        name={idea.owner.display_name}
                        src={idea.owner.avatar_url}
                        size="xs"
                        decorative
                      />
                      <span className="max-w-32 truncate max-sm:sr-only">
                        {idea.owner.display_name}
                      </span>
                    </span>
                  ) : (
                    <span className="max-sm:sr-only">No owner</span>
                  )}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
