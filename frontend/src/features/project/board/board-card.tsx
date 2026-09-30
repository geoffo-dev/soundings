import { useDraggable } from '@dnd-kit/core'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'

import type { IdeaSummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { cn, mergeRefs } from '@/lib/utils'

import {
  EngagementCounts,
  EvaluatorProgress,
  IdeaScore,
  OwnerAvatar,
} from '@/features/project/idea-meta'
import { useBoardFocus } from './board-focus'

const MAX_TAGS = 3

export interface CardDragData {
  type: 'card'
  idea: IdeaSummary
}

/**
 * A board card. The whole card is a link (Enter opens the idea); when the
 * viewer may change its status it is also draggable — with the mouse, a long
 * press on touch screens, or Space and the arrow keys.
 */
export function BoardCard({ idea }: { idea: IdeaSummary }) {
  const draggable = idea.permissions.can_change_status
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: idea.id,
    data: { type: 'card', idea } satisfies CardDragData,
    disabled: !draggable,
  })
  const node = useRef<HTMLAnchorElement | null>(null)
  const focus = useBoardFocus()

  // After a keyboard move the card re-mounts in its new column: keep focus on it.
  useEffect(() => {
    if (focus.take(idea.id)) node.current?.focus({ preventScroll: false })
  }, [focus, idea.id])

  return (
    <Link
      ref={mergeRefs(node, setNodeRef)}
      to="/ideas/$ideaKey"
      params={{ ideaKey: idea.key }}
      draggable={false}
      data-card-id={idea.id}
      {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
      {...(draggable ? listeners : undefined)}
      aria-describedby={draggable ? attributes['aria-describedby'] : undefined}
      className={cn(
        'block rounded-lg outline-offset-2',
        draggable && 'cursor-grab touch-manipulation active:cursor-grabbing',
        isDragging && 'opacity-40',
      )}
    >
      <CardBody idea={idea} />
    </Link>
  )
}

/** The card's content; also rendered in the drag overlay. */
export function CardBody({ idea, lifted = false }: { idea: IdeaSummary; lifted?: boolean }) {
  const tags = idea.tags.slice(0, MAX_TAGS)
  const moreTags = idea.tags.length - tags.length
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border bg-surface p-3 transition-[border-color,box-shadow] duration-150 hover:border-strong',
        lifted && 'rotate-1 border-strong shadow-raised',
      )}
    >
      <div className="flex min-h-5 items-center justify-between gap-2">
        <span className="text-xs text-muted tabular-nums">{idea.key}</span>
        {/* Unscored ideas show nothing: a column of "–" badges is noise. */}
        {(idea.score_hidden || idea.score) && <IdeaScore idea={idea} />}
      </div>
      <p className="line-clamp-2 text-sm font-medium break-words text-primary">{idea.title}</p>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tags.map((tag) => (
            <Badge key={tag} className="max-w-full truncate">
              {tag}
            </Badge>
          ))}
          {moreTags > 0 && <Badge variant="outline">+{moreTags}</Badge>}
        </div>
      )}
      <div className="flex min-h-6 items-center gap-3 pt-0.5">
        <OwnerAvatar owner={idea.owner} size="xs" />
        {idea.evaluator_progress.total > 0 && (
          <EvaluatorProgress
            progress={idea.evaluator_progress}
            className="[&>span:last-child]:text-xs"
          />
        )}
        <EngagementCounts idea={idea} className="ml-auto" />
      </div>
    </div>
  )
}
