import { CloudOff, KeyRound } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

import { useAuthConfig } from '@/api/auth'
import type { AuthConfig } from '@/api/types'
import { LogoMark } from '@/components/layout/logo'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'

import { BreakGlassForm } from './break-glass-form'
import { DevLogin } from './dev-login'
import { loginMessage } from './login-messages'
import { followSsoLink, ssoLoginHref } from './sso'

export interface LoginPageProps {
  next?: string
  error?: string
  signed_out?: boolean
  expired?: boolean
}

/**
 * /login (contract-phase2 §3.1): the organisation's single sign-on first (the
 * one primary action), the break-glass admin form while SSO isn't configured,
 * and the development sign-in below a divider when it is on. Messages after a
 * redirect back here (`?error=`, `?signed_out=1`, `?expired=1`) sit on top.
 */
export function LoginPage({ next, error, signed_out, expired }: LoginPageProps) {
  const config = useAuthConfig()
  const message = loginMessage({ error, signed_out, expired })

  return (
    <div className="flex min-h-dvh flex-col items-center bg-background px-4 py-10 sm:justify-center sm:py-16">
      <main id="main" className="flex w-full max-w-md flex-col gap-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <LogoMark className="size-10" />
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold text-primary">Sign in to Soundings</h1>
            <p className="text-base text-muted">Share ideas, own them, and score them fairly.</p>
          </div>
        </div>

        <div className="flex flex-col gap-4 rounded-xl border bg-surface p-4 sm:p-6">
          {message && (
            <Callout role={message.role} tone={message.tone} title={message.title}>
              {message.description}
            </Callout>
          )}
          {config.isPending ? (
            <SkeletonGroup label="Loading the sign-in options" className="flex flex-col gap-3">
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="mx-auto h-3 w-56" />
            </SkeletonGroup>
          ) : config.isError ? (
            <EmptyState
              role="alert"
              size="compact"
              icon={<CloudOff />}
              title="We couldn’t load the sign-in options"
              description="Check your connection and try again."
              action={
                <Button variant="primary" onClick={() => void config.refetch()}>
                  Try again
                </Button>
              }
            />
          ) : (
            <SignInMethods config={config.data} next={next} />
          )}
        </div>

        {config.data && !config.data.sso && !config.data.break_glass && config.data.dev_login && (
          <p className="text-center text-xs text-muted pointer-coarse:hidden">
            Use <kbd className="font-sans">↑</kbd> <kbd className="font-sans">↓</kbd> to choose and{' '}
            <kbd className="font-sans">Enter</kbd> to sign in.
          </p>
        )}
      </main>
    </div>
  )
}

function SignInMethods({ config, next }: { config: AuthConfig; next?: string }) {
  const devHeadingId = useId()
  const breakGlassHeadingId = useId()
  const primary = config.sso || config.break_glass

  if (!config.sso && !config.break_glass && !config.dev_login) {
    return (
      <EmptyState
        size="compact"
        icon={<KeyRound />}
        title="Sign-in isn’t set up yet"
        description="Single sign-on hasn’t been configured for Soundings. Ask your administrator: the operator guide explains how."
      />
    )
  }

  return (
    <>
      {config.sso && <SsoSignIn next={next} />}
      {config.break_glass && (
        <section aria-labelledby={breakGlassHeadingId} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 id={breakGlassHeadingId} className="text-base font-semibold text-primary">
              Break-glass admin
            </h2>
            <p className="text-sm text-muted">
              For first-time setup and emergencies, while single sign-on is off. Every use is
              recorded in the audit log.
            </p>
          </div>
          <BreakGlassForm next={next} headingId={breakGlassHeadingId} />
        </section>
      )}
      {config.dev_login && (
        <section aria-labelledby={devHeadingId} className="flex flex-col gap-3">
          {primary ? (
            <div className="flex flex-col gap-1 pt-2">
              <div className="flex items-center gap-3">
                <span aria-hidden="true" className="flex-1 border-t" />
                <h2 id={devHeadingId} className="text-xs font-medium text-muted">
                  Development sign-in
                </h2>
                <span aria-hidden="true" className="flex-1 border-t" />
              </div>
              <p className="text-center text-xs text-muted">
                No password needed. Never turned on in production.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-1 px-1">
              <h2 id={devHeadingId} className="text-base font-semibold text-primary">
                Choose who you are
              </h2>
              <p className="text-sm text-muted">
                Development sign-in: no password needed. Single sign-on replaces this in production.
              </p>
            </div>
          )}
          <DevLogin next={next} focusOnLoad={!primary} headingId={devHeadingId} />
        </section>
      )}
    </>
  )
}

/**
 * "Sign in with SSO": a link (a full-page navigation to `GET /auth/login`, never
 * a fetch), styled as the page's primary button and focused on arrival so Enter
 * signs in. Shows a spinner while the browser goes to the identity provider.
 */
function SsoSignIn({ next }: { next?: string }) {
  const [leaving, setLeaving] = useState(false)
  const linkRef = useRef<HTMLAnchorElement>(null)

  // The page's one primary action: Enter signs in. (React's autoFocus skips links.)
  useEffect(() => {
    linkRef.current?.focus()
  }, [])

  // Back from the IdP may restore this page from the bfcache: not "leaving" any more.
  useEffect(() => {
    const reset = (event: PageTransitionEvent) => {
      if (event.persisted) setLeaving(false)
    }
    window.addEventListener('pageshow', reset)
    return () => window.removeEventListener('pageshow', reset)
  }, [])

  return (
    <div className="flex flex-col gap-2">
      <Button asChild variant="primary" size="lg" className="w-full">
        <a
          href={ssoLoginHref(next)}
          aria-busy={leaving || undefined}
          onClick={(event) => {
            if (leaving) {
              event.preventDefault()
              return
            }
            setLeaving(true)
            followSsoLink(event, next)
          }}
          ref={linkRef}
        >
          {leaving ? <Spinner /> : <KeyRound aria-hidden="true" />}
          Sign in with SSO
        </a>
      </Button>
      <p className="text-center text-sm text-muted">
        {leaving
          ? 'Taking you to your organisation’s sign-in page…'
          : 'You’ll continue to your organisation’s sign-in page.'}
      </p>
    </div>
  )
}
