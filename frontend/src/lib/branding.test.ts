import { afterEach, describe, expect, it } from 'vitest'

import {
  applyBranding,
  brandingStylesheet,
  brandPreviewProperties,
  brandTitle,
  currentBranding,
  DEFAULT_BRANDING,
  DEFAULT_EFFECTIVE_BRANDING,
  deriveBrandTokens,
  readableOn,
  resetBranding,
  resetRuntimeBranding,
  restoreRememberedBranding,
  sanitizeEffectiveBranding,
  sanitizeFontFamily,
  setBrandingOverride,
  setGlobalBranding,
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

afterEach(() => {
  resetRuntimeBranding()
  resetBranding()
})

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

const ASSET = '/api/v1/branding/assets/0f0f0f0f-0000-4000-8000-000000000001'
const ACME = {
  app_name: 'Acme Ideas',
  primary_color: '#b42318',
  accent_color: '#2e7d4f',
  font: 'ibm_plex_sans' as const,
  logo_url: ASSET,
  favicon_url: ASSET,
}

describe('runtime branding (GET /branding)', () => {
  it('checks every field before it reaches the page', () => {
    expect(
      sanitizeEffectiveBranding({
        app_name: 'Acme\u202e',
        primary_color: 'red; } body { display: none',
        accent_color: 'url(javascript:alert(1))',
        font: 'Comic Sans"; } *{',
        logo_url: 'https://evil.example/x.svg',
        favicon_url: 'javascript:alert(1)',
      }),
    ).toEqual(DEFAULT_EFFECTIVE_BRANDING)
    expect(sanitizeEffectiveBranding(ACME)).toEqual(ACME)
    expect(sanitizeEffectiveBranding(null)).toEqual(DEFAULT_EFFECTIVE_BRANDING)
  })

  it('applies colours, font, favicon and the app name in titles', () => {
    document.head.innerHTML = '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
    document.title = 'My work · Soundings'
    setGlobalBranding(ACME)
    const css = document.getElementById('soundings-branding')?.textContent ?? ''
    expect(css).toContain('--brand-primary: #b42318')
    expect(css).toContain('--brand-accent: #2e7d4f')
    expect(css).toContain('--brand-font: "IBM Plex Sans"')
    expect(document.querySelector('link[rel="icon"]')?.getAttribute('href')).toBe(ASSET)
    expect(document.title).toBe('My work · Acme Ideas')
    expect(currentBranding().app_name).toBe('Acme Ideas')
    // Remembered for the next load (no flash of the defaults).
    expect(JSON.parse(localStorage.getItem('soundings-branding') ?? '{}')).toEqual(ACME)
  })

  it('lets a public page show its project’s branding, then restores the global one', () => {
    setGlobalBranding(ACME)
    setBrandingOverride({ ...ACME, app_name: 'Green Ideas', primary_color: '#2e7d4f' })
    expect(currentBranding().app_name).toBe('Green Ideas')
    expect(document.getElementById('soundings-branding')?.textContent).toContain(
      '--brand-primary: #2e7d4f',
    )
    setBrandingOverride(null)
    expect(currentBranding().app_name).toBe('Acme Ideas')
  })

  it('restores only valid remembered branding', () => {
    localStorage.setItem(
      'soundings-branding',
      JSON.stringify({ ...ACME, primary_color: '#000; } html { display:none' }),
    )
    restoreRememberedBranding()
    expect(currentBranding().primary_color).toBe(DEFAULT_EFFECTIVE_BRANDING.primary_color)
    expect(currentBranding().app_name).toBe('Acme Ideas')
    localStorage.setItem('soundings-branding', '{not json')
    expect(() => restoreRememberedBranding()).not.toThrow()
  })

  it('goes back to the defaults (no custom stylesheet)', () => {
    setGlobalBranding(ACME)
    setGlobalBranding(DEFAULT_EFFECTIVE_BRANDING)
    expect(document.getElementById('soundings-branding')).toBeNull()
  })
})

describe('brandTitle', () => {
  it('replaces the product name at the end of a title', () => {
    expect(brandTitle('Soundings', 'Acme')).toBe('Acme')
    expect(brandTitle('CUST-12 · Soundings', 'Acme')).toBe('CUST-12 · Acme')
    expect(brandTitle('Soundings research', 'Acme')).toBe('Soundings research')
  })
})

describe('brandPreviewProperties', () => {
  it('sets only derived hex tokens and a bundled family', () => {
    const props = brandPreviewProperties(
      { primary_color: 'red;}', accent_color: '#2e7d4f', font: 'source_serif_4' },
      'dark',
    )
    expect(props['--brand-primary']).toBe(DEFAULT_BRANDING.primary)
    expect(props['--brand-accent']).toBe('#2e7d4f')
    expect(props['--font-sans']).toMatch(/^"Source Serif 4", /)
    for (const [name, value] of Object.entries(props)) {
      if (name.includes('font')) continue
      expect(value).toMatch(/^#[0-9a-f]{6}$/)
    }
  })
})

describe('readableOn', () => {
  it('picks white or ink text, whichever reads better', () => {
    expect(readableOn('#1d5fa8').color).toBe('#ffffff')
    expect(readableOn('#ffeb3b').color).not.toBe('#ffffff')
  })
})
