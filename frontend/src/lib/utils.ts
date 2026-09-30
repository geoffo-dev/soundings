import type React from 'react'

import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

/**
 * Teach tailwind-merge our custom shadow names, otherwise `shadow-overlay` is
 * mistaken for a shadow *colour* and conflicting classes aren't merged.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      shadow: ['overlay', 'dialog', 'raised'],
      text: ['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl'],
    },
  },
})

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** Stable, well-distributed 32-bit hash (FNV-1a) — used for avatar colours. */
export function hashString(value: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return hash >>> 0
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] ?? '?'
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return (first + last).toUpperCase()
}

export const isMac =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent)

/** Combines several refs (object or callback) into one callback ref. */
export function mergeRefs<T>(...refs: (React.Ref<T> | undefined)[]): React.RefCallback<T> {
  return (value) => {
    for (const ref of refs) {
      if (typeof ref === 'function') ref(value)
      else if (ref) ref.current = value
    }
  }
}
