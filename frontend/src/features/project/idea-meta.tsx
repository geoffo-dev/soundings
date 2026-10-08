import { ListChecks, MessageSquare, ThumbsUp, TriangleAlert } from 'lucide-react'

import type { IdeaSummary, UserRef } from '@/api/types'
import { Avatar, type AvatarSize } from '@/components/ui/avatar'
import { ProgressTicks } from '@/components/ui/progress-ticks'
import { ScoreBadge } from '@/components/ui/score-badge'
import { HoverTooltip } from '@/components/ui/tooltip'
import { badgeLabel, badgeWords, showsResearchBadge } from '@/features/research/research-copy'
import { cn } from '@/lib/utils'

/** The owner's avatar, or a dashed circle for "no owner". */
export function OwnerAvatar({
  owner,
  size = 'sm',
  tooltip = false,
  className,
}: {
  owner: UserRef | null
  size?: AvatarSize
  tooltip?: boolean
  className?: string
}) {
  if (owner) {
    return (
      <Avatar
        name={owner.display_name}
        src={owner.avatar_url}
        size={size}
        tooltip={tooltip}
        className={className}
      />
    )
  }
  return (
    <span
      role="img"
      aria-label="No owner"
      className={cn(
        'inline-block shrink-0 rounded-full border border-dashed border-strong',
        size === 'xs' ? 'size-5' : 'size-6',
        className,
      )}
    />
  )
}

/** Aggregate score (or the blind-evaluation lock) plus the disagreement flag. */
export function IdeaScore({
  idea,
  className,
}: {
  idea: Pick<IdeaSummary, 'score' | 'score_hidden' | 'high_disagreement'>
  className?: string
}) {
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      {idea.high_disagreement && <DisagreementFlag />}
      <ScoreBadge size="sm" hidden={idea.score_hidden} score={idea.score?.overall ?? null} />
    </span>
  )
}

export function DisagreementFlag() {
  return (
    <HoverTooltip content="High disagreement: evaluators are 2+ points apart on a criterion">
      <span role="img" aria-label="High disagreement" className="inline-flex text-warning">
        <TriangleAlert aria-hidden="true" className="size-3.5" />
      </span>
    </HoverTooltip>
  )
}

/** "3/4" with ticks; nothing assigned yet reads "–". */
export function EvaluatorProgress({
  progress,
  showTicks = true,
  className,
}: {
  progress: IdeaSummary['evaluator_progress']
  showTicks?: boolean
  className?: string
}) {
  if (progress.total === 0) {
    return (
      <span
        role="img"
        aria-label="No evaluators yet"
        className={cn('text-sm text-muted', className)}
      >
        –
      </span>
    )
  }
  return (
    <ProgressTicks
      done={progress.submitted}
      total={progress.total}
      className={cn(!showTicks && '[&>span:first-child]:hidden', className)}
    />
  )
}

/** Comment and vote counts, shown only when there is something to count. */
export function EngagementCounts({
  idea,
  className,
}: {
  idea: Pick<IdeaSummary, 'comment_count' | 'vote_count' | 'has_voted'>
  className?: string
}) {
  if (idea.comment_count === 0 && idea.vote_count === 0) return null
  return (
    <span className={cn('inline-flex items-center gap-2.5 text-xs text-muted', className)}>
      {idea.comment_count > 0 && (
        <span
          role="img"
          aria-label={`${idea.comment_count} comment${idea.comment_count === 1 ? '' : 's'}`}
          className="inline-flex items-center gap-1 tabular-nums"
        >
          <MessageSquare aria-hidden="true" className="size-3.5" />
          <span aria-hidden="true">{idea.comment_count}</span>
        </span>
      )}
      {idea.vote_count > 0 && (
        <span
          role="img"
          aria-label={`${idea.vote_count} vote${idea.vote_count === 1 ? '' : 's'}${idea.has_voted ? ', including yours' : ''}`}
          className={cn(
            'inline-flex items-center gap-1 tabular-nums',
            idea.has_voted && 'text-accent',
          )}
        >
          <ThumbsUp aria-hidden="true" className="size-3.5" />
          <span aria-hidden="true">{idea.vote_count}</span>
        </span>
      )}
    </span>
  )
}

/**
 * Phase 8: the research checklist at a glance (contract-phase8 §3.13), "2 open" while
 * required items are left, "Ready" once none are: on ideas in Research, and in the
 * status before it once something is answered (`showsResearchBadge`). Quiet while
 * items are open; the accessible name has the whole sentence ("Research 1 of 3
 * answered, 2 required items open").
 */
export function ResearchProgressBadge({
  idea,
  className,
}: {
  idea: Pick<IdeaSummary, 'status' | 'research'>
  className?: string
}) {
  const research = idea.research
  if (!research || !showsResearchBadge(idea)) return null
  const complete = research.required_open === 0
  const label = badgeLabel(research)
  return (
    <HoverTooltip content={label}>
      <span
        role="img"
        aria-label={label}
        className={cn(
          'inline-flex h-5 items-center gap-1 rounded-sm px-1.5 text-xs font-medium tabular-nums',
          complete ? 'bg-success-subtle text-success' : 'bg-subtle text-secondary',
          className,
        )}
      >
        <ListChecks aria-hidden="true" className="size-3.5" />
        <span aria-hidden="true">{badgeWords(research)}</span>
      </span>
    </HoverTooltip>
  )
}
