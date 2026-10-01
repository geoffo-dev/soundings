import { deriveBrandTokens, MIN_TEXT_CONTRAST, readableOn } from '@/lib/branding'
import { contrastHex } from '@/lib/color'

/**
 * Contrast advice for the colour pickers (WCAG 2.2 AA). Any colour can be
 * saved: the SPA derives readable shades from it (lib/branding.ts), so these
 * say what will happen rather than refusing.
 */

export interface ColourAdvice {
  tone: 'ok' | 'warning'
  message: string
}

const ratio = (value: number) => `${(Math.floor(value * 10) / 10).toFixed(1)}:1`

/** The primary colour fills buttons: white or dark text must reach 4.5:1 on it. */
export function primaryAdvice(hex: string): ColourAdvice {
  const { contrast } = readableOn(hex)
  if (contrast >= MIN_TEXT_CONTRAST) {
    return { tone: 'ok', message: `Button text on it: ${ratio(contrast)} (meets AA).` }
  }
  const light = deriveBrandTokens(hex, 'light')
  const darker = contrastHex(light.accent, '#ffffff') > contrastHex(hex, '#ffffff')
  return {
    tone: 'warning',
    message: `Text on this colour is hard to read (${ratio(contrast)}; AA needs 4.5:1). Buttons use a ${darker ? 'darker' : 'lighter'} shade so their text stays readable, as the preview shows.`,
  }
}

/** The accent colour is the logo mark's tile behind white lines: aim for 3:1 (non-text). */
export function accentAdvice(hex: string): ColourAdvice {
  const contrast = contrastHex(hex, '#ffffff')
  if (contrast >= 3) {
    return { tone: 'ok', message: `The logo mark’s white lines: ${ratio(contrast)}.` }
  }
  return {
    tone: 'warning',
    message: `The logo mark’s white lines are hard to see on this colour (${ratio(contrast)}; aim for 3:1). Pick a darker colour, or upload a logo.`,
  }
}
