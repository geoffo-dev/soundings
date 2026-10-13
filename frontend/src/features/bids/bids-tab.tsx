import { CloudOff, FileStack, Gavel, Lock } from 'lucide-react'
import { useState } from 'react'

import { useBidCall } from '@/api/bids'
import type { BidCallSummary, BidCallView } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { useIdeaPage } from '@/features/idea/idea-context'
import { formatDate } from '@/lib/dates'

import { AssessmentQueue } from './assessment-queue'
import { AssessmentSheet } from './assessment-sheet'
import { BidList } from './bid-list'
import { BidSheet } from './bid-sheet'
import { CALL_STATUS } from './bid-copy'
import { BidsTabSkeleton } from './bids-tab-skeleton'
import { CallHeader } from './call-header'
import { CreateCallDialog } from './call-dialogs'
import { Comparison } from './comparison'
import { EvaluationPanel } from './evaluation-panel'
import { useBidCommands } from './use-bid-commands'

/**
 * The idea's Bids tab (contract-phase10 §3, role matrix table M): the call for bids as
 * much as you may see of it. Call managers run it (bids, documents, must-haves, the
 * assessors, the comparison and the award); section assessors score their sections;
 * everyone else who can see the idea sees only that a call exists.
 */
export function BidsTab() {
  const { ideaKey } = useIdeaPage()
  const view = useBidCall(ideaKey)
  if (view.isPending) return <BidsTabSkeleton />
  if (view.isError) {
    return (
      <EmptyState
        role="alert"
        size="compact"
        icon={<CloudOff />}
        title="We couldn’t load the call for bids"
        description="Check your connection and try again."
        action={<Button onClick={() => void view.refetch()}>Try again</Button>}
      />
    )
  }
  return <BidsView view={view.data} />
}

function BidsView({ view }: { view: BidCallView }) {
  const { ideaKey, idea } = useIdeaPage()
  const [creating, setCreating] = useState(false)
  if (!view.summary) {
    return (
      <>
        <EmptyState
          size="compact"
          headingLevel={2}
          icon={<Gavel />}
          title="No call for bids yet"
          description={
            view.permissions.can_create
              ? 'Once the proposal is agreed, run a call for bids: enter the bids that come in with their documents, check their must-haves, and have assessors score them section by section.'
              : 'The idea’s owner or an admin can start one once the idea is in Proposal, with a proposal.'
          }
          action={
            view.permissions.can_create ? (
              <Button variant="primary" onClick={() => setCreating(true)}>
                Start a call for bids
              </Button>
            ) : undefined
          }
        />
        <CreateCallDialog
          ideaKey={ideaKey}
          ideaTitle={idea.title}
          open={creating}
          onOpenChange={setCreating}
        />
      </>
    )
  }
  if (!view.call) return <SummaryOnly summary={view.summary} />
  return <CallView view={view as BidCallView & { call: NonNullable<BidCallView['call']> }} />
}

/** Members, viewers and internal non-members: that a call exists, nothing about its bids. */
function SummaryOnly({ summary }: { summary: BidCallSummary }) {
  const status = CALL_STATUS[summary.status]
  return (
    <section
      aria-labelledby="bid-call-title"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="bid-call-title" className="text-lg font-semibold text-primary">
          {summary.title}
        </h2>
        <Badge variant={status.tone}>{status.label}</Badge>
      </div>
      <p className="text-sm text-secondary">
        {[
          summary.deadline_at ? `Deadline ${formatDate(summary.deadline_at)}` : 'No deadline yet',
          `${summary.bid_count} ${summary.bid_count === 1 ? 'bid' : 'bids'}`,
        ].join(' · ')}
      </p>
      <p className="flex items-center gap-2 text-sm text-muted">
        <Lock aria-hidden="true" className="size-4 shrink-0" />
        Only the idea’s owner, admins and the call’s assessors see the bids.
      </p>
    </section>
  )
}

function CallView({ view }: { view: BidCallView & { call: NonNullable<BidCallView['call']> } }) {
  const { ideaKey, search, setSearch } = useIdeaPage()
  const { call, permissions } = view
  useBidCommands(view)
  const openBid = (bidId: string | undefined, assess?: string) =>
    setSearch?.({ tab: 'bids', bid: bidId, assess })
  const assessing = permissions.can_assess || permissions.assess_section_ids.length > 0

  return (
    <div className="flex flex-col gap-10">
      <CallHeader view={view} />
      {assessing && (
        <AssessmentQueue
          ideaKey={ideaKey}
          call={call}
          canAssess={permissions.can_assess}
          onAssess={(bidId, sectionId) => openBid(bidId, sectionId)}
        />
      )}
      <BidList view={view} onOpen={(bidId) => openBid(bidId)} />
      {permissions.can_view_scores && call.bid_count > 0 && call.status !== 'draft' && (
        <Comparison view={view} onOpen={(bidId) => openBid(bidId)} />
      )}
      <EvaluationPanel view={view} />
      {call.bid_count === 0 && call.status === 'draft' && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <FileStack aria-hidden="true" className="size-4 shrink-0" />
          Next: check the evaluation template and the assessors, set a deadline, then open the call.
        </p>
      )}
      <BidSheet
        view={view}
        bidId={search?.assess ? undefined : search?.bid}
        onOpenChange={(open) => !open && openBid(undefined)}
        onAssess={(bidId, sectionId) => openBid(bidId, sectionId)}
      />
      <AssessmentSheet
        view={view}
        bidId={search?.assess ? search.bid : undefined}
        sectionId={search?.assess}
        onOpenChange={(open) => !open && openBid(undefined)}
        onSwitch={(bidId, sectionId) => openBid(bidId, sectionId)}
      />
    </div>
  )
}
