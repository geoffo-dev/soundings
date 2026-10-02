/**
 * Phase 4 branding in the mock API (contract-phase4 §3.10–3.11): one global
 * profile and optional per-project overrides, resolved field by field
 * (project → global → built-in default), and uploaded logos and favicons
 * (PNG or SVG, checked roughly like the API does). The backend is the authority.
 */
import type {
  BrandAsset,
  BrandAssetKind,
  BrandFont,
  BrandingSettings,
  EffectiveBranding,
  InheritedBranding,
} from '@/api/types'

import type { MockDb } from './db'
import { userRefById } from './domain'

export interface MockBrandingProfile {
  /** Null: the global profile (at most one). */
  project_id: string | null
  app_name: string | null
  primary_color: string | null
  accent_color: string | null
  font: BrandFont | null
  email_footer: string | null
  logo_asset_id: string | null
  favicon_asset_id: string | null
  updated_at: string
  updated_by_id: string | null
}

export interface MockBrandAsset {
  id: string
  /** Null: uploaded for the global profile. */
  project_id: string | null
  kind: BrandAssetKind
  content_type: 'image/png' | 'image/svg+xml'
  bytes: Uint8Array
  width: number | null
  height: number | null
  created_at: string
}

/** `DEFAULT_BRANDING` (ADR 0009): Soundings, deep ocean blue, Inter. */
export const DEFAULT_BRANDING = {
  app_name: 'Soundings',
  primary_color: '#1d5fa8',
  accent_color: '#1d5fa8',
  font: 'inter' as BrandFont,
}

export const BRAND_FONTS: BrandFont[] = [
  'inter',
  'ibm_plex_sans',
  'source_serif_4',
  'atkinson_hyperlegible',
]
export const APP_NAME_MAX_LENGTH = 40
export const EMAIL_FOOTER_MAX_LENGTH = 500
export const EMAIL_FOOTER_MAX_LINES = 5
/** `SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES` default. */
export const MAX_UPLOAD_BYTES = 512 * 1024
export const UPLOADS_PER_DAY = 20

export function profileFor(db: MockDb, projectId: string | null): MockBrandingProfile | undefined {
  return db.brandingProfiles.find((profile) => profile.project_id === projectId)
}

export function assetUrl(asset: MockBrandAsset): string {
  return `/api/v1/branding/assets/${asset.id}`
}

export function assetOut(asset: MockBrandAsset): BrandAsset {
  return {
    id: asset.id,
    kind: asset.kind,
    content_type: asset.content_type,
    byte_size: asset.bytes.byteLength,
    width: asset.width,
    height: asset.height,
    url: assetUrl(asset),
    created_at: asset.created_at,
  }
}

function asset(db: MockDb, id: string | null | undefined): MockBrandAsset | undefined {
  return id ? db.brandAssets.find((a) => a.id === id) : undefined
}

/** What a global field falls back to (built-in defaults) or a project's (the global result). */
export function inheritedBranding(db: MockDb, projectId: string | null): InheritedBranding {
  if (projectId === null) {
    return { ...DEFAULT_BRANDING, email_footer: null, logo: null, favicon: null }
  }
  const global = profileFor(db, null)
  const inherited = inheritedBranding(db, null)
  const logo = asset(db, global?.logo_asset_id)
  const favicon = asset(db, global?.favicon_asset_id)
  return {
    app_name: global?.app_name ?? inherited.app_name,
    primary_color: global?.primary_color ?? inherited.primary_color,
    accent_color: global?.accent_color ?? inherited.accent_color,
    font: global?.font ?? inherited.font,
    email_footer: global?.email_footer ?? null,
    logo: logo ? assetOut(logo) : null,
    favicon: favicon ? assetOut(favicon) : null,
  }
}

/**
 * Resolved field by field: project override → global → default (§3.10); a project
 * with a logo of its own and no app name is named after itself (UX M3, as the API).
 */
export function effectiveBranding(db: MockDb, projectId: string | null): EffectiveBranding {
  const inherited = inheritedBranding(db, projectId)
  const profile = profileFor(db, projectId)
  const logo = asset(db, profile?.logo_asset_id)
  const favicon = asset(db, profile?.favicon_asset_id)
  const ownBrand =
    projectId !== null && logo && !profile?.app_name
      ? db.projects.find((project) => project.id === projectId)?.name
      : undefined
  return {
    app_name: profile?.app_name ?? ownBrand ?? inherited.app_name,
    primary_color: profile?.primary_color ?? inherited.primary_color,
    accent_color: profile?.accent_color ?? inherited.accent_color,
    font: profile?.font ?? inherited.font,
    logo_url: logo ? assetUrl(logo) : (inherited.logo?.url ?? null),
    favicon_url: favicon ? assetUrl(favicon) : (inherited.favicon?.url ?? null),
  }
}

export function brandingSettings(db: MockDb, projectId: string | null): BrandingSettings {
  const profile = profileFor(db, projectId)
  const logo = asset(db, profile?.logo_asset_id)
  const favicon = asset(db, profile?.favicon_asset_id)
  return {
    scope: projectId === null ? 'global' : 'project',
    app_name: profile?.app_name ?? null,
    primary_color: profile?.primary_color ?? null,
    accent_color: profile?.accent_color ?? null,
    font: profile?.font ?? null,
    email_footer: profile?.email_footer ?? null,
    logo: logo ? assetOut(logo) : null,
    favicon: favicon ? assetOut(favicon) : null,
    inherited: inheritedBranding(db, projectId),
    effective: effectiveBranding(db, projectId),
    updated_at: profile?.updated_at ?? null,
    updated_by: userRefById(db, profile?.updated_by_id),
  }
}

/* ------------------------------------------------------------------ */
/* Image checks (contract-phase4 §3.11, roughly)                        */
/* ------------------------------------------------------------------ */

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
const SVG_ELEMENTS = new Set([
  'svg',
  'g',
  'defs',
  'title',
  'desc',
  'path',
  'rect',
  'circle',
  'ellipse',
  'line',
  'polyline',
  'polygon',
  'lineargradient',
  'radialgradient',
  'stop',
  'clippath',
  'mask',
  'text',
  'tspan',
])

export type ImageCheck =
  | {
      ok: true
      content_type: 'image/png' | 'image/svg+xml'
      width: number | null
      height: number | null
    }
  | { ok: false; reason: string }

/** PNG by its signature (size from IHDR), SVG by an allow-list of elements and no href/on*. */
export function checkImage(bytes: Uint8Array, kind: BrandAssetKind): ImageCheck {
  if (PNG_SIGNATURE.every((byte, i) => bytes[i] === byte)) {
    if (bytes.length < 24) return { ok: false, reason: 'The PNG file is damaged.' }
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const width = view.getUint32(16)
    const height = view.getUint32(20)
    const max = kind === 'favicon' ? 512 : 2048
    if (width > max || height > max) {
      return { ok: false, reason: `The image is larger than ${max} × ${max} pixels.` }
    }
    return { ok: true, content_type: 'image/png', width, height }
  }
  const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  if (!/<svg[\s>]/i.test(text)) return { ok: false, reason: 'Upload a PNG or SVG image.' }
  if (/<!DOCTYPE|<!ENTITY|<\?xml-stylesheet/i.test(text)) {
    return { ok: false, reason: 'SVG files can’t have a DOCTYPE, entities or stylesheets.' }
  }
  for (const match of text.matchAll(/<([A-Za-z][\w:-]*)/g)) {
    const name = (match[1] ?? '').toLowerCase()
    if (!SVG_ELEMENTS.has(name))
      return { ok: false, reason: `SVG element <${name}> isn’t allowed.` }
  }
  if (/\s(on\w+|href|xlink:href|style)\s*=/i.test(text)) {
    return {
      ok: false,
      reason: 'SVG attributes such as href, style and event handlers aren’t allowed.',
    }
  }
  const size = (name: string) => {
    const match = new RegExp(`<svg[^>]*\\s${name}="(\\d+(?:\\.\\d+)?)(px)?"`, 'i').exec(text)
    return match ? Math.round(Number(match[1])) : null
  }
  return { ok: true, content_type: 'image/svg+xml', width: size('width'), height: size('height') }
}
