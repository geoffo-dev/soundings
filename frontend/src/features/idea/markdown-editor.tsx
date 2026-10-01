import {
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
} from 'react'
import { flushSync } from 'react-dom'

import { Markdown } from '@/components/ui/markdown'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import {
  applyShownEdit,
  mentionAt,
  removeMention,
  toShown,
  toStored,
  type MentionDraft,
} from '@/lib/mentions'
import { cn, mergeRefs } from '@/lib/utils'

import { MentionHighlights } from './mention-highlights'
import { useMentionPicker, type MentionOptions } from './mention-picker'

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
  /** Extra text left of the actions (e.g. "⌘↵ to post"); by default what the box understands. */
  hint?: ReactNode
  className?: string
  id?: string
  /**
   * @mentions: "@" opens a picker of the project's people (comments). The box
   * then shows each mention as "@Name" (tinted); `value` and `onValueChange`
   * still carry the stored text with its `@[Name](user:<id>)` tokens.
   */
  mentions?: MentionOptions
  /** Highlights mentions of this user in the preview. */
  mentionSelfId?: string
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
  mentions,
  mentionSelfId,
}: MarkdownEditorProps) {
  const autoId = useId()
  const fieldId = id ?? `md-${autoId}`
  const [mode, setMode] = useState<'write' | 'preview'>('write')
  const innerRef = useRef<HTMLTextAreaElement>(null)
  const withMentions = Boolean(mentions)
  // What the box shows: "@Name" for each token (lib/mentions).
  const draft = useMemo<MentionDraft>(
    () => (withMentions ? toShown(value) : { text: value, mentions: [] }),
    [withMentions, value],
  )
  const changeDraft = (next: MentionDraft) =>
    onValueChange(withMentions ? toStored(next) : next.text)
  const picker = useMentionPicker({
    draft,
    onDraftChange: changeDraft,
    textareaRef: innerRef,
    options: mode === 'write' ? mentions : undefined,
  })
  // The limit is on the stored text, which is longer than "@Name" by each token's id.
  const fieldMaxLength =
    maxLength === undefined ? undefined : maxLength - (value.length - draft.text.length)

  /** Backspace right after a mention (or Delete right before it) removes all of it. */
  const removeWholeMention = (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!withMentions || (event.key !== 'Backspace' && event.key !== 'Delete')) return false
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false
    const field = event.currentTarget
    if (field.selectionStart !== field.selectionEnd) return false
    const mention = mentionAt(
      draft,
      field.selectionStart,
      event.key === 'Backspace' ? 'end' : 'start',
    )
    if (!mention) return false
    event.preventDefault()
    const result = removeMention(draft, mention)
    flushSync(() => changeDraft(result.draft))
    field.setSelectionRange(result.caret, result.caret)
    picker.sync(result.draft)
    return true
  }

  return (
    <div
      data-slot="markdown-editor"
      className={cn(
        'relative flex flex-col rounded-lg border border-input bg-surface transition-[border-color,box-shadow] duration-150',
        'has-[textarea:focus-visible]:border-focus has-[textarea:focus-visible]:ring-3 has-[textarea:focus-visible]:ring-focus/20',
        invalid && 'border-danger',
        className,
      )}
    >
      {mode === 'write' ? (
        <Textarea
          id={fieldId}
          ref={mergeRefs(innerRef, textareaRef)}
          value={draft.text}
          {...picker.fieldProps}
          aria-label={label}
          aria-describedby={describedBy}
          aria-invalid={invalid ? true : undefined}
          placeholder={placeholder}
          minRows={minRows}
          maxRows={maxRows}
          maxLength={fieldMaxLength}
          disabled={disabled}
          // Focus moves here when editing starts: the user asked for the editor.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus={focusOnMount}
          onChange={(event) => {
            const field = event.target
            const next = applyShownEdit(draft, field.value, field.selectionEnd)
            changeDraft(next)
            picker.sync(next)
          }}
          onSelect={() => picker.sync()}
          onBlur={() => picker.sync(null)}
          onKeyDown={(event) => {
            if (picker.onKeyDown(event)) return
            if (removeWholeMention(event)) return
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
            <Markdown mentionSelfId={mentionSelfId}>{value}</Markdown>
          ) : (
            <p className="text-sm text-muted">Nothing to preview yet.</p>
          )}
        </div>
      )}
      {/* After the field, so its ref is set when the tints measure it. */}
      {mode === 'write' && withMentions && <MentionHighlights fieldRef={innerRef} draft={draft} />}
      {picker.picker}
      {mentions && (
        <p aria-live="polite" className="sr-only">
          {picker.announcement}
        </p>
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
        <span className="hidden text-xs text-muted sm:inline">
          {hint ?? (mentions ? 'Markdown · @ to mention' : 'Markdown supported')}
        </span>
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>
    </div>
  )
}
