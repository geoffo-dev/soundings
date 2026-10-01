import { Filter, Inbox, Lightbulb, SearchX, WifiOff } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import {
  Skeleton,
  SkeletonBoardCard,
  SkeletonIdeaPage,
  SkeletonListRow,
} from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'

import { Code, DesignSection, Example, Specimen } from './specimen'

export function FeedbackSection() {
  return (
    <DesignSection
      id="states"
      title="Empty, loading & error states"
      description={
        <>
          Every screen needs all three. Empty states say what the place is for and offer the next
          step. Load with skeletons shaped like the content; <Code>Spinner</Code> is only for inline
          button loading.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="EmptyState · default" flush className="flex items-center justify-center">
          <EmptyState
            icon={<Lightbulb />}
            title="No ideas yet"
            description="Ideas submitted to Customer Innovation show up here. Share the first one — it takes a minute."
            action={<Button variant="primary">Submit an idea</Button>}
            secondaryAction={<Button variant="ghost">Invite members</Button>}
          />
        </Specimen>
        <div className="flex flex-col gap-4">
          <Specimen title="EmptyState · compact (filtered)" flush>
            <EmptyState
              size="compact"
              icon={<SearchX />}
              title="No ideas match these filters"
              description="Try removing a filter or searching for something else."
              action={
                <Button variant="outline" size="sm">
                  <Filter /> Clear filters
                </Button>
              }
            />
          </Specimen>
          <Specimen title="Error state" flush>
            <EmptyState
              size="compact"
              role="alert"
              icon={<WifiOff />}
              title="Couldn’t load evaluations"
              description="We’ll retry automatically. You can also try now."
              action={
                <Button variant="outline" size="sm">
                  Try again
                </Button>
              }
            />
          </Specimen>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="Skeleton · list rows" flush>
          <div aria-hidden="true">
            <SkeletonListRow />
            <SkeletonListRow />
            <SkeletonListRow className="border-b-0" />
          </div>
        </Specimen>
        <Specimen title="Skeleton · board cards" className="grid grid-cols-2 gap-3 bg-background">
          <SkeletonBoardCard />
          <SkeletonBoardCard />
        </Specimen>
      </div>
      <Specimen title="Callout · inline messages (sign-in problems, notes on a setting)">
        <div className="flex max-w-xl flex-col gap-2">
          <Callout tone="success" title="You’re signed out." />
          <Callout tone="info" title="Your session has ended">
            Sign in again to carry on where you left off.
          </Callout>
          <Callout tone="warning" title="You don’t have a Soundings account yet">
            Ask an administrator to add you, then sign in again.
          </Callout>
          <Callout tone="danger" title="We couldn’t verify your sign-in">
            Try again. If it keeps happening, contact your administrator.
          </Callout>
          <Callout title="Platform admins can see and manage every project without a role here." />
        </div>
      </Specimen>
      <Specimen title="Skeleton · idea page">
        <SkeletonIdeaPage />
      </Specimen>
      <Specimen title="Primitives" className="flex flex-wrap items-end gap-6">
        <Example label="Skeleton">
          <div className="flex items-center gap-2">
            <Skeleton className="size-8 rounded-full" />
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-3 w-20" />
            </div>
          </div>
        </Example>
        <Example label="Spinner (inline only)">
          <Spinner label="Loading" className="text-muted" />
        </Example>
        <Example label="Compact empty (in a card)">
          <span className="inline-flex items-center gap-2 text-sm text-muted">
            <Inbox className="size-4" aria-hidden="true" /> Nothing here yet
          </span>
        </Example>
      </Specimen>
    </DesignSection>
  )
}
