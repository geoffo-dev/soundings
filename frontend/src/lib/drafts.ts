/**
 * Unsent drafts (New idea in localStorage, comments in sessionStorage) hold what
 * someone typed, so they are kept per user and removed when the session ends: on
 * sign-out, on a 401 and when switching user (ASVS 8.2.3). The next person on the
 * same browser never sees them.
 */
const PREFIX = 'soundings-draft:'

/** Keys from before drafts were per user; removed with the rest. */
const LEGACY_PREFIXES = [
  'soundings-new-idea-draft',
  'soundings-new-idea-project',
  'soundings-comment-draft:',
]

/** The storage key of one of this user's drafts, e.g. draftKey(me.id, 'new-idea'). */
export function draftKey(userId: string, name: string): string {
  return `${PREFIX}${userId}:${name}`
}

function clear(storage: Storage): void {
  const keys: string[] = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (key && [PREFIX, ...LEGACY_PREFIXES].some((prefix) => key.startsWith(prefix))) keys.push(key)
  }
  for (const key of keys) storage.removeItem(key)
}

/** Removes every draft of every user from this browser. */
export function clearDrafts(): void {
  for (const storage of [() => localStorage, () => sessionStorage]) {
    try {
      clear(storage())
    } catch {
      // Storage unavailable: nothing was kept.
    }
  }
}
