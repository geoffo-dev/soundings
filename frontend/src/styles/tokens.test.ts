import { describe, expect, it } from 'vitest'

import { contrastHex } from '@/lib/color'
import tokensCss from '@/styles/tokens.css?raw'

function block(selector: RegExp): string {
  return tokensCss.match(selector)?.[0] ?? ''
}

function token(css: string, name: string): string {
  const value = new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i').exec(css)?.[1]
  if (!value) throw new Error(`--${name} missing`)
  return value
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
