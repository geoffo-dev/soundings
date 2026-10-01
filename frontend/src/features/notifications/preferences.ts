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

/** "Immediately", "In the daily digest", "Not emailed". */
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
 * What an unsubscribe link is about, as the page's heading and list:
 * one type ("Evaluation reminders"), the digest, or everything.
 */
export function unsubscribeSubject(info: Pick<UnsubscribeInfo, 'scope' | 'types'>): {
  title: string
  done: string
  /** The types, for the digest and "all" (a list on the page). */
  list: string[]
  /** One type: what those emails are about (instead of a one-item list). */
  detail?: string
} {
  const list = info.types.map((type) => TYPE_COPY[type].label)
  if (info.scope === 'all') {
    return {
      title: 'Unsubscribe from all Soundings email?',
      done: 'You won’t get any email from Soundings',
      list,
    }
  }
  if (info.scope === 'digest') {
    return {
      title: 'Stop the daily digest?',
      done:
        info.types.length > 0
          ? `You won’t get the daily digest (${joinWords(info.types.map(typePhrase))})`
          : 'You won’t get the daily digest',
      list,
    }
  }
  const { label, description } = TYPE_COPY[info.scope]
  return {
    title: `Unsubscribe from “${label}” emails?`,
    done: `You won’t get “${label}” emails any more`,
    list,
    detail: description.charAt(0).toLowerCase() + description.slice(1),
  }
}
