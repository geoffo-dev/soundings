import { useSyncExternalStore } from 'react'

import type { BrandFont, EffectiveBranding } from '@/api/types'
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

/* ------------------------------------------------------------------ */
/* Runtime branding from the API (contract-phase4 §3.10)               */
/* ------------------------------------------------------------------ */

/**
 * The bundled fonts a branding profile may choose (`BrandFont`), as CSS family
 * names. Inter is always loaded (main.tsx); the others load only when chosen.
 * The key is mapped here, so no font name from the API ever reaches CSS.
 */
export const BRAND_FONTS = {
  inter: { family: 'Inter Variable', label: 'Inter', note: 'The default: neutral and compact' },
  ibm_plex_sans: { family: 'IBM Plex Sans', label: 'IBM Plex Sans', note: 'Technical, friendly' },
  source_serif_4: {
    family: 'Source Serif 4',
    label: 'Source Serif 4',
    note: 'A serif, for a classic look',
  },
  atkinson_hyperlegible: {
    family: 'Atkinson Hyperlegible',
    label: 'Atkinson Hyperlegible',
    note: 'Designed for low-vision readers',
  },
} as const satisfies Record<BrandFont, { family: string; label: string; note: string }>

export const BRAND_FONT_KEYS = Object.keys(BRAND_FONTS) as BrandFont[]

export function isBrandFont(value: unknown): value is BrandFont {
  return typeof value === 'string' && Object.hasOwn(BRAND_FONTS, value)
}

/** Latin + Latin Extended, the weights the design system uses (Atkinson has 400 and 700). */
const FONT_LOADERS: Record<BrandFont, () => Promise<unknown>> = {
  inter: () => Promise.resolve(),
  ibm_plex_sans: () =>
    Promise.all([
      import('@fontsource/ibm-plex-sans/latin-400.css'),
      import('@fontsource/ibm-plex-sans/latin-ext-400.css'),
      import('@fontsource/ibm-plex-sans/latin-500.css'),
      import('@fontsource/ibm-plex-sans/latin-ext-500.css'),
      import('@fontsource/ibm-plex-sans/latin-600.css'),
      import('@fontsource/ibm-plex-sans/latin-ext-600.css'),
      import('@fontsource/ibm-plex-sans/latin-700.css'),
      import('@fontsource/ibm-plex-sans/latin-ext-700.css'),
    ]),
  source_serif_4: () =>
    Promise.all([
      import('@fontsource/source-serif-4/latin-400.css'),
      import('@fontsource/source-serif-4/latin-ext-400.css'),
      import('@fontsource/source-serif-4/latin-500.css'),
      import('@fontsource/source-serif-4/latin-ext-500.css'),
      import('@fontsource/source-serif-4/latin-600.css'),
      import('@fontsource/source-serif-4/latin-ext-600.css'),
      import('@fontsource/source-serif-4/latin-700.css'),
      import('@fontsource/source-serif-4/latin-ext-700.css'),
    ]),
  atkinson_hyperlegible: () =>
    Promise.all([
      import('@fontsource/atkinson-hyperlegible/latin-400.css'),
      import('@fontsource/atkinson-hyperlegible/latin-ext-400.css'),
      import('@fontsource/atkinson-hyperlegible/latin-700.css'),
      import('@fontsource/atkinson-hyperlegible/latin-ext-700.css'),
    ]),
}

const fontLoads = new Map<BrandFont, Promise<unknown>>()

/** Loads a bundled font's files once (a CSS chunk of the build; nothing is fetched elsewhere). */
export function loadBrandFont(font: BrandFont): Promise<unknown> {
  let load = fontLoads.get(font)
  if (!load) {
    load = FONT_LOADERS[font]().catch(() => {
      fontLoads.delete(font)
    })
    fontLoads.set(font, load)
  }
  return load
}

/** `DEFAULT_BRANDING` (contract-phase4 §3.10): Soundings, #1d5fa8, Inter, the bundled favicon. */
export const DEFAULT_EFFECTIVE_BRANDING: EffectiveBranding = {
  app_name: 'Soundings',
  primary_color: DEFAULT_BRANDING.primary,
  accent_color: DEFAULT_BRANDING.accent,
  font: 'inter',
  logo_url: null,
  favicon_url: null,
}

const HEX_COLOR = /^#[0-9a-f]{6}$/i
/** Images are served by the app itself; nothing else may become an `<img src>` or icon. */
const ASSET_URL = /^\/api\/v1\/branding\/assets\/[0-9a-fA-F-]{36}$/
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f\u2028\u2029\u202a-\u202e\u2066-\u2069]/

/** A branding object as the API sends it, checked field by field (anything odd → default). */
export function sanitizeEffectiveBranding(value: unknown): EffectiveBranding {
  const record = (typeof value === 'object' && value !== null ? value : {}) as Record<
    string,
    unknown
  >
  const text = (key: string) => (typeof record[key] === 'string' ? record[key] : '')
  const appName = text('app_name').trim()
  const color = (key: string, fallback: string) =>
    HEX_COLOR.test(text(key)) ? text(key).toLowerCase() : fallback
  const asset = (key: string) => (ASSET_URL.test(text(key)) ? text(key) : null)
  return {
    app_name:
      appName && appName.length <= 40 && !CONTROL.test(appName)
        ? appName
        : DEFAULT_EFFECTIVE_BRANDING.app_name,
    primary_color: color('primary_color', DEFAULT_EFFECTIVE_BRANDING.primary_color),
    accent_color: color('accent_color', DEFAULT_EFFECTIVE_BRANDING.accent_color),
    font: isBrandFont(record.font) ? record.font : 'inter',
    logo_url: asset('logo_url'),
    favicon_url: asset('favicon_url'),
  }
}

/** The colours and font of an effective branding, for applyBranding(). */
export function brandingOf(branding: EffectiveBranding): Branding {
  return {
    primary: branding.primary_color,
    accent: branding.accent_color,
    font: BRAND_FONTS[branding.font].family,
  }
}

/**
 * CSS custom properties that re-theme one subtree (the settings' live
 * previews): the derived accent tokens for `theme` and the brand font (for
 * `font-brand`, as in the app: page titles and the wordmark; a preview of a
 * public page or an email uses it for all its text). Applied with
 * `style.setProperty`, so only validated hex colours and fixed family names
 * ever reach CSS.
 */
export function brandPreviewProperties(
  branding: Pick<EffectiveBranding, 'primary_color' | 'accent_color' | 'font'>,
  theme: ResolvedTheme,
): Record<string, string> {
  const primary = HEX_COLOR.test(branding.primary_color)
    ? branding.primary_color
    : DEFAULT_BRANDING.primary
  const accent = HEX_COLOR.test(branding.accent_color) ? branding.accent_color : primary
  const tokens = deriveBrandTokens(primary, theme)
  const family = BRAND_FONTS[isBrandFont(branding.font) ? branding.font : 'inter'].family
  const fontStack = `"${family}", "Inter Variable", ui-sans-serif, system-ui, sans-serif`
  return {
    '--brand-primary': primary,
    '--brand-accent': accent,
    '--brand-font': `"${family}"`,
    '--accent': tokens.accent,
    '--accent-hover': tokens.accentHover,
    '--accent-foreground': tokens.accentForeground,
    '--accent-subtle': tokens.accentSubtle,
    '--fg-accent': tokens.accentText,
    '--focus': tokens.focus,
    '--font-brand': fontStack,
  }
}

/** Sets `properties` on an element (and removes the ones it set before). */
export function setElementProperties(
  element: HTMLElement,
  properties: Record<string, string>,
): () => void {
  for (const [name, value] of Object.entries(properties)) element.style.setProperty(name, value)
  return () => {
    for (const name of Object.keys(properties)) element.style.removeProperty(name)
  }
}

/** Text colour (white or ink) with the better contrast on a colour, and that contrast. */
export function readableOn(hex: string): { color: string; contrast: number } {
  const rgb = parseHex(hex) ?? WHITE
  const white = contrastRatio(rgb, WHITE)
  const ink = contrastRatio(rgb, INK)
  return white >= ink ? { color: '#ffffff', contrast: white } : { color: toHex(INK), contrast: ink }
}

/* The applied branding: a small store so the shell (logo, app name) follows it. */

const BRANDING_STORAGE_KEY = 'soundings-branding'
const DEFAULT_FAVICON = { href: '/favicon.svg', type: 'image/svg+xml' }

let globalBranding: EffectiveBranding | null = null
let overrideBranding: EffectiveBranding | null = null
let appliedBranding: EffectiveBranding = DEFAULT_EFFECTIVE_BRANDING
const brandingListeners = new Set<() => void>()

function sameBranding(a: EffectiveBranding, b: EffectiveBranding): boolean {
  return (
    a.app_name === b.app_name &&
    a.primary_color === b.primary_color &&
    a.accent_color === b.accent_color &&
    a.font === b.font &&
    a.logo_url === b.logo_url &&
    a.favicon_url === b.favicon_url
  )
}

function setFavicon(url: string | null, doc: Document): void {
  let link = doc.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!link) {
    link = doc.createElement('link')
    link.rel = 'icon'
    doc.head.appendChild(link)
  }
  const href = url ?? DEFAULT_FAVICON.href
  if (link.getAttribute('href') === href) return
  link.href = href
  // An uploaded favicon may be a PNG or an SVG: let the browser read the type.
  if (url) link.removeAttribute('type')
  else link.type = DEFAULT_FAVICON.type
}

/* document.title: route titles end in "· Soundings"; the app name replaces it. */
let titleObserver: MutationObserver | null = null
let titleName = DEFAULT_EFFECTIVE_BRANDING.app_name

/** Replaces the product name in a page title with the app name (exposed for tests). */
export function brandTitle(title: string, appName: string): string {
  const name = DEFAULT_EFFECTIVE_BRANDING.app_name
  if (title === name) return appName
  return title.endsWith(` · ${name}`) ? `${title.slice(0, -name.length)}${appName}` : title
}

function syncTitle(appName: string, doc: Document): void {
  titleName = appName
  const fix = () => {
    const next = brandTitle(doc.title, titleName)
    if (next !== doc.title) doc.title = next
  }
  if (appName === DEFAULT_EFFECTIVE_BRANDING.app_name) {
    titleObserver?.disconnect()
    titleObserver = null
    return
  }
  fix()
  if (!titleObserver && typeof MutationObserver !== 'undefined') {
    titleObserver = new MutationObserver(fix)
    titleObserver.observe(doc.head, { subtree: true, childList: true, characterData: true })
  }
}

function refreshBranding(doc: Document = document): void {
  const next = overrideBranding ?? globalBranding ?? DEFAULT_EFFECTIVE_BRANDING
  const isDefault = sameBranding(next, DEFAULT_EFFECTIVE_BRANDING)
  if (isDefault) resetBranding(doc)
  else applyBranding(brandingOf(next), doc)
  void loadBrandFont(next.font)
  setFavicon(next.favicon_url, doc)
  // Restore titles that already carry a previous custom name.
  if (titleName !== next.app_name && titleName !== DEFAULT_EFFECTIVE_BRANDING.app_name) {
    const previous = ` · ${titleName}`
    if (doc.title === titleName) doc.title = DEFAULT_EFFECTIVE_BRANDING.app_name
    else if (doc.title.endsWith(previous)) {
      doc.title = `${doc.title.slice(0, -previous.length)} · ${DEFAULT_EFFECTIVE_BRANDING.app_name}`
    }
  }
  syncTitle(next.app_name, doc)
  if (!sameBranding(next, appliedBranding)) {
    appliedBranding = next
    brandingListeners.forEach((listener) => listener())
  }
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage
  } catch {
    return undefined
  }
}

/** The instance's branding (GET /branding): applied, and remembered for the next page load. */
export function setGlobalBranding(branding: EffectiveBranding, storage = safeStorage()): void {
  globalBranding = sanitizeEffectiveBranding(branding)
  try {
    storage?.setItem(BRANDING_STORAGE_KEY, JSON.stringify(globalBranding))
  } catch {
    // Storage full or disabled: the next load starts from the defaults.
  }
  refreshBranding()
}

/** A public page's project branding (null: back to the global one). */
export function setBrandingOverride(branding: EffectiveBranding | null): void {
  overrideBranding = branding ? sanitizeEffectiveBranding(branding) : null
  refreshBranding()
}

/**
 * Applies the branding remembered from the last visit before the first render
 * (main.tsx), so a branded instance doesn't flash the default colours.
 */
export function restoreRememberedBranding(storage = safeStorage()): void {
  try {
    const raw = storage?.getItem(BRANDING_STORAGE_KEY)
    if (raw) {
      globalBranding = sanitizeEffectiveBranding(JSON.parse(raw) as unknown)
      refreshBranding()
    }
  } catch {
    // Unreadable: the defaults stay until GET /branding answers.
  }
}

/** The branding in effect now (the shell's logo and app name follow it). */
export function currentBranding(): EffectiveBranding {
  return appliedBranding
}

export function subscribeBranding(listener: () => void): () => void {
  brandingListeners.add(listener)
  return () => brandingListeners.delete(listener)
}

export function useAppBranding(): EffectiveBranding {
  return useSyncExternalStore(subscribeBranding, currentBranding, currentBranding)
}

/** Back to the defaults (tests). */
export function resetRuntimeBranding(doc: Document = document): void {
  globalBranding = null
  overrideBranding = null
  refreshBranding(doc)
}
