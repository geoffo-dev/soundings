import { createContext, use, useCallback, useMemo, useState, type ReactNode } from 'react'

import { useShortcut } from '@/lib/shortcuts'

const STORAGE_KEY = 'soundings-sidebar-collapsed'

interface SidebarState {
  /** Desktop: sidebar hidden to give content the full width. */
  collapsed: boolean
  toggleCollapsed: () => void
  /** Mobile: navigation drawer open. */
  mobileOpen: boolean
  setMobileOpen: (open: boolean) => void
}

const SidebarContext = createContext<SidebarState | null>(null)

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)

  const toggleCollapsed = useCallback(() => {
    setCollapsed((previous) => {
      const next = !previous
      try {
        window.localStorage.setItem(STORAGE_KEY, String(next))
      } catch {
        // Not persisted — fine.
      }
      return next
    })
  }, [])

  useShortcut('toggleSidebar', () => {
    if (window.matchMedia('(min-width: 48rem)').matches) toggleCollapsed()
    else setMobileOpen((open) => !open)
  })

  const value = useMemo(
    () => ({ collapsed, toggleCollapsed, mobileOpen, setMobileOpen }),
    [collapsed, toggleCollapsed, mobileOpen],
  )
  return <SidebarContext value={value}>{children}</SidebarContext>
}

export function useSidebar(): SidebarState {
  const context = use(SidebarContext)
  if (!context) throw new Error('useSidebar must be used inside <SidebarProvider>')
  return context
}
