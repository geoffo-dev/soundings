import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { useCreateGroup } from '@/api/admin'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import type { GroupSyncMode } from '@/api/types'
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
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import { IdpValuesInput, SyncModeField } from './mapping-fields'

const NAME_ID = 'create-group-name'

/**
 * New group (contract-phase2 §3.5): a name, an optional description, and
 * optionally the identity-provider groups it follows. Opens the group when done
 * (members and project roles are added there and in project settings).
 */
export function CreateGroupDialog({
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
          document.getElementById(NAME_ID)?.focus()
        }}
      >
        {open && <CreateGroupForm onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function CreateGroupForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate()
  const create = useCreateGroup()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [syncMode, setSyncMode] = useState<GroupSyncMode>('managed')
  const [values, setValues] = useState<string[]>([])
  const [errors, setErrors] = useState<{ name?: string; idp_values?: string; form?: string }>({})

  const submit = () => {
    if (create.isPending) return
    if (!name.trim()) {
      setErrors({ name: 'Give the group a name' })
      document.getElementById(NAME_ID)?.focus()
      return
    }
    setErrors({})
    create.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        sync_mode: syncMode,
        idp_values: values,
      },
      {
        onSuccess: (group) => {
          onDone()
          toast.success(`${group.name} created`, {
            description: 'Give it a role in a project from that project’s Members settings.',
          })
          void navigate({ to: '/settings/groups/$groupId', params: { groupId: group.id } })
        },
        onError: (error) => {
          if (hasErrorCode(error, 'group_name_taken')) {
            setErrors({ name: 'A group with this name already exists.' })
            document.getElementById(NAME_ID)?.focus()
          } else if (isApiError(error) && error.status === 422) {
            const fields = error.fieldErrors
            const valueError = error.problem?.errors?.find((e) => e.loc.includes('idp_values'))
            setErrors({ name: fields.name, idp_values: valueError?.msg })
          } else {
            const { title, description: detail } = describeError(error)
            setErrors({ form: detail ? `${title}. ${detail}` : title })
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
        <DialogTitle>New group</DialogTitle>
        <DialogDescription>
          Give project roles to many people at once. Map it to your identity provider’s groups to
          keep members in sync at sign-in, or add people by hand.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-5">
        {errors.form && <Callout role="alert" tone="danger" title={errors.form} />}
        <Field label="Name" required error={errors.name} id={NAME_ID}>
          <Input
            value={name}
            maxLength={80}
            autoComplete="off"
            placeholder="e.g. Innovation members"
            onChange={(event) => {
              setName(event.target.value)
              if (errors.name) setErrors((e) => ({ ...e, name: undefined }))
            }}
          />
        </Field>
        <Field label="Description">
          <Textarea
            value={description}
            maxLength={500}
            rows={2}
            placeholder="Who is in it, and why"
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Field
          label="Identity provider groups"
          description="Optional. Members of any of these groups join at their next sign-in. Keycloak paths work with or without the leading slash."
          error={errors.idp_values}
        >
          <IdpValuesInput value={values} onChange={setValues} />
        </Field>
        <Field label="Sync">
          <SyncModeField value={syncMode} onChange={setSyncMode} idPrefix="create-group-sync" />
        </Field>
      </DialogBody>
      <DialogFooter className="pt-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Create group
          <KbdShortcut keys={SHORTCUTS.submitForm.keys} tone="accent" />
        </Button>
      </DialogFooter>
    </form>
  )
}
