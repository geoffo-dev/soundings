import { Logo } from '@/components/layout/logo'
import { Skeleton, SkeletonGroup, SkeletonListRow } from '@/components/ui/skeleton'
import { BoardSkeleton } from '@/features/project/board/board-skeleton'
import { resolveView } from '@/features/project/view-preference'

/** A project's board (not its settings or review queue) about to open: its URL and view. */
function opensBoard(): boolean {
  if (typeof window === 'undefined') return false
  const match = /^\/p\/([^/]+)\/?$/.exec(window.location.pathname)
  if (!match?.[1]) return false
  const view = new URLSearchParams(window.location.search).get('view')
  return (
    resolveView(
      decodeURIComponent(match[1]),
      view === 'list' || view === 'board' ? view : undefined,
    ) === 'board'
  )
}

/**
 * What the signed-in layout shows while the session check (GET /auth/me) is
 * in flight on a slow network: the shell's shape, no data, no spinner.
 */
export function AppShellPending() {
  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <div className="hidden w-(--sidebar-width) shrink-0 flex-col gap-5 px-3 py-3 md:flex">
        <Logo />
        <div className="flex flex-col gap-3 pt-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-28" />
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col md:py-2 md:pr-2">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface md:rounded-lg md:border">
          <div className="h-12 shrink-0 border-b border-subtle" />
          {opensBoard() ? (
            // A board on a hard reload: columns, not list rows.
            <div className="flex min-h-0 flex-1 flex-col gap-5 px-4 pt-6 lg:px-6">
              <Skeleton className="h-7 w-48" />
              <BoardSkeleton />
            </div>
          ) : (
            <SkeletonGroup
              label="Loading Soundings"
              className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-10 lg:py-8"
            >
              <Skeleton className="h-7 w-40" />
              <div className="overflow-hidden rounded-lg border">
                <SkeletonListRow />
                <SkeletonListRow />
                <SkeletonListRow className="border-b-0" />
              </div>
            </SkeletonGroup>
          )}
        </div>
      </div>
    </div>
  )
}
