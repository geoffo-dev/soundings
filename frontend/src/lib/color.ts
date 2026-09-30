/**
 * Minimal colour maths for runtime branding: hex <-> OKLCH conversion and
 * WCAG 2 contrast. Kept dependency-free on purpose (a few dozen lines beats a
 * colour library in the bundle).
 */

export interface Rgb {
  /** 0..1 gamma-encoded sRGB channels */
  r: number
  g: number
  b: number
}

export interface Oklch {
  /** perceptual lightness 0..1 */
  l: number
  /** chroma, roughly 0..0.37 */
  c: number
  /** hue in degrees 0..360 */
  h: number
}

const HEX_RE = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i

export function parseHex(input: string): Rgb | null {
  const match = HEX_RE.exec(input.trim())
  if (!match?.[1]) return null
  let hex = match[1]
  if (hex.length === 3) hex = hex.replace(/./g, '$&$&')
  const n = Number.parseInt(hex, 16)
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 }
}

export function toHex({ r, g, b }: Rgb): string {
  const channel = (v: number) =>
    Math.round(clamp(v, 0, 1) * 255)
      .toString(16)
      .padStart(2, '0')
  return `#${channel(r)}${channel(g)}${channel(b)}`
}

const toLinear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
const toGamma = (v: number) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)

export function rgbToOklch(rgb: Rgb): Oklch {
  const r = toLinear(rgb.r)
  const g = toLinear(rgb.g)
  const b = toLinear(rgb.b)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
  const c = Math.sqrt(A * A + B * B)
  const h = c < 1e-4 ? 0 : ((Math.atan2(B, A) * 180) / Math.PI + 360) % 360
  return { l: L, c, h }
}

function oklchToLinear({ l: L, c, h }: Oklch): [number, number, number] {
  const hr = (h * Math.PI) / 180
  const A = c * Math.cos(hr)
  const B = c * Math.sin(hr)
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ]
}

const inGamut = (channels: number[]) => channels.every((v) => v >= -1e-4 && v <= 1 + 1e-4)

/** Converts to sRGB, reducing chroma until the colour fits the sRGB gamut. */
export function oklchToRgb(color: Oklch): Rgb {
  let c = color.c
  let linear = oklchToLinear({ ...color, c })
  while (!inGamut(linear) && c > 0) {
    c = Math.max(0, c - 0.005)
    linear = oklchToLinear({ ...color, c })
  }
  const [r, g, b] = linear.map((v) => toGamma(clamp(v, 0, 1))) as [number, number, number]
  return { r, g, b }
}

export function relativeLuminance({ r, g, b }: Rgb): number {
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
}

/** WCAG 2.x contrast ratio, 1..21. */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a)
  const lb = relativeLuminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

export function contrastHex(a: string, b: string): number {
  const ra = parseHex(a)
  const rb = parseHex(b)
  if (!ra || !rb) throw new Error(`Invalid colour: ${a} / ${b}`)
  return contrastRatio(ra, rb)
}

/** Linear sRGB mix of two colours (weight = share of `a`). */
export function mixRgb(a: Rgb, b: Rgb, weight: number): Rgb {
  return {
    r: a.r * weight + b.r * (1 - weight),
    g: a.g * weight + b.g * (1 - weight),
    b: a.b * weight + b.b * (1 - weight),
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
