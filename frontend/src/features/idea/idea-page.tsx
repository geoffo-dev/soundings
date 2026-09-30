import { Link } from '@tanstack/react-router'
import { SearchX } from 'lucide-react'

import { useCachedIdeaSummary, useIdea } from '@/api/ideas'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { KbdShortcut } from '@/components/ui/kbd'
import { SkeletonGroup, SkeletonIdeaPage } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status-badge'

import type { IdeaSearch } from './idea-search'

/**
 * PLACEHOLDER — the frontend-idea agent replaces this with the idea page
 * (SPEC §5 screen 3, wireframe 03), the evaluate sheet (`search.evaluate`)
 * and activity/comments. The route has already loaded the idea (404 → not
 * found) and canonicalised the key to upper case.
 */
export function IdeaPage({ ideaKey, search }: { ideaKey: string; search: IdeaSearch }) {
  const idea = useIdea(ideaKey)
  const cached = useCachedIdeaSummary(ideaKey)
  const title = idea.data?.title ?? cached?.title
  return (
    <Page>
      <PageHeader
        title={title ?? ideaKey}
        description={idea.data?.summary ?? cached?.summary}
        actions={
          idea.data && (
            <StatusBadge
              status={idea.data.status}
              resolution={idea.data.resolution}
              label={idea.data.status_label}
            />
          )
        }
      />
      {search.evaluate && (
        <p className="text-sm text-muted">The evaluate sheet opens here (?evaluate=1).</p>
      )}
      {!idea.data && <IdeaPageSkeleton />}
    </Page>
  )
}

export function IdeaPageSkeleton() {
  return (
    <SkeletonGroup label="Loading idea">
      <SkeletonIdeaPage />
    </SkeletonGroup>
  )
}

/** Same text whether the idea doesn't exist or is hidden, to avoid leaking (wireframe 03). */
export function IdeaNotFound() {
  return (
    <EmptyState
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
