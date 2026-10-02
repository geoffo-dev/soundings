import { Check, ChevronRight, CloudOff, MessageSquarePlus, RotateCcw, Trash2 } from 'lucide-react'
import { useId, useState } from 'react'

import {
  useCreateProposalThread,
  useDeleteProposalComment,
  useReplyToProposalThread,
  useSetProposalThreadResolved,
} from '@/api/proposals'
import type {
  ProposalComment,
  ProposalSection,
  ProposalSectionKey,
  ProposalThread,
} from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/ui/markdown'
import { RelativeTime } from '@/components/ui/relative-time'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { MarkdownEditor } from '@/features/idea/markdown-editor'
import { byId, focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { useProposalEditor } from './editor-context'
import { markdownExcerpt, PROPOSAL_COMMENT_LIMIT } from './text'

type Variant = 'margin' | 'sheet'

/**
 * DOM ids for focus to follow actions (WCAG 2.4.3): a posted thread, a resolved
 * thread's line, the margin's "Comment" button. Per variant: the margin stays in
 * the DOM (hidden below `lg`) while the sheet shows the same threads.
 */
const threadDomId = (variant: Variant, threadId: string) => `proposal-thread-${variant}-${threadId}`
const resolvedToggleId = (variant: Variant, threadId: string) =>
  `${threadDomId(variant, threadId)}-toggle`
const commentButtonId = (sectionKey: ProposalSectionKey) => `proposal-comment-${sectionKey}`
/** The open thread's card (not the copy inside a resolved thread's line, about to move). */
const openThreadCard = (variant: Variant, threadId: string) => () => {
  const card = document.getElementById(threadDomId(variant, threadId))
  return card?.closest('[data-resolved-thread]') ? null : card
}

/**
 * A section's margin threads: open ones first, resolved ones collapsed to a
 * line, and "Comment on this section" for members and admins. Comments are
 * plain Markdown (no @mentions in Phase 4: margin comments notify nobody).
 */
export function SectionThreads({
  sectionKey,
  sectionTitle,
  threads,
  variant,
}: {
  sectionKey: ProposalSectionKey
  sectionTitle: string
  threads: ProposalThread[] | undefined
  variant: Variant
}) {
  const {
    permissions,
    composingIn,
    setComposingIn,
    threads: loaded,
    threadsError,
    retryThreads,
  } = useProposalEditor()
  const composing = variant === 'sheet' || composingIn === sectionKey

  if (threadsError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-2 text-sm text-muted">
        <span className="flex items-center gap-1.5">
          <CloudOff aria-hidden="true" className="size-4" />
          Comments didn’t load.
        </span>
        <Button size="sm" variant="outline" onClick={retryThreads}>
          Try again
        </Button>
      </div>
    )
  }
  if (!loaded && variant === 'margin') {
    return <Skeleton className="h-16 w-full rounded-lg" />
  }

  const open = (threads ?? []).filter((thread) => !thread.resolved_at)
  const resolved = (threads ?? []).filter((thread) => thread.resolved_at)

  return (
    <div className="flex flex-col gap-3">
      {permissions.can_comment &&
        (composing ? (
          <NewThread
            sectionKey={sectionKey}
            sectionTitle={sectionTitle}
            variant={variant}
            onDone={variant === 'margin' ? () => setComposingIn(null) : undefined}
            focusOnMount={variant === 'margin'}
          />
        ) : (
          <Button
            id={commentButtonId(sectionKey)}
            variant="ghost"
            size="sm"
            className="self-start text-muted"
            onClick={() => setComposingIn(sectionKey)}
          >
            <MessageSquarePlus aria-hidden="true" />
            Comment
            <span className="sr-only"> on {sectionTitle}</span>
          </Button>
        ))}
      {open.map((thread) => (
        <ThreadCard key={thread.id} thread={thread} variant={variant} sectionTitle={sectionTitle} />
      ))}
      {resolved.map((thread) => (
        <ResolvedThread
          key={thread.id}
          thread={thread}
          variant={variant}
          sectionTitle={sectionTitle}
        />
      ))}
      {variant === 'sheet' && open.length === 0 && resolved.length === 0 && (
        <p className="text-sm text-muted">
          No comments on this section yet.
          {permissions.can_comment ? ' Ask a question or suggest a change.' : ''}
        </p>
      )}
    </div>
  )
}

function NewThread({
  sectionKey,
  sectionTitle,
  variant,
  onDone,
  focusOnMount,
}: {
  sectionKey: ProposalSectionKey
  sectionTitle: string
  variant: Variant
  onDone?: () => void
  focusOnMount: boolean
}) {
  const { ideaKey } = useProposalEditor()
  const create = useCreateProposalThread(ideaKey)
  const [body, setBody] = useState('')
  const post = () => {
    const text = body.trim()
    if (!text || create.isPending) return
    create.mutate(
      { sectionKey, bodyMd: text },
      {
        onSuccess: (thread) => {
          setBody('')
          if (!onDone) return
          // The margin composer closes: focus goes to the thread just posted.
          onDone()
          focusWhenRendered(byId(threadDomId(variant, thread.id)))
        },
      },
    )
  }
  const cancel = onDone
    ? () => {
        onDone()
        focusWhenRendered(byId(commentButtonId(sectionKey)))
      }
    : undefined
  return (
    <MarkdownEditor
      label={`Comment on ${sectionTitle}`}
      placeholder="Ask a question or suggest a change…"
      value={body}
      onValueChange={setBody}
      onSubmit={post}
      onCancel={cancel}
      maxLength={PROPOSAL_COMMENT_LIMIT}
      minRows={2}
      focusOnMount={focusOnMount}
      actions={
        <>
          {cancel && (
            <Button size="sm" variant="ghost" onClick={cancel}>
              Cancel
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            onClick={post}
            loading={create.isPending}
            disabled={!body.trim()}
            aria-keyshortcuts="Control+Enter Meta+Enter"
          >
            Comment
          </Button>
        </>
      }
    />
  )
}

function ThreadCard({
  thread,
  variant,
  sectionTitle,
}: {
  thread: ProposalThread
  variant: Variant
  sectionTitle: string
}) {
  const { ideaKey, permissions } = useProposalEditor()
  const setResolved = useSetProposalThreadResolved(ideaKey)
  const [replying, setReplying] = useState(false)
  const headingId = useId()
  const first = thread.comments.find((comment) => !comment.deleted) ?? thread.comments[0]
  const starter = first?.author?.display_name ?? 'Someone'
  const resolved = Boolean(thread.resolved_at)
  const id = threadDomId(variant, thread.id)
  const replyButtonId = `${id}-reply`

  const toggleResolved = () => {
    setResolved.mutate({ threadId: thread.id, resolved: !resolved })
    // Resolved: the thread collapses to its line; reopened: it is a card among the open ones.
    focusWhenRendered(
      resolved ? openThreadCard(variant, thread.id) : byId(resolvedToggleId(variant, thread.id)),
    )
  }

  return (
    <article
      id={id}
      tabIndex={-1}
      aria-labelledby={headingId}
      className="flex scroll-mt-16 flex-col rounded-lg border bg-surface text-sm"
    >
      <h3 id={headingId} className="sr-only">
        {resolved ? 'Resolved thread' : 'Thread'} by {starter} on {sectionTitle}
      </h3>
      {resolved && thread.resolved_by && (
        <p className="flex items-center gap-1.5 border-b border-subtle px-3 py-1.5 text-xs text-muted">
          <Check aria-hidden="true" className="size-3.5 text-success" />
          Resolved by {thread.resolved_by.display_name}
          {thread.resolved_at && (
            <>
              {' '}
              <RelativeTime date={thread.resolved_at} />
            </>
          )}
        </p>
      )}
      <ol className="flex flex-col divide-y divide-subtle">
        {thread.comments.map((comment) => (
          <CommentItem key={comment.id} comment={comment} threadId={thread.id} variant={variant} />
        ))}
      </ol>
      {permissions.can_comment && (
        <div className="border-t border-subtle p-2">
          {replying ? (
            <Reply
              threadId={thread.id}
              starter={starter}
              onPosted={() => {
                setReplying(false)
                // A reply reopens a resolved thread, so the card may move: follow it.
                focusWhenRendered(openThreadCard(variant, thread.id))
              }}
              onCancel={() => {
                setReplying(false)
                focusWhenRendered(byId(replyButtonId))
              }}
            />
          ) : (
            <div className="flex items-center gap-1">
              <Button
                id={replyButtonId}
                size="sm"
                variant="ghost"
                onClick={() => setReplying(true)}
              >
                Reply
              </Button>
              <Button size="sm" variant="ghost" className="ml-auto" onClick={toggleResolved}>
                {resolved ? <RotateCcw aria-hidden="true" /> : <Check aria-hidden="true" />}
                {resolved ? 'Reopen' : 'Resolve'}
              </Button>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

/** Resolved threads collapse to one line; open it to read, reply or reopen. */
function ResolvedThread({
  thread,
  variant,
  sectionTitle,
}: {
  thread: ProposalThread
  variant: Variant
  sectionTitle: string
}) {
  const [expanded, setExpanded] = useState(false)
  const contentId = useId()
  const first = thread.comments.find((comment) => !comment.deleted)
  const count = thread.comments.filter((comment) => !comment.deleted).length
  return (
    <div data-resolved-thread="" className="flex flex-col gap-2">
      <button
        id={resolvedToggleId(variant, thread.id)}
        type="button"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={() => setExpanded((value) => !value)}
        className="flex min-w-0 items-center gap-1.5 rounded-md px-1 py-1 text-left text-xs text-muted hover:bg-subtle hover:text-primary"
      >
        <ChevronRight
          aria-hidden="true"
          className={cn('size-3.5 shrink-0 transition-transform', expanded && 'rotate-90')}
        />
        <Check aria-hidden="true" className="size-3.5 shrink-0 text-success" />
        <span className="min-w-0 truncate">
          Resolved · {first?.author?.display_name ?? 'Someone'}:{' '}
          {markdownExcerpt(first?.body_md ?? '')}
        </span>
        <span className="ml-auto shrink-0 tabular-nums">
          {count}
          <span className="sr-only"> {count === 1 ? 'comment' : 'comments'}</span>
        </span>
      </button>
      {expanded && (
        <div id={contentId}>
          <ThreadCard thread={thread} variant={variant} sectionTitle={sectionTitle} />
        </div>
      )}
    </div>
  )
}

function CommentItem({
  comment,
  threadId,
  variant,
}: {
  comment: ProposalComment
  threadId: string
  variant: Variant
}) {
  const { ideaKey, me } = useProposalEditor()
  const remove = useDeleteProposalComment(ideaKey)
  const [confirming, setConfirming] = useState(false)
  const author = comment.author?.display_name ?? 'Someone'
  const pending = comment.id.startsWith('pending-')

  if (comment.deleted) {
    return <li className="px-3 py-2 text-xs text-muted italic">Comment deleted</li>
  }
  return (
    <li
      className={cn('flex flex-col gap-1 px-3 py-2.5', pending && 'opacity-70')}
      aria-busy={pending || undefined}
    >
      <div className="flex min-h-6 items-center gap-2">
        <Avatar name={author} src={comment.author?.avatar_url} size="xs" decorative />
        <span className="min-w-0 truncate font-medium text-primary">
          {comment.author?.id === me.id ? `${author} (you)` : author}
        </span>
        <RelativeTime date={comment.created_at} className="shrink-0 text-xs text-muted" />
        {comment.can_delete && !confirming && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="-mr-1 ml-auto text-muted"
            aria-label={`Delete ${author}’s comment`}
            // In a sheet the Undo toast can't be reached (the sheet is modal): confirm there.
            onClick={() =>
              variant === 'sheet' ? setConfirming(true) : remove(threadId, comment.id)
            }
          >
            <Trash2 />
          </Button>
        )}
      </div>
      <Markdown className="text-sm">{comment.body_md}</Markdown>
      {confirming && (
        <div
          role="group"
          aria-label="Delete this comment?"
          className="flex items-center gap-2 pt-1"
        >
          <span className="text-xs text-secondary">Delete this comment?</span>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => setConfirming(false)}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              setConfirming(false)
              remove(threadId, comment.id)
            }}
          >
            Delete
          </Button>
        </div>
      )}
    </li>
  )
}

function Reply({
  threadId,
  starter,
  onPosted,
  onCancel,
}: {
  threadId: string
  starter: string
  onPosted: () => void
  onCancel: () => void
}) {
  const { ideaKey } = useProposalEditor()
  const reply = useReplyToProposalThread(ideaKey)
  const [body, setBody] = useState('')
  const post = () => {
    const text = body.trim()
    if (!text) return
    onPosted()
    reply.mutate({ threadId, bodyMd: text })
  }
  return (
    <MarkdownEditor
      label={`Reply to ${starter}’s thread`}
      placeholder="Reply…"
      value={body}
      onValueChange={setBody}
      onSubmit={post}
      onCancel={onCancel}
      maxLength={PROPOSAL_COMMENT_LIMIT}
      minRows={2}
      focusOnMount
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button size="sm" variant="secondary" onClick={post} disabled={!body.trim()}>
            Reply
          </Button>
        </>
      }
    />
  )
}

/** Phones and tablets: one section's comments in a sheet ("Comments" by each section). */
export function CommentsSheet({ sections }: { sections: readonly ProposalSection[] }) {
  const { sheetFor, setSheetFor, threads } = useProposalEditor()
  const section = sections.find((s) => s.key === sheetFor)
  return (
    <Sheet open={Boolean(sheetFor)} onOpenChange={(open) => !open && setSheetFor(null)}>
      <SheetContent size="md">
        <SheetHeader>
          <SheetTitle>Comments on {section?.title ?? 'this section'}</SheetTitle>
          <SheetDescription>
            Questions and suggestions about this part of the proposal.
          </SheetDescription>
        </SheetHeader>
        <SheetBody>
          {section && (
            <SectionThreads
              sectionKey={section.key}
              sectionTitle={section.title}
              threads={threads?.get(section.key)}
              variant="sheet"
            />
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}
