import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'
import type { BrandAsset, InheritedBranding } from '@/api/types'

import {
  EMPTY_BRANDING_FORM,
  isEmptyProfile,
  normaliseHex,
  previewBranding,
  sameProfile,
  saveErrors,
  toUpdate,
  uploadErrorMessage,
  validateBranding,
} from './branding-form'
import { accentAdvice, primaryAdvice } from './contrast'

const LOGO: BrandAsset = {
  id: '0f0f0f0f-0000-4000-8000-000000000001',
  kind: 'logo',
  content_type: 'image/png',
  byte_size: 2048,
  width: 64,
  height: 64,
  url: '/api/v1/branding/assets/0f0f0f0f-0000-4000-8000-000000000001',
  created_at: '2026-10-01T10:00:00Z',
}
const INHERITED: InheritedBranding = {
  app_name: 'Soundings',
  primary_color: '#1d5fa8',
  accent_color: '#1d5fa8',
  font: 'inter',
  email_footer: null,
  logo: null,
  favicon: null,
}
const form = (patch = {}) => ({ ...EMPTY_BRANDING_FORM, ...patch })

describe('normaliseHex', () => {
  it('accepts hex colours only, normalised to #rrggbb', () => {
    expect(normaliseHex('#1D5FA8')).toBe('#1d5fa8')
    expect(normaliseHex('1d5fa8')).toBe('#1d5fa8')
    expect(normaliseHex('#abc')).toBe('#aabbcc')
    for (const bad of [
      'red',
      '#12345g',
      'rgb(0,0,0)',
      '#1d5fa8; } body { display: none',
      'url(http://x/y.png)',
      'var(--x)',
      '',
    ]) {
      expect(normaliseHex(bad)).toBeNull()
    }
  })
})

describe('validateBranding', () => {
  it('refuses anything but hex colours (no CSS injection)', () => {
    const errors = validateBranding(form({ primary_color: 'red; } * { color: red' }))
    expect(Object.keys(errors)).toEqual(['primary_color'])
    expect(errors.primary_color).toMatch(/hex colour/)
    expect(
      validateBranding(form({ accent_color: 'expression(alert(1))' })).accent_color,
    ).toBeDefined()
    expect(validateBranding(form({ primary_color: '#2e7d4f' }))).toEqual({})
  })

  it('keeps the app name to one short line of text', () => {
    expect(validateBranding(form({ app_name: 'x'.repeat(41) })).app_name).toMatch(/40/)
    expect(validateBranding(form({ app_name: 'Acme\nIdeas' })).app_name).toMatch(/one line/)
    expect(validateBranding(form({ app_name: 'Acme‮seditI' })).app_name).toBeDefined()
    expect(validateBranding(form({ app_name: 'Acme Ideas' }))).toEqual({})
  })

  it('keeps the email footer to five lines of plain text', () => {
    expect(validateBranding(form({ email_footer: 'a\nb\nc\nd\ne\nf' })).email_footer).toMatch(
      /5 lines/,
    )
    expect(validateBranding(form({ email_footer: 'x'.repeat(501) })).email_footer).toMatch(/500/)
    expect(validateBranding(form({ email_footer: 'Acme\u0007' })).email_footer).toBeDefined()
    expect(validateBranding(form({ email_footer: 'Acme Ltd\n1 High Street' }))).toEqual({})
  })
})

describe('toUpdate', () => {
  it('sends the complete profile with null for every inherited field', () => {
    expect(toUpdate(EMPTY_BRANDING_FORM)).toEqual({
      app_name: null,
      primary_color: null,
      accent_color: null,
      font: null,
      email_footer: null,
      logo_asset_id: null,
      favicon_asset_id: null,
    })
    expect(
      toUpdate(
        form({
          app_name: '  Acme Ideas ',
          primary_color: 'B42318',
          font: 'ibm_plex_sans',
          email_footer: ' Acme Ltd  \r\n 1 High Street \n',
          logo: LOGO,
        }),
      ),
    ).toEqual({
      app_name: 'Acme Ideas',
      primary_color: '#b42318',
      accent_color: null,
      font: 'ibm_plex_sans',
      email_footer: 'Acme Ltd\n 1 High Street',
      logo_asset_id: LOGO.id,
      favicon_asset_id: null,
    })
  })

  it('compares profiles by what would be saved', () => {
    expect(sameProfile(form({ primary_color: '#ABC' }), form({ primary_color: '#aabbcc' }))).toBe(
      true,
    )
    expect(isEmptyProfile(form({ app_name: '  ' }))).toBe(true)
    expect(isEmptyProfile(form({ logo: LOGO }))).toBe(false)
  })
})

describe('previewBranding', () => {
  it('shows each field, or what it inherits while empty or invalid', () => {
    expect(previewBranding(form({ primary_color: '#zzz', logo: LOGO }), INHERITED)).toEqual({
      app_name: 'Soundings',
      primary_color: '#1d5fa8',
      accent_color: '#1d5fa8',
      font: 'inter',
      email_footer: null,
      logo_url: LOGO.url,
      favicon_url: null,
    })
    expect(
      previewBranding(form({ app_name: 'Acme', primary_color: '#b42318' }), INHERITED),
    ).toMatchObject({ app_name: 'Acme', primary_color: '#b42318' })
  })

  it('names a project with its own logo and no app name after the project', () => {
    const project = 'Customer Innovation'
    expect(previewBranding(form({ logo: LOGO }), INHERITED, project).app_name).toBe(project)
    // Its own app name wins; without a logo of its own it inherits the name.
    expect(
      previewBranding(form({ logo: LOGO, app_name: 'Lab' }), INHERITED, project).app_name,
    ).toBe('Lab')
    expect(previewBranding(form({ primary_color: '#b42318' }), INHERITED, project).app_name).toBe(
      'Soundings',
    )
    // The global profile has no project.
    expect(previewBranding(form({ logo: LOGO }), INHERITED).app_name).toBe('Soundings')
  })
})

describe('errors', () => {
  const error = (status: number, code: string, loc?: string, msg = 'bad') =>
    new ApiError({
      status,
      code,
      title: code,
      problem: loc ? { errors: [{ loc: ['body', loc], msg, type: 'value_error' }] } : undefined,
    })

  it('puts save errors on their fields', () => {
    expect(saveErrors(error(422, 'validation_error', 'primary_color', 'hex only'))).toEqual({
      primary_color: 'hex only',
    })
    expect(saveErrors(error(422, 'invalid_asset', 'logo_asset_id'))).toEqual({
      logo: 'Upload this image again, then save.',
    })
    expect(saveErrors(error(409, 'project_archived')).form).toMatch(/archived/)
  })

  it('explains upload failures', () => {
    expect(uploadErrorMessage(error(413, 'content_too_large'), 512)).toMatch(/512 KB/)
    expect(uploadErrorMessage(error(429, 'too_many_attempts'), 512)).toMatch(/tomorrow/)
    expect(
      uploadErrorMessage(error(422, 'invalid_image', 'body', 'SVG element <script>'), 512),
    ).toBe('That image can’t be used: SVG element <script>')
  })
})

describe('contrast advice', () => {
  it('says when button text would be hard to read on the primary colour', () => {
    expect(primaryAdvice('#1d5fa8').tone).toBe('ok')
    const pale = primaryAdvice('#ffeb3b')
    expect(pale.tone).toBe('ok') // dark text on yellow reads fine
    const mid = primaryAdvice('#787878')
    expect(mid.tone).toBe('warning')
    expect(mid.message).toMatch(/AA needs 4\.5:1/)
  })

  it('warns when the logo mark’s white lines would vanish', () => {
    expect(accentAdvice('#1d5fa8').tone).toBe('ok')
    expect(accentAdvice('#ffeb3b').tone).toBe('warning')
  })
})
