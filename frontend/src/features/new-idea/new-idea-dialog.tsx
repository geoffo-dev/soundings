import { useNavigate } from '@tanstack/react-router'
import { CircleAlert } from 'lucide-react'
import { lazy, Suspense, useEffect, useId, useState } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { useCreateIdea } from '@/api/ideas'
import { useProjects, useProjectTags } from '@/api/projects'
import { ProjectTile } from '@/components/layout/project-tile'
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
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { TagInput } from '@/components/ui/tag-input'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { closeDialog, useAppDialog } from '@/lib/dialogs'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import {
  clearDraft,
  EMPTY_DRAFT,
  hasContent,
  readDraft,
  readLastProject,
  writeDraft,
  writeLastProject,
  type IdeaDraft,
} from './draft'

// The Markdown renderer is only needed for Preview: keep it out of the app shell's bundle.
const Markdown = lazy(() =>
  import('@/components/ui/markdown').then((module) => ({ default: module.Markdown })),
)

const LIMITS = { title: 200, summary: 500, description: 50_000 }
const TITLE_ID = 'new-idea-title'

type FieldName = 'title' | 'summary' | 'description' | 'tags'
type Errors = Partial<Record<FieldName | 'form', string>>

/**
 * Submit an idea (SPEC §5 screen 6, wireframe 06): opened with "n", the
 * palette, the sidebar, or `openNewIdea({ projectSlug })` from a project view.
 * Mounted once in routes/_app.tsx.
 */
export function NewIdeaDialog() {
  const dialog = useAppDialog()
  const open = dialog?.name === 'newIdea'
  return (
    <Dialog open={open} onOpenChange={(next) => !next && closeDialog()}>
      <DialogContent
        size="lg"
        mobile="fullscreen"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          document.getElementById(TITLE_ID)?.focus()
        }}
      >
        {/* Mounted per opening: it reads the draft and the project context once. */}
        <NewIdeaForm contextSlug={open ? dialog.projectSlug : undefined} />
      </DialogContent>
    </Dialog>
  )
}

function NewIdeaForm({ contextSlug }: { contextSlug?: string }) {
  const navigate = useNavigate()
  const projects = useProjects()
  const create = useCreateIdea()
  const [draft, setDraft] = useState<IdeaDraft>(readDraft)
  const [restored, setRestored] = useState(() => hasContent(draft))
  const [chosenSlug, setChosenSlug] = useState(
    () => contextSlug ?? draft.projectSlug ?? readLastProject(),
  )
  const [mode, setMode] = useState<'write' | 'preview'>('write')
  const [errors, setErrors] = useState<Errors>({})
  const [wantTags, setWantTags] = useState(false)
  const projectFieldId = useId()

  const eligible = projects.data?.filter((project) => project.permissions.can_create_ideas) ?? []
  const project = eligible.find((p) => p.slug === chosenSlug) ?? eligible[0]
  const tags = useProjectTags(wantTags ? project?.slug : undefined)

  useEffect(() => {
    writeDraft({ ...draft, projectSlug: project?.slug })
  }, [draft, project?.slug])

  const update = (patch: Partial<IdeaDraft>) => {
    setDraft((current) => ({ ...current, ...patch }))
    const fields = Object.keys(patch) as FieldName[]
    if (fields.some((field) => errors[field]) || errors.form) {
      setErrors((current) => {
        const next = { ...current, form: undefined }
        for (const field of fields) next[field] = undefined
        return next
      })
    }
  }

  const focusFirstError = (found: Errors) => {
    const order: FieldName[] = ['title', 'summary', 'description', 'tags']
    const first = order.find((field) => found[field])
    if (first) document.querySelector<HTMLElement>(`[data-new-idea-field="${first}"]`)?.focus()
  }

  const submit = () => {
    if (create.isPending || !project) return
    const found: Errors = {}
    if (!draft.title.trim()) found.title = 'Give your idea a short title.'
    if (!draft.summary.trim()) found.summary = 'Add a sentence or two: what and why.'
    if (Object.keys(found).length > 0) {
      setErrors(found)
      focusFirstError(found)
      return
    }
    create.mutate(
      {
        slug: project.slug,
        title: draft.title.trim(),
        summary: draft.summary.trim(),
        description_md: draft.description.trim(),
        tags: draft.tags,
      },
      {
        onSuccess: (idea) => {
          clearDraft()
          writeLastProject(project.slug)
          closeDialog()
          setDraft(EMPTY_DRAFT)
          void navigate({ to: '/ideas/$ideaKey', params: { ideaKey: idea.key } })
          const link = `${window.location.origin}/ideas/${idea.key}`
          toast.success(`${idea.key} created`, {
            description: idea.title,
            action: {
              label: 'Copy link',
              onClick: () =>
                void navigator.clipboard
                  .writeText(link)
                  .then(() => toast.message('Link copied'))
                  .catch(() => toast.error('Couldn’t copy the link', { description: link })),
            },
          })
        },
        onError: (error) => {
          const fieldErrors = serverFieldErrors(error)
          if (Object.keys(fieldErrors).length > 0) {
            setErrors(fieldErrors)
            focusFirstError(fieldErrors)
          } else {
            const { title, description } = describeError(error)
            setErrors({ form: description ? `${title}. ${description}` : title })
          }
        },
      },
    )
  }

  useShortcut('submitForm', submit)

  const discard = () => {
    clearDraft()
    setDraft(EMPTY_DRAFT)
    setRestored(false)
    setErrors({})
    document.getElementById(TITLE_ID)?.focus()
  }

  const noProjects = projects.isSuccess && eligible.length === 0

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <DialogHeader>
        <DialogTitle>New idea</DialogTitle>
        <DialogDescription>
          {restored ? (
            <>
              We kept your draft.{' '}
              <button
                type="button"
                onClick={discard}
                className="font-medium text-accent underline-offset-4 hover:underline"
              >
                Start over
              </button>
            </>
          ) : (
            'Only a title and a summary are needed. You can add detail later.'
          )}
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

        {projects.isPending ? (
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-16" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : noProjects ? (
          <p role="alert" className="rounded-md bg-subtle px-3 py-2 text-sm text-secondary">
            You can’t submit ideas yet. Ask a project admin to add you as a member.
          </p>
        ) : eligible.length > 1 && project ? (
          <Field label="Project" id={projectFieldId}>
            <Select value={project.slug} onValueChange={(slug) => setChosenSlug(slug)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {eligible.map((option) => (
                  <SelectItem key={option.slug} value={option.slug}>
                    <span className="flex items-center gap-2">
                      <ProjectTile name={option.name} />
                      {option.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        ) : null}

        <Field
          label="Title"
          required
          error={errors.title}
          description={
            nearLimit(draft.title, LIMITS.title) ?? 'A short name people will recognise.'
          }
          id={TITLE_ID}
        >
          <Input
            data-new-idea-field="title"
            value={draft.title}
            maxLength={LIMITS.title}
            autoComplete="off"
            placeholder="e.g. Print-free returns with a QR code"
            onChange={(event) => update({ title: event.target.value })}
          />
        </Field>

        <Field
          label="Summary"
          required
          error={errors.summary}
          description={nearLimit(draft.summary, LIMITS.summary)}
        >
          <Textarea
            data-new-idea-field="summary"
            value={draft.summary}
            maxLength={LIMITS.summary}
            minRows={2}
            maxRows={5}
            placeholder="One or two sentences: what it is and why it matters."
            onChange={(event) => update({ summary: event.target.value })}
          />
        </Field>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor="new-idea-description" className="text-sm font-medium text-primary">
              Description <span className="font-normal text-muted">(optional)</span>
            </label>
            <SegmentedControl
              size="sm"
              aria-label="Description mode"
              value={mode}
              onValueChange={setMode}
              options={[
                { value: 'write', label: 'Write' },
                { value: 'preview', label: 'Preview' },
              ]}
            />
          </div>
          {mode === 'write' ? (
            <Textarea
              id="new-idea-description"
              data-new-idea-field="description"
              value={draft.description}
              maxLength={LIMITS.description}
              minRows={5}
              maxRows={14}
              aria-describedby="new-idea-description-help"
              aria-invalid={errors.description ? true : undefined}
              placeholder="Who is it for? What changes? What would it take?"
              onChange={(event) => update({ description: event.target.value })}
            />
          ) : (
            <div
              id="new-idea-description"
              className="min-h-32 rounded-md border px-3 py-2"
              aria-live="polite"
            >
              {draft.description.trim() ? (
                <Suspense fallback={<Skeleton className="h-4 w-2/3" />}>
                  <Markdown>{draft.description}</Markdown>
                </Suspense>
              ) : (
                <p className="text-sm text-muted">Nothing to preview yet.</p>
              )}
            </div>
          )}
          <p id="new-idea-description-help" className="text-sm text-muted">
            {errors.description ?? 'Markdown works: **bold**, lists, links.'}
          </p>
        </div>

        <Field
          label="Tags"
          error={errors.tags}
          description={draft.tags.length >= 10 ? 'Up to 10 tags.' : 'Press Enter or comma to add.'}
        >
          <TagInput
            value={draft.tags}
            onValueChange={(next) => update({ tags: next })}
            suggestions={tags.data?.map((tag) => tag.name)}
            onFirstFocus={() => setWantTags(true)}
            placeholder="returns, logistics…"
          />
        </Field>
      </DialogBody>

      <DialogFooter className="pt-1">
        <p className="mr-auto text-sm text-muted max-sm:hidden" aria-live="polite">
          {project && eligible.length === 1 ? (
            <span className="inline-flex items-center gap-1.5">
              <ProjectTile name={project.name} /> {project.name}
            </span>
          ) : hasContent(draft) ? (
            'Draft saved on this device'
          ) : null}
        </p>
        <Button variant="ghost" type="button" onClick={closeDialog}>
          Cancel
        </Button>
        <Button
          variant="primary"
          type="submit"
          loading={create.isPending}
          disabled={!project || create.isPending}
          className="max-sm:h-11"
        >
          Submit idea
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

/** "180/200" once a field gets close to its limit (limits appear only when they matter). */
function nearLimit(value: string, limit: number): string | undefined {
  return value.length >= limit * 0.8 ? `${value.length}/${limit} characters` : undefined
}

/** 422 field errors keyed by form field (description_md → description). */
function serverFieldErrors(error: unknown): Errors {
  if (!isApiError(error) || error.status !== 422) return {}
  const out: Errors = {}
  for (const entry of error.problem?.errors ?? []) {
    const field = entry.loc[1]
    const message = entry.msg
    if (!message) continue
    if (field === 'title' || field === 'summary' || field === 'tags') out[field] ??= message
    if (field === 'description_md') out.description ??= message
  }
  return out
}
