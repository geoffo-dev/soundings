import { useNavigate } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { useBreakGlassLogin } from '@/api/auth'
import { isApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

import { safeNextPath } from './session'

/** "about 12 minutes", "about a minute", "a few seconds". */
export function waitDescription(seconds: number): string {
  if (seconds < 45) return 'a few seconds'
  const minutes = Math.round(seconds / 60)
  return minutes <= 1 ? 'about a minute' : `about ${minutes} minutes`
}

interface FormProblem {
  title: string
  description?: string
}

/** What the form says for each answer of `POST /auth/break-glass` (contract-phase2 §2). */
export function breakGlassProblem(error: unknown): FormProblem {
  if (!isApiError(error)) {
    return { title: 'Something went wrong', description: 'Please try again.' }
  }
  switch (error.code) {
    case 'invalid_credentials':
      return {
        title: 'That username and password don’t match',
        description: 'Check both and try again. They come from the break-glass Secret.',
      }
    case 'too_many_attempts':
      return {
        title: 'Too many attempts',
        description: `For safety, sign-in is paused for ${waitDescription(
          error.retryAfterSeconds ?? 15 * 60,
        )}. Try again then.`,
      }
    case 'account_disabled':
      return {
        title: 'The break-glass account is deactivated',
        description: 'Another platform admin can reactivate it in Admin settings → Users.',
      }
    case 'not_found':
      return {
        title: 'Break-glass sign-in is off',
        description:
          'Single sign-on may have been configured. Reload the page to see how to sign in.',
      }
    case 'network_error':
      return {
        title: 'Can’t reach the server',
        description: 'Check your connection and try again.',
      }
    default:
      return {
        title: 'Something went wrong on our side',
        description: 'Try again in a moment.',
      }
  }
}

/**
 * The break-glass admin form (contract-phase2 §3.8): only shown while it is
 * available (before single sign-on is configured). Credentials come from the
 * Kubernetes Secret; every attempt is audited and throttled per network address.
 */
export function BreakGlassForm({ next, headingId }: { next?: string; headingId: string }) {
  const navigate = useNavigate()
  const login = useBreakGlassLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ username?: string; password?: string }>({})
  const [lockedUntil, setLockedUntil] = useState<number | null>(null)
  const usernameRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)

  // Unlock the button when the wait is over.
  useEffect(() => {
    if (lockedUntil === null) return
    const timer = window.setTimeout(() => setLockedUntil(null), lockedUntil - Date.now())
    return () => window.clearTimeout(timer)
  }, [lockedUntil])

  const submit = () => {
    if (login.isPending || lockedUntil !== null) return
    const missing = {
      username: username ? undefined : 'Enter the username.',
      password: password ? undefined : 'Enter the password.',
    }
    setErrors(missing)
    if (missing.username) return usernameRef.current?.focus()
    if (missing.password) return passwordRef.current?.focus()
    login.mutate(
      { username, password },
      {
        onSuccess: () => void navigate({ to: safeNextPath(next), replace: true }),
        onError: (error) => {
          if (isApiError(error) && error.code === 'too_many_attempts') {
            setLockedUntil(Date.now() + (error.retryAfterSeconds ?? 15 * 60) * 1000)
          }
          if (isApiError(error) && error.code === 'invalid_credentials') {
            setPassword('')
            passwordRef.current?.focus()
          }
        },
      },
    )
  }

  const problem = login.isError ? breakGlassProblem(login.error) : null

  return (
    <form
      noValidate
      aria-labelledby={headingId}
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      {problem && (
        <Callout role="alert" tone="danger" title={problem.title}>
          {problem.description}
        </Callout>
      )}
      <Field label="Username" error={errors.username} id="break-glass-username">
        <Input
          ref={usernameRef}
          value={username}
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          maxLength={200}
          onChange={(event) => setUsername(event.target.value)}
          // The one form on the page: start typing straight away.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
        />
      </Field>
      <Field label="Password" error={errors.password} id="break-glass-password">
        <Input
          ref={passwordRef}
          type="password"
          value={password}
          autoComplete="current-password"
          maxLength={1024}
          onChange={(event) => setPassword(event.target.value)}
        />
      </Field>
      <Button
        type="submit"
        variant="primary"
        size="lg"
        loading={login.isPending}
        disabled={lockedUntil !== null || login.isPending}
        className="w-full"
      >
        Sign in
      </Button>
    </form>
  )
}
