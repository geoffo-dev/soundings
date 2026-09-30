/**
 * Theme preference handling. index.html contains an inline copy of the
 * `resolve + apply` logic so the right class is on <html> before first paint;
 * keep the storage key and class names in sync with it.
 */

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'soundings-theme'
export const THEME_PREFERENCES: readonly ThemePreference[] = ['light', 'dark', 'system']

const DARK_QUERY = '(prefers-color-scheme: dark)'

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'light' || value === 'dark' || value === 'system'
}

export function readThemePreference(storage: Storage | undefined = safeStorage()): ThemePreference {
  try {
    const stored = storage?.getItem(THEME_STORAGE_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function writeThemePreference(
  preference: ThemePreference,
  storage: Storage | undefined = safeStorage(),
): void {
  try {
    if (preference === 'system') storage?.removeItem(THEME_STORAGE_KEY)
    else storage?.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // Private mode / disabled storage: the preference simply isn't remembered.
  }
}

export function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(DARK_QUERY).matches
}

export function resolveTheme(
  preference: ThemePreference,
  prefersDark = systemPrefersDark(),
): ResolvedTheme {
  if (preference === 'system') return prefersDark ? 'dark' : 'light'
  return preference
}

export function subscribeToSystemTheme(callback: () => void): () => void {
  const query = window.matchMedia(DARK_QUERY)
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

/**
 * Sets `light`/`dark` on <html>. Transitions are suppressed for one frame so
 * switching themes doesn't animate every colour on the page.
 */
export function applyResolvedTheme(
  theme: ResolvedTheme,
  root: HTMLElement = document.documentElement,
): void {
  if (root.classList.contains(theme) && !root.classList.contains(otherTheme(theme))) return
  const pause = document.createElement('style')
  pause.textContent = '*,*::before,*::after{transition:none!important}'
  document.head.appendChild(pause)
  root.classList.remove(otherTheme(theme))
  root.classList.add(theme)
  root.style.colorScheme = theme
  // Force a style flush before re-enabling transitions.
  window.getComputedStyle(root).getPropertyValue('opacity')
  requestAnimationFrame(() => pause.remove())
}

function otherTheme(theme: ResolvedTheme): ResolvedTheme {
  return theme === 'dark' ? 'light' : 'dark'
}

function safeStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}
