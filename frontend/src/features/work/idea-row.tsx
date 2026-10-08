import { Link } from '@tanstack/react-router'
import { TriangleAlert } from 'lucide-react'

import type { IdeaSummary } from '@/api/types'
import { ProgressTicks } from '@/components/ui/progress-ticks'
import { RelativeTime } from '@/components/ui/relative-time'
import { ScoreBadge } from '@/components/ui/score-badge'
import { StatusDot } from '@/components/ui/status-badge'
import { HoverTooltip } from '@/components/ui/tooltip'
import { ResearchProgressBadge } from '@/features/project/idea-meta'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { statusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

/** Row classes shared by My work lists: 44px rows, hover fill, inset focus ring. */
export const rowLink = cn(
  'group flex min-h-11 items-center gap-3 px-4 py-2 transition-colors duration-100',
  'hover:bg-subtle focus-visible:bg-subtle focus-visible:-outline-offset-2',
)

/** A compact idea row (My work "Ideas I own"): key, title, progress, score, updated. */
export function IdeaRow({ idea, showStatus = false }: { idea: IdeaSummary; showStatus?: boolean }) {
  return (
    <li>
      <Link
        to="/ideas/$ideaKey"
        params={{ ideaKey: idea.key }}
        className={rowLink}
        {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
      >
        {showStatus && <StatusDot tone={statusTone(idea.status, idea.resolution)} />}
        {/* Keys never wrap ("TOOLS-10"): the column grows to fit them. */}
        <span className="min-w-16 shrink-0 text-xs whitespace-nowrap text-muted tabular-nums max-sm:hidden">
          {idea.key}
        </span>
        <span className="line-clamp-2 min-w-0 flex-1 text-sm font-medium text-primary sm:truncate">
          <span className="mr-2 text-xs font-normal whitespace-nowrap text-muted tabular-nums sm:hidden">
            {idea.key}
          </span>
          {idea.title}
        </span>
        {showStatus && (
          <span className="shrink-0 text-sm text-muted max-sm:hidden">{idea.status_label}</span>
        )}
        <span className="flex shrink-0 items-center gap-3 sm:gap-4">
          {/* Phase 8: the research checklist, while the idea is in Research or right before it. */}
          <ResearchProgressBadge research={idea.research} />
          {idea.evaluator_progress.total > 0 && (
            <ProgressTicks
              done={idea.evaluator_progress.submitted}
              total={idea.evaluator_progress.total}
              className="max-sm:[&>span:first-child]:hidden"
            />
          )}
          {idea.high_disagreement && (
            <HoverTooltip content="Evaluators disagree on at least one criterion">
              <span role="img" aria-label="High disagreement" className="inline-flex text-warning">
                <TriangleAlert aria-hidden="true" className="size-3.5" />
              </span>
            </HoverTooltip>
          )}
          <ScoreBadge size="sm" hidden={idea.score_hidden} score={idea.score?.overall ?? null} />
          <RelativeTime
            date={idea.last_activity_at}
            style="narrow"
            className="w-16 text-right text-xs text-muted max-md:hidden"
          />
        </span>
      </Link>
    </li>
  )
}
