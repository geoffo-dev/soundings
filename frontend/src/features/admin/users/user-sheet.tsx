import { Link } from '@tanstack/react-router'
import { History, KeyRound, UserRoundX } from 'lucide-react'
import { useState } from 'react'

import { isNotFound, useAdminUser, useUpdateAdminUser } from '@/api/admin'
import { describeError, hasErrorCode } from '@/api/errors'
import type { AdminUser } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
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
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toaster'
import { useCurrentUser } from '@/features/auth/current-user'
import { focusRow } from '@/lib/return-to-row'

import { ConfirmDialog } from '@/features/admin/confirm-dialog'
import { validateEmail } from './add-user-dialog'
import { UserBadges, isSystemAccount } from './user-badges'
import { UserGroups, UserProjectAccess } from './user-access'
import { UserSignIn } from './user-sign-in'

const NOT_FOR_YOURSELF = 'You can’t change this for yourself. Ask another platform admin.'

/**
 * One user (contract-phase2 §3.4), in a sheet over the users list: profile,
 * platform admin, where their project access comes from (direct or via a
 * group), groups with provenance, linked SSO accounts, external IDs, sessions,
 * and deactivate / reactivate. Closing returns to the list as it was.
 */
export function UserSheet({ userId, onClose }: { userId: string; onClose: () => void }) {
  const query = useAdminUser(userId)
  const user = query.data
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        size="lg"
        aria-describedby={undefined}
        // Back to this user's row in the list (it stays rendered under the sheet).
        onCloseAutoFocus={(event) => {
          if (focusRow(userId)) event.preventDefault()
        }}
      >
        {user ? (
          <UserDetail key={user.id} user={user} />
        ) : query.isError ? (
          <>
            <SheetHeader>
              <SheetTitle>
                {isNotFound(query.error) ? 'User not found' : 'Couldn’t load'}
              </SheetTitle>
            </SheetHeader>
            <SheetBody>
              <EmptyState
                role="alert"
                size="compact"
                icon={<UserRoundX />}
                title={
                  isNotFound(query.error) ? 'We couldn’t find that user' : 'Couldn’t load this user'
                }
                description={
                  isNotFound(query.error)
                    ? 'The link may be out of date.'
                    : describeError(query.error).title
                }
                action={
                  isNotFound(query.error) ? (
                    <Button variant="secondary" onClick={onClose}>
                      Back to users
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={() => void query.refetch()}>
                      Try again
                    </Button>
                  )
                }
              />
            </SheetBody>
          </>
        ) : (
          <UserSheetSkeleton />
        )}
      </SheetContent>
    </Sheet>
  )
}

function UserSheetSkeleton() {
  return (
    <>
      <SheetHeader>
        <SheetTitle className="sr-only">Loading user</SheetTitle>
        <div className="flex items-center gap-3">
          <Skeleton className="size-10 rounded-full" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-52" />
          </div>
        </div>
      </SheetHeader>
      <SheetBody>
        <SkeletonGroup label="Loading user" className="flex flex-col gap-6">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-2">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-4/5" />
            </div>
          ))}
        </SkeletonGroup>
      </SheetBody>
    </>
  )
}

function UserDetail({ user }: { user: AdminUser }) {
  const me = useCurrentUser()
  const isMe = user.id === me.id
  const system = isSystemAccount(user)
  const [confirm, setConfirm] = useState<
    'deactivate' | 'reactivate' | 'grant-admin' | 'revoke-admin' | null
  >(null)
  const update = useUpdateAdminUser(user.id)
  const name = user.display_name

  const setActive = (active: boolean) =>
    update.mutate(
      { is_active: active },
      {
        onSuccess: () => {
          setConfirm(null)
          toast.success(active ? `${name} reactivated` : `${name} deactivated`, {
            description: active
              ? 'They can sign in again; their groups and project roles apply again.'
              : 'They’re signed out everywhere and can’t sign in.',
          })
        },
        onError: () => setConfirm(null),
      },
    )

  const setAdmin = (admin: boolean) =>
    update.mutate(
      { is_platform_admin: admin },
      {
        onSuccess: () => {
          setConfirm(null)
          toast.success(
            admin ? `${name} is now a platform admin` : `${name} is no longer a platform admin`,
          )
        },
        onError: () => setConfirm(null),
      },
    )

  const adminLock = isMe
    ? NOT_FOR_YOURSELF
    : system
      ? 'System accounts keep their admin rights.'
      : !user.is_active
        ? 'Reactivate them first.'
        : null

  return (
    <>
      <SheetHeader>
        <div className="flex items-center gap-3">
          <Avatar
            size="lg"
            name={name}
            src={user.avatar_url}
            isAgent={user.is_service_account}
            decorative
          />
          <div className="flex min-w-0 flex-col gap-0.5">
            <SheetTitle className="truncate">
              {name}
              {isMe && <span className="font-normal text-muted"> (you)</span>}
            </SheetTitle>
            <SheetDescription className="truncate">{user.email}</SheetDescription>
          </div>
        </div>
        <div className="pt-1">
          <UserBadges user={user} showActive />
        </div>
      </SheetHeader>
      <SheetBody className="flex flex-col gap-8">
        {!user.is_active && (
          <Callout tone="neutral" title="Deactivated">
            They can’t sign in, and their groups and project roles grant nothing until they’re
            reactivated. Nothing else is removed.
          </Callout>
        )}
        {user.is_break_glass && (
          <Callout tone="warning" title="The break-glass account">
            Signs in with the credentials in the Kubernetes Secret, only while single sign-on is
            off. Every action it takes is in the audit log.
          </Callout>
        )}
        {user.is_service_account && (
          <Callout tone="neutral" title="An agent account">
            Used by an AI agent through an API key. It never signs in.
          </Callout>
        )}

        <ProfileForm user={user} system={system} />

        <section aria-labelledby="user-admin-heading" className="flex flex-col gap-3">
          <h3 id="user-admin-heading" className="text-base font-semibold text-primary">
            Platform access
          </h3>
          <div className="flex items-start justify-between gap-4 rounded-lg border px-4 py-3">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span id="user-admin-label" className="text-sm font-medium text-primary">
                Platform admin
              </span>
              <span id="user-admin-help" className="text-sm text-muted">
                Manages users, groups, every project and the audit log.
                {adminLock && <span className="block text-secondary">{adminLock}</span>}
              </span>
            </div>
            <Switch
              aria-labelledby="user-admin-label"
              aria-describedby="user-admin-help"
              checked={user.is_platform_admin}
              disabled={Boolean(adminLock) || update.isPending}
              className="mt-0.5"
              // Asks both ways: an Undo toast can't be reached while this sheet is open.
              onCheckedChange={(checked) => setConfirm(checked ? 'grant-admin' : 'revoke-admin')}
            />
          </div>
        </section>

        <UserProjectAccess user={user} />
        <UserGroups user={user} />
        <UserSignIn user={user} isMe={isMe} />
      </SheetBody>
      <SheetFooter className="justify-between">
        <div className="flex items-center gap-1">
          <Button asChild variant="ghost" size="sm" className="text-secondary">
            <Link to="/settings/audit" search={{ target: `user:${user.id}` }}>
              <History />
              Audit log
            </Link>
          </Button>
          <Button asChild variant="ghost" size="sm" className="text-secondary">
            <Link to="/settings/all-api-keys" search={{ user_id: user.id }}>
              <KeyRound />
              API keys
            </Link>
          </Button>
        </div>
        {isMe ? (
          <p className="text-sm text-muted">You can’t deactivate yourself.</p>
        ) : user.is_active ? (
          <Button
            variant="outline"
            size="sm"
            className="text-danger"
            onClick={() => setConfirm('deactivate')}
          >
            Deactivate…
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setConfirm('reactivate')}>
            Reactivate…
          </Button>
        )}
      </SheetFooter>

      <ConfirmDialog
        open={confirm === 'deactivate'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Deactivate ${name}?`}
        description="They’re signed out everywhere now and can’t sign in by any method until reactivated."
        confirmLabel="Deactivate"
        tone="danger"
        pending={update.isPending}
        onConfirm={() => setActive(false)}
      >
        Their groups, project roles and ideas stay, but grant nothing while they’re deactivated.
        Their API keys are revoked for good. Use this when someone leaves.
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'reactivate'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Reactivate ${name}?`}
        description="They can sign in again, and their groups and project roles apply again."
        confirmLabel="Reactivate"
        pending={update.isPending}
        onConfirm={() => setActive(true)}
      />
      <ConfirmDialog
        open={confirm === 'grant-admin'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Make ${name} a platform admin?`}
        description="They’ll be able to manage users, groups and every project, and read the audit log."
        confirmLabel="Make platform admin"
        pending={update.isPending}
        onConfirm={() => setAdmin(true)}
      />
      <ConfirmDialog
        open={confirm === 'revoke-admin'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Remove ${name}’s platform admin rights?`}
        description="They keep their project roles and groups, but can no longer manage users, groups, every project or the audit log."
        confirmLabel="Remove admin rights"
        pending={update.isPending}
        onConfirm={() => setAdmin(false)}
      />
    </>
  )
}

function ProfileForm({ user, system }: { user: AdminUser; system: boolean }) {
  const update = useUpdateAdminUser(user.id, { silent: true })
  const [name, setName] = useState(user.display_name)
  const [email, setEmail] = useState(user.email)
  const [errors, setErrors] = useState<{ name?: string; email?: string; form?: string }>({})
  // Saved elsewhere (or by this form): start again from the server's values.
  const [saved, setSaved] = useState({ name: user.display_name, email: user.email })
  if (saved.name !== user.display_name || saved.email !== user.email) {
    setSaved({ name: user.display_name, email: user.email })
    setName(user.display_name)
    setEmail(user.email)
  }
  const dirty = name.trim() !== user.display_name || email.trim() !== user.email

  const submit = () => {
    if (!dirty || update.isPending) return
    const found = {
      name: name.trim() ? undefined : 'Enter their name',
      email: system ? undefined : validateEmail(email),
    }
    if (found.name ?? found.email) {
      setErrors(found)
      return
    }
    setErrors({})
    update.mutate(
      {
        display_name: name.trim() !== user.display_name ? name.trim() : undefined,
        email: !system && email.trim() !== user.email ? email.trim() : undefined,
      },
      {
        onSuccess: () => toast.success('Profile saved'),
        onError: (error) => {
          if (hasErrorCode(error, 'email_taken')) {
            setErrors({ email: 'Someone else already has this email address.' })
          } else if (hasErrorCode(error, 'validation_error')) {
            setErrors({ email: error.fieldErrors.email, name: error.fieldErrors.display_name })
          } else {
            const { title, description } = describeError(error)
            setErrors({ form: description ? `${title}. ${description}` : title })
          }
        },
      },
    )
  }

  return (
    <section aria-labelledby="user-profile-heading" className="flex flex-col gap-3">
      <h3 id="user-profile-heading" className="text-base font-semibold text-primary">
        Profile
      </h3>
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        {errors.form && <Callout role="alert" tone="danger" title={errors.form} />}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" error={errors.name}>
            <Input
              value={name}
              maxLength={100}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field
            label="Email"
            error={errors.email}
            description={system ? 'System accounts keep their address.' : undefined}
          >
            <Input
              type="email"
              value={email}
              maxLength={320}
              autoComplete="off"
              spellCheck={false}
              disabled={system}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
        </div>
        <p className="text-sm text-muted">Sign-in doesn’t overwrite these; edit them here.</p>
        {dirty && (
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setName(user.display_name)
                setEmail(user.email)
                setErrors({})
              }}
            >
              Discard
            </Button>
            <Button type="submit" variant="secondary" size="sm" loading={update.isPending}>
              Save profile
            </Button>
          </div>
        )}
      </form>
    </section>
  )
}
