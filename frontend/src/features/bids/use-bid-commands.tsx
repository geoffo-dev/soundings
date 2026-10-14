import { Download, FileSpreadsheet, Gavel, PencilLine } from 'lucide-react'

import { useBids, useExportBidReport } from '@/api/bids'
import { describeError } from '@/api/errors'
import type { BidCallView } from '@/api/types'
import type { CommandAction } from '@/components/ui/command-palette'
import { toast } from '@/components/ui/toaster'
import { useIdeaPage } from '@/features/idea/idea-context'
import { useCommands } from '@/lib/command-registry'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

/**
 * ⌘K actions while the Bids tab shows a call: open any bid, continue your next
 * assessment, export the evaluation report. Only what `permissions` allow.
 */
export function useBidCommands(view: CallWithView): void {
  const { idea, ideaKey, setSearch } = useIdeaPage()
  const bids = useBids(ideaKey, { enabled: view.permissions.can_view_bids })
  const report = useExportBidReport(ideaKey)
  const { call, permissions } = view
  const items = bids.data?.items ?? []
  const actions: CommandAction[] = []

  const next = items
    .filter((bid) => bid.status !== 'rejected')
    .flatMap((bid) => bid.my_sections.map((section) => ({ bid, section })))
    .find((row) => row.section.state !== 'submitted')
  if (permissions.can_assess && next) {
    actions.push({
      id: 'bids-next-assessment',
      label: `Assess ${next.bid.bidder}: ${next.section.section.title}`,
      icon: <PencilLine />,
      keywords: ['assess', 'bid', 'score', 'next'],
      onSelect: () =>
        setSearch?.({ tab: 'bids', bid: next.bid.id, assess: next.section.section.id }),
    })
  }
  for (const bid of items) {
    actions.push({
      id: `bid-${bid.id}`,
      label: `Open the bid from ${bid.bidder}`,
      icon: <Gavel />,
      hint: call.title,
      keywords: ['bid', 'bidder', bid.bidder],
      onSelect: () => setSearch?.({ tab: 'bids', bid: bid.id }),
    })
  }
  if (permissions.can_view_scores && call.bid_count > 0) {
    for (const format of ['pdf', 'markdown'] as const) {
      actions.push({
        id: `bid-report-${format}`,
        label: `Export the report (${format === 'pdf' ? 'PDF' : 'Markdown'})`,
        hint: call.title,
        icon: format === 'pdf' ? <Download /> : <FileSpreadsheet />,
        keywords: ['report', 'export', 'bids', 'comparison'],
        onSelect: () =>
          report.mutate(format, {
            onError: (error) => {
              const { title, description } = describeError(error)
              toast.error(title, { description })
            },
          }),
      })
    }
  }

  useCommands(
    actions.length > 0 ? { id: 'bid-call', heading: `${idea.key} bids`, actions, order: 1 } : null,
  )
}
