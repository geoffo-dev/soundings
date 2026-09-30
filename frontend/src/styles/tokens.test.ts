import { describe, expect, it } from 'vitest'

import { contrastHex, contrastRatio, mixRgb, parseHex, type Rgb } from '@/lib/color'
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
