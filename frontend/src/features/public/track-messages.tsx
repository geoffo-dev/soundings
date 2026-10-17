import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from 'react'

import { useSendTrackingReply } from '@/api/public'
import type { TrackedMessage, TrackedSubmission } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { ariaKeys } from '@/components/ui/kbd'
import { RelativeTime } from '@/components/ui/relative-time'
import { Textarea } from '@/components/ui/textarea'
import { LiveRegion, useLiveRegion } from '@/features/idea/live-region'
import {
  MESSAGE_MAX_LENGTH,
  REPLY_BLOCKED_COPY,
  repliesLeftText,
  replyProblem,
} from '@/features/moderation/message-copy'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { PublicCard } from './public-layout'

/**
 * The tracking page's conversation with the team (contract-phase11 §3): shown once
 * the team has written (the public never starts one). The team's messages are
 * signed "The <project> team" (public pages show no people), the submitter's read
 * "You"; plain text with its line breaks, never Markdown or links. The reply box
 * shows while `can_reply`; otherwise `reply_blocked` says why in plain words.
 * `toReply` (the message email's Reply button, `/track?reply=1#…`: UX review m4) brings
 * the reply box into view and focuses it once, or the section's heading when replying
 * isn't possible just now.
 */
export function TrackedMessages({
  token,
  tracked,
  toReply = false,
}: {
  token: string
  tracked: TrackedSubmission
  toReply?: boolean
}) {
  const headingId = useId()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const boxRef = useRef<HTMLTextAreaElement>(null)
  const team = `The ${tracked.project.name} team`
  const { message: announcement, announce } = useLiveRegion()
  const listRef = useRef<HTMLOListElement>(null)
  const lastId = tracked.messages.at(-1)?.id
  const shownLast = useRef(lastId)
  useEffect(() => {
    if (!lastId || shownLast.current === lastId) return
    shownLast.current = lastId
    listRef.current?.lastElementChild?.scrollIntoView({ block: 'nearest' })
  }, [lastId])

  const hasMessages = tracked.messages.length > 0
  const tookReply = useRef(false)
  useEffect(() => {
    if (!toReply || !hasMessages || tookReply.current) return
    tookReply.current = true
    const target = boxRef.current ?? headingRef.current
    if (!target) return
    target.scrollIntoView({ block: 'center' })
    target.focus({ preventScroll: true })
  }, [toReply, hasMessages])

  if (tracked.messages.length === 0) return null
  const blocked = tracked.reply_blocked
  return (
    <PublicCard className="gap-4">
      <LiveRegion message={announcement} />
      <section aria-labelledby={headingId} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2
            id={headingId}
            ref={headingRef}
            tabIndex={-1}
            className="text-base font-semibold text-primary focus:outline-none"
          >
            Messages
          </h2>
          <p className="text-sm text-muted">
            {tracked.team_messages_emailed
              ? `${team} wrote to you about your idea. We’ll also email you when they write again.`
              : tracked.email_hint && !tracked.email_verified
                ? `${team} wrote to you about your idea. New messages appear on this page; confirm your email address to get them by email too.`
                : `${team} wrote to you about your idea. New messages appear on this page: check back here.`}
          </p>
        </div>
        <ol ref={listRef} aria-label="Messages, oldest first" className="flex flex-col gap-4">
          {tracked.messages.map((message) => (
            <MessageItem key={message.id} message={message} team={team} />
          ))}
        </ol>
        {tracked.can_reply ? (
          <ReplyBox
            ref={boxRef}
            token={token}
            left={repliesLeftText(tracked.messages)}
            onSent={() => announce('Reply sent')}
          />
        ) : (
          blocked && (
            <p className="rounded-lg bg-subtle px-3 py-2.5 text-sm text-secondary">
              {REPLY_BLOCKED_COPY[blocked]}
            </p>
          )
        )}
      </section>
    </PublicCard>
  )
}

function MessageItem({ message, team }: { message: TrackedMessage; team: string }) {
  const fromTeam = message.direction === 'team'
  return (
    <li className="flex min-w-0 flex-col gap-1.5">
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="font-medium text-primary">{fromTeam ? team : 'You'}</span>
        <RelativeTime date={message.created_at} tooltip={false} className="text-muted" />
      </p>
      <div
        // Plain text as written: line breaks kept, long words wrapped, overflow clipped.
        className={cn(
          'overflow-hidden rounded-lg px-3 py-2.5 text-base wrap-anywhere whitespace-pre-wrap text-primary',
          fromTeam ? 'border border-subtle bg-surface' : 'bg-subtle',
        )}
      >
        {message.body}
      </div>
    </li>
  )
}

const SEND_KEYS = SHORTCUTS.submitForm.keys

function ReplyBox({
  ref: boxRef,
  token,
  left,
  onSent,
}: {
  ref: RefObject<HTMLTextAreaElement | null>
  token: string
  /** "You can send 2 more replies until the team writes back." near a limit (UX review p9). */
  left: string | null
  onSent: () => void
}) {
  const reply = useSendTrackingReply(token)
  const [body, setBody] = useState('')
  const problem = reply.isError ? replyProblem(reply.error) : undefined
  const submit = () => {
    const text = body.trim()
    if (!text || reply.isPending) return
    reply.mutate(text, {
      onSuccess: () => {
        setBody('')
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
    <div className="flex flex-col gap-2 border-t border-subtle pt-4">
      <Field
        label="Reply to the team"
        description={[
          near
            ? `${body.length.toLocaleString('en')}/${MESSAGE_MAX_LENGTH.toLocaleString('en')} characters.`
            : 'Only the team sees your reply.',
          left,
        ]
          .filter(Boolean)
          .join(' ')}
        error={problem}
      >
        <Textarea
          ref={boxRef}
          value={body}
          maxLength={MESSAGE_MAX_LENGTH}
          minRows={3}
          maxRows={10}
          onChange={(event) => {
            setBody(event.target.value)
            if (reply.isError) reply.reset()
          }}
          onKeyDown={onKeyDown}
        />
      </Field>
      <div>
        <Button
          variant="primary"
          loading={reply.isPending}
          disabled={!body.trim()}
          aria-keyshortcuts={ariaKeys(SEND_KEYS)}
          className="h-11 w-full sm:h-9 sm:w-auto"
          onClick={submit}
        >
          {/* ⌘Enter / Ctrl+Enter works, but public pages show no shortcut hints (as the form). */}
          Send reply
        </Button>
      </div>
    </div>
  )
}
