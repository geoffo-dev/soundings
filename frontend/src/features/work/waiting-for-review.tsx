import { Link } from '@tanstack/react-router'

import { useProjects } from '@/api/projects'
import { useReviewCounts } from '@/api/submissions'
import { PageSection } from '@/components/layout/page'
import { CountBadge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

/**
 * "Waiting for review" (project admins; contract-phase4 §3.6): public ideas
 * held for moderation are on no board, list or inbox, and their senders wait
 * until someone looks. One row per project with ideas waiting; nothing at all
 * when none are (most people never see this section).
 */
export function WaitingForReviewSection() {
  const projects = useProjects()
  const reviews = useReviewCounts(projects.data)
  if (reviews.length === 0) return null
  const total = reviews.reduce((sum, review) => sum + review.count, 0)
  return (
    <PageSection
      id="review"
      title={
        <>
          Waiting for review
          <CountBadge>{total}</CountBadge>
        </>
      }
      description="Ideas sent through the public form. They reach the team once approved."
    >
      <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
        {reviews.map(({ project, count }) => (
          <li
            key={project.id}
            className="relative flex items-center gap-4 px-4 py-3 transition-colors duration-100 hover:bg-subtle"
          >
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <Link
                to="/p/$slug/review"
                params={{ slug: project.slug }}
                {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
                className={cn(
                  'truncate text-base font-medium text-primary outline-none',
                  // The whole row is the link; the focus ring outlines the row.
                  'after:absolute after:inset-0 after:content-[""]',
                  'focus-visible:after:ring-2 focus-visible:after:ring-focus focus-visible:after:ring-inset',
                )}
              >
                {project.name}
                <span className="sr-only">
                  : review {count === 1 ? '1 idea' : `${String(count)} ideas`}
                </span>
              </Link>
              <p className="truncate text-sm text-muted">
                {count === 1 ? '1 idea waiting' : `${count.toLocaleString('en')} ideas waiting`}
              </p>
            </div>
            {/* The whole row is the link: this only looks like a button. */}
            <span
              aria-hidden="true"
              className={cn(buttonVariants({ variant: 'outline' }), 'shrink-0 max-sm:h-11')}
            >
              Review
            </span>
          </li>
        ))}
      </ul>
    </PageSection>
  )
}
