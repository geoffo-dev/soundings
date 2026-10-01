import { CircleAlert, FileText, Pencil } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

import { describeError } from '@/api/errors'
import { useUpdateIdea } from '@/api/ideas'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/ui/markdown'
import { WithTooltip } from '@/components/ui/tooltip'

import { useIdeaPage } from './idea-context'
import { MarkdownEditor } from './markdown-editor'

export const DESCRIPTION_LIMIT = 50_000

/**
 * The idea's description: rendered Markdown, click "Edit" (or the empty
 * state's "Add details") for a Write / Preview editor. ⌘/Ctrl+Enter saves,
 * Esc cancels; a failed save keeps the editor open with the error.
 */
export function DescriptionSection() {
  const { idea, ideaKey } = useIdeaPage()
  const update = useUpdateIdea(ideaKey)
  const canEdit = idea.permissions.can_edit
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const errorId = useId()
  const description = idea.description_md.trim()
  // Closing the editor removes the focused field: go back to "Edit" (or "Add details").
  const editButtonRef = useRef<HTMLButtonElement>(null)
  const refocus = useRef(false)
  useEffect(() => {
    if (editing || !refocus.current) return
    refocus.current = false
    editButtonRef.current?.focus()
  }, [editing])

  const start = () => {
    setDraft(idea.description_md)
    setError(null)
    setEditing(true)
  }
  const cancel = () => {
    refocus.current = true
    setEditing(false)
    setError(null)
  }
  const save = () => {
    if (draft.trim() === description) {
      cancel()
      return
    }
    update.mutate(
      { description_md: draft.trim() },
      {
        onSuccess: cancel,
        onError: (failure) => {
          const { title, description: detail } = describeError(failure)
          setError(detail ? `${title}. ${detail}` : title)
        },
      },
    )
  }

  return (
    <section aria-labelledby="idea-description-heading" className="flex flex-col gap-2">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h2 id="idea-description-heading" className="text-sm font-medium text-muted">
          Description
        </h2>
        {canEdit && !editing && description && (
          <WithTooltip content="Edit description">
            <Button
              ref={editButtonRef}
              variant="ghost"
              size="icon-sm"
              aria-label="Edit description"
              onClick={start}
            >
              <Pencil />
            </Button>
          </WithTooltip>
        )}
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <MarkdownEditor
            label="Description"
            value={draft}
            onValueChange={setDraft}
            onSubmit={save}
            onCancel={cancel}
            maxLength={DESCRIPTION_LIMIT}
            minRows={6}
            maxRows={24}
            focusOnMount
            invalid={Boolean(error)}
            describedBy={error ? errorId : undefined}
            placeholder="Who is it for? What changes? What would it take?"
            actions={
              <>
                <Button size="sm" variant="ghost" onClick={cancel}>
                  Cancel
                </Button>
                <Button size="sm" variant="primary" onClick={save} loading={update.isPending}>
                  Save
                </Button>
              </>
            }
          />
          {error && (
            <p id={errorId} role="alert" className="flex items-start gap-1.5 text-sm text-danger">
              <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
              {error}
            </p>
          )}
        </div>
      ) : description ? (
        <Markdown>{idea.description_md}</Markdown>
      ) : canEdit ? (
        <button
          ref={editButtonRef}
          type="button"
          onClick={start}
          className="flex items-center gap-2 rounded-lg border border-dashed px-4 py-5 text-left text-sm text-muted transition-colors hover:border-strong hover:text-primary"
        >
          <FileText aria-hidden="true" className="size-4 shrink-0" />
          <span>
            <span className="font-medium text-primary">Add details</span> — who it’s for, what
            changes and what it would take.
          </span>
        </button>
      ) : (
        <p className="text-sm text-muted">No details yet.</p>
      )}
    </section>
  )
}
