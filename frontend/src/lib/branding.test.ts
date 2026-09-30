import { afterEach, describe, expect, it } from 'vitest'

import {
  applyBranding,
  brandingStylesheet,
  DEFAULT_BRANDING,
  deriveBrandTokens,
  resetBranding,
  sanitizeFontFamily,
  THEME_SURFACES,
} from '@/lib/branding'
import { contrastHex } from '@/lib/color'
import tokensCss from '@/styles/tokens.css?raw'

const THEMES = ['light', 'dark'] as const
// Deliberately awkward brand colours: pale, dark, saturated, mid-grey.
const BRANDS = [
  DEFAULT_BRANDING.primary,
  '#ffeb3b',
  '#0b1a33',
  '#7fdbff',
  '#ff0000',
  '#808080',
  '#10b981',
]

afterEach(() => resetBranding())

describe('deriveBrandTokens', () => {
  for (const brand of BRANDS) {
    for (const theme of THEMES) {
      it(`keeps ${brand} readable in ${theme} mode`, () => {
        const tokens = deriveBrandTokens(brand, theme)
        const surfaces = Object.values(THEME_SURFACES[theme])

        // Text on the solid accent (primary buttons).
        expect(contrastHex(tokens.accentForeground, tokens.accent)).toBeGreaterThanOrEqual(4.5)
        expect(contrastHex(tokens.accentForeground, tokens.accentHover)).toBeGreaterThanOrEqual(4.5)
        // Accent used as text (links) on every surface and on the accent tint.
        for (const surface of [...surfaces, tokens.accentSubtle]) {
          expect(contrastHex(tokens.accentText, surface)).toBeGreaterThanOrEqual(4.5)
        }
        // Focus ring: non-text contrast.
        for (const surface of surfaces) {
          expect(contrastHex(tokens.focus, surface)).toBeGreaterThanOrEqual(3)
        }
      })
    }
  }

  it('keeps the default brand colour exact', () => {
    expect(deriveBrandTokens(DEFAULT_BRANDING.primary, 'light').accent).toBe(
      DEFAULT_BRANDING.primary,
    )
  })

  it('falls back to the default for invalid input', () => {
    expect(deriveBrandTokens('not-a-colour', 'light')).toEqual(
      deriveBrandTokens(DEFAULT_BRANDING.primary, 'light'),
    )
  })
})

describe('applyBranding', () => {
  it('injects one stylesheet with light and dark variants and replaces it on re-apply', () => {
    applyBranding({ primary: '#ffeb3b', accent: '#123456', font: 'Inter Variable' })
    const style = document.getElementById('soundings-branding')
    expect(style?.textContent).toContain('--brand-primary: #ffeb3b')
    expect(style?.textContent).toContain('--brand-accent: #123456')
    expect(style?.textContent).toContain('--brand-font: "Inter Variable"')
    expect(style?.textContent).toMatch(/:root, \.light \{[^}]*--accent-foreground: #101014/)
    expect(style?.textContent).toMatch(/\.dark \{[^}]*--fg-accent:/)

    applyBranding({ primary: '#1d5fa8' })
    expect(document.querySelectorAll('#soundings-branding')).toHaveLength(1)
    expect(document.getElementById('soundings-branding')?.textContent).toContain(
      '--brand-primary: #1d5fa8',
    )
  })

  it('ignores invalid colours and fonts that could inject CSS', () => {
    expect(brandingStylesheet({ primary: 'red; } body { display: none' })).toBe('')
    expect(sanitizeFontFamily('Inter"; } * { color: red')).toBeNull()
    expect(sanitizeFontFamily('  Source Sans 3 ')).toBe('Source Sans 3')
    applyBranding({ primary: 'nope' })
    expect(document.getElementById('soundings-branding')).toBeNull()
  })
})

describe('tokens.css', () => {
  it('matches the surfaces branding uses for contrast checks', () => {
    const block = (selector: RegExp) => tokensCss.match(selector)?.[0] ?? ''
    const light = block(/:root,\s*\.light\s*\{[^}]*\}/)
    const dark = block(/\.dark\s*\{[^}]*\}/)
    for (const [css, theme] of [
      [light, 'light'],
      [dark, 'dark'],
    ] as const) {
      for (const [name, value] of Object.entries(THEME_SURFACES[theme])) {
        expect(css).toContain(`--${name}: ${value};`)
      }
    }
    expect(tokensCss).toContain(`--brand-primary: ${DEFAULT_BRANDING.primary};`)
  })
})
