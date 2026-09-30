import { useId, useState, type ReactNode, type Ref } from 'react'

import { Markdown } from '@/components/ui/markdown'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export interface MarkdownEditorProps {
  value: string
  onValueChange: (value: string) => void
  /** ⌘/Ctrl+Enter. */
  onSubmit: () => void
  /** Esc (only while writing, so Esc in the preview doesn't discard). */
  onCancel?: () => void
  /** Accessible name of the text field. */
  label: string
  placeholder?: string
  minRows?: number
  maxRows?: number
  maxLength?: number
  disabled?: boolean
  /** Focus the text field when the editor appears (the user just asked to edit). */
  focusOnMount?: boolean
  /** Error or help text id(s) for the text field. */
  describedBy?: string
  invalid?: boolean
  textareaRef?: Ref<HTMLTextAreaElement>
  /** Buttons on the right of the toolbar (Save/Cancel, Comment). */
  actions?: ReactNode
  /** Extra text left of the actions (e.g. "⌘↵ to post"). */
  hint?: ReactNode
  className?: string
  id?: string
}

/**
 * A quiet Markdown box: the text field and a toolbar with Write / Preview and
 * the actions. ⌘/Ctrl+Enter submits, Esc cancels. Used for the description,
 * new comments and comment edits.
 */
export function MarkdownEditor({
  value,
  onValueChange,
  onSubmit,
  onCancel,
  label,
  placeholder,
  minRows = 3,
  maxRows = 16,
  maxLength,
  disabled,
  focusOnMount,
  describedBy,
  invalid,
  textareaRef,
  actions,
  hint,
  className,
  id,
}: MarkdownEditorProps) {
  const autoId = useId()
  const fieldId = id ?? `md-${autoId}`
  const [mode, setMode] = useState<'write' | 'preview'>('write')

  return (
    <div
      data-slot="markdown-editor"
      className={cn(
        'flex flex-col rounded-lg border border-input bg-surface transition-[border-color,box-shadow] duration-150',
        'has-[textarea:focus-visible]:border-focus has-[textarea:focus-visible]:ring-3 has-[textarea:focus-visible]:ring-focus/20',
        invalid && 'border-danger',
        className,
      )}
    >
      {mode === 'write' ? (
        <Textarea
          id={fieldId}
          ref={textareaRef}
          value={value}
          aria-label={label}
          aria-describedby={describedBy}
          aria-invalid={invalid ? true : undefined}
          placeholder={placeholder}
          minRows={minRows}
          maxRows={maxRows}
          maxLength={maxLength}
          disabled={disabled}
          // Focus moves here when editing starts: the user asked for the editor.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus={focusOnMount}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault()
              onSubmit()
            } else if (event.key === 'Escape' && onCancel) {
              event.preventDefault()
              event.stopPropagation()
              onCancel()
            }
          }}
          className="rounded-b-none border-0 bg-transparent px-3 py-2.5 hover:border-0 focus-visible:ring-0"
        />
      ) : (
        <div
          id={fieldId}
          role="region"
          aria-label={`${label} (preview)`}
          className="min-h-24 px-3 py-2.5"
        >
          {value.trim() ? (
            <Markdown>{value}</Markdown>
          ) : (
            <p className="text-sm text-muted">Nothing to preview yet.</p>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-subtle px-2 py-1.5">
        <SegmentedControl
          size="sm"
          aria-label={`${label}: write or preview`}
          value={mode}
          onValueChange={setMode}
          options={[
            { value: 'write', label: 'Write' },
            { value: 'preview', label: 'Preview' },
          ]}
        />
        <span className="hidden text-xs text-muted sm:inline">{hint ?? 'Markdown supported'}</span>
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>
    </div>
  )
}
