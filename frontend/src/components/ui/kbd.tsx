import type { ComponentProps } from 'react'

import { formatKeys } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'

export function Kbd({ className, ...props }: ComponentProps<'kbd'>) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-sm border bg-surface px-1',
        'font-sans text-xs font-medium text-muted tabular-nums shadow-[0_1px_0_var(--border)]',
        className,
      )}
      {...props}
    />
  )
}

/**
 * Renders a shortcut such as "mod+k" or "g m" as platform-aware keys
 * (⌘ K on macOS, Ctrl K elsewhere).
 */
export function KbdShortcut({
  keys,
  className,
  ...props
}: { keys: string } & Omit<ComponentProps<'span'>, 'children'>) {
  const sequence = formatKeys(keys)
  return (
    <span className={cn('inline-flex items-center gap-1', className)} {...props}>
      {sequence.map((combo, i) => (
        <span key={i} className="inline-flex items-center gap-0.5">
          {i > 0 && <span className="px-0.5 text-xs text-muted">then</span>}
          {combo.map((key) => (
            <Kbd key={key}>{key}</Kbd>
          ))}
        </span>
      ))}
    </span>
  )
}
