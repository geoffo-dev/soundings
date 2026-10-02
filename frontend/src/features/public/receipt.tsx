import { Link } from '@tanstack/react-router'
import { ArrowRight, Check, CircleCheck, Copy, MailCheck, Share } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

import type { PublicSubmissionReceipt } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Textarea } from '@/components/ui/textarea'
import { copyText } from '@/features/admin/copy-button'

import { PublicCard } from './public-layout'

/** The receipt's heading and what happens next, by what the idea is waiting for. */
export function nextStep(receipt: Pick<PublicSubmissionReceipt, 'held_for' | 'email_sent'>): {
  heading: string
  title: string
  text: string
} {
  if (receipt.held_for === 'email_verification') {
    return {
      heading: 'One more step: confirm your email',
      title: 'Open the link we’ve just emailed you',
      text: 'Your idea reaches the team once you confirm (within 3 days). Can’t see the email? Check your spam folder.',
    }
  }
  if (receipt.held_for === 'moderation') {
    return {
      heading: 'Thanks! Your idea is in',
      title: 'The team reviews new ideas first',
      text: 'Your link shows when it’s through and what happens to it next.',
    }
  }
  return {
    heading: 'Thanks! Your idea is in',
    title: 'The team can see it now',
    text: 'Your link shows what happens to it next.',
  }
}

/**
 * The confirmation after sending (wireframe 06): the private tracking link,
 * shown once (only its hash is kept), with Copy, and what happens next.
 * Focus moves to the heading so the result is announced.
 */
export function SubmissionReceipt({
  receipt,
  title,
  projectName,
  onAnother,
}: {
  receipt: PublicSubmissionReceipt
  title: string
  projectName: string
  onAnother: () => void
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  const linkId = useId()
  const [copied, setCopied] = useState<boolean | null>(null)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    heading.current?.focus()
    return () => window.clearTimeout(timer.current)
  }, [])
  const step = nextStep(receipt)
  // Held until the address is confirmed: that is the one thing to do now.
  const confirming = receipt.held_for === 'email_verification'
  // Phones (and some desktops) can hand the link to another app: notes, a message to yourself.
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  return (
    <PublicCard>
      <div className="flex flex-col items-center gap-3 text-center">
        <span
          aria-hidden="true"
          className="flex size-10 items-center justify-center rounded-full bg-success-subtle text-success"
        >
          <CircleCheck className="size-5" />
        </span>
        <h1
          ref={heading}
          tabIndex={-1}
          className="text-xl font-semibold text-balance text-primary focus:outline-none"
        >
          {step.heading}
        </h1>
        <p className="text-base break-words text-secondary">
          “{title}” was sent to {projectName}.
        </p>
      </div>

      {confirming && (
        <Callout tone="info" icon={<MailCheck />} title={step.title}>
          {step.text}
        </Callout>
      )}

      <div className="flex flex-col gap-2">
        <label htmlFor={linkId} className="text-sm font-medium text-primary">
          Your private link
        </label>
        {/* The whole link, wrapped: a one-line field would cut it off on a phone. */}
        <Textarea
          id={linkId}
          readOnly
          value={receipt.tracking_url}
          aria-describedby={`${linkId}-help`}
          minRows={1}
          maxRows={4}
          spellCheck={false}
          className="font-mono text-sm break-all"
          onFocus={(event) => event.currentTarget.select()}
        />
        <div className="flex gap-2">
          <Button
            type="button"
            variant="primary"
            className="h-11 flex-1 sm:h-9 sm:flex-none"
            onClick={() => {
              void copyText(receipt.tracking_url).then((ok) => {
                setCopied(ok)
                window.clearTimeout(timer.current)
                timer.current = window.setTimeout(() => setCopied(null), 2500)
              })
            }}
          >
            {copied ? <Check /> : <Copy />}
            {/* Both labels take the same room, so the button keeps its width. */}
            <span className="grid">
              <span className="col-start-1 row-start-1">{copied ? 'Copied' : 'Copy link'}</span>
              <span aria-hidden="true" className="invisible col-start-1 row-start-1">
                Copy link
              </span>
            </span>
          </Button>
          {canShare && (
            <Button
              type="button"
              variant="outline"
              className="h-11 flex-1 sm:h-9 sm:flex-none"
              onClick={() => {
                // Cancelling the share sheet rejects: nothing to do.
                navigator
                  .share({ title: `Your idea for ${projectName}`, url: receipt.tracking_url })
                  .catch(() => undefined)
              }}
            >
              <Share />
              Share…
            </Button>
          )}
        </div>
        <p id={`${linkId}-help`} className="text-sm text-muted">
          Keep it somewhere safe: it’s the only way to follow your idea, and we can’t show it again.
          Anyone with the link can see its status.
        </p>
        <p aria-live="polite" className="sr-only">
          {copied === true
            ? 'Link copied'
            : copied === false
              ? 'Couldn’t copy: select the link and copy it'
              : ''}
        </p>
        {copied === false && (
          <p className="text-sm text-danger">Couldn’t copy: select the link and copy it instead.</p>
        )}
      </div>

      {!confirming && (
        <Callout tone="neutral" title={step.title}>
          {step.text}
          {receipt.email_sent &&
            ' We’ve also emailed you this link: check your spam folder if it isn’t there.'}
        </Callout>
      )}

      <div className="flex flex-col gap-2 sm:flex-row-reverse">
        <Button asChild variant="secondary" size="lg" className="sm:flex-1">
          {/* The token stays in the fragment: never in a URL the server sees. */}
          <Link to="/track" hash={receipt.tracking_token}>
            Open your tracking page
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
        <Button variant="ghost" size="lg" className="sm:flex-1" onClick={onAnother}>
          Send another idea
        </Button>
      </div>
    </PublicCard>
  )
}
