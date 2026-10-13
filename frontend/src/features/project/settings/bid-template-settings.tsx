import { CircleAlert, Info } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useBidTemplate, useReplaceBidTemplate } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { BidTemplate, Project } from '@/api/types'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import {
  hasErrors,
  isDirty,
  serverErrors,
  toDraft,
  toTemplateIn,
  validateTemplate,
  type TemplateDraft,
  type TemplateErrors,
} from '@/features/bids/bid-template'
import { BidTemplateFields, BidTemplateSummary, fieldId } from '@/features/bids/bid-template-fields'
import { formatShortDate } from '@/lib/dates'
import { useShortcut } from '@/lib/shortcuts'

import { LoadError } from './proposal-template-editor'
import { FormActions, SettingsSection } from './settings-layout'

const TITLE = 'Bid evaluation template'
const DESCRIPTION =
  'How bids are evaluated in this project: weighted sections of questions, the must-haves every bid needs, and what each score means. A new call for bids copies it; calls already started keep their own copy.'

/**
 * Project settings → Bids (contract-phase10 §4.1): the project's default bid evaluation
 * template. Project and platform admins edit it (session only); everyone else reads it.
 */
export function BidTemplateSettings({ project, active }: { project: Project; active: boolean }) {
  const template = useBidTemplate(project.slug)
  if (template.isPending) return <TemplateSkeleton />
  if (template.isError) {
    return (
      <SettingsSection title={TITLE} description={DESCRIPTION}>
        <LoadError what="the bid template" onRetry={() => void template.refetch()} />
      </SettingsSection>
    )
  }
  if (!template.data.can_edit) {
    return (
      <SettingsSection
        title={TITLE}
        description="How bids are evaluated in this project. Only project admins can change it."
      >
        <BidTemplateSummary draft={toDraft(template.data)} />
      </SettingsSection>
    )
  }
  return <TemplateForm slug={project.slug} template={template.data} active={active} />
}

function TemplateForm({
  slug,
  template,
  active,
}: {
  slug: string
  template: BidTemplate
  active: boolean
}) {
  const replace = useReplaceBidTemplate(slug)
  const [baseline, setBaseline] = useState(template)
  const [draft, setDraft] = useState<TemplateDraft>(() => toDraft(template))
  const [submitted, setSubmitted] = useState(false)
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const [server, setServer] = useState<TemplateErrors | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const saved = useMemo(() => toDraft(baseline), [baseline])

  if (template !== baseline) {
    // Saved elsewhere: follow the server unless there are edits here.
    if (!isDirty(draft, saved)) setDraft(toDraft(template))
    setBaseline(template)
  }

  const dirty = isDirty(draft, saved)
  const local = validateTemplate(draft)
  const error = (key: string) =>
    server?.fields[key] ?? (submitted || touched.has(key) ? local.fields[key] : undefined)

  const change = (next: TemplateDraft) => {
    setNotice(null)
    setServer(null)
    setDraft(next)
  }

  const discard = () => {
    setDraft(toDraft(template))
    setSubmitted(false)
    setTouched(new Set())
    setServer(null)
    setNotice(null)
  }

  const save = () => {
    if (replace.isPending) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    setSubmitted(true)
    if (hasErrors(local)) {
      const first = Object.keys(local.fields)[0]
      if (first) {
        const [row = '', field = ''] = first.split(':')
        document.getElementById(fieldId(row, field))?.focus()
      }
      return
    }
    replace.mutate(toTemplateIn(draft), {
      onSuccess: (next) => {
        setDraft(toDraft(next))
        setBaseline(next)
        setSubmitted(false)
        setTouched(new Set())
        toast.success('Bid template saved', {
          description: 'New calls for bids copy it. Calls already started keep theirs.',
        })
      },
      onError: (failure) => {
        const details = isApiError(failure) ? (failure.problem?.errors ?? []) : []
        if (details.length > 0) setServer(serverErrors(draft, details))
        else {
          const { title, description } = describeError(failure)
          setServer({ fields: {}, form: description ? `${title}. ${description}` : title })
        }
      },
    })
  }

  useShortcut('saveSettings', save, { enabled: active })
  const formError = server?.form ?? (submitted ? local.form : undefined)

  return (
    <SettingsSection
      title={TITLE}
      description={
        <>
          {DESCRIPTION}
          {template.updated_at && template.updated_by && (
            <>
              {' '}
              Last changed by {template.updated_by.display_name},{' '}
              {formatShortDate(template.updated_at)}.
            </>
          )}
        </>
      }
    >
      <form
        noValidate
        className="flex flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {formError && (
          <p
            role="alert"
            className="flex max-w-3xl items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {formError}
          </p>
        )}
        <BidTemplateFields
          draft={draft}
          onChange={change}
          error={error}
          onBlurField={(key) => setTouched((current) => new Set(current).add(key))}
        />
        <div className="flex max-w-3xl gap-3 rounded-lg border bg-subtle px-4 py-3 text-sm text-secondary">
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
          <p>
            Saving changes only the template new calls copy. A call already started keeps its own
            copy, which its managers can change until the first assessment is submitted.
          </p>
        </div>
        <FormActions
          form="the bid template"
          dirty={dirty}
          saving={replace.isPending}
          notice={notice}
          onDiscard={discard}
          saveLabel="Save template"
        />
      </form>
    </SettingsSection>
  )
}

function TemplateSkeleton() {
  return (
    <SkeletonGroup label="Loading the bid template" className="flex max-w-3xl flex-col gap-3">
      <Skeleton className="h-6 w-56" />
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-40 w-full rounded-lg" />
      ))}
    </SkeletonGroup>
  )
}
