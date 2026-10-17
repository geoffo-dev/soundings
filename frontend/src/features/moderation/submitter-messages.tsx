import { Globe, MessagesSquare, Send } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import { useSendSubmissionMessage, useSubmissionMessages } from '@/api/submissions'
import type { IdeaSubmission, SubmissionMessage, SubmissionMessagesSummary } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Field } from '@/components/ui/field'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { RelativeTime } from '@/components/ui/relative-time'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useIdeaPage } from '@/features/idea/idea-context'
import { LiveRegion, useLiveRegion } from '@/features/idea/live-region'
import { formatDateTime } from '@/lib/dates'
import { readDraft, writeDraft } from '@/lib/drafts'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import {
  deliveryText,
  MESSAGE_MAX_LENGTH,
  messageCount,
  SEND_BLOCKED_COPY,
  sendProblem,
} from './message-copy'

/*
 * Messages with the person who sent an idea through the public form
 * (contract-phase11 §3): for holders of `public.message_submitter` only (the
 * idea's owner, project and platform admins; `IdeaSubmission.messages` is null for
 * everyone else, who sees nothing of it). The submission panel shows a summary and
 * opens the conversation in a sheet (`?submission=1`, as "The submitter replied"
 * links do). Every message is plain text: never Markdown, never a link, its line
 * breaks kept; a submitter's text is untrusted public input.
 */

const SEND_KEYS = SHORTCUTS.submitForm.keys

/** The unsent message, per user and idea (lib/drafts: cleared when the session ends). */
export const messageDraftName = (ideaId: string) => `submission-message:${ideaId}`

/** In the submission panel: how the conversation stands, and the way into it. */
export function SubmissionMessagesEntry({
  submission,
  summary,
}: {
  submission: IdeaSubmission
  summary: SubmissionMessagesSummary
}) {
  const { openMessages } = useIdeaPage()
  const headingId = useId()
  const blocked = summary.blocked ? SEND_BLOCKED_COPY[summary.blocked] : null
  const canWrite = submission.permissions.can_message
  return (
    <div
      role="group"
      aria-labelledby={headingId}
      className="flex flex-col gap-1.5 border-t border-subtle pt-3"
    >
      <h3 id={headingId} className="text-sm font-medium text-primary">
        Messages
      </h3>
      <p className="text-sm text-secondary">
        {summary.count === 0 ? (
          summary.blocked === 'submitter_erased' ? (
            'None: their details were erased.'
          ) : (
            'No messages yet.'
          )
        ) : (
          <>
            {messageCount(summary.count)}
            {summary.last_message_at && (
              <span className="text-muted">
                {' · '}
                {summary.last_direction === 'submitter' ? 'They replied ' : 'Last sent '}
                <RelativeTime date={summary.last_message_at} />
              </span>
            )}
          </>
        )}
      </p>
      {blocked && summary.count === 0 && summary.blocked !== 'submitter_erased' && (
        <p className="text-sm text-muted">{blocked.title}.</p>
      )}
      {(summary.count > 0 || canWrite) && (
        <Button variant="outline" size="sm" className="self-start" onClick={() => openMessages?.()}>
          <MessagesSquare aria-hidden="true" />
          {summary.count === 0 ? 'Message the submitter…' : 'Open messages'}
        </Button>
      )}
    </div>
  )
}

/**
 * The conversation and the composer, in a sheet. `open` follows `?submission=1`;
 * it never opens for anyone without the rule (the idea page drops the flag).
 */
export function SubmitterMessagesSheet({
  open,
  onOpenChange,
  submission,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  submission: IdeaSubmission | undefined
}) {
  const { idea } = useIdeaPage()
  const contentRef = useRef<HTMLDivElement>(null)
  const summary = submission?.messages ?? null
  const who = submission?.name ?? null
  return (
    <Sheet open={open && summary !== null} onOpenChange={onOpenChange}>
      <SheetContent
        ref={contentRef}
        size="md"
        onOpenAutoFocus={(event) => {
          // Straight into the message box with a keyboard; touch opens on the sheet, so
          // the conversation isn't hidden behind the on-screen keyboard.
          event.preventDefault()
          const box = contentRef.current?.querySelector<HTMLTextAreaElement>('textarea')
          if (box && !window.matchMedia('(pointer: coarse)').matches) box.focus()
          else contentRef.current?.focus()
        }}
      >
        <SheetHeader>
          <SheetTitle>{who ? `Messages with ${who}` : 'Messages with the submitter'}</SheetTitle>
          <SheetDescription className="truncate">
            <span className="tabular-nums">{idea.key}</span> · {idea.title}
          </SheetDescription>
        </SheetHeader>
        {submission && summary && (
          <Conversation submission={submission} summary={summary} who={who} />
        )}
      </SheetContent>
    </Sheet>
  )
}

function Conversation({
  submission,
  summary,
  who,
}: {
  submission: IdeaSubmission
  summary: SubmissionMessagesSummary
  who: string | null
}) {
  const { ideaKey, idea } = useIdeaPage()
  const messages = useSubmissionMessages(ideaKey)
  const bodyRef = useRef<HTMLDivElement>(null)
  const { message: announcement, announce } = useLiveRegion()
  const items = messages.data?.messages
  const count = items?.length ?? 0
  const lastId = items?.at(-1)?.id

  // The latest message in view: on open, and after one arrives (yours or theirs).
  const shownLast = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!lastId || shownLast.current === lastId) return
    shownLast.current = lastId
    const body = bodyRef.current
    if (body) body.scrollTop = body.scrollHeight
  }, [lastId])

  const earlier = async () => {
    const firstBefore = items?.[0]?.id
    await messages.fetchNextPage()
    // Focus the message that was the oldest one shown, so reading goes on from there.
    if (firstBefore) document.getElementById(messageAnchor(firstBefore))?.focus()
  }

  return (
    <>
      <LiveRegion message={announcement} />
      <SheetBody
        ref={bodyRef}
        // The conversation scrolls on its own: keyboard users can focus and scroll it.
        tabIndex={0}
        role="region"
        aria-label="Conversation"
        className="flex flex-col gap-4 focus-visible:-outline-offset-2"
      >
        {messages.isPending ? (
          <SkeletonGroup label="Loading messages" className="flex flex-col gap-4">
            {[0, 1].map((n) => (
              <div key={n} className="flex flex-col gap-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-14 w-full" />
              </div>
            ))}
          </SkeletonGroup>
        ) : messages.isError && !items ? (
          <Callout
            role="alert"
            tone="danger"
            title="The messages didn’t load"
            action={
              <Button variant="ghost" size="sm" onClick={() => void messages.refetch()}>
                Try again
              </Button>
            }
          >
            Check your connection and try again.
          </Callout>
        ) : count === 0 ? (
          <div className="flex flex-col items-start gap-1 py-6 text-sm">
            <p className="font-medium text-primary">
              {summary.blocked === 'submitter_erased' ? 'No messages' : 'No messages yet'}
            </p>
            <p className="text-secondary">
              {submission.permissions.can_message
                ? `Ask ${who ?? 'them'} something about their idea. They read and answer on their private tracking page.`
                : summary.blocked === 'submitter_erased'
                  ? 'Any messages with them were deleted with their details.'
                  : 'Nobody has written to them about this idea.'}
            </p>
          </div>
        ) : (
          <>
            {messages.hasNextPage && (
              <Button
                variant="ghost"
                size="sm"
                className="self-center"
                loading={messages.isFetchingNextPage}
                onClick={() => void earlier()}
              >
                Show earlier messages
              </Button>
            )}
            <ol aria-label="Messages, oldest first" className="flex flex-col gap-4">
              {items?.map((message) => (
                <MessageRow key={message.id} message={message} who={who} />
              ))}
            </ol>
          </>
        )}
      </SheetBody>
      <SheetFooter className="flex-col items-stretch gap-3">
        {summary.blocked ? (
          <Callout role="status" tone="neutral" title={SEND_BLOCKED_COPY[summary.blocked].title}>
            {SEND_BLOCKED_COPY[summary.blocked].text}
          </Callout>
        ) : (
          <Composer
            ideaId={idea.id}
            ideaKey={ideaKey}
            projectName={idea.project.name}
            summary={summary}
            who={who}
            onSent={() => announce('Message sent')}
          />
        )}
      </SheetFooter>
    </>
  )
}

const messageAnchor = (id: string) => `submission-message-${id}`

function MessageRow({ message, who }: { message: SubmissionMessage; who: string | null }) {
  const team = message.direction === 'team'
  const name = team ? (message.author?.display_name ?? 'Someone on the team') : 'Submitter'
  return (
    <li>
      <article
        id={messageAnchor(message.id)}
        tabIndex={-1}
        aria-label={`${name}, ${formatDateTime(message.created_at)}`}
        className="flex min-w-0 flex-col gap-1.5 rounded-md focus-visible:outline-offset-4"
      >
        <header className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
          {team ? (
            <Avatar
              name={message.author?.display_name ?? '?'}
              src={message.author?.avatar_url ?? null}
              size="xs"
              decorative
            />
          ) : (
            <span
              aria-hidden="true"
              className="flex size-5 items-center justify-center rounded-full bg-subtle text-muted"
            >
              <Globe className="size-3" />
            </span>
          )}
          <span className="min-w-0 truncate font-medium text-primary">
            {name}
            {!team && who && <span className="font-normal text-muted"> ({who})</span>}
          </span>
          <span className="text-muted">
            <RelativeTime date={message.created_at} />
          </span>
          {team && (
            <span className="text-muted">
              · {message.emailed ? 'Email queued' : 'Tracking page only'}
            </span>
          )}
        </header>
        <div
          // Plain text, kept as written: line breaks shown, long words wrapped, and
          // anything that would paint outside its box (combining marks) clipped.
          className={cn(
            'overflow-hidden rounded-lg px-3 py-2 text-sm wrap-anywhere whitespace-pre-wrap text-primary',
            team ? 'border border-subtle bg-surface' : 'bg-subtle',
          )}
        >
          {message.body}
        </div>
      </article>
    </li>
  )
}

function Composer({
  ideaId,
  ideaKey,
  projectName,
  summary,
  who,
  onSent,
}: {
  ideaId: string
  ideaKey: string
  projectName: string
  summary: SubmissionMessagesSummary
  who: string | null
  onSent: () => void
}) {
  const { me } = useIdeaPage()
  const send = useSendSubmissionMessage(ideaKey)
  const draftName = messageDraftName(ideaId)
  const [body, setBody] = useState(() => readDraft(me.id, draftName) ?? '')
  const boxRef = useRef<HTMLTextAreaElement>(null)
  const fieldId = useId()
  const problem = send.isError ? sendProblem(send.error) : null

  const change = (value: string) => {
    setBody(value)
    writeDraft(me.id, draftName, value.trim() ? value : null)
    if (send.isError) send.reset()
  }
  const submit = () => {
    const text = body.trim()
    if (!text || send.isPending) return
    send.mutate(text, {
      onSuccess: () => {
        setBody('')
        writeDraft(me.id, draftName, null)
        onSent()
        boxRef.current?.focus()
      },
    })
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.altKey) {
      event.preventDefault()
      submit()
    }
  }
  const near = body.length >= MESSAGE_MAX_LENGTH * 0.8

  return (
    <div className="flex flex-col gap-2">
      {problem && (
        <Callout role="alert" tone="danger" title={problem.title}>
          {problem.text}
        </Callout>
      )}
      <Field
        id={fieldId}
        label={who ? `Message to ${who}` : 'Message to the submitter'}
        description={deliveryText(summary.delivery, projectName)}
      >
        <Textarea
          ref={boxRef}
          value={body}
          maxLength={MESSAGE_MAX_LENGTH}
          minRows={3}
          maxRows={10}
          placeholder="Write a message…"
          // Plain text: no Markdown, no @mentions (a colleague's name never reaches the public).
          spellCheck
          onChange={(event) => change(event.target.value)}
          onKeyDown={onKeyDown}
        />
      </Field>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted tabular-nums" aria-live="polite">
          {near
            ? `${body.length.toLocaleString('en')}/${MESSAGE_MAX_LENGTH.toLocaleString('en')} characters`
            : ''}
        </p>
        <Button
          variant="primary"
          loading={send.isPending}
          disabled={!body.trim()}
          aria-keyshortcuts={ariaKeys(SEND_KEYS)}
          onClick={submit}
        >
          <Send aria-hidden="true" />
          Send
          <ButtonShortcut keys={SEND_KEYS} />
        </Button>
      </div>
    </div>
  )
}
