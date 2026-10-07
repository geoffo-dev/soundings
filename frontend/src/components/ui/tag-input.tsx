import { X } from 'lucide-react'
import { useId, useRef, useState, type KeyboardEvent } from 'react'

import { useFieldControl } from '@/components/ui/field'
import { controlStyles } from '@/components/ui/input'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

export interface TagInputProps {
  value: string[]
  onValueChange: (value: string[]) => void
  /** Existing tags to suggest (e.g. the project's tags in use). */
  suggestions?: string[]
  /** Called the first time the field gets focus — load suggestions lazily. */
  onFirstFocus?: () => void
  max?: number
  maxLength?: number
  placeholder?: string
  disabled?: boolean
  id?: string
  className?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}

/** Tag names can't contain commas, tabs or line breaks (the API's rule). */
export function cleanTag(raw: string, maxLength = 32): string {
  return raw
    .replace(/[,\t\r\n]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength)
}

/**
 * Free-text tags as removable chips. Enter or comma adds, Backspace on an
 * empty field removes the last one, ↑/↓ pick a suggestion. Duplicates are
 * merged case-insensitively (the API keeps the first spelling).
 */
export function TagInput({
  value,
  onValueChange,
  suggestions = [],
  onFirstFocus,
  max = 10,
  maxLength = 32,
  placeholder = 'Add a tag…',
  className,
  ...props
}: TagInputProps) {
  const field = useFieldControl({
    id: props.id,
    disabled: props.disabled,
    'aria-describedby': props['aria-describedby'],
    'aria-invalid': props['aria-invalid'],
  })
  const listId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const focusedOnce = useRef(false)
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)
  const [focused, setFocused] = useState(false)

  const lower = new Set(value.map((tag) => tag.toLowerCase()))
  const query = text.trim().toLowerCase()
  const matches = query
    ? suggestions
        .filter((tag) => !lower.has(tag.toLowerCase()) && tag.toLowerCase().includes(query))
        .sort(
          (a, b) =>
            Number(!a.toLowerCase().startsWith(query)) - Number(!b.toLowerCase().startsWith(query)),
        )
        .slice(0, 6)
    : []
  const open = focused && matches.length > 0
  const full = value.length >= max

  /** Adds one or more tags (a pasted "a, b, c" adds three), up to `max`. */
  const addAll = (raws: string[], rest = '') => {
    const next = [...value]
    const seen = new Set(lower)
    for (const raw of raws) {
      const tag = cleanTag(raw, maxLength)
      if (!tag || next.length >= max || seen.has(tag.toLowerCase())) continue
      seen.add(tag.toLowerCase())
      next.push(suggestions.find((s) => s.toLowerCase() === tag.toLowerCase()) ?? tag)
    }
    if (next.length !== value.length) onValueChange(next)
    setText(rest)
    setActive(0)
  }
  const add = (raw: string) => addAll([raw])
  const remove = (tag: string) => {
    onValueChange(value.filter((t) => t !== tag))
    inputRef.current?.focus()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      if (!text.trim()) return
      event.preventDefault()
      add(open ? (matches[active] ?? text) : text)
    } else if (event.key === 'Backspace' && !text && value.length > 0) {
      onValueChange(value.slice(0, -1))
    } else if (event.key === 'ArrowDown' && open) {
      event.preventDefault()
      setActive((i) => (i + 1) % matches.length)
    } else if (event.key === 'ArrowUp' && open) {
      event.preventDefault()
      setActive((i) => (i - 1 + matches.length) % matches.length)
    } else if (event.key === 'Escape' && open) {
      setText('')
    }
  }

  return (
    <Popover open={open}>
      <PopoverAnchor asChild>
        <div
          data-slot="tag-input"
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) {
              event.preventDefault()
              inputRef.current?.focus()
            }
          }}
          className={cn(
            controlStyles,
            'flex min-h-9 flex-wrap items-center gap-1 px-1.5 py-1 sm:min-h-8',
            'has-[input:focus-visible]:border-focus has-[input:focus-visible]:ring-3 has-[input:focus-visible]:ring-focus/20',
            field['aria-invalid'] && 'border-danger',
            className,
          )}
        >
          {value.map((tag) => (
            <span
              key={tag}
              className="inline-flex h-6 items-center gap-0.5 rounded-sm bg-subtle-hover pr-0.5 pl-1.5 text-sm text-primary"
            >
              {tag}
              <button
                type="button"
                onClick={() => remove(tag)}
                aria-label={`Remove tag ${tag}`}
                disabled={field.disabled}
                className="inline-flex size-5 items-center justify-center rounded-sm text-muted transition-colors hover:bg-subtle hover:text-primary"
              >
                <X aria-hidden="true" className="size-3" />
              </button>
            </span>
          ))}
          <input
            ref={inputRef}
            {...field}
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-controls={open ? listId : undefined}
            aria-autocomplete="list"
            aria-activedescendant={open ? `${listId}-${active}` : undefined}
            value={text}
            maxLength={maxLength}
            disabled={field.disabled ?? full}
            placeholder={full ? `Up to ${max} tags` : value.length ? '' : placeholder}
            onChange={(event) => {
              const next = event.target.value
              // Typing or pasting a comma completes the tags before it.
              if (/[,\n]/.test(next)) {
                const parts = next.split(/[,\n]/)
                addAll(parts.slice(0, -1), parts.at(-1) ?? '')
              } else {
                setText(next)
                setActive(0)
              }
            }}
            onKeyDown={onKeyDown}
            onFocus={() => {
              setFocused(true)
              if (!focusedOnce.current) {
                focusedOnce.current = true
                onFirstFocus?.()
              }
            }}
            onBlur={() => {
              setFocused(false)
              if (text.trim()) add(text)
            }}
            className="h-6 min-w-24 flex-1 bg-transparent px-1 text-lg text-primary outline-none placeholder:text-muted sm:text-base"
          />
        </div>
      </PopoverAnchor>
      <PopoverContent
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
        aria-label="Tag suggestions"
        className="w-(--radix-popover-trigger-width) min-w-48 p-1"
      >
        <ul id={listId} role="listbox" aria-label="Suggested tags">
          {matches.map((tag, index) => (
            <li
              key={tag}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              onPointerDown={(event) => {
                event.preventDefault()
                add(tag)
              }}
              className="flex h-8 cursor-default items-center rounded-md px-2 text-sm aria-selected:bg-subtle-hover aria-selected:highlight-ring"
            >
              {tag}
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
