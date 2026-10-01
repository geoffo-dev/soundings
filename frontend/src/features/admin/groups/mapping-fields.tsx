import { X } from 'lucide-react'
import { useId, useState } from 'react'

import type { GroupSyncMode } from '@/api/types'
import { useFieldControl } from '@/components/ui/field'
import { controlStyles } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { cn } from '@/lib/utils'

import { MAX_IDP_VALUE_LENGTH, MAX_IDP_VALUES, normaliseIdpValue, SYNC_MODES } from './mapping'

/** Managed or additive, each with its one-line explanation (inside a `Field`). */
export function SyncModeField({
  value,
  onChange,
  idPrefix,
  disabled = false,
}: {
  value: GroupSyncMode
  onChange: (mode: GroupSyncMode) => void
  idPrefix: string
  disabled?: boolean
}) {
  return (
    <RadioGroup
      value={value}
      onValueChange={(next) => onChange(next as GroupSyncMode)}
      disabled={disabled}
      className="sm:grid-cols-2"
    >
      {SYNC_MODES.map((mode) => (
        <label
          key={mode.value}
          htmlFor={`${idPrefix}-${mode.value}`}
          className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent"
        >
          <RadioGroupItem
            id={`${idPrefix}-${mode.value}`}
            value={mode.value}
            className="mt-0.5"
            aria-describedby={`${idPrefix}-${mode.value}-help`}
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-sm font-medium text-primary">{mode.label}</span>
            <span id={`${idPrefix}-${mode.value}-help`} className="text-sm text-muted">
              {mode.description}
            </span>
          </span>
        </label>
      ))}
    </RadioGroup>
  )
}

/**
 * The IdP group values a group maps to, as chips. What you type is shown as it
 * will be stored (normalised: "/Innovation/Admins" → "innovation/admins") before
 * you add it. Enter, comma or a new line adds; pasting a list adds every entry;
 * Backspace in the empty field removes the last chip.
 */
export function IdpValuesInput({
  value,
  onChange,
  disabled = false,
  ...props
}: {
  value: string[]
  onChange: (values: string[]) => void
  disabled?: boolean
  id?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}) {
  const field = useFieldControl({
    id: props.id,
    disabled,
    'aria-describedby': props['aria-describedby'],
    'aria-invalid': props['aria-invalid'],
  })
  const previewId = useId()
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const full = value.length >= MAX_IDP_VALUES
  const preview = normaliseIdpValue(text)

  const addAll = (raws: string[], rest = '') => {
    const next = [...value]
    let issue: string | null = null
    for (const raw of raws) {
      if (!raw.trim()) continue
      const normalised = normaliseIdpValue(raw)
      if (!normalised) issue = `“${raw.trim()}” is empty once the slashes are removed.`
      else if (normalised.length > MAX_IDP_VALUE_LENGTH)
        issue = 'Values are at most 255 characters.'
      else if (next.length >= MAX_IDP_VALUES) issue = `At most ${MAX_IDP_VALUES} values per group.`
      else if (!next.includes(normalised)) next.push(normalised)
    }
    if (next.length !== value.length) onChange(next)
    setProblem(issue)
    setText(rest)
  }

  const describedBy = [field['aria-describedby'], previewId].filter(Boolean).join(' ')

  return (
    <div className="flex flex-col gap-1.5">
      <div
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) {
            event.preventDefault()
            event.currentTarget.querySelector('input')?.focus()
          }
        }}
        className={cn(
          controlStyles,
          'flex min-h-9 flex-wrap items-center gap-1 px-1.5 py-1 sm:min-h-8',
          'has-[input:focus-visible]:border-focus has-[input:focus-visible]:ring-3 has-[input:focus-visible]:ring-focus/20',
          (field['aria-invalid'] ?? problem) && 'border-danger',
          disabled && 'opacity-50',
        )}
      >
        {value.map((item) => (
          <span
            key={item}
            className="inline-flex h-6 max-w-full items-center gap-0.5 rounded-sm bg-subtle-hover pr-0.5 pl-1.5 font-mono text-sm text-primary"
          >
            <span className="truncate">{item}</span>
            <button
              type="button"
              onClick={() => onChange(value.filter((v) => v !== item))}
              aria-label={`Remove ${item}`}
              disabled={disabled}
              className="inline-flex size-5 shrink-0 items-center justify-center rounded-sm text-muted transition-colors hover:bg-subtle hover:text-primary"
            >
              <X aria-hidden="true" className="size-3" />
            </button>
          </span>
        ))}
        <input
          {...field}
          aria-describedby={describedBy || undefined}
          type="text"
          value={text}
          disabled={disabled || full}
          autoCapitalize="none"
          autoComplete="off"
          spellCheck={false}
          placeholder={
            full ? `Up to ${MAX_IDP_VALUES} values` : value.length ? '' : '/innovation/members'
          }
          onChange={(event) => {
            const next = event.target.value
            setProblem(null)
            if (/[,\n]/.test(next)) {
              const parts = next.split(/[,\n]/)
              addAll(parts.slice(0, -1), parts.at(-1) ?? '')
            } else setText(next)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              if (!text.trim()) return
              event.preventDefault()
              addAll([text])
            } else if (event.key === 'Backspace' && !text && value.length > 0) {
              onChange(value.slice(0, -1))
            }
          }}
          onBlur={() => {
            if (text.trim()) addAll([text])
          }}
          className="h-6 min-w-40 flex-1 bg-transparent px-1 font-mono text-lg text-primary outline-none placeholder:text-muted sm:text-base"
        />
      </div>
      <p id={previewId} aria-live="polite" className="text-sm text-muted empty:hidden">
        {problem ? (
          <span className="text-danger">{problem}</span>
        ) : text.trim() && preview !== text.trim() ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            Saved as
            <code className="font-mono text-secondary">{preview || '(empty)'}</code>
          </span>
        ) : text.trim() ? (
          'Press Enter to add it.'
        ) : null}
      </p>
    </div>
  )
}
