import {
  clamp,
  contrastRatio,
  oklchToRgb,
  parseHex,
  rgbToOklch,
  toHex,
  type Oklch,
  type Rgb,
} from '@/lib/color'
import type { ResolvedTheme } from '@/lib/theme'

/**
 * Runtime branding. The CSS in styles/tokens.css derives every accent token from
 * `--brand-primary` with color-mix(), so a plain CSS override already works;
 * applyBranding() additionally computes contrast-checked values in OKLCH so any
 * brand colour stays readable (WCAG AA 4.5:1 for text) in light and dark mode.
 */

export interface Branding {
  /** Brand primary colour (hex). Drives buttons, links, focus rings, selection. */
  primary?: string
  /** Secondary brand colour (hex). Used sparingly: logo mark and highlights. */
  accent?: string
  /** Font family name. Must be a bundled font (see README) — nothing is fetched. */
  font?: string
}

export interface BrandTokens {
  /** Solid fill for primary actions. */
  accent: string
  accentHover: string
  /** Text/icon colour placed on `accent`. */
  accentForeground: string
  /** Tinted background for selected/highlighted states. */
  accentSubtle: string
  /** Accent used as text on normal surfaces (links, active icons). */
  accentText: string
  /** Focus ring colour (≥ 3:1 against surfaces). */
  focus: string
}

export const DEFAULT_BRANDING = {
  primary: '#1d5fa8',
  accent: '#1d5fa8',
  font: 'Inter Variable',
} as const satisfies Required<Branding>

/** Mirrors the neutral surfaces in styles/tokens.css (a unit test keeps them in sync). */
export const THEME_SURFACES: Record<
  ResolvedTheme,
  { background: string; surface: string; elevated: string }
> = {
  light: { background: '#f6f6f7', surface: '#ffffff', elevated: '#ffffff' },
  dark: { background: '#151518', surface: '#1b1b1f', elevated: '#222227' },
}

const WHITE: Rgb = { r: 1, g: 1, b: 1 }
const INK: Rgb = { r: 0.063, g: 0.063, b: 0.078 } // #101014
const MIN_TEXT_CONTRAST = 4.5
/** Aim a little above the AA floor so rounding never tips a value under it. */
const TARGET_TEXT_CONTRAST = 4.8
const STYLE_ELEMENT_ID = 'soundings-branding'

const hexOf = (c: Oklch) => toHex(oklchToRgb(c))
const rgbOf = (c: Oklch) => oklchToRgb(c)

/** Moves lightness in `direction` until `test` passes (or lightness runs out). */
function adjustLightness(start: Oklch, direction: 1 | -1, test: (c: Oklch) => boolean): Oklch {
  let color = start
  for (let i = 0; i < 100 && !test(color); i++) {
    const l = clamp(color.l + direction * 0.01, 0, 1)
    if (l === color.l) break
    color = { ...color, l }
  }
  return color
}

export function deriveBrandTokens(primary: string, theme: ResolvedTheme): BrandTokens {
  const parsed = parseHex(primary) ?? parseHex(DEFAULT_BRANDING.primary)
  if (!parsed) throw new Error('Unreachable: default brand colour is valid')
  const base = rgbToOklch(parsed)
  const surfaces = THEME_SURFACES[theme]

  // 1. Solid fill + foreground: pick the more readable of white/ink, then nudge the
  //    fill's lightness until the pair reaches AA.
  const onWhite = contrastRatio(oklchToRgb(base), WHITE)
  const onInk = contrastRatio(oklchToRgb(base), INK)
  const foreground = onWhite >= onInk ? WHITE : INK
  const direction = foreground === WHITE ? -1 : 1
  const fill = adjustLightness(
    base,
    direction,
    (c) => contrastRatio(rgbOf(c), foreground) >= TARGET_TEXT_CONTRAST,
  )
  // Hover always moves away from the foreground, so contrast only improves.
  const hover = { ...fill, l: clamp(fill.l + direction * 0.05, 0, 1) }

  // 2. Subtle tint for selected rows / highlighted chips.
  const subtle: Oklch =
    theme === 'light'
      ? { l: 0.955, c: Math.min(base.c * 0.3, 0.035), h: base.h }
      : { l: 0.29, c: Math.min(base.c * 0.45, 0.06), h: base.h }

  // 3. Accent as text: must read on every surface it can sit on, including the tint.
  const backgrounds = [surfaces.background, surfaces.surface, surfaces.elevated]
    .map((hex) => parseHex(hex))
    .filter((rgb): rgb is Rgb => rgb !== null)
    .concat(oklchToRgb(subtle))
  const readable = (c: Oklch) =>
    backgrounds.every((bg) => contrastRatio(rgbOf(c), bg) >= TARGET_TEXT_CONTRAST)
  const textStart = theme === 'dark' ? { ...base, l: Math.max(base.l, 0.72) } : base
  const text = adjustLightness(textStart, theme === 'light' ? -1 : 1, readable)

  return {
    accent: hexOf(fill),
    accentHover: hexOf(hover),
    accentForeground: toHex(foreground),
    accentSubtle: hexOf(subtle),
    accentText: hexOf(text),
    focus: hexOf(text),
  }
}

/** Only allow plain family names so a branding value can never inject CSS. */
export function sanitizeFontFamily(font: string): string | null {
  const trimmed = font.trim()
  return /^[A-Za-z0-9 _-]{1,64}$/.test(trimmed) ? trimmed : null
}

function tokensToCss(tokens: BrandTokens): string {
  return [
    `--accent: ${tokens.accent}`,
    `--accent-hover: ${tokens.accentHover}`,
    `--accent-foreground: ${tokens.accentForeground}`,
    `--accent-subtle: ${tokens.accentSubtle}`,
    `--fg-accent: ${tokens.accentText}`,
    `--focus: ${tokens.focus}`,
  ].join('; ')
}

/** Builds the stylesheet applyBranding() injects. Exposed for tests. */
export function brandingStylesheet(branding: Branding): string {
  const primary = branding.primary && parseHex(branding.primary) ? branding.primary : null
  const accent = branding.accent && parseHex(branding.accent) ? branding.accent : null
  const font = branding.font ? sanitizeFontFamily(branding.font) : null

  const rootVars: string[] = []
  if (primary) rootVars.push(`--brand-primary: ${toHex(parseHex(primary) ?? WHITE)}`)
  if (accent) rootVars.push(`--brand-accent: ${toHex(parseHex(accent) ?? WHITE)}`)
  if (font) rootVars.push(`--brand-font: "${font}"`)

  const rules: string[] = []
  if (rootVars.length) rules.push(`:root { ${rootVars.join('; ')}; }`)
  if (primary) {
    rules.push(`:root, .light { ${tokensToCss(deriveBrandTokens(primary, 'light'))}; }`)
    rules.push(`.dark { ${tokensToCss(deriveBrandTokens(primary, 'dark'))}; }`)
  }
  return rules.join('\n')
}

/**
 * Applies brand colours/font at runtime. Unset or invalid fields fall back to
 * the defaults in tokens.css. Calling it again replaces the previous branding.
 */
export function applyBranding(branding: Branding, doc: Document = document): void {
  const css = brandingStylesheet(branding)
  let style = doc.getElementById(STYLE_ELEMENT_ID)
  if (!css) {
    style?.remove()
    return
  }
  if (!style) {
    style = doc.createElement('style')
    style.id = STYLE_ELEMENT_ID
    doc.head.appendChild(style)
  }
  style.textContent = css
}

export function resetBranding(doc: Document = document): void {
  doc.getElementById(STYLE_ELEMENT_ID)?.remove()
}

export { MIN_TEXT_CONTRAST }
