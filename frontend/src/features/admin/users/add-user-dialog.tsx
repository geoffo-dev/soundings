import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { useCreateAdminUser, useSsoConfig } from '@/api/admin'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { KbdShortcut } from '@/components/ui/kbd'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toaster'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import {
  ExternalIdsEditor,
  newRow,
  serverRowErrors,
  validateExternalIds,
  type ExternalIdRow,
  type RowErrors,
} from './external-ids'

const EMAIL_ID = 'add-user-email'

interface FormErrors {
  email?: string
  display_name?: string
  external_ids?: string
  form?: string
}

/** Something@something, not under the reserved `.invalid` domain (contract-phase2 §3.4). */
export function validateEmail(value: string): string | undefined {
  const email = value.trim()
  if (!email) return 'Enter an email address'
  if (!/^[^@\s]+@[^@\s]+$/.test(email)) return 'Enter an email address like name@example.com'
  if (/\.invalid$/i.test(email)) return 'Addresses under .invalid are reserved for system accounts'
  return undefined
}

/**
 * "Add user" (contract-phase2 §3.4): pre-create someone so their first SSO
 * sign-in links to this account by external ID or verified email. Opens the new
 * user's sheet when done.
 */
export function AddUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="lg"
        mobile="fullscreen"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          document.getElementById(EMAIL_ID)?.focus()
        }}
      >
        {/* Mounted per opening: every new user starts from a blank form. */}
        {open && <AddUserForm onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function AddUserForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate()
  const create = useCreateAdminUser()
  const sso = useSsoConfig()
  const kind = sso.data?.external_id_kind ?? undefined
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [admin, setAdmin] = useState(false)
  const [rows, setRows] = useState<ExternalIdRow[]>(() => (kind ? [newRow(kind)] : []))
  const [errors, setErrors] = useState<FormErrors>({})
  const [rowErrors, setRowErrors] = useState<RowErrors>({})
  // The configured kind arrives after the form opened: offer it in an empty first row.
  const [offeredKind, setOfferedKind] = useState(kind)
  if (kind && kind !== offeredKind) {
    setOfferedKind(kind)
    if (rows.length === 0) setRows([newRow(kind)])
  }

  const submit = () => {
    if (create.isPending) return
    const found: FormErrors = {
      email: validateEmail(email),
      display_name: name.trim() ? undefined : 'Enter their name',
    }
    const ids = validateExternalIds(rows)
    setRowErrors(ids.errors)
    if (found.email ?? found.display_name ?? Object.keys(ids.errors).length) {
      setErrors(found)
      if (found.email) document.getElementById(EMAIL_ID)?.focus()
      else if (found.display_name) document.getElementById('add-user-name')?.focus()
      return
    }
    setErrors({})
    create.mutate(
      {
        email: email.trim(),
        display_name: name.trim(),
        is_platform_admin: admin,
        external_ids: ids.ids,
      },
      {
        onSuccess: (user) => {
          onDone()
          toast.success(`${user.display_name} added`, {
            description: 'Their account is linked at their first SSO sign-in.',
          })
          void navigate({
            to: '/settings/users/$userId',
            params: { userId: user.id },
            search: true,
          })
        },
        onError: (error) => {
          if (hasErrorCode(error, 'email_taken')) {
            setErrors({ email: 'Someone already has this email address.' })
            document.getElementById(EMAIL_ID)?.focus()
          } else if (hasErrorCode(error, 'external_id_taken')) {
            setErrors({
              external_ids:
                'Another person already has one of these external IDs. Each ID belongs to one person.',
            })
          } else if (isApiError(error) && error.status === 422) {
            const fields = error.fieldErrors
            setErrors({ email: fields.email, display_name: fields.display_name })
            setRowErrors(serverRowErrors(error, rows))
          } else {
            const { title, description } = describeError(error)
            setErrors({ form: description ? `${title}. ${description}` : title })
          }
        },
      },
    )
  }

  useShortcut('submitForm', submit)

  return (
    <form
      noValidate
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <DialogHeader>
        <DialogTitle>Add user</DialogTitle>
        <DialogDescription>
          Add someone before their first sign-in. Their SSO account is linked by external ID or
          verified email; access comes from groups and project roles.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-5">
        {errors.form && <Callout role="alert" tone="danger" title={errors.form} />}
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Email" required error={errors.email} id={EMAIL_ID}>
            <Input
              type="email"
              value={email}
              maxLength={320}
              autoComplete="off"
              spellCheck={false}
              placeholder="name@example.com"
              onChange={(event) => {
                setEmail(event.target.value)
                if (errors.email) setErrors((e) => ({ ...e, email: undefined }))
              }}
            />
          </Field>
          <Field label="Name" required error={errors.display_name} id="add-user-name">
            <Input
              value={name}
              maxLength={100}
              autoComplete="off"
              placeholder="Lena Novak"
              onChange={(event) => {
                setName(event.target.value)
                if (errors.display_name) setErrors((e) => ({ ...e, display_name: undefined }))
              }}
            />
          </Field>
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-primary">External IDs</legend>
          <p className="text-sm text-muted">
            {sso.data?.external_id_claim && kind ? (
              <>
                Sign-in links this account when the identity provider’s{' '}
                <code className="font-mono text-secondary">{sso.data.external_id_claim}</code> claim
                equals their <code className="font-mono text-secondary">{kind}</code> ID. Safer than
                email for platform admins.
              </>
            ) : (
              'Optional IDs from other systems, e.g. an employee number.'
            )}
          </p>
          {errors.external_ids && (
            <p role="alert" className="text-sm text-danger">
              {errors.external_ids}
            </p>
          )}
          <ExternalIdsEditor
            rows={rows}
            onChange={(next) => {
              setRows(next)
              if (Object.keys(rowErrors).length) setRowErrors({})
              if (errors.external_ids) setErrors((e) => ({ ...e, external_ids: undefined }))
            }}
            errors={rowErrors}
            kindPlaceholder={kind ?? 'employee_no'}
          />
        </fieldset>
        <Field
          inline
          label="Platform admin"
          description="Can manage users, groups, every project and the audit log. Give this to as few people as possible."
        >
          <Switch checked={admin} onCheckedChange={setAdmin} />
        </Field>
      </DialogBody>
      <DialogFooter className="pt-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Add user
          <KbdShortcut keys={SHORTCUTS.submitForm.keys} tone="accent" />
        </Button>
      </DialogFooter>
    </form>
  )
}
