import { Link } from '@tanstack/react-router'
import { ArrowRight, Check, CircleCheck, Copy, MailCheck } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

import type { PublicSubmissionReceipt } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Input } from '@/components/ui/input'
import { copyText } from '@/features/admin/copy-button'

import { PublicCard } from './public-layout'

/** What happens next, by what the idea is waiting for. */
export function nextStep(receipt: Pick<PublicSubmissionReceipt, 'held_for' | 'email_sent'>): {
  title: string
  text: string
} {
  if (receipt.held_for === 'email_verification') {
    return {
      title: 'One more step: confirm your email address',
      text: 'Open the link we’ve just emailed you. Your idea reaches the team once you confirm (within 3 days).',
    }
  }
  if (receipt.held_for === 'moderation') {
    return {
      title: 'The team reviews new ideas first',
      text: 'Your link shows when it’s through and what happens to it next.',
    }
  }
  return {
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
          Thanks! Your idea is in
        </h1>
        <p className="text-base text-secondary">
          “{title}” was sent to {projectName}.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={linkId} className="text-sm font-medium text-primary">
          Your private link
        </label>
        <div className="flex gap-2">
          <Input
            id={linkId}
            readOnly
            value={receipt.tracking_url}
            aria-describedby={`${linkId}-help`}
            className="h-11 font-mono text-sm sm:h-9"
            onFocus={(event) => event.currentTarget.select()}
          />
          <Button
            type="button"
            variant="primary"
            className="h-11 shrink-0 sm:h-9"
            onClick={() => {
              void copyText(receipt.tracking_url).then((ok) => {
                setCopied(ok)
                window.clearTimeout(timer.current)
                timer.current = window.setTimeout(() => setCopied(null), 2500)
              })
            }}
          >
            {copied ? <Check /> : <Copy />}
            {copied ? 'Copied' : 'Copy link'}
          </Button>
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

      {receipt.email_sent && (
        <Callout tone="info" icon={<MailCheck />} title="We’ve also emailed it to you">
          Can’t see it? Check your spam folder.
        </Callout>
      )}

      <Callout tone="neutral" title={step.title}>
        {step.text}
      </Callout>

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
