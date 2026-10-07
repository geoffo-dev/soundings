import { describe, expect, it } from 'vitest'

import { DEFAULT_BRANDING, deriveBrandTokens } from '@/lib/branding'
import {
  contrastHex,
  contrastRatio,
  mixRgb,
  oklchToRgb,
  parseHex,
  rgbToOklch,
  type Rgb,
} from '@/lib/color'
import type { ResolvedTheme } from '@/lib/theme'
import tokensCss from '@/styles/tokens.css?raw'

function block(selector: RegExp): string {
  return tokensCss.match(selector)?.[0] ?? ''
}

function token(css: string, name: string): string {
  const value = new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i').exec(css)?.[1]
  if (!value) throw new Error(`--${name} missing`)
  return value
}

function rgb(css: string, name: string): Rgb {
  const value = parseHex(token(css, name))
  if (!value) throw new Error(`--${name} is not a colour`)
  return value
}

/** A translucent fill such as `--subtle: rgb(255 255 255 / 0.05)`, laid over `base`. */
function over(css: string, name: string, base: Rgb): Rgb {
  const match = new RegExp(`--${name}:\\s*rgb\\((\\d+) (\\d+) (\\d+) / ([\\d.]+)\\)`).exec(css)
  if (!match) throw new Error(`--${name} missing`)
  const [r, g, b, alpha] = match.slice(1).map(Number) as [number, number, number, number]
  return mixRgb({ r: r / 255, g: g / 255, b: b / 255 }, base, alpha)
}

const THEMES = {
  light: block(/:root,\s*\.light\s*\{[^}]*\}/),
  dark: block(/\.dark\s*\{[^}]*\}/),
}

describe('non-text contrast (WCAG 1.4.11)', () => {
  for (const [theme, css] of Object.entries(THEMES)) {
    it(`text-field borders are at least 3:1 against surfaces in ${theme} mode`, () => {
      for (const surface of ['surface', 'elevated']) {
        expect(contrastHex(token(css, 'border-input'), token(css, surface))).toBeGreaterThanOrEqual(
          3,
        )
        expect(
          contrastHex(token(css, 'border-input-hover'), token(css, surface)),
        ).toBeGreaterThanOrEqual(3)
      }
    })

    it(`checkbox, radio and switch outlines are at least 3:1 in ${theme} mode`, () => {
      for (const surface of ['surface', 'elevated']) {
        expect(
          contrastHex(token(css, 'border-control'), token(css, surface)),
        ).toBeGreaterThanOrEqual(3)
      }
    })
  }
})

describe('text contrast (WCAG 1.4.3)', () => {
  for (const [theme, css] of Object.entries(THEMES)) {
    it(`secondary and muted text are at least 4.5:1 on every canvas and fill in ${theme} mode`, () => {
      for (const canvas of ['background', 'surface', 'elevated']) {
        const base = rgb(css, canvas)
        // Quiet fills sit on every canvas: chips, input add-ons, the selected row of a
        // menu or the command palette.
        const backdrops = [base, over(css, 'subtle', base), over(css, 'subtle-hover', base)]
        for (const text of ['fg-secondary', 'fg-muted']) {
          const fg = rgb(css, text)
          for (const backdrop of backdrops) {
            expect(contrastRatio(fg, backdrop), `${text} on ${canvas}`).toBeGreaterThanOrEqual(4.5)
          }
        }
      }
    })
  }
})

describe('selected and highlighted states (WCAG 1.4.11)', () => {
  function hex(value: string): Rgb {
    const parsed = parseHex(value)
    if (!parsed) throw new Error(`${value} is not a colour`)
    return parsed
  }

  /** `color-mix(in oklch, primary 58%, white)`, as tokens.css writes dark mode's accents. */
  function mixWithWhite(color: string, weight: number): Rgb {
    const base = rgbToOklch(hex(color))
    return oklchToRgb({ l: base.l * weight + (1 - weight), c: base.c * weight, h: base.h })
  }

  for (const [theme, css] of Object.entries(THEMES) as [ResolvedTheme, string][]) {
    // What `--accent-control` and `--focus` resolve to: the stylesheet's own default and the
    // contrast-checked values applyBranding() writes for the default brand colour.
    const stylesheet =
      theme === 'dark'
        ? mixWithWhite(DEFAULT_BRANDING.primary, 0.58)
        : hex(DEFAULT_BRANDING.primary)
    const derived = hex(deriveBrandTokens(DEFAULT_BRANDING.primary, theme).accentText)

    it(`the selected radio, switch and score ring are at least 3:1 in ${theme} mode`, () => {
      for (const canvas of ['background', 'surface', 'elevated']) {
        const base = rgb(css, canvas)
        // A segmented control's track is the subtle fill over the canvas.
        for (const backdrop of [base, over(css, 'subtle', base)]) {
          for (const control of [stylesheet, derived]) {
            expect(contrastRatio(control, backdrop), `on ${canvas}`).toBeGreaterThanOrEqual(3)
          }
        }
      }
    })

    it(`a highlighted list item's ring is at least 3:1 in ${theme} mode`, () => {
      for (const canvas of ['surface', 'elevated']) {
        const base = rgb(css, canvas)
        const fill = over(css, 'subtle-hover', base)
        for (const ring of [stylesheet, derived]) {
          expect(contrastRatio(ring, fill), `on ${canvas}`).toBeGreaterThanOrEqual(3)
        }
      }
    })

    it(`the selected segment's outline is at least 3:1 against its track in ${theme} mode`, () => {
      const surface = rgb(css, 'surface')
      const outline = rgb(css, 'border-control')
      expect(contrastRatio(outline, surface)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(outline, over(css, 'subtle', surface))).toBeGreaterThanOrEqual(3)
    })
  }
})
