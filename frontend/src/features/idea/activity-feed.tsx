import {
  ArrowRightLeft,
  CalendarClock,
  CircleCheck,
  CloudOff,
  Eye,
  Lock,
  LockOpen,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Sparkle,
  Sparkles,
  Trash2,
  UserMinus,
  UserPlus,
  UserRound,
  UserSearch,
} from 'lucide-react'
import { useLocation } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import {
  useCreateComment,
  useDeleteComment,
  useIdeaActivity,
  useUpdateComment,
} from '@/api/activity'
import { useIdeaAiRuns } from '@/api/ai'
import { useIdeaSubmission } from '@/api/submissions'
import { ResearchNoteItem } from '@/features/ai/research-note'
import { useAssignment } from '@/features/research/research-assignment'
import type { ActivityItem, CommentActivity, IdeaDetail } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
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
import { activityActor, describeEntry, groupActivity, type ActivityEntry } from '@/lib/activity'
import { draftKey } from '@/lib/drafts'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { useIdeaPage } from './idea-context'
import type { MentionOptions, MentionPerson } from './mention-picker'
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
  const highlighted = useLinkedComment(items)

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
              {groupActivity(items).map((entry) =>
                entry.item.type === 'comment' && !entry.item.comment.deleted ? (
                  <CommentItem
                    key={entry.item.id}
                    item={entry.item}
                    highlighted={entry.item.comment.id === highlighted}
                  />
                ) : entry.item.type === 'ai_research_note' && !entry.item.note.deleted ? (
                  <ResearchNoteItem key={entry.item.id} item={entry.item} ideaKey={ideaKey} />
                ) : (
                  <EventItem key={entry.item.id} entry={entry} />
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

/**
 * `#comment-<id>` (links from notifications and emails): once the comment has
 * loaded, scroll to it, focus it and highlight it for a few seconds.
 */
function useLinkedComment(items: ActivityItem[] | undefined): string | null {
  const hash = useLocation({ select: (location) => location.hash })
  const commentId = hash.startsWith('comment-') ? hash.slice('comment-'.length) : null
  const [highlighted, setHighlighted] = useState<string | null>(null)
  const handled = useRef<string | null>(null)
  const loaded = Boolean(
    commentId && items?.some((item) => item.type === 'comment' && item.comment.id === commentId),
  )
  useEffect(() => {
    if (!commentId || !loaded || handled.current === commentId) return
    handled.current = commentId
    setHighlighted(commentId)
    const timer = window.setTimeout(() => setHighlighted(null), 4000)
    requestAnimationFrame(() => {
      const article = document.querySelector<HTMLElement>(
        `[data-comment-id="${CSS.escape(commentId)}"]`,
      )
      article?.scrollIntoView({ block: 'center' })
      article?.focus({ preventScroll: true })
    })
    return () => window.clearTimeout(timer)
  }, [commentId, loaded])
  return highlighted
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

/**
 * Who "@" offers (contract-phase8b §6.4): the project's people plus the idea's
 * researcher (who may have no role there), labelled "researcher". A guest researcher,
 * who can't read the project's people, gets only the people on this page: the owner
 * and whoever acted in the feed (who asked them, who commented). Mentioning anyone
 * else would notify nobody (UX review M2).
 */
export function mentionOptions(
  idea: IdeaDetail,
  meId: string,
  items: readonly ActivityItem[] | undefined,
): MentionOptions {
  if (!idea.permissions.can_view_project) {
    const people = new Map<string, MentionPerson>()
    if (idea.owner) people.set(idea.owner.id, { ...idea.owner, note: 'owner' })
    for (const item of items ?? []) {
      // An AI research note's actor is an agent: never someone to mention.
      if (!item.actor || item.type === 'ai_research_note' || people.has(item.actor.id)) continue
      people.set(item.actor.id, item.actor)
    }
    return {
      excludeUserId: meId,
      only: [...people.values()].sort((a, b) => a.display_name.localeCompare(b.display_name)),
    }
  }
  return {
    project: idea.project.slug,
    excludeUserId: meId,
    extra: idea.researcher ? [{ ...idea.researcher, note: 'researcher' }] : [],
  }
}

/** mentionOptions for this page (the feed's people come from its cached query). */
function useMentionOptions(): MentionOptions {
  const { ideaKey, idea, me } = useIdeaPage()
  const items = useIdeaActivity(ideaKey).data?.items
  return mentionOptions(idea, me.id, items)
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
  ai_research_note: <Sparkles />,
  researcher_changed: <UserSearch />,
  research_due_date_changed: <CalendarClock />,
}

/**
 * The idea's AI agents by service-account id (its AI evaluators and the agents
 * of its runs, from data the page already has): their lines in the feed carry
 * the AI badge too (contract-phase6 §1 "AI text is untrusted": labelled
 * wherever its work appears).
 */
function useIdeaAgents(ideaKey: string, idea: IdeaDetail): Map<string, string> {
  // A guest researcher can't read the AI runs (404): only an idea's people ask.
  const runs = useIdeaAiRuns(ideaKey, { enabled: idea.permissions.can_view_project }).data
  const agents = new Map<string, string>()
  for (const evaluator of idea.evaluators) {
    if (evaluator.is_ai) agents.set(evaluator.user.id, evaluator.user.display_name)
  }
  for (const agent of [...(runs?.agents ?? []), ...(runs?.items.map((run) => run.agent) ?? [])]) {
    agents.set(agent.user_id, agent.display_name)
  }
  return agents
}

/** The line's text with the AI badge after each agent it names ("invited Idea evaluator [AI] to evaluate"). */
function WithAgentBadges({ text, names }: { text: string; names: readonly string[] }) {
  const parts: ReactNode[] = []
  let rest = text
  for (;;) {
    let at = -1
    let name = ''
    for (const candidate of names) {
      const index = candidate ? rest.indexOf(candidate) : -1
      if (index !== -1 && (at === -1 || index < at)) {
        at = index
        name = candidate
      }
    }
    if (at === -1) break
    // Spaces around the badge, not margins: read aloud, it is a word of its own.
    parts.push(rest.slice(0, at + name.length), ' ', <AiBadge key={parts.length} />)
    rest = rest.slice(at + name.length)
  }
  parts.push(rest)
  return <>{parts}</>
}

/** One quiet line: icon, "Alice moved it from New to Evaluating", time. */
function EventItem({ entry }: { entry: ActivityEntry }) {
  const { statusLabel, idea, ideaKey } = useIdeaPage()
  const agents = useIdeaAgents(ideaKey, idea)
  const { item } = entry
  // A public idea's "sent it through the public form" names its sender, like the header.
  const submitter = useIdeaSubmission(ideaKey, {
    enabled:
      idea.via_public_form &&
      item.type === 'idea_created' &&
      !item.actor &&
      idea.permissions.can_view_project,
  }).data?.name
  const icon = item.type === 'comment' ? <MessageSquare /> : EVENT_ICONS[item.type]
  const evaluator =
    item.type === 'evaluator_added' || item.type === 'evaluator_removed' ? item.evaluator : null
  // The line's subject is an agent: it acted, or (no actor) its run took it off.
  const actorIsAgent = item.actor
    ? agents.has(item.actor.id)
    : item.type === 'evaluator_removed' && Boolean(evaluator && agents.has(evaluator.id))
  // Agents the line names after the verb (invited, removed), when someone else acted.
  const namedAgents = item.actor
    ? entry.invited
      ? entry.invited.filter((name) => [...agents.values()].includes(name))
      : evaluator && agents.has(evaluator.id)
        ? [evaluator.display_name]
        : []
    : []
  return (
    <li className="relative flex items-start gap-2.5 py-1.5 text-sm">
      <span
        aria-hidden="true"
        className="z-10 flex size-6 shrink-0 items-center justify-center rounded-full border bg-surface text-muted [&_svg]:size-3"
      >
        {icon}
      </span>
      <p className="min-w-0 pt-0.5 text-secondary">
        <span className="font-medium text-primary">{activityActor(item, submitter)}</span>{' '}
        {actorIsAgent && (
          <>
            <AiBadge />{' '}
          </>
        )}
        <WithAgentBadges text={describeEntry(entry, statusLabel)} names={namedAgents} />
        <span aria-hidden="true" className="text-muted">
          {' '}
          ·{' '}
        </span>
        <RelativeTime date={item.created_at} className="text-muted" />
      </p>
    </li>
  )
}

function CommentItem({ item, highlighted }: { item: CommentActivity; highlighted: boolean }) {
  const { ideaKey, me } = useIdeaPage()
  const mentions = useMentionOptions()
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
        data-comment-id={comment.id}
        tabIndex={highlighted ? -1 : undefined}
        className={cn(
          'scroll-mt-20 rounded-lg border bg-surface transition-[border-color,box-shadow] duration-500 focus:outline-none',
          pending && 'opacity-70',
          highlighted && 'border-accent ring-3 ring-focus/20',
        )}
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
              mentions={mentions}
              mentionSelfId={me.id}
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
            <Markdown mentionSelfId={me.id}>{comment.body_md}</Markdown>
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
  const mentions = useMentionOptions()
  const guestReader = useGuestReader()
  const guestNoteId = useId()
  const create = useCreateComment(ideaKey)
  // Per user, and cleared when the session ends (lib/drafts).
  const storageKey = draftKey(me.id, `comment:${ideaKey}`)
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
    <div className="flex flex-col gap-1.5 pt-2">
      {guestReader && (
        // Members are told who outside the project reads along (guest review L3, UX m8).
        <p id={guestNoteId} className="flex items-center gap-1.5 pl-8.5 text-xs text-muted">
          <Eye aria-hidden="true" className="size-3.5 shrink-0" />
          {guestReader.display_name} (researching, not in this project) can read comments.
        </p>
      )}
      <div className="flex items-start gap-2.5">
        <Avatar name={me.display_name} src={me.avatar_url} size="sm" decorative className="mt-2" />
        <MarkdownEditor
          id={COMMENT_INPUT_ID}
          describedBy={guestReader ? guestNoteId : undefined}
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
          mentions={mentions}
          mentionSelfId={me.id}
          hint={
            <span className="inline-flex items-center gap-1">
              Markdown · @ to mention · <KbdShortcut keys={SHORTCUTS.submitForm.keys} /> to post
            </span>
          }
          actions={
            <Button size="sm" onClick={post} disabled={!body.trim()}>
              Comment
            </Button>
          }
        />
      </div>
    </div>
  )
}

/**
 * A researcher outside a private project (a guest: role matrix column R) reads this
 * idea's comments; null otherwise, and for the guest themselves.
 */
function useGuestReader() {
  const { guest, project, me } = useIdeaPage()
  const { assignment } = useAssignment()
  const researcher = assignment.researcher
  if (guest || project?.visibility !== 'private' || !researcher) return null
  if (assignment.researcher_in_project || researcher.id === me.id) return null
  return researcher
}
