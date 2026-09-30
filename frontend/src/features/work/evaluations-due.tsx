import { Link } from '@tanstack/react-router'
import { CircleCheckBig } from 'lucide-react'

import type { WorkEvaluation } from '@/api/types'
import { PageSection } from '@/components/layout/page'
import { Badge, CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

/**
 * "Evaluations due": overdue first, then soonest (the API's order). The most
 * urgent row carries the page's one primary action.
 */
export function EvaluationsDueSection({ items }: { items: WorkEvaluation[] | undefined }) {
  return (
    <PageSection
      id="evaluations"
      title={
        <>
          Evaluations due
          {items && items.length > 0 && <CountBadge>{items.length}</CountBadge>}
        </>
      }
    >
      {!items ? (
        <SkeletonGroup
          label="Loading evaluations"
          className="divide-y divide-subtle overflow-hidden rounded-lg border"
        >
          {[0, 1].map((i) => (
            <div key={i} className="flex min-h-16 items-center gap-4 px-4 py-3">
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-3.5 w-[min(20rem,70%)]" />
                <Skeleton className="h-3 w-[min(12rem,50%)]" />
              </div>
              <Skeleton className="hidden h-3.5 w-24 sm:block" />
              <Skeleton className="h-8 w-20" />
            </div>
          ))}
        </SkeletonGroup>
      ) : items.length === 0 ? (
        <div className="rounded-lg border">
          <EmptyState
            size="compact"
            icon={<CircleCheckBig />}
            title="Nothing to evaluate"
            description="When someone asks for your view on an idea, it appears here with its due date."
          />
        </div>
      ) : (
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
          {items.map((item, index) => (
            <EvaluationRow key={item.idea.id} item={item} primary={index === 0} />
          ))}
        </ul>
      )}
    </PageSection>
  )
}

function EvaluationRow({ item, primary }: { item: WorkEvaluation; primary: boolean }) {
  const { idea } = item
  return (
    <li
      data-evaluate-key={idea.key}
      className="relative flex flex-col gap-2.5 px-4 py-3 transition-colors duration-100 hover:bg-subtle sm:flex-row sm:items-center sm:gap-4"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="shrink-0 text-xs text-muted tabular-nums">{idea.key}</span>
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
            className={cn(
              'line-clamp-2 text-base font-medium text-primary outline-none sm:truncate',
              // The whole row is the link; the focus ring outlines the row.
              'after:absolute after:inset-0 after:content-[""]',
              'focus-visible:after:ring-2 focus-visible:after:ring-focus focus-visible:after:ring-inset',
            )}
          >
            {idea.title}
          </Link>
        </div>
        <p className="truncate text-sm text-muted">
          {idea.project.name}
          {item.owner && <> · owner {item.owner.display_name}</>}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 sm:shrink-0 sm:flex-nowrap">
        {item.state === 'draft' && <Badge>Draft saved</Badge>}
        <DueDateLabel value={item.due_at} />
        <Button
          asChild
          variant={primary ? 'primary' : 'outline'}
          className={cn(
            'relative z-10 ml-auto max-sm:h-11 max-sm:px-5',
            primary && 'max-sm:basis-full',
          )}
        >
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            search={{ evaluate: true }}
            aria-label={`Evaluate ${idea.key}: ${idea.title}`}
          >
            {item.state === 'draft' ? 'Continue' : 'Evaluate'}
          </Link>
        </Button>
      </div>
    </li>
  )
}
