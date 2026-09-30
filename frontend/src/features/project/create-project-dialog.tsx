import { useNavigate } from '@tanstack/react-router'
import { CircleAlert, Globe, Lock } from 'lucide-react'
import { useState } from 'react'

import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import { useCreateProject } from '@/api/projects'
import type { ProjectVisibility } from '@/api/types'
import { Button } from '@/components/ui/button'
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
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { closeDialog, useAppDialog } from '@/lib/dialogs'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import {
  LIMITS,
  suggestKey,
  suggestSlug,
  validateCreateProject,
  type CreateProjectErrors,
  type CreateProjectForm,
} from './create-project'

const NAME_ID = 'create-project-name'

const VISIBILITY: { value: ProjectVisibility; label: string; help: string; icon: typeof Lock }[] = [
  { value: 'private', label: 'Private', help: 'Only members can see it.', icon: Lock },
  {
    value: 'internal',
    label: 'Internal',
    help: 'Anyone signed in can see it.',
    icon: Globe,
  },
]

/**
 * New project (platform admins): name → suggested URL and idea key, then
 * visibility. Opened by `openCreateProject()` (sidebar, palette); mounted in
 * routes/_app.tsx. You become the project's first admin.
 */
export function CreateProjectDialog() {
  const dialog = useAppDialog()
  const open = dialog?.name === 'createProject'
  return (
    <Dialog open={open} onOpenChange={(next) => !next && closeDialog()}>
      <DialogContent
        size="lg"
        mobile="fullscreen"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          document.getElementById(NAME_ID)?.focus()
        }}
      >
        {/* Mounted per opening, so each project starts from a blank form. */}
        {open && <CreateProjectForm />}
      </DialogContent>
    </Dialog>
  )
}

function CreateProjectForm() {
  const navigate = useNavigate()
  const create = useCreateProject()
  const [form, setForm] = useState<CreateProjectForm>({
    name: '',
    slug: '',
    key: '',
    description: '',
  })
  const [visibility, setVisibility] = useState<ProjectVisibility>('private')
  // The URL and key follow the name until someone edits them.
  const [edited, setEdited] = useState({ slug: false, key: false })
  const [errors, setErrors] = useState<CreateProjectErrors>({})

  const set = (patch: Partial<CreateProjectForm>) => {
    setForm((current) => {
      const next = { ...current, ...patch }
      if (patch.name !== undefined) {
        if (!edited.slug) next.slug = suggestSlug(patch.name)
        if (!edited.key) next.key = suggestKey(patch.name)
      }
      return next
    })
    const touched = [
      ...Object.keys(patch),
      ...(patch.name !== undefined ? ['slug', 'key'] : []),
    ] as (keyof CreateProjectErrors)[]
    if (touched.some((field) => errors[field]) || errors.form) {
      setErrors((current) => {
        const next = { ...current, form: undefined }
        for (const field of touched) next[field] = undefined
        return next
      })
    }
  }

  const focusFirst = (found: CreateProjectErrors) => {
    const first = (['name', 'slug', 'key', 'description'] as const).find((field) => found[field])
    if (first) document.getElementById(`create-project-${first}`)?.focus()
  }

  const submit = () => {
    if (create.isPending) return
    const found = validateCreateProject(form)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      focusFirst(found)
      return
    }
    create.mutate(
      {
        name: form.name.trim(),
        slug: form.slug.trim(),
        key: form.key.trim(),
        description: form.description.trim(),
        visibility,
      },
      {
        onSuccess: (project) => {
          closeDialog()
          toast.success(`${project.name} created`, {
            description: 'Add members and adjust the rubric in project settings.',
          })
          void navigate({ to: '/p/$slug', params: { slug: project.slug } })
        },
        onError: (error) => {
          let found: CreateProjectErrors = {}
          if (hasErrorCode(error, 'slug_taken')) {
            found = { slug: 'Another project uses this URL. Try another.' }
          } else if (hasErrorCode(error, 'key_taken')) {
            found = { key: 'Another project uses this key. Try another.' }
          } else if (isApiError(error) && Object.keys(error.fieldErrors).length > 0) {
            found = error.fieldErrors
          } else {
            const { title, description } = describeError(error)
            found = { form: description ? `${title}. ${description}` : title }
          }
          setErrors(found)
          focusFirst(found)
        },
      },
    )
  }

  useShortcut('submitForm', submit)

  const exampleKey = form.key.trim() || 'KEY'

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
        <DialogTitle>New project</DialogTitle>
        <DialogDescription>
          A space for ideas with its own members and rubric. You’ll be its first admin.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-5">
        {errors.form && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {errors.form}
          </p>
        )}
        <Field label="Name" required error={errors.name} id={NAME_ID}>
          <Input
            value={form.name}
            maxLength={LIMITS.name}
            autoComplete="off"
            placeholder="e.g. Customer Innovation"
            onChange={(event) => set({ name: event.target.value })}
          />
        </Field>
        <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_9rem]">
          <Field
            label="URL"
            required
            error={errors.slug}
            description="Can’t be changed later."
            id="create-project-slug"
          >
            <div className="flex items-center">
              <span className="flex h-9 shrink-0 items-center rounded-l-md border border-r-0 border-input bg-subtle px-2.5 text-sm text-secondary sm:h-8">
                /p/
              </span>
              <Input
                value={form.slug}
                maxLength={LIMITS.slug}
                autoComplete="off"
                spellCheck={false}
                placeholder="customer-innovation"
                className="rounded-l-none"
                onChange={(event) => {
                  setEdited((current) => ({ ...current, slug: true }))
                  set({ slug: event.target.value.toLowerCase() })
                }}
              />
            </div>
          </Field>
          <Field
            label="Idea key"
            required
            error={errors.key}
            description={`${exampleKey}-1, ${exampleKey}-2…`}
            id="create-project-key"
          >
            <Input
              value={form.key}
              maxLength={6}
              autoComplete="off"
              spellCheck={false}
              placeholder="CUST"
              className="uppercase"
              onChange={(event) => {
                setEdited((current) => ({ ...current, key: true }))
                set({ key: event.target.value.toUpperCase() })
              }}
            />
          </Field>
        </div>
        <Field
          label="Description"
          description="Optional. One or two sentences about what belongs here."
          error={errors.description}
          id="create-project-description"
        >
          <Textarea
            value={form.description}
            maxLength={LIMITS.description}
            minRows={2}
            maxRows={5}
            onChange={(event) => set({ description: event.target.value })}
          />
        </Field>
        <Field label="Visibility">
          <RadioGroup
            value={visibility}
            onValueChange={(value) => setVisibility(value as ProjectVisibility)}
            className="gap-2 sm:grid-cols-2"
          >
            {VISIBILITY.map((option) => {
              const Icon = option.icon
              return (
                <label
                  key={option.value}
                  htmlFor={`create-visibility-${option.value}`}
                  className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent"
                >
                  <RadioGroupItem
                    id={`create-visibility-${option.value}`}
                    value={option.value}
                    className="mt-0.5"
                    aria-describedby={`create-visibility-${option.value}-help`}
                  />
                  <span className="flex flex-col gap-0.5">
                    <span className="flex items-center gap-1.5 text-sm font-medium text-primary">
                      <Icon aria-hidden="true" className="size-3.5 text-muted" />
                      {option.label}
                    </span>
                    <span
                      id={`create-visibility-${option.value}-help`}
                      className="text-sm text-muted"
                    >
                      {option.help}
                    </span>
                  </span>
                </label>
              )
            })}
          </RadioGroup>
        </Field>
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={closeDialog}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Create project
          <KbdShortcut
            keys={SHORTCUTS.submitForm.keys}
            tone="accent"
            className="ml-1 hidden sm:inline-flex"
          />
        </Button>
      </DialogFooter>
    </form>
  )
}
