import type {
  NotificationMode,
  NotificationPreferences,
  NotificationPreferencesUpdate,
  UnsubscribeInfo,
} from '@/api/types'

import { TYPE_COPY, typePhrase } from './notification-text'

/**
 * Email preference helpers (contract-phase3 §3.4, §3.5): the three modes as a
 * segmented control, how a mode reads, the inverse of a bulk change (Undo),
 * and what an unsubscribe link turns off, in words.
 */

export const MODE_OPTIONS: { value: NotificationMode; label: string }[] = [
  { value: 'immediate', label: 'Immediate' },
  { value: 'digest', label: 'Daily digest' },
  { value: 'off', label: 'Off' },
]

const MODE_WORDS: Record<NotificationMode, string> = {
  immediate: 'Immediately',
  digest: 'In the daily digest',
  off: 'Not emailed',
}

/** The option's own label ("Immediate", "Daily digest", "Off"): "Default: Daily digest". */
export function modeLabel(mode: NotificationMode): string {
  return MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode
}

/** "Immediately", "In the daily digest", "Not emailed" (inside a sentence). */
export function describeMode(mode: NotificationMode): string {
  return MODE_WORDS[mode]
}

/** The update that restores every type to its current mode (Undo of a bulk change). */
export function previousModes(preferences: NotificationPreferences): NotificationPreferencesUpdate {
  const out: NotificationPreferencesUpdate = {}
  for (const item of preferences.items) out[item.type] = item.mode
  return out
}

/** Only the types whose mode differs from `preferences` (what a save actually changes). */
export function changedModes(
  preferences: NotificationPreferences,
  update: NotificationPreferencesUpdate,
): NotificationPreferencesUpdate {
  const out: NotificationPreferencesUpdate = {}
  for (const item of preferences.items) {
    const mode = update[item.type]
    if (mode && mode !== item.mode) out[item.type] = mode
  }
  return out
}

/** "a, b and c". */
function joinWords(words: string[]): string {
  if (words.length <= 1) return words.join('')
  return `${words.slice(0, -1).join(', ')} and ${words.at(-1) ?? ''}`
}

/**
 * What an unsubscribe link is about, for the page: its heading, what stops
 * (one type: when those emails come; the digest and "all": a list), and the
 * sentence once it's done, around the masked address
 * (`${done.before}c•••@example.com${done.after}`).
 */
export function unsubscribeSubject(info: Pick<UnsubscribeInfo, 'scope' | 'types'>): {
  title: string
  /** One type: when those emails come ("someone asks you to evaluate an idea"). */
  when?: string
  /** The types (for the digest and "all"). */
  list: string[]
  done: { before: string; after: string }
} {
  const list = info.types.map((type) => TYPE_COPY[type].label)
  if (info.scope === 'all') {
    return {
      title: 'Unsubscribe from all Soundings email?',
      list,
      done: { before: 'Soundings won’t email ', after: ' any more.' },
    }
  }
  if (info.scope === 'digest') {
    return {
      title: 'Stop the daily digest?',
      list,
      done: {
        before: 'Soundings won’t send the daily digest to ',
        after:
          info.types.length > 0
            ? ` any more (it had ${joinWords(info.types.map(typePhrase))}).`
            : ' any more.',
      },
    }
  }
  const { phrase, when } = TYPE_COPY[info.scope]
  return {
    title: `Unsubscribe from ${phrase}?`,
    when,
    list,
    done: { before: 'Soundings won’t email ', after: ` about ${phrase} any more.` },
  }
}
