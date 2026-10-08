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

/** This user's drafts whose names start with `prefix`, as `[name, value]` (localStorage). */
export function readDrafts(userId: string, prefix: string): [string, string][] {
  const start = draftKey(userId, prefix)
  const out: [string, string][] = []
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (!key?.startsWith(start)) continue
      const value = localStorage.getItem(key)
      if (value !== null) out.push([key.slice(draftKey(userId, '').length), value])
    }
  } catch {
    // Storage unavailable: nothing kept.
  }
  return out
}

/** Keeps (or with `null` removes) one of this user's drafts in localStorage. */
export function writeDraft(userId: string, name: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(draftKey(userId, name))
    else localStorage.setItem(draftKey(userId, name), value)
  } catch {
    // Storage unavailable or full: the text stays on the page until it is left.
  }
}
