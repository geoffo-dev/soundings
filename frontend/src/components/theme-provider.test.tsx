import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ThemeProvider, useTheme } from '@/components/theme-provider'
import { readThemePreference, resolveTheme, THEME_STORAGE_KEY } from '@/lib/theme'

function Probe() {
  const { preference, resolvedTheme, setPreference } = useTheme()
  return (
    <div>
      <span data-testid="preference">{preference}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
      <button onClick={() => setPreference('dark')}>dark</button>
      <button onClick={() => setPreference('light')}>light</button>
      <button onClick={() => setPreference('system')}>system</button>
    </div>
  )
}

const html = document.documentElement

describe('theme', () => {
  it('defaults to following the system', () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('preference')).toHaveTextContent('system')
    // matchMedia is stubbed to "light" in the test setup.
    expect(screen.getByTestId('resolved')).toHaveTextContent('light')
    expect(html).toHaveClass('light')
  })

  it('persists the choice and applies it to <html>', async () => {
    const user = userEvent.setup()
    const { unmount } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )

    await user.click(screen.getByRole('button', { name: 'dark' }))
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(html).toHaveClass('dark')
    expect(html).not.toHaveClass('light')
    expect(html.style.colorScheme).toBe('dark')

    // A fresh mount (e.g. next visit) reads the stored preference.
    unmount()
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('preference')).toHaveTextContent('dark')

    // Choosing "system" forgets the explicit choice.
    await user.click(screen.getByRole('button', { name: 'system' }))
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
    expect(html).toHaveClass('light')
  })

  it('syncs when another tab changes the preference', () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    act(() => {
      localStorage.setItem(THEME_STORAGE_KEY, 'dark')
      window.dispatchEvent(new StorageEvent('storage', { key: THEME_STORAGE_KEY }))
    })
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark')
  })

  it('ignores junk in storage and resolves system preference', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'purple')
    expect(readThemePreference()).toBe('system')
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
    expect(resolveTheme('light', true)).toBe('light')
  })
})
