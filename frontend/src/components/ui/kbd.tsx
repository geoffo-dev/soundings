import type { ComponentProps } from 'react'

import { formatKeys } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'

/** `accent`: inside a primary (accent) button, e.g. "New idea  N". */
export type KbdTone = 'default' | 'accent'

const TONES: Record<KbdTone, string> = {
  default: 'border bg-surface text-muted shadow-[0_1px_0_var(--border)]',
  accent: 'border border-white/25 bg-white/15 text-accent-foreground',
}

export function Kbd({
  tone = 'default',
  className,
  ...props
}: ComponentProps<'kbd'> & { tone?: KbdTone }) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-sm px-1',
        'font-sans text-xs font-medium tabular-nums',
        TONES[tone],
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
  tone = 'default',
  className,
  ...props
}: { keys: string; tone?: KbdTone } & Omit<ComponentProps<'span'>, 'children'>) {
  const sequence = formatKeys(keys)
  return (
    <span className={cn('inline-flex items-center gap-1', className)} {...props}>
      {sequence.map((combo, i) => (
        <span key={i} className="inline-flex items-center gap-0.5">
          {i > 0 && (
            <span className={cn('px-0.5 text-xs', tone === 'accent' ? 'opacity-70' : 'text-muted')}>
              then
            </span>
          )}
          {combo.map((key) => (
            <Kbd key={key} tone={tone}>
              {key}
            </Kbd>
          ))}
        </span>
      ))}
    </span>
  )
}
