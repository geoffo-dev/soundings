import { useSyncExternalStore } from 'react'

import { WithTooltip } from '@/components/ui/tooltip'
import { formatDateTime, formatRelative, type DateInput } from '@/lib/dates'
import { cn } from '@/lib/utils'

/* A shared clock: one timer for every <RelativeTime> on the page. */
const TICK_MS = 30_000
let now = Date.now()
const listeners = new Set<() => void>()
let timer: number | undefined

function subscribe(listener: () => void) {
  listeners.add(listener)
  if (timer === undefined) {
    now = Date.now()
    timer = window.setInterval(() => {
      now = Date.now()
      listeners.forEach((l) => l())
    }, TICK_MS)
  }
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && timer !== undefined) {
      window.clearInterval(timer)
      timer = undefined
    }
  }
}

/** The current time, updated every 30 s while something displays it. */
export function useNow(): number {
  return useSyncExternalStore(
    subscribe,
    () => now,
    () => now,
  )
}

export interface RelativeTimeProps {
  date: DateInput
  /** `long` "5 minutes ago" (default) · `narrow` "5m ago" for dense rows. */
  style?: Intl.RelativeTimeFormatStyle
  className?: string
  /** Show the absolute date in a tooltip (default true). */
  tooltip?: boolean
}

/** "5 minutes ago" with the full date on hover; a <time> element for assistive tech. */
export function RelativeTime({
  date,
  style = 'long',
  className,
  tooltip = true,
}: RelativeTimeProps) {
  const current = useNow()
  const iso = new Date(date).toISOString()
  const node = (
    <time dateTime={iso} className={cn('whitespace-nowrap tabular-nums', className)}>
      {formatRelative(date, { now: current, style })}
    </time>
  )
  if (!tooltip) return node
  return <WithTooltip content={formatDateTime(date)}>{node}</WithTooltip>
}
