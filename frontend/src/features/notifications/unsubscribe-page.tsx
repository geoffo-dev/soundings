import { Link } from '@tanstack/react-router'
import { CircleCheck, CloudOff, LinkIcon, MailX } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'

import { hasErrorCode, isApiError } from '@/api/errors'
import { useConfirmUnsubscribe, useUnsubscribeInfo } from '@/api/notifications'
import type { UnsubscribeInfo } from '@/api/types'
import { Logo } from '@/components/layout/logo'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

import { unsubscribeSubject } from './preferences'

const PREFERENCES = '/settings/notifications'

/**
 * /unsubscribe?token=… (contract-phase3 §3.5): public, no sign-in. Opening the
 * page changes nothing (mail scanners prefetch links); it says what stops and
 * for which address (masked), and one button confirms. People can also stop
 * all Soundings email, or sign in to fine-tune their preferences.
 */
export function UnsubscribePage({ token }: { token: string | undefined }) {
  const info = useUnsubscribeInfo(token)
  const invalid =
    !token || (info.isError && isApiError(info.error) && [404, 422].includes(info.error.status))

  return (
    <div className="flex min-h-dvh flex-col items-center bg-background px-4 py-10 sm:justify-center sm:py-16">
      <main id="main" className="flex w-full max-w-md flex-col gap-6">
        <Logo className="self-center" />
        <div className="flex flex-col gap-5 rounded-xl border bg-surface p-5 sm:p-6">
          {invalid ? (
            <BrokenLink />
          ) : info.data && token ? (
            <Unsubscribe token={token} info={info.data} />
          ) : info.isError ? (
            <EmptyState
              role="alert"
              size="compact"
              headingLevel={1}
              icon={<CloudOff />}
              title="We couldn’t load this page"
              description="Check your connection and try again."
              action={
                <Button variant="primary" onClick={() => void info.refetch()}>
                  Try again
                </Button>
              }
            />
          ) : (
            <SkeletonGroup label="Loading" className="flex flex-col gap-3">
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="mt-2 h-10 w-full rounded-md" />
            </SkeletonGroup>
          )}
        </div>
        <p className="text-center text-xs text-muted">
          Soundings only emails you about ideas you own, evaluate, follow or are mentioned in.
        </p>
      </main>
    </div>
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

/** Missing, cut-off, forged or outdated (the secret key changed) links all read the same. */
function BrokenLink() {
  return (
    <EmptyState
      role="alert"
      size="compact"
      headingLevel={1}
      icon={<LinkIcon />}
      title="This unsubscribe link doesn’t work"
      description="It may be incomplete or no longer valid. Sign in to choose which emails you get."
      action={
        <Button variant="primary" asChild>
          <Link to="/login" search={{ next: PREFERENCES }}>
            Sign in to your email preferences
          </Link>
        </Button>
      }
    />
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
            {subject.done} at <span className="font-medium text-primary">{info.email_hint}</span>.
            You’ll still see notifications when you open Soundings.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <Button variant="secondary" size="lg" asChild>
            <Link to="/login" search={{ next: PREFERENCES }}>
              Email preferences
            </Link>
          </Button>
          {info.scope !== 'all' && (
            <Button
              variant="ghost"
              loading={confirm.isPending}
              onClick={() => confirm.mutate({ all: true })}
            >
              Unsubscribe from all Soundings email
            </Button>
          )}
        </div>
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
        <span
          aria-hidden="true"
          className="flex size-10 items-center justify-center rounded-xl border bg-surface text-muted"
        >
          <MailX className="size-5" />
        </span>
        <h1 className="text-xl font-semibold text-primary">{subject.title}</h1>
        <p className="text-base text-secondary">
          Emails to <span className="font-medium text-primary">{info.email_hint}</span>
          {subject.detail ? `: ${subject.detail}` : subject.list.length > 0 ? ' about:' : '.'}
        </p>
        {!subject.detail && subject.list.length > 0 && (
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
      <div className="flex flex-col gap-2">
        <Button
          variant="primary"
          size="lg"
          loading={confirm.isPending && !confirm.variables.all}
          disabled={confirm.isPending}
          onClick={() => confirm.mutate({ all: false })}
        >
          Unsubscribe
        </Button>
        {info.scope !== 'all' && (
          <Button
            variant="ghost"
            loading={confirm.isPending && confirm.variables.all}
            disabled={confirm.isPending}
            onClick={() => confirm.mutate({ all: true })}
          >
            Unsubscribe from all Soundings email
          </Button>
        )}
      </div>
      <p className="text-center text-sm text-muted">
        Want to choose per kind of email, or get a daily digest instead?{' '}
        <SignInToPreferences>Sign in to your email preferences</SignInToPreferences>.
      </p>
    </div>
  )
}
