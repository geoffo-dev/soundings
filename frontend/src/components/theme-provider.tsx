import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

import {
  applyResolvedTheme,
  readThemePreference,
  resolveTheme,
  subscribeToSystemTheme,
  systemPrefersDark,
  writeThemePreference,
  type ResolvedTheme,
  type ThemePreference,
} from '@/lib/theme'

interface ThemeContextValue {
  /** What the user chose: light, dark or follow the system. */
  preference: ThemePreference
  /** What is actually shown. */
  resolvedTheme: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => readThemePreference())
  const prefersDark = useSyncExternalStore(subscribeToSystemTheme, systemPrefersDark, () => false)
  const resolvedTheme = resolveTheme(preference, prefersDark)

  useEffect(() => {
    applyResolvedTheme(resolvedTheme)
  }, [resolvedTheme])

  // Keep tabs in sync when the preference changes elsewhere.
  useEffect(() => {
    const onStorage = () => setPreferenceState(readThemePreference())
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setPreference = useCallback((next: ThemePreference) => {
    writeThemePreference(next)
    setPreferenceState(next)
  }, [])

  const value = useMemo(
    () => ({ preference, resolvedTheme, setPreference }),
    [preference, resolvedTheme, setPreference],
  )
  return <ThemeContext value={value}>{children}</ThemeContext>
}

export function useTheme(): ThemeContextValue {
  const context = use(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside <ThemeProvider>')
  return context
}
