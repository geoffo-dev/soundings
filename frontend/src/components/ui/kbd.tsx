import type { ComponentProps } from 'react'

import { formatKeys, isSingleKeyShortcut } from '@/lib/hotkeys'
import { useSingleKeyShortcuts } from '@/lib/shortcut-preference'
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
 * (⌘ K on macOS, Ctrl K elsewhere). A single-key hint ("N") disappears while
 * single-key shortcuts are turned off, since the key does nothing then (`always`
 * keeps it: the "?" sheet lists every shortcut).
 */
export function KbdShortcut({
  keys,
  tone = 'default',
  always = false,
  className,
  ...props
}: { keys: string; tone?: KbdTone; always?: boolean } & Omit<ComponentProps<'span'>, 'children'>) {
  const singleKeys = useSingleKeyShortcuts()
  if (!always && !singleKeys && isSingleKeyShortcut(keys)) return null
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

/**
 * A shortcut hint inside a button ("Create group  Ctrl ↵"), on the button's
 * fill. Hidden from assistive tech (give the button `aria-keyshortcuts`, see
 * `ariaKeys`) and wherever there's probably no keyboard: below `sm` and on
 * touch-first devices (coarse primary pointer).
 */
export function ButtonShortcut({
  keys,
  tone = 'accent',
  className,
}: {
  keys: string
  tone?: KbdTone
  className?: string
}) {
  return (
    <KbdShortcut
      keys={keys}
      aria-hidden="true"
      tone={tone}
      className={cn('ml-1 hidden sm:pointer-fine:inline-flex', className)}
    />
  )
}

/** `aria-keyshortcuts` for the registry's key syntax ("e" → "E", "mod+enter" → both platforms). */
export function ariaKeys(keys: string): string {
  if (keys.startsWith('mod+')) {
    const rest = keys.slice('mod+'.length)
    const key = rest === 'enter' ? 'Enter' : rest.toUpperCase()
    return `Control+${key} Meta+${key}`
  }
  return keys.toUpperCase()
}
