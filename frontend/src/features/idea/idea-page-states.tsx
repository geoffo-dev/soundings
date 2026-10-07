import { Link } from '@tanstack/react-router'
import { SearchX } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { KbdShortcut } from '@/components/ui/kbd'
import { SkeletonGroup, SkeletonIdeaPage } from '@/components/ui/skeleton'

/*
 * Kept apart from idea-page.tsx so the /ideas/$ideaKey route (whose pending and
 * not-found states these are) doesn't pull the idea page, AI and Markdown into
 * every first visit: they load with the route's own chunk (perf review B3).
 */

export function IdeaPageSkeleton() {
  return (
    <SkeletonGroup
      label="Loading idea"
      className="mx-auto w-full max-w-7xl px-4 pt-5 sm:px-6 lg:px-10 lg:pt-8"
    >
      <SkeletonIdeaPage className="lg:grid-cols-[minmax(0,1fr)_18rem]" />
    </SkeletonGroup>
  )
}

/** Same text whether the idea doesn't exist or is hidden, to avoid leaking (wireframe 03). */
export function IdeaNotFound() {
  return (
    <EmptyState
      headingLevel={1}
      icon={<SearchX />}
      title="This idea doesn’t exist or you don’t have access"
      description={
        <>
          Check the link, or search for it with{' '}
          <KbdShortcut keys="mod+k" className="align-middle" />.
        </>
      }
      action={
        <Button asChild variant="primary">
          <Link to="/">Go to My work</Link>
        </Button>
      }
    />
  )
}
