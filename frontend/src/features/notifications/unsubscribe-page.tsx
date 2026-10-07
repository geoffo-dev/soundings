import { Link } from '@tanstack/react-router'
import { CircleCheck, CloudOff, LinkIcon, MailX } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'

import { hasErrorCode, isApiError } from '@/api/errors'
import { useConfirmUnsubscribe, useUnsubscribeInfo } from '@/api/notifications'
import type { UnsubscribeInfo } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { PublicCard, PublicLayout, PublicMessage } from '@/features/public/public-layout'

import { unsubscribeSubject } from './preferences'

const PREFERENCES = '/settings/notifications'

/**
 * /unsubscribe?token=… (contract-phase3 §3.5): public, no sign-in. Opening the
 * page changes nothing (mail scanners prefetch links); it says what stops and
 * for which address (masked), and one button confirms. A link stops only what
 * it was made for: its type, the digest, or (the footer's "Unsubscribe from
 * all email") everything. People can sign in to fine-tune their preferences.
 */
export function UnsubscribePage({ token }: { token: string | undefined }) {
  const info = useUnsubscribeInfo(token)
  const invalid =
    !token || (info.isError && isApiError(info.error) && [404, 422].includes(info.error.status))

  return (
    // The public pages' frame and message layout (UX review m5), in the instance's branding.
    <PublicLayout
      branding={null}
      width="narrow"
      footer={
        <p className="text-center text-xs">
          Soundings only emails you about ideas you own, evaluate, follow or are mentioned in.
        </p>
      }
    >
      <PublicCard>
        {invalid ? (
          <BrokenLink />
        ) : info.data && token ? (
          <Unsubscribe token={token} info={info.data} />
        ) : info.isError ? (
          <PublicMessage
            role="alert"
            icon={<CloudOff />}
            title="We couldn’t load this page"
            action={
              <Button variant="primary" onClick={() => void info.refetch()}>
                Try again
              </Button>
            }
          >
            Check your connection and try again.
          </PublicMessage>
        ) : (
          <SkeletonGroup label="Loading" className="flex flex-col gap-3">
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="mt-2 h-10 w-full rounded-md" />
          </SkeletonGroup>
        )}
      </PublicCard>
    </PublicLayout>
  )
}

function SignInToPreferences({ children }: { children: ReactNode }) {
  return (
    <Link
      to="/login"
      search={{ next: PREFERENCES }}
      className="font-medium text-accent underline-offset-4 hover:underline"
    >
      {children}
    </Link>
  )
}

/**
 * Missing, cut-off, forged or outdated (the secret key changed) links all read
 * the same.
 */
function BrokenLink() {
  return (
    <PublicMessage
      role="alert"
      icon={<LinkIcon />}
      title="This unsubscribe link doesn’t work"
      action={
        <Button variant="primary" size="lg" className="w-full" asChild>
          <Link to="/login" search={{ next: PREFERENCES }}>
            Sign in to your email preferences
          </Link>
        </Button>
      }
    >
      It may be incomplete or no longer valid. Sign in to choose which emails you get.
    </PublicMessage>
  )
}

function Unsubscribe({ token, info }: { token: string; info: UnsubscribeInfo }) {
  const confirm = useConfirmUnsubscribe(token)
  const subject = unsubscribeSubject(info)
  const doneHeading = useRef<HTMLHeadingElement>(null)
  const justDone = confirm.isSuccess

  // After confirming, move focus to the result so it is announced.
  useEffect(() => {
    if (justDone) doneHeading.current?.focus()
  }, [justDone])

  if (confirm.isError && hasErrorCode(confirm.error, 'not_found')) return <BrokenLink />

  if (info.unsubscribed) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col items-center gap-3 text-center">
          <span
            aria-hidden="true"
            className="flex size-10 items-center justify-center rounded-full bg-success-subtle text-success"
          >
            <CircleCheck className="size-5" />
          </span>
          <h1
            ref={doneHeading}
            tabIndex={-1}
            className="text-xl font-semibold text-primary focus:outline-none"
          >
            {justDone ? 'You’re unsubscribed' : 'You’re already unsubscribed'}
          </h1>
          <p className="text-base text-secondary">
            {subject.done.before}
            <span className="font-medium text-primary">{info.email_hint}</span>
            {subject.done.after} You’ll still see notifications when you open Soundings.
          </p>
        </div>
        <Button variant="secondary" size="lg" asChild>
          <Link to="/login" search={{ next: PREFERENCES }}>
            Email preferences
          </Link>
        </Button>
        <p className="text-center text-sm text-muted">
          Changed your mind? <SignInToPreferences>Sign in</SignInToPreferences> and turn them back
          on.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <PublicMessage icon={<MailX />} title={subject.title}>
          Soundings will stop emailing{' '}
          <span className="font-medium text-primary">{info.email_hint}</span>
          {subject.when ? ` when ${subject.when}.` : subject.list.length > 0 ? ' about:' : '.'}
        </PublicMessage>
        {!subject.when && subject.list.length > 0 && (
          <ul className="flex list-disc flex-col gap-0.5 pl-5 text-base text-primary marker:text-muted">
            {subject.list.map((label) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
        )}
        <p className="text-sm text-muted">You’ll still see these in Soundings itself.</p>
      </div>
      {confirm.isError && (
        <Callout role="alert" tone="danger" title="That didn’t work">
          Nothing changed. Check your connection and try again.
        </Callout>
      )}
      <Button
        variant="primary"
        size="lg"
        loading={confirm.isPending}
        onClick={() => confirm.mutate()}
      >
        Unsubscribe
      </Button>
      <p className="text-center text-sm text-muted">
        {info.scope === 'all'
          ? 'Want to choose per kind of email, or get a daily digest instead? '
          : 'Want to stop all Soundings email, or get a daily digest instead? '}
        <SignInToPreferences>Sign in to your email preferences</SignInToPreferences>.
      </p>
    </div>
  )
}
