import { useId } from 'react'

import { CopyButton } from '@/features/admin/copy-button'
import { cn } from '@/lib/utils'

/**
 * A copyable block of code or config (monospace). Long lines (a key in a header)
 * wrap softly instead of running out of sight: the copy button and a selection
 * both get the text as written, without the wrapping. `label` names it for the
 * copy button ("Copy the MCP config") and assistive tech.
 */
export function CodeSnippet({
  code,
  label,
  className,
}: {
  code: string
  label: string
  className?: string
}) {
  const id = useId()
  return (
    <figure
      aria-labelledby={id}
      className={cn('relative flex min-w-0 rounded-md border bg-subtle', className)}
    >
      <figcaption id={id} className="sr-only">
        {label}
      </figcaption>
      <pre className="min-w-0 flex-1 px-3 py-2.5 pr-11 font-mono text-xs leading-relaxed wrap-anywhere whitespace-pre-wrap text-primary">
        <code>{code}</code>
      </pre>
      <div className="absolute top-1.5 right-1.5">
        <CopyButton value={code} label={label} />
      </div>
    </figure>
  )
}

/** One line to copy: a URL, a header, a key. */
export function CopyLine({
  value,
  label,
  className,
  id,
  wrap = false,
}: {
  value: string
  label: string
  className?: string
  id?: string
  /** Show all of it on several lines (a key) instead of cutting it off. */
  wrap?: boolean
}) {
  return (
    <span
      id={id}
      className={cn(
        'flex min-w-0 items-center gap-1 rounded-md border bg-subtle py-0.5 pr-0.5 pl-2.5',
        className,
      )}
    >
      <code
        className={cn(
          'min-w-0 flex-1 font-mono text-sm text-primary',
          wrap ? 'break-all' : 'truncate',
        )}
        title={wrap ? undefined : value}
      >
        {value}
      </code>
      <CopyButton value={value} label={label} />
    </span>
  )
}
