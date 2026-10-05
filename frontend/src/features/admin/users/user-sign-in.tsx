import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import {
  useEndUserSessions,
  useReplaceExternalIds,
  useSsoConfig,
  useUnlinkIdentity,
} from '@/api/admin'
import { describeError, hasErrorCode } from '@/api/errors'
import type { AdminUser, LinkedIdentity } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { RelativeTime } from '@/components/ui/relative-time'
import { toast } from '@/components/ui/toaster'
import { formatDate } from '@/lib/dates'

import { ConfirmDialog } from '@/features/admin/confirm-dialog'
import { isSystemAccount } from './user-badges'
import {
  ExternalIdsEditor,
  rowsFrom,
  sameIds,
  serverRowErrors,
  validateExternalIds,
  type ExternalIdRow,
  type RowErrors,
} from './external-ids'

function sessions(count: number): string {
  return count === 1 ? '1 session' : `${count} sessions`
}

/**
 * How the user signs in (contract-phase2 §3.3, §3.4): linked SSO accounts
 * (issuer + subject; unlink ends their SSO sessions), external IDs that link a
 * pre-created account at first sign-in, and live sessions ("Sign out everywhere").
 */
export function UserSignIn({ user, isMe }: { user: AdminUser; isMe: boolean }) {
  return (
    <section aria-labelledby="user-sign-in-heading" className="flex flex-col gap-6">
      <div className="flex flex-col gap-0.5">
        <h3 id="user-sign-in-heading" className="text-base font-semibold text-primary">
          Sign-in
        </h3>
        <p className="text-sm text-muted">
          The SSO account linked to them, and the IDs that link it at first sign-in.
        </p>
      </div>
      <Identities user={user} />
      {!isSystemAccount(user) && <ExternalIds user={user} />}
      <Sessions user={user} isMe={isMe} />
    </section>
  )
}

function Identities({ user }: { user: AdminUser }) {
  const unlink = useUnlinkIdentity(user.id)
  const [pending, setPending] = useState<LinkedIdentity | null>(null)

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-sm font-medium text-primary">Linked SSO account</h4>
      {user.identities.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted">
          {user.is_break_glass || user.is_service_account
            ? 'System accounts never sign in with SSO.'
            : 'Not linked yet. Their first SSO sign-in links an account by external ID or verified email.'}
        </p>
      ) : (
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border">
          {user.identities.map((identity) => (
            <li
              key={identity.id}
              className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start"
            >
              <dl className="grid min-w-0 flex-1 grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
                <dt className="text-muted">Issuer</dt>
                <dd
                  className="truncate font-mono text-xs leading-5 text-secondary"
                  title={identity.issuer}
                >
                  {identity.issuer}
                </dd>
                <dt className="text-muted">Subject</dt>
                <dd
                  className="truncate font-mono text-xs leading-5 text-secondary"
                  title={identity.subject}
                >
                  {identity.subject}
                </dd>
                <dt className="text-muted">Last sign-in</dt>
                <dd className="text-secondary">
                  {identity.last_login_at ? (
                    <RelativeTime date={identity.last_login_at} />
                  ) : (
                    'Never'
                  )}
                  <span className="text-muted"> · linked {formatDate(identity.linked_at)}</span>
                </dd>
              </dl>
              <Button
                variant="ghost"
                size="sm"
                className="self-start text-secondary"
                onClick={() => setPending(identity)}
              >
                Unlink…
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Unlink this SSO account?"
        description={`${user.display_name}’s SSO sessions end now. Their next sign-in is matched again by external ID or verified email.`}
        confirmLabel="Unlink"
        tone="danger"
        pending={unlink.isPending}
        onConfirm={() => {
          if (!pending) return
          unlink.mutate(pending.id, {
            onSuccess: () => {
              setPending(null)
              toast.success('SSO account unlinked', {
                description: `${user.display_name}’s SSO sessions have ended.`,
              })
            },
            onError: () => setPending(null),
          })
        }}
      >
        Use this when their identity provider account was recreated, or linked to the wrong person.
      </ConfirmDialog>
    </div>
  )
}

function ExternalIds({ user }: { user: AdminUser }) {
  const sso = useSsoConfig()
  const replace = useReplaceExternalIds(user.id)
  const [rows, setRows] = useState<ExternalIdRow[]>(() => rowsFrom(user.external_ids))
  const [errors, setErrors] = useState<RowErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  // Saved (here or elsewhere): start again from the server's list.
  const savedKey = user.external_ids.map((id) => `${id.kind}=${id.value}`).join('\n')
  const [seenKey, setSeenKey] = useState(savedKey)
  if (seenKey !== savedKey) {
    setSeenKey(savedKey)
    setRows(rowsFrom(user.external_ids))
  }
  const dirty = !sameIds(rows, user.external_ids)
  const kind = sso.data?.external_id_kind ?? null
  const claim = sso.data?.external_id_claim ?? null

  const save = () => {
    if (replace.isPending) return
    const checked = validateExternalIds(rows)
    setErrors(checked.errors)
    setFormError(null)
    if (Object.keys(checked.errors).length) return
    replace.mutate(checked.ids, {
      onSuccess: () => toast.success('External IDs saved'),
      onError: (error) => {
        if (hasErrorCode(error, 'external_id_taken')) {
          setFormError(
            'Another person already has one of these IDs. Each ID belongs to one person.',
          )
        } else if (hasErrorCode(error, 'validation_error')) {
          setErrors(serverRowErrors(error, rows))
        } else {
          const { title, description } = describeError(error)
          setFormError(description ? `${title}. ${description}` : title)
        }
      },
    })
  }

  return (
    <form
      noValidate
      className="flex flex-col gap-2"
      aria-labelledby="user-external-ids-heading"
      onSubmit={(event) => {
        event.preventDefault()
        save()
      }}
    >
      <h4 id="user-external-ids-heading" className="text-sm font-medium text-primary">
        External IDs
      </h4>
      <p className="text-sm text-muted">
        {claim && kind ? (
          <>
            Sign-in links this account when the{' '}
            <code className="font-mono text-secondary">{claim}</code> claim equals their{' '}
            <code className="font-mono text-secondary">{kind}</code>. Someone with an ID of that
            kind is never linked by email.
          </>
        ) : (
          'IDs from other systems, e.g. an employee number. External-ID matching is off in the SSO settings.'
        )}
      </p>
      {formError && <Callout role="alert" tone="danger" title={formError} />}
      <ExternalIdsEditor
        rows={rows}
        onChange={(next) => {
          setRows(next)
          if (Object.keys(errors).length) setErrors({})
          setFormError(null)
        }}
        errors={errors}
        kindPlaceholder={kind ?? 'employee_no'}
      />
      {dirty && (
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setRows(rowsFrom(user.external_ids))
              setErrors({})
              setFormError(null)
            }}
          >
            Discard
          </Button>
          <Button type="submit" variant="secondary" size="sm" loading={replace.isPending}>
            Save external IDs
          </Button>
        </div>
      )}
    </form>
  )
}

function Sessions({ user, isMe }: { user: AdminUser; isMe: boolean }) {
  const end = useEndUserSessions(user.id)
  const [confirming, setConfirming] = useState(false)
  const count = user.active_session_count

  const run = () =>
    end.mutate(undefined, {
      onSuccess: () => {
        setConfirming(false)
        toast.success(
          isMe
            ? 'You were signed out everywhere'
            : `${user.display_name} was signed out everywhere`,
          {
            description: `${sessions(count)} ended. Group changes apply at their next sign-in.`,
          },
        )
      },
      onError: () => setConfirming(false),
    })

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-sm font-medium text-primary">Sessions</h4>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
        <p className="text-sm text-secondary">
          {count === 0
            ? 'Not signed in anywhere.'
            : `Signed in on ${count === 1 ? '1 browser' : `${count} browsers`}.`}
        </p>
        {count > 0 && (
          <Button variant="outline" size="sm" onClick={() => setConfirming(true)}>
            Sign out everywhere
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={isMe ? 'Sign yourself out everywhere?' : `Sign ${user.display_name} out everywhere?`}
        description={
          isMe
            ? 'This ends this session too: you’ll go to the sign-in page.'
            : `Their ${sessions(count)} end now; group changes apply at their next sign-in.`
        }
        confirmLabel="Sign out everywhere"
        pending={end.isPending}
        onConfirm={run}
      >
        {/* contract-phase5 §2: ending sessions doesn't stop API keys. */}
        API keys keep working.{' '}
        <Link
          to="/settings/all-api-keys"
          search={{ user_id: user.id }}
          className="text-accent underline-offset-4 hover:underline"
        >
          {isMe ? 'Review your keys' : 'Review their keys'}
        </Link>{' '}
        to revoke any that should stop too.
      </ConfirmDialog>
    </div>
  )
}
