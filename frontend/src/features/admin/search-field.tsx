import { Search } from 'lucide-react'
import { useEffect, useRef, useState, type Ref } from 'react'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const SEARCH_DELAY_MS = 250

/**
 * Search box for an admin list: typing updates `value` (the URL) after a short
 * pause; Enter applies at once; Esc clears.
 */
export function SearchField({
  value,
  onChange,
  label,
  placeholder,
  inputRef,
  className,
}: {
  value: string | undefined
  onChange: (q: string | undefined) => void
  label: string
  placeholder: string
  inputRef?: Ref<HTMLInputElement>
  className?: string
}) {
  const [text, setText] = useState(value ?? '')
  // The URL value this field last agreed with; a different one came from outside (Clear, Back).
  const [synced, setSynced] = useState(value ?? '')
  if ((value ?? '') !== synced) {
    setSynced(value ?? '')
    setText(value ?? '')
  }
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const push = (next: string) => {
    window.clearTimeout(timer.current)
    const q = next.trim()
    setSynced(q)
    if (q !== (value ?? '')) onChange(q || undefined)
  }

  return (
    <Input
      ref={inputRef}
      type="search"
      aria-label={label}
      placeholder={placeholder}
      startIcon={<Search />}
      value={text}
      maxLength={100}
      className={cn('w-full shrink-0 sm:w-56 [&_input]:h-7 sm:[&_input]:text-sm', className)}
      onChange={(event) => {
        const next = event.target.value
        setText(next)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => push(next), SEARCH_DELAY_MS)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') push(text)
        if (event.key === 'Escape' && text) {
          event.preventDefault()
          setText('')
          push('')
        }
      }}
    />
  )
}
