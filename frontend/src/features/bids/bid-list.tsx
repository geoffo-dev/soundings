import { CloudOff, Inbox, Plus, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { useBids } from '@/api/bids'
import type { Bid, BidCallView } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useIdeaPage } from '@/features/idea/idea-context'
import { formatDate } from '@/lib/dates'
import { cn } from '@/lib/utils'

import { BID_STATUS, formatPrice, mustHaveSummary, progressText } from './bid-copy'
import { BidFormDialog } from './bid-form-dialog'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

/**
 * The call's bids, in the order received (rejected ones last for call managers; assessors
 * never see them). Each row opens the bid. Prices show only to those who may see them;
 * a flagged must-have says so in words and with an icon.
 */
export function BidList({ view, onOpen }: { view: CallWithView; onOpen: (bidId: string) => void }) {
  const { ideaKey } = useIdeaPage()
  const bids = useBids(ideaKey)
  const [entering, setEntering] = useState(false)
  const { call, permissions } = view
  const canEnter = permissions.can_manage_call && call.status === 'open'
  const manager = permissions.can_view_scores

  const items = bids.data
    ? [...bids.data.items].sort(
        (a, b) => Number(a.status === 'rejected') - Number(b.status === 'rejected'),
      )
    : []

  return (
    <section aria-labelledby="bids-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="bids-heading" className="text-lg font-semibold text-primary">
          Bids
        </h2>
        {canEnter && (
          <Button size="sm" variant="outline" onClick={() => setEntering(true)}>
            <Plus /> Enter a bid
          </Button>
        )}
      </div>
      {bids.isPending ? (
        <SkeletonGroup
          label="Loading bids"
          className="flex flex-col divide-y divide-subtle rounded-lg border"
        >
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-3">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="ml-auto h-4 w-20" />
            </div>
          ))}
        </SkeletonGroup>
      ) : bids.isError ? (
        <EmptyState
          role="alert"
          size="inline"
          icon={<CloudOff />}
          title="We couldn’t load the bids"
          action={
            <Button size="sm" onClick={() => void bids.refetch()}>
              Try again
            </Button>
          }
          className="rounded-lg border"
        />
      ) : items.length === 0 ? (
        <EmptyState
          size="inline"
          icon={<Inbox />}
          title="No bids yet"
          description={
            call.status === 'draft'
              ? 'Bids are entered once the call is open.'
              : canEnter
                ? 'Enter each bid as it comes in, then upload its documents.'
                : 'Bids appear here as the team enters them.'
          }
          className="rounded-lg border"
        />
      ) : (
        <div className="rounded-lg border">
          <Table mobile="container-cards" aria-label="Bids" className="@3xl:table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="@3xl:w-[34%]">Bidder</TableHead>
                <TableHead>Received</TableHead>
                {permissions.can_see_prices && <TableHead className="text-right">Price</TableHead>}
                <TableHead>Must-haves</TableHead>
                <TableHead>{manager ? 'Assessed' : 'Your sections'}</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((bid) => (
                <BidRow
                  key={bid.id}
                  bid={bid}
                  currency={call.currency}
                  showPrice={permissions.can_see_prices}
                  manager={manager}
                  onOpen={() => onOpen(bid.id)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {permissions.can_view_bids && !permissions.can_see_prices && items.length > 0 && (
        <p className="text-sm text-muted">
          Prices and pricing documents are only for the call’s managers and the assessors of the
          section with the price.
        </p>
      )}
      <BidFormDialog
        ideaKey={ideaKey}
        call={call}
        open={entering}
        onOpenChange={setEntering}
        onCreated={(bid) => onOpen(bid.id)}
      />
    </section>
  )
}

function BidRow({
  bid,
  currency,
  showPrice,
  manager,
  onOpen,
}: {
  bid: Bid
  currency: string
  showPrice: boolean
  manager: boolean
  onOpen: () => void
}) {
  const status = BID_STATUS[bid.status]
  const musts = mustHaveSummary(bid.must_haves)
  const rejected = bid.status === 'rejected'
  const mine = bid.my_sections
  const ownDone = mine.filter((s) => s.state === 'submitted').length
  return (
    <TableRow className={cn(rejected && 'text-muted')}>
      <TableCell primary>
        <button
          type="button"
          onClick={onOpen}
          className="text-left font-medium text-primary underline-offset-4 hover:underline focus-visible:underline"
        >
          {bid.bidder}
        </button>
      </TableCell>
      <TableCell label="Received">
        <span className="inline-flex items-center gap-1.5 text-sm text-secondary">
          {formatDate(bid.received_at)}
          {bid.late && <Badge variant="warning">Late</Badge>}
        </span>
      </TableCell>
      {showPrice && (
        <TableCell label="Price" className="text-right tabular-nums @max-3xl:text-left">
          {formatPrice(bid.price, currency)}
        </TableCell>
      )}
      <TableCell label="Must-haves">
        <span
          className={cn(
            'inline-flex items-center gap-1.5 text-sm',
            musts.flagged && !rejected ? 'font-medium text-danger' : 'text-secondary',
          )}
        >
          {musts.flagged && !rejected && <TriangleAlert aria-hidden="true" className="size-3.5" />}
          {musts.text}
        </span>
      </TableCell>
      <TableCell label={manager ? 'Assessed' : 'Your sections'}>
        <span className="text-sm text-secondary tabular-nums">
          {rejected
            ? '—'
            : manager
              ? progressText(bid.progress)
              : mine.length === 0
                ? '—'
                : `${ownDone} of ${mine.length} submitted`}
        </span>
      </TableCell>
      <TableCell label="Status">
        <Badge variant={status.tone}>{status.label}</Badge>
      </TableCell>
    </TableRow>
  )
}
