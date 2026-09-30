import {
  ArrowRightLeft,
  CalendarClock,
  CircleCheck,
  CloudOff,
  Lock,
  LockOpen,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Sparkle,
  Trash2,
  UserMinus,
  UserPlus,
  UserRound,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
  useCreateComment,
  useDeleteComment,
  useIdeaActivity,
  useUpdateComment,
} from '@/api/activity'
import type { ActivityItem, CommentActivity } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { KbdShortcut } from '@/components/ui/kbd'
import { Markdown } from '@/components/ui/markdown'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { activityActor, describeActivity } from '@/lib/activity'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { useIdeaPage } from './idea-context'
import { MarkdownEditor } from './markdown-editor'

export const COMMENT_LIMIT = 10_000
export const COMMENT_INPUT_ID = 'idea-comment-input'

/**
 * Comments and events in one feed, oldest → newest with the composer at the
 * bottom (wireframe 03). Older activity loads on demand at the top.
 */
export function ActivitySection() {
  const { ideaKey, idea, archived } = useIdeaPage()
  const activity = useIdeaActivity(ideaKey)
  const items = activity.data?.items

  return (
    <section aria-labelledby="idea-activity-heading" className="flex flex-col gap-3">
      <h2 id="idea-activity-heading" className="text-sm font-medium text-muted">
        Activity
      </h2>
      {activity.isPending ? (
        <ActivitySkeleton />
      ) : activity.isError ? (
        <div role="alert" className="rounded-lg border">
          <EmptyState
            size="compact"
            icon={<CloudOff />}
            title="We couldn’t load the activity"
            description="Check your connection and try again."
            action={
              <Button size="sm" onClick={() => void activity.refetch()}>
                Try again
              </Button>
            }
          />
        </div>
      ) : (
        <>
          {activity.hasNextPage && (
            <Button
              variant="ghost"
              size="sm"
              className="self-start text-muted"
              loading={activity.isFetchingNextPage}
              onClick={() => void activity.fetchNextPage()}
            >
              Load older activity
            </Button>
          )}
          {items && items.length > 0 ? (
            <ol
              aria-label="Activity, oldest first"
              className={cn(
                'relative flex flex-col',
                // The timeline: a hairline behind the event icons.
                'before:absolute before:inset-y-3 before:left-3 before:w-px before:bg-subtle-hover',
              )}
            >
              {items.map((item) =>
                item.type === 'comment' && !item.comment.deleted ? (
                  <CommentItem key={item.id} item={item} />
                ) : (
                  <EventItem key={item.id} item={item} />
                ),
              )}
            </ol>
          ) : (
            <p className="text-sm text-muted">
              No comments yet. Ask a question or share a thought.
            </p>
          )}
        </>
      )}
      {idea.permissions.can_comment ? (
        <CommentComposer />
      ) : archived ? (
        <p className="text-sm text-muted">This project is archived, so comments are closed.</p>
      ) : null}
    </section>
  )
}

function ActivitySkeleton() {
  return (
    <SkeletonGroup label="Loading activity" className="flex flex-col gap-3">
      {[0, 1].map((i) => (
        <div key={i} className="flex items-center gap-2.5">
          <Skeleton className="size-6 rounded-full" />
          <Skeleton className="h-3.5 w-[min(20rem,70%)]" />
        </div>
      ))}
      <div className="flex flex-col gap-2 rounded-lg border p-3.5">
        <div className="flex items-center gap-2">
          <Skeleton className="size-6 rounded-full" />
          <Skeleton className="h-3.5 w-28" />
        </div>
        <Skeleton className="h-3.5 w-4/5" />
      </div>
    </SkeletonGroup>
  )
}

const EVENT_ICONS: Record<Exclude<ActivityItem['type'], 'comment'>, ReactNode> = {
  idea_created: <Sparkle />,
  idea_edited: <Pencil />,
  status_changed: <ArrowRightLeft />,
  owner_changed: <UserRound />,
  evaluator_added: <UserPlus />,
  evaluator_removed: <UserMinus />,
  evaluation_submitted: <CircleCheck />,
  evaluation_closed: <Lock />,
  evaluation_reopened: <LockOpen />,
  due_date_changed: <CalendarClock />,
}

/** One quiet line: icon, "Alice moved it from New to Evaluating", time. */
function EventItem({ item }: { item: ActivityItem }) {
  const { statusLabel } = useIdeaPage()
  const icon = item.type === 'comment' ? <MessageSquare /> : EVENT_ICONS[item.type]
  return (
    <li className="relative flex items-start gap-2.5 py-1.5 text-sm">
      <span
        aria-hidden="true"
        className="z-10 flex size-6 shrink-0 items-center justify-center rounded-full border bg-surface text-muted [&_svg]:size-3"
      >
        {icon}
      </span>
      <p className="min-w-0 pt-0.5 text-secondary">
        <span className="font-medium text-primary">{activityActor(item)}</span>{' '}
        {describeActivity(item, statusLabel)}
        <span aria-hidden="true" className="text-muted">
          {' '}
          ·{' '}
        </span>
        <RelativeTime date={item.created_at} className="text-muted" />
      </p>
    </li>
  )
}

function CommentItem({ item }: { item: CommentActivity }) {
  const { ideaKey } = useIdeaPage()
  const update = useUpdateComment(ideaKey)
  const remove = useDeleteComment(ideaKey)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const { comment } = item
  const pending = comment.id.startsWith('pending-')
  const author = item.actor?.display_name ?? 'Someone'
  const headingId = `comment-${comment.id}`

  const startEdit = () => {
    setDraft(comment.body_md)
    setEditing(true)
  }
  const stopEdit = () => {
    setEditing(false)
    // Back to where the edit started.
    requestAnimationFrame(() => menuTrigger.current?.focus())
  }
  const save = () => {
    const body = draft.trim()
    if (!body) return
    if (body === comment.body_md.trim()) {
      stopEdit()
      return
    }
    update.mutate({ commentId: comment.id, bodyMd: body }, { onSuccess: stopEdit })
  }

  return (
    <li className="relative py-2">
      <article
        aria-labelledby={headingId}
        aria-busy={pending || undefined}
        className={cn('rounded-lg border bg-surface', pending && 'opacity-70')}
      >
        <header className="flex min-h-10 items-center gap-2 pt-1.5 pr-1.5 pl-3 text-sm">
          <Avatar name={author} src={item.actor?.avatar_url} size="sm" decorative />
          <h3 id={headingId} className="min-w-0 truncate font-medium text-primary">
            {author}
          </h3>
          <span className="flex min-w-0 items-center gap-1 text-muted">
            <RelativeTime date={item.created_at} />
            {comment.edited_at && <span>· edited</span>}
            {pending && <span>· posting…</span>}
          </span>
          {(comment.can_edit || comment.can_delete) && !editing && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  ref={menuTrigger}
                  variant="ghost"
                  size="icon-sm"
                  className="ml-auto"
                  aria-label={`Comment actions for ${author}’s comment`}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {comment.can_edit && (
                  <DropdownMenuItem onSelect={startEdit}>
                    <Pencil /> Edit
                  </DropdownMenuItem>
                )}
                {comment.can_delete && (
                  <DropdownMenuItem variant="destructive" onSelect={() => remove(comment.id)}>
                    <Trash2 /> Delete
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </header>
        <div className="px-3 pt-1 pb-3">
          {editing ? (
            <MarkdownEditor
              label="Edit your comment"
              value={draft}
              onValueChange={setDraft}
              onSubmit={save}
              onCancel={stopEdit}
              maxLength={COMMENT_LIMIT}
              minRows={2}
              focusOnMount
              actions={
                <>
                  <Button size="sm" variant="ghost" onClick={stopEdit}>
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={save}
                    loading={update.isPending}
                    disabled={!draft.trim()}
                  >
                    Save
                  </Button>
                </>
              }
            />
          ) : (
            <Markdown>{comment.body_md}</Markdown>
          )}
        </div>
      </article>
    </li>
  )
}

function readDraft(key: string): string {
  try {
    return sessionStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function writeDraft(key: string, value: string) {
  try {
    if (value) sessionStorage.setItem(key, value)
    else sessionStorage.removeItem(key)
  } catch {
    // Storage unavailable: the draft just isn't kept across pages.
  }
}

/** Markdown comment box at the end of the feed. `c` focuses it; ⌘/Ctrl+Enter posts. */
function CommentComposer() {
  const { ideaKey, me, takeCommentFocus, commentFocusRequest } = useIdeaPage()
  const create = useCreateComment(ideaKey)
  const storageKey = `soundings-comment-draft:${ideaKey}`
  const [body, setBody] = useState(() => readDraft(storageKey))
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!takeCommentFocus()) return
    const input = inputRef.current
    if (!input) return
    input.focus()
    input.scrollIntoView({ block: 'nearest' })
  }, [commentFocusRequest, takeCommentFocus])

  const change = (value: string) => {
    setBody(value)
    writeDraft(storageKey, value)
  }
  const post = () => {
    const text = body.trim()
    if (!text || create.isPending) return
    change('')
    create.mutate(text, { onError: () => change(text) })
  }

  return (
    <div className="flex items-start gap-2.5 pt-2">
      <Avatar name={me.display_name} src={me.avatar_url} size="sm" decorative className="mt-2" />
      <MarkdownEditor
        id={COMMENT_INPUT_ID}
        textareaRef={inputRef}
        label="Write a comment"
        placeholder="Write a comment…"
        value={body}
        onValueChange={change}
        onSubmit={post}
        onCancel={() => inputRef.current?.blur()}
        maxLength={COMMENT_LIMIT}
        minRows={2}
        className="min-w-0 flex-1"
        hint={
          <span className="inline-flex items-center gap-1">
            Markdown supported · <KbdShortcut keys={SHORTCUTS.submitForm.keys} /> to post
          </span>
        }
        actions={
          <Button size="sm" onClick={post} disabled={!body.trim()}>
            Comment
          </Button>
        }
      />
    </div>
  )
}
