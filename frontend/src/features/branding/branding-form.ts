import { isApiError } from '@/api/errors'
import type {
  BrandAsset,
  BrandFont,
  BrandingSettings,
  BrandingUpdate,
  InheritedBranding,
} from '@/api/types'
import { parseHex, toHex } from '@/lib/color'

/**
 * The branding settings form (contract-phase4 §3.10): one profile, every field
 * optional (empty = inherit: the built-in default for the global profile, the
 * global branding for a project). Values are checked here as the API checks
 * them, so CSS never sees anything but a `#rrggbb` colour or a font key.
 */

export interface BrandingForm {
  app_name: string
  primary_color: string
  accent_color: string
  font: BrandFont | null
  email_footer: string
  logo: BrandAsset | null
  favicon: BrandAsset | null
}

export type BrandingField = keyof BrandingForm
export type BrandingErrors = Partial<Record<BrandingField | 'form', string>>

export const BRANDING_LIMITS = { appName: 40, footer: 500, footerLines: 5 }

export const EMPTY_BRANDING_FORM: BrandingForm = {
  app_name: '',
  primary_color: '',
  accent_color: '',
  font: null,
  email_footer: '',
  logo: null,
  favicon: null,
}

export function fromSettings(settings: BrandingSettings): BrandingForm {
  return {
    app_name: settings.app_name ?? '',
    primary_color: settings.primary_color ?? '',
    accent_color: settings.accent_color ?? '',
    font: settings.font,
    email_footer: settings.email_footer ?? '',
    logo: settings.logo,
    favicon: settings.favicon,
  }
}

export const HEX_COLOUR_ERROR = 'Use a hex colour such as #1d5fa8.'

/** `#1d5fa8` from "1D5FA8", "#1d5" or "1d5fa8"; null if it isn't a hex colour. */
export function normaliseHex(value: string): string | null {
  const trimmed = value.trim()
  if (!/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(trimmed)) return null
  const rgb = parseHex(trimmed)
  return rgb ? toHex(rgb) : null
}

// Control and bidirectional-override characters (newlines are allowed in the footer only).
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f\u2028\u2029\u202a-\u202e\u2066-\u2069]/
const TAB_OR_NEWLINE = /[\t\r\n]/

export function validateBranding(form: BrandingForm): BrandingErrors {
  const errors: BrandingErrors = {}
  const name = form.app_name.trim()
  if (name.length > BRANDING_LIMITS.appName) {
    errors.app_name = `Use at most ${BRANDING_LIMITS.appName} characters.`
  } else if (CONTROL.test(name) || TAB_OR_NEWLINE.test(name)) {
    errors.app_name = 'Use one line of plain text.'
  }
  for (const field of ['primary_color', 'accent_color'] as const) {
    if (form[field].trim() && !normaliseHex(form[field])) {
      errors[field] = HEX_COLOUR_ERROR
    }
  }
  const footer = form.email_footer.trim()
  if (footer.length > BRANDING_LIMITS.footer) {
    errors.email_footer = `Use at most ${BRANDING_LIMITS.footer} characters.`
  } else if (footer.split('\n').length > BRANDING_LIMITS.footerLines) {
    errors.email_footer = `Use at most ${BRANDING_LIMITS.footerLines} lines.`
  } else if (CONTROL.test(footer.replace(/\t/g, ' '))) {
    errors.email_footer = 'Use plain text only.'
  }
  return errors
}

/** The complete profile to save (null = inherit). */
export function toUpdate(form: BrandingForm): BrandingUpdate {
  const footer = form.email_footer
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => line.trimEnd())
    .join('\n')
    .trim()
  return {
    app_name: form.app_name.trim() || null,
    primary_color: normaliseHex(form.primary_color),
    accent_color: normaliseHex(form.accent_color),
    font: form.font,
    email_footer: footer || null,
    logo_asset_id: form.logo?.id ?? null,
    favicon_asset_id: form.favicon?.id ?? null,
  }
}

/** Same profile once saved; a colour being typed (not valid yet) counts as a change. */
export function sameProfile(a: BrandingForm, b: BrandingForm): boolean {
  const key = (form: BrandingForm) =>
    JSON.stringify({
      ...toUpdate(form),
      primary_color: normaliseHex(form.primary_color) ?? form.primary_color.trim(),
      accent_color: normaliseHex(form.accent_color) ?? form.accent_color.trim(),
    })
  return key(a) === key(b)
}

export function isEmptyProfile(form: BrandingForm): boolean {
  return Object.values(toUpdate(form)).every((value) => value === null)
}

/** What the form would look like once saved: each field or what it inherits. */
export interface PreviewBranding {
  app_name: string
  primary_color: string
  accent_color: string
  font: BrandFont
  email_footer: string | null
  logo_url: string | null
  favicon_url: string | null
}

/**
 * `projectName` is given for a project's override: one with a logo of its own and no
 * app name is the project's own brand, so the project's name is its wordmark (in its
 * emails, PDF header and public pages), as the API resolves it.
 */
export function previewBranding(
  form: BrandingForm,
  inherited: InheritedBranding,
  projectName?: string,
): PreviewBranding {
  const name = form.app_name.trim()
  const ownName = name && name.length <= BRANDING_LIMITS.appName ? name : null
  const projectBrand = projectName && form.logo && !name ? projectName : null
  return {
    app_name: ownName ?? projectBrand ?? inherited.app_name,
    primary_color: normaliseHex(form.primary_color) ?? inherited.primary_color,
    accent_color: normaliseHex(form.accent_color) ?? inherited.accent_color,
    font: form.font ?? inherited.font,
    email_footer: form.email_footer.trim() || inherited.email_footer,
    logo_url: form.logo?.url ?? inherited.logo?.url ?? null,
    favicon_url: form.favicon?.url ?? inherited.favicon?.url ?? null,
  }
}

const SERVER_FIELDS: Record<string, BrandingField> = {
  app_name: 'app_name',
  primary_color: 'primary_color',
  accent_color: 'accent_color',
  font: 'font',
  email_footer: 'email_footer',
  logo_asset_id: 'logo',
  favicon_asset_id: 'favicon',
}

/** A failed save as inline errors (fields, or one message for the form). */
export function saveErrors(error: unknown): BrandingErrors {
  if (isApiError(error)) {
    const errors: BrandingErrors = {}
    for (const entry of error.problem?.errors ?? []) {
      const field = SERVER_FIELDS[String(entry.loc.at(-1))]
      if (field && !errors[field]) {
        errors[field] =
          error.code === 'invalid_asset' ? 'Upload this image again, then save.' : entry.msg
      }
    }
    if (Object.keys(errors).length > 0) return errors
    if (error.code === 'invalid_asset') {
      return { form: 'An image can’t be used any more. Upload it again, then save.' }
    }
    if (error.code === 'project_archived') {
      return { form: 'This project is archived, so its settings are read-only.' }
    }
    if (error.isNetworkError) return { form: 'Can’t reach the server. Check your connection.' }
  }
  return { form: 'Couldn’t save the branding. Try again.' }
}

/** What an image upload failure means for the person (413, 422 invalid_image, 429). */
export function uploadErrorMessage(error: unknown, maxKb: number): string {
  if (isApiError(error)) {
    if (error.status === 413) return `That file is larger than ${maxKb} KB.`
    if (error.status === 429) return 'You’ve uploaded a lot of images today. Try again tomorrow.'
    if (error.code === 'invalid_image') {
      const reason = error.problem?.errors?.[0]?.msg ?? error.detail
      return reason ? `That image can’t be used: ${reason}` : 'That image can’t be used.'
    }
    if (error.code === 'project_archived') return 'This project is archived.'
    if (error.isNetworkError) return 'Can’t reach the server. Check your connection.'
  }
  return 'The upload didn’t work. Try again.'
}
