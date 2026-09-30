import { CircleAlert } from 'lucide-react'
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export interface InlineTextProps {
  value: string
  /** Show the click-to-edit affordance (the API's `permissions.can_edit`). */
  canEdit: boolean
  /** Field name for labels: "Edit title", "Title". */
  label: string
  /** Saves the trimmed value; the editor closes at once and reopens with the error if it fails. */
  onSave: (value: string) => Promise<unknown>
  /** The API field name, to pick its message out of a 422 (`title`, `summary`). */
  field: string
  multiline?: boolean
  maxLength: number
  /** Message when the field is emptied (both title and summary are required). */
  requiredMessage: string
  /** The read-only rendering (an h1, a paragraph). */
  children: ReactNode
  /** Type size of the editor so it doesn't jump (e.g. `text-2xl font-semibold`). */
  editorClassName?: string
  className?: string
}

/**
 * Click-to-edit text (title, summary). Enter saves, Shift+Enter adds a line
 * (multiline), Esc cancels. The whole text is the edit target for the mouse; a
 * transparent button over it keeps it one Tab stop with a clear name.
 */
export function InlineText({
  value,
  canEdit,
  label,
  onSave,
  field,
  multiline = false,
  maxLength,
  requiredMessage,
  children,
  editorClassName,
  className,
}: InlineTextProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [error, setError] = useState<string | null>(null)
  const errorId = useId()
  const fieldRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null)

  const start = () => {
    setDraft(value)
    setError(null)
    setEditing(true)
  }
  const cancel = () => {
    setEditing(false)
    setError(null)
  }
  const save = () => {
    const next = draft.trim()
    if (!next) {
      setError(requiredMessage)
      // Back to the field the message is about (Save may have taken focus).
      fieldRef.current?.focus()
      return
    }
    setEditing(false)
    setError(null)
    if (next === value.trim()) return
    onSave(next).catch((failure: unknown) => {
      // The optimistic change was rolled back: reopen with what they typed.
      setDraft(next)
      setError(messageFor(failure, field))
      setEditing(true)
    })
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      cancel()
    } else if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      save()
    }
  }

  if (editing) {
    const common = {
      ref: fieldRef,
      value: draft,
      maxLength,
      'aria-label': label,
      'aria-invalid': error ? true : undefined,
      'aria-describedby': error ? errorId : undefined,
      onKeyDown,
      // The user just asked to edit this field.
      autoFocus: true,
      onFocus: (event: { currentTarget: HTMLInputElement | HTMLTextAreaElement }) =>
        event.currentTarget.select(),
    }
    return (
      <div className={cn('flex flex-col gap-2', className)}>
        {multiline ? (
          <Textarea
            {...common}
            minRows={2}
            maxRows={6}
            onChange={(event) => setDraft(event.target.value)}
            className={editorClassName}
          />
        ) : (
          <Input
            {...common}
            onChange={(event) => setDraft(event.target.value)}
            className={cn('h-auto py-1 sm:h-auto', editorClassName)}
          />
        )}
        {error && (
          <p id={errorId} role="alert" className="flex items-start gap-1.5 text-sm text-danger">
            <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            {error}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button size="sm" variant="primary" onClick={save}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={cancel}>
            Cancel
          </Button>
          <span className="hidden text-xs text-muted sm:inline">
            Enter to save{multiline ? ', Shift+Enter for a new line' : ''} · Esc to cancel
          </span>
        </div>
      </div>
    )
  }

  if (!canEdit) return <div className={className}>{children}</div>

  return (
    <div
      className={cn(
        'group relative -mx-2 rounded-md px-2 transition-colors duration-150 hover:bg-subtle',
        'has-[button:focus-visible]:ring-2 has-[button:focus-visible]:ring-focus',
        className,
      )}
    >
      {children}
      <button
        type="button"
        onClick={start}
        aria-label={`Edit ${label.toLowerCase()}`}
        className="absolute inset-0 cursor-text rounded-md outline-none"
      />
    </div>
  )
}

function messageFor(error: unknown, field: string): string {
  if (isApiError(error) && error.status === 422) {
    const message = error.problem?.errors?.find((item) => item.loc[1] === field)?.msg
    if (message) return message
  }
  const { title, description } = describeError(error)
  return description ? `${title}. ${description}` : title
}
