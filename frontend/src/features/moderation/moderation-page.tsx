import { Link } from '@tanstack/react-router'
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CloudOff,
  Inbox,
  Lock,
  Mail,
  MailCheck,
  Settings,
  Trash2,
} from 'lucide-react'
import { useRef, useState } from 'react'

import { isApiError } from '@/api/errors'
import { useProject } from '@/api/projects'
import { useModerate, useModerationQueue } from '@/api/submissions'
import type { ModerationItem, Project } from '@/api/types'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Markdown } from '@/components/ui/markdown'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { byId, focusWhenRendered } from '@/lib/focus'
import { useListNavigation } from '@/lib/list-navigation'

const EMPTY_ID = 'moderation-queue-empty'
const titleLinkId = (ideaId: string) => `queue-${ideaId}-link`

/**
 * Where focus goes when a card leaves the queue (WCAG 2.4.3): the next card's
 * title, else the one before, else the "Nothing waiting" state.
 */
function focusAfterLeaving(card: HTMLElement | null) {
  const cards = [...(card?.closest('ul')?.querySelectorAll<HTMLElement>('[data-queue-item]') ?? [])]
  const index = card ? cards.indexOf(card) : -1
  const neighbour = cards[index + 1] ?? cards[index - 1]
  const link = neighbour?.querySelector<HTMLElement>('[data-nav-item]')
  focusWhenRendered(link ? () => link : byId(EMPTY_ID))
}

/**
 * /p/$slug/review — the moderation queue (contract-phase4 §3.6; project and
 * platform admins): ideas sent through the public form wait here, oldest
 * first, until an admin approves one (it appears in New) or rejects it (spam
 * or abuse: the idea is deleted). Both wait for their Undo toast before they
 * are sent, so a slip costs nothing.
 */
export function ModerationPage({ slug }: { slug: string }) {
  const project = useProject(slug)
  if (!project.data) return <ModerationSkeleton />
  return <ModerationContent key={slug} project={project.data} />
}

function ModerationContent({ project }: { project: Project }) {
  const queue = useModerationQueue(project.slug, { enabled: project.permissions.can_manage })
  const { listRef } = useListNavigation()
  const total = queue.data?.total

  let content
  if (!project.permissions.can_manage || (isApiError(queue.error) && queue.error.status === 403)) {
    content = (
      <EmptyState
        headingLevel={2}
        icon={<Lock />}
        title="Only project admins review new ideas"
        description="Ask an admin of this project if an idea you sent seems stuck."
      />
    )
  } else if (queue.isError && !queue.data) {
    content = (
      <EmptyState
        role="alert"
        headingLevel={2}
        icon={<CloudOff />}
        title="We couldn’t load the ideas waiting for review"
        description="Check your connection and try again."
        action={
          <Button variant="primary" onClick={() => void queue.refetch()}>
            Try again
          </Button>
        }
      />
    )
  } else if (!queue.data) {
    content = <QueueSkeleton />
  } else if (queue.data.items.length === 0) {
    content = (
      <EmptyState
        id={EMPTY_ID}
        tabIndex={-1}
        className="rounded-lg focus-visible:outline-offset-0"
        headingLevel={2}
        icon={<Inbox />}
        title="Nothing waiting for review"
        description="Ideas sent through the public form wait here when the project reviews them first."
        action={
          <Button asChild variant="outline">
            <Link
              to="/p/$slug/settings"
              params={{ slug: project.slug }}
              search={{ tab: 'public-form' }}
            >
              <Settings aria-hidden="true" /> Public form settings
            </Link>
          </Button>
        }
      />
    )
  } else {
    content = (
      <div className="flex flex-col gap-3">
        <ul ref={listRef} aria-label="Ideas waiting for review" className="flex flex-col gap-3">
          {queue.data.items.map((item) => (
            <li key={item.id}>
              <QueueItem item={item} archived={Boolean(project.archived_at)} />
            </li>
          ))}
        </ul>
        {queue.hasNextPage && (
          <Button
            variant="outline"
            className="self-center"
            loading={queue.isFetchingNextPage}
            onClick={() => void queue.fetchNextPage()}
          >
            Show more
          </Button>
        )}
      </div>
    )
  }

  return (
    <Page>
      <PageHeader
        title="Review new ideas"
        description={
          total === undefined
            ? `${project.name} · from the public form`
            : `${project.name} · ${total === 0 ? 'nothing waiting' : `${total.toLocaleString('en')} waiting, oldest first`}`
        }
        actions={
          <Button asChild variant="ghost" size="sm" className="text-secondary">
            <Link to="/p/$slug" params={{ slug: project.slug }}>
              <ArrowLeft /> Back to ideas
            </Link>
          </Button>
        }
      />
      <p className="-mt-2 max-w-2xl text-sm text-muted">
        Approve an idea to put it in New for the team. Reject spam, abuse and off-topic posts: the
        idea is deleted. A genuine idea you won’t pursue is better approved and closed as Rejected,
        so its sender sees that.
      </p>
      {content}
    </Page>
  )
}

const COLLAPSED_LENGTH = 280

function QueueItem({ item, archived }: { item: ModerationItem; archived: boolean }) {
  const moderate = useModerate()
  const [expanded, setExpanded] = useState(false)
  const submission = item.submission
  const contact = submission.contact
  const long = item.description_md.length > COLLAPSED_LENGTH
  const canModerate = submission.permissions.can_moderate && !archived
  const target = { id: item.id, key: item.key, title: item.title, project: item.project }
  const card = useRef<HTMLElement>(null)
  // The card leaves the queue at once (Undo in the toast): focus moves on. After Undo the
  // toaster returns focus to where it was (the next card); only if that was lost does it
  // go to the card that came back.
  const callbacks = {
    onHide: () => focusAfterLeaving(card.current),
    onRestore: () => focusWhenRendered(byId(titleLinkId(item.id))),
  }

  return (
    <article
      ref={card}
      data-queue-item=""
      aria-labelledby={`queue-${item.id}-title`}
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <div className="flex flex-col gap-1">
        {/* The page says these are waiting for review: no badge on every card. */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span className="tabular-nums">{item.key}</span>
          <span aria-hidden="true">·</span>
          <span>
            Sent <RelativeTime date={submission.submitted_at} />
          </span>
        </div>
        <h2
          id={`queue-${item.id}-title`}
          className="text-lg font-semibold break-words text-primary"
        >
          <Link
            id={titleLinkId(item.id)}
            to="/ideas/$ideaKey"
            params={{ ideaKey: item.key }}
            data-nav-item
            className="rounded-sm hover:underline focus-visible:outline-offset-2"
          >
            {item.title}
          </Link>
        </h2>
        <p className="text-base break-words text-primary">{item.summary}</p>
      </div>
      {item.description_md && (
        <div className="flex flex-col gap-1">
          <div className={expanded || !long ? undefined : 'line-clamp-3'}>
            <Markdown className="text-sm text-secondary">{item.description_md}</Markdown>
          </div>
          {long && (
            <Button
              variant="link"
              size="sm"
              className="self-start"
              aria-expanded={expanded}
              onClick={() => setExpanded((open) => !open)}
            >
              {expanded ? 'Show less' : 'Show the whole description'}
              <ChevronDown aria-hidden="true" className={expanded ? 'rotate-180' : undefined} />
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-col gap-3 border-t border-subtle pt-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm text-secondary">
          <span>{submission.name ? `From ${submission.name}` : 'No name given'}</span>
          {contact?.email && (
            <span className="inline-flex min-w-0 items-center gap-1 text-muted">
              {contact.email_verified ? (
                <MailCheck aria-hidden="true" className="size-3.5 text-success" />
              ) : (
                <Mail aria-hidden="true" className="size-3.5" />
              )}
              <span className="truncate">{contact.email}</span>
              <span className="sr-only">
                {contact.email_verified ? '(confirmed)' : '(not confirmed)'}
              </span>
            </span>
          )}
        </p>
        {canModerate && (
          <div className="flex shrink-0 gap-2">
            <Button
              variant="ghost"
              className="flex-1 sm:flex-none"
              aria-label={`Reject and delete ${item.key}`}
              onClick={() => moderate.reject(target, callbacks)}
            >
              <Trash2 aria-hidden="true" /> Reject
            </Button>
            <Button
              variant="outline"
              className="flex-1 sm:flex-none"
              aria-label={`Approve ${item.key}`}
              onClick={() => moderate.approve(target, callbacks)}
            >
              <Check aria-hidden="true" /> Approve
            </Button>
          </div>
        )}
      </div>
    </article>
  )
}

function QueueSkeleton() {
  return (
    <SkeletonGroup label="Loading the ideas waiting for review" className="flex flex-col gap-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <div className="flex justify-between border-t border-subtle pt-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-8 w-44 rounded-md" />
          </div>
        </div>
      ))}
    </SkeletonGroup>
  )
}

function ModerationSkeleton() {
  return (
    <Page>
      <SkeletonGroup label="Loading" className="flex flex-col gap-2">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-4 w-72 max-w-full" />
      </SkeletonGroup>
      <QueueSkeleton />
    </Page>
  )
}
