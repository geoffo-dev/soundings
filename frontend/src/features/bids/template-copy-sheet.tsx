import { useState } from 'react'

import { useReplaceBidCallTemplate } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { BidCall } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { toast } from '@/components/ui/toaster'

import {
  hasErrors,
  isDirty,
  serverErrors,
  toCallTemplateIn,
  toDraft,
  validateTemplate,
  type TemplateDraft,
  type TemplateErrors,
} from './bid-template'
import { BidTemplateFields, fieldId } from './bid-template-fields'

/**
 * The call's own copy of the evaluation template (contract-phase10 §4.3), editable until
 * the first person's assessment is submitted. Removing a section or must-have takes its
 * assessors, results and document links with it; any change clears the AI's assessments
 * (they answered the old questions), which the sheet says before Save.
 */
export function TemplateCopySheet({
  ideaKey,
  call,
  open,
  onOpenChange,
}: {
  ideaKey: string
  call: BidCall
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const replace = useReplaceBidCallTemplate(ideaKey)
  const [draft, setDraft] = useState<TemplateDraft>(() => toDraft(call.template))
  const [baseline, setBaseline] = useState<TemplateDraft>(() => toDraft(call.template))
  const [submitted, setSubmitted] = useState(false)
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const [server, setServer] = useState<TemplateErrors | null>(null)
  const local = validateTemplate(draft)
  const dirty = isDirty(draft, baseline)
  const error = (key: string) =>
    server?.fields[key] ?? (submitted || touched.has(key) ? local.fields[key] : undefined)
  const formError = server?.form ?? (submitted ? local.form : undefined)

  const reset = () => {
    const fresh = toDraft(call.template)
    setDraft(fresh)
    setBaseline(fresh)
    setSubmitted(false)
    setTouched(new Set())
    setServer(null)
    replace.reset()
  }

  const save = () => {
    if (replace.isPending) return
    if (!dirty) {
      onOpenChange(false)
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
    replace.mutate(toCallTemplateIn(draft), {
      onSuccess: () => {
        toast.success('Evaluation template saved', {
          description: 'It applies to this call only.',
        })
        onOpenChange(false)
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

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (next) reset()
        onOpenChange(next)
      }}
    >
      <SheetContent size="lg">
        <SheetHeader>
          <SheetTitle>Evaluation template</SheetTitle>
          <SheetDescription>
            This call’s own copy. Changes apply to this call only, until the first assessment is
            submitted.
          </SheetDescription>
        </SheetHeader>
        <SheetBody>
          <form
            id="template-copy"
            noValidate
            className="flex flex-col gap-6"
            onSubmit={(event) => {
              event.preventDefault()
              save()
            }}
          >
            {formError && <Callout tone="danger" title={formError} role="alert" />}
            {call.bid_count > 0 && (
              <Callout
                tone="info"
                title="Saving a change clears the AI’s assessments of these bids"
              >
                They answered the old questions: ask the AI again afterwards. Removing a must-have
                unlinks its documents, which stay on the bids.
              </Callout>
            )}
            <BidTemplateFields
              draft={draft}
              onChange={(next) => {
                setServer(null)
                setDraft(next)
              }}
              error={error}
              onBlurField={(key) => setTouched((current) => new Set(current).add(key))}
            />
          </form>
        </SheetBody>
        <SheetFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="template-copy" loading={replace.isPending}>
            {dirty ? 'Save template' : 'Done'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
