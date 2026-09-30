import { Eye, Link2, MoreHorizontal, ThumbsUp, Trash2 } from 'lucide-react'
import type { ReactNode } from 'react'

import { useUpdateIdea, useVoteIdea, useWatchIdea } from '@/api/ideas'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { RelativeTime } from '@/components/ui/relative-time'
import { WithTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

import { copyIdeaLink } from './idea-commands'
import { useIdeaPage } from './idea-context'
import { InlineText } from './inline-text'

const LIMITS = { title: 200, summary: 500 }

/**
 * Key and submitter, vote / watch / more; then the title and summary
 * (click to edit for people allowed to) with the page's one primary action.
 */
export function IdeaHeader({ primary }: { primary: ReactNode }) {
  const { idea, ideaKey } = useIdeaPage()
  const update = useUpdateIdea(ideaKey)
  const canEdit = idea.permissions.can_edit

  return (
    <header className="flex flex-col gap-2">
      <div className="flex min-h-8 min-w-0 items-center gap-2 text-sm text-muted">
        <span className="shrink-0 font-medium text-secondary tabular-nums">{idea.key}</span>
        {idea.submitted_by && (
          <span className="hidden min-w-0 truncate xs:inline">
            <span aria-hidden="true">· </span>
            Submitted by {idea.submitted_by.display_name}{' '}
            <RelativeTime date={idea.created_at} tooltip={false} />
          </span>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <VoteButton />
          <WatchButton />
          <MoreMenu />
        </div>
      </div>
      <div className="flex items-start gap-6">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <InlineText
            value={idea.title}
            canEdit={canEdit}
            label="Title"
            field="title"
            maxLength={LIMITS.title}
            requiredMessage="An idea needs a title."
            onSave={(title) => update.mutateAsync({ title })}
            editorClassName="text-2xl font-semibold sm:text-2xl"
          >
            <h1 className="py-0.5 text-2xl font-semibold [overflow-wrap:anywhere] text-primary">
              {idea.title}
            </h1>
          </InlineText>
          <InlineText
            value={idea.summary}
            canEdit={canEdit}
            label="Summary"
            field="summary"
            multiline
            maxLength={LIMITS.summary}
            requiredMessage="Keep a sentence or two: what it is and why it matters."
            onSave={(summary) => update.mutateAsync({ summary })}
            editorClassName="text-lg sm:text-lg"
          >
            <p className="py-0.5 text-lg [overflow-wrap:anywhere] text-secondary">{idea.summary}</p>
          </InlineText>
        </div>
        {primary && <div className="hidden shrink-0 pt-1 sm:block">{primary}</div>}
      </div>
    </header>
  )
}

function VoteButton() {
  const { idea, ideaKey } = useIdeaPage()
  const vote = useVoteIdea(ideaKey)
  const count = `${idea.vote_count} ${idea.vote_count === 1 ? 'vote' : 'votes'}`
  if (!idea.permissions.can_vote) {
    if (idea.vote_count === 0) return null
    return (
      <span role="img" aria-label={count} className="inline-flex h-7 items-center gap-1.5 px-2">
        <ThumbsUp aria-hidden="true" className="size-3.5" />
        <span aria-hidden="true" className="tabular-nums">
          {idea.vote_count}
        </span>
      </span>
    )
  }
  return (
    <WithTooltip content={idea.has_voted ? 'Remove your vote' : 'Vote for this idea'}>
      <Button
        variant="ghost"
        size="sm"
        aria-pressed={idea.has_voted}
        aria-label={`Vote, ${count}`}
        onClick={() => vote.mutate({ vote: !idea.has_voted })}
        className={cn(
          'tabular-nums',
          idea.has_voted && 'bg-accent-subtle text-accent hover:bg-accent-subtle hover:text-accent',
        )}
      >
        <ThumbsUp className={cn(idea.has_voted && 'fill-current')} />
        {idea.vote_count}
      </Button>
    </WithTooltip>
  )
}

function WatchButton() {
  const { idea, ideaKey } = useIdeaPage()
  const watch = useWatchIdea(ideaKey)
  return (
    <WithTooltip content={idea.watching ? 'Stop getting updates' : 'Get updates about this idea'}>
      <Button
        variant="ghost"
        size="sm"
        aria-pressed={idea.watching}
        onClick={() => watch.mutate({ watch: !idea.watching })}
        className={cn(
          idea.watching && 'bg-accent-subtle text-accent hover:bg-accent-subtle hover:text-accent',
        )}
      >
        <Eye />
        <span className="max-sm:sr-only">Watch</span>
      </Button>
    </WithTooltip>
  )
}

function MoreMenu() {
  const { idea, openDialog } = useIdeaPage()
  return (
    <DropdownMenu>
      <WithTooltip content="More actions">
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label="More actions">
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
      </WithTooltip>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => copyIdeaLink(idea.key)}>
          <Link2 /> Copy link
        </DropdownMenuItem>
        {idea.permissions.can_delete && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={() => openDialog('delete')}>
              <Trash2 /> Delete idea…
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
