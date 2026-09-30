import { Link, useLocation } from '@tanstack/react-router'
import { FolderSearch } from 'lucide-react'

import { Page } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { BoardSkeleton } from '@/features/project/board/board-skeleton'

/*
 * Kept apart from project-page.tsx so the /p/$slug layout route (which shows
 * these while it loads the project) doesn't pull the board and list into the
 * main bundle.
 */

/** The /p/$slug layout's pending state: shaped like the page being opened. */
export function ProjectRoutePending() {
  const settings = useLocation({ select: (location) => location.pathname.endsWith('/settings') })
  return settings ? <ProjectSettingsSkeleton /> : <ProjectPageSkeleton />
}

/** Shown while the project loads. */
export function ProjectPageSkeleton() {
  return (
    <Page width="full" className="h-full min-h-0 gap-4 pb-0 sm:gap-5 lg:px-6 lg:py-6">
      <SkeletonGroup label="Loading project" className="flex flex-col gap-2">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </SkeletonGroup>
      <div className="flex gap-2">
        <Skeleton className="h-7 w-52" />
        <Skeleton className="h-7 w-20" />
        <Skeleton className="h-7 w-16" />
      </div>
      <BoardSkeleton />
    </Page>
  )
}

/** 404 for /p/$slug: the same answer whether it doesn't exist or is private. */
export function ProjectNotFound() {
  return (
    <EmptyState
      headingLevel={1}
      icon={<FolderSearch />}
      title="This project doesn’t exist or you don’t have access"
      description="Check the link, or ask a project admin to add you."
      action={
        <Button asChild variant="primary">
          <Link to="/">Go to My work</Link>
        </Button>
      }
    />
  )
}

/** Settings is loading (the project is usually cached from the board already). */
export function ProjectSettingsSkeleton() {
  return (
    <Page>
      <SkeletonGroup label="Loading settings" className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-80" />
        </div>
        <div className="flex gap-4 border-b pb-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-4 w-20" />
        </div>
        <div className="flex max-w-2xl flex-col gap-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-8 w-full" />
            </div>
          ))}
        </div>
      </SkeletonGroup>
    </Page>
  )
}
