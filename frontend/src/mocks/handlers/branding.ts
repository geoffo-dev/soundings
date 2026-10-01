/**
 * Branding (contract-phase4 §2 "Branding", §3.10–3.11): the global profile
 * (platform admins), project overrides (project admins), uploaded logos and
 * favicons (raw PNG or SVG bodies) and serving them.
 */
import { HttpResponse } from 'msw'

import type { BrandFont } from '@/api/types'
import { recordAudit } from '@/mocks/access'
import { ID_KIND, newId, type MockDb } from '@/mocks/db'
import { isProjectAdmin } from '@/mocks/domain'
import {
  failValidation,
  forbidden,
  created,
  fail,
  notFound,
  publicRoute,
  readJson,
  route,
  tooManyAttempts,
  type RouteContext,
} from '@/mocks/http'
import {
  APP_NAME_MAX_LENGTH,
  assetOut,
  BRAND_FONTS,
  brandingSettings,
  checkImage,
  effectiveBranding,
  EMAIL_FOOTER_MAX_LENGTH,
  EMAIL_FOOTER_MAX_LINES,
  MAX_UPLOAD_BYTES,
  profileFor,
  UPLOADS_PER_DAY,
  type MockBrandAsset,
  type MockBrandingProfile,
} from '@/mocks/branding'

import { ensureNotArchived, viewProject } from '@/mocks/handlers/common'

const HEX = /^#[0-9a-fA-F]{6}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const FIELDS = [
  'app_name',
  'primary_color',
  'accent_color',
  'font',
  'email_footer',
  'logo_asset_id',
  'favicon_asset_id',
] as const

function invalid(field: string, msg: string): never {
  failValidation([{ loc: ['body', field], msg, type: 'value_error' }])
}

/** `BrandingUpdate`: every field optional, null = inherit; values validated as the API does. */
function parseUpdate(body: Record<string, unknown>) {
  const extra = Object.keys(body).filter((key) => !(FIELDS as readonly string[]).includes(key))
  if (extra.length) invalid(extra[0] ?? 'body', 'Extra inputs are not permitted')
  const text = (field: string): string | null => {
    const value = body[field]
    if (value === undefined || value === null) return null
    if (typeof value !== 'string') invalid(field, 'Input should be a valid string')
    return value.trim()
  }
  const appName = text('app_name')
  if (
    appName !== null &&
    (!appName || appName.length > APP_NAME_MAX_LENGTH || /[\r\n]/.test(appName))
  ) {
    invalid('app_name', `One line of 1–${APP_NAME_MAX_LENGTH} characters`)
  }
  const color = (field: string) => {
    const value = text(field)
    if (value !== null && !HEX.test(value)) invalid(field, 'must be a hex colour such as #1d5fa8')
    return value?.toLowerCase() ?? null
  }
  const font = text('font')
  if (font !== null && !BRAND_FONTS.includes(font as BrandFont)) {
    invalid('font', `Input should be ${BRAND_FONTS.join(', ')}`)
  }
  const footer = text('email_footer')
  if (footer !== null) {
    if (!footer || footer.length > EMAIL_FOOTER_MAX_LENGTH) {
      invalid('email_footer', `1–${EMAIL_FOOTER_MAX_LENGTH} characters`)
    }
    if (footer.split('\n').length > EMAIL_FOOTER_MAX_LINES) {
      invalid('email_footer', `at most ${EMAIL_FOOTER_MAX_LINES} lines`)
    }
    // eslint-disable-next-line no-control-regex
    if (/[\u0000-\u0009\u000b-\u001f\u007f‪-‮⁦-⁩]/.test(footer)) {
      invalid('email_footer', 'Control characters aren’t allowed')
    }
  }
  const assetId = (field: string) => {
    const value = text(field)
    if (value !== null && !UUID.test(value)) invalid(field, 'Input should be a valid UUID')
    return value?.toLowerCase() ?? null
  }
  return {
    app_name: appName,
    primary_color: color('primary_color'),
    accent_color: color('accent_color'),
    font: font as BrandFont | null,
    email_footer: footer,
    logo_asset_id: assetId('logo_asset_id'),
    favicon_asset_id: assetId('favicon_asset_id'),
  }
}

function saveProfile(
  ctx: RouteContext,
  projectId: string | null,
  update: ReturnType<typeof parseUpdate>,
): string[] {
  for (const [field, kind] of [
    ['logo_asset_id', 'logo'],
    ['favicon_asset_id', 'favicon'],
  ] as const) {
    const id = update[field]
    if (!id) continue
    const asset = ctx.db.brandAssets.find((a) => a.id === id)
    if (asset?.kind !== kind || asset.project_id !== projectId) {
      failValidation(
        [
          {
            loc: ['body', field],
            msg: `Upload a ${kind} for this profile first`,
            type: 'value_error',
          },
        ],
        'invalid_asset',
      )
    }
  }
  const empty = Object.values(update).every((value) => value === null)
  const existing = profileFor(ctx.db, projectId)
  const changed = FIELDS.filter((field) => (existing?.[field] ?? null) !== update[field])
  if (projectId !== null && empty) {
    // `{}` removes the project's override.
    ctx.db.brandingProfiles = ctx.db.brandingProfiles.filter((p) => p !== existing)
    return changed
  }
  const profile: MockBrandingProfile = {
    project_id: projectId,
    ...update,
    updated_at: new Date().toISOString(),
    updated_by_id: ctx.user.id,
  }
  if (existing) Object.assign(existing, profile)
  else ctx.db.brandingProfiles.push(profile)
  return changed
}

async function upload(ctx: RouteContext, projectId: string | null) {
  const kind = ctx.url.searchParams.get('kind')
  if (kind !== 'logo' && kind !== 'favicon') {
    failValidation([
      { loc: ['query', 'kind'], msg: 'Input should be logo or favicon', type: 'enum' },
    ])
  }
  const bytes = new Uint8Array(await ctx.request.arrayBuffer())
  if (bytes.byteLength > MAX_UPLOAD_BYTES) {
    fail(413, 'content_too_large', `Images can be at most ${MAX_UPLOAD_BYTES / 1024} KB.`)
  }
  const day = Date.now() - 24 * 3_600_000
  const recent = ctx.db.brandAssets.filter(
    (a) => a.project_id === projectId && Date.parse(a.created_at) > day,
  )
  if (recent.length >= UPLOADS_PER_DAY) {
    tooManyAttempts(3600, 'You’ve uploaded a lot of images today. Try again tomorrow.')
  }
  const check = checkImage(bytes, kind)
  if (!check.ok) {
    failValidation([{ loc: ['body'], msg: check.reason, type: 'value_error' }], 'invalid_image')
  }
  const asset: MockBrandAsset = {
    id: newId(ctx.db, ID_KIND.phase4),
    project_id: projectId,
    kind,
    content_type: check.content_type,
    bytes,
    width: check.width,
    height: check.height,
    created_at: new Date().toISOString(),
  }
  ctx.db.brandAssets.push(asset)
  return created(assetOut(asset))
}

function adminOnly(ctx: RouteContext): void {
  if (!ctx.user.is_platform_admin) forbidden('forbidden', 'Only platform admins can do this.')
}

function editableProject(ctx: RouteContext) {
  const project = viewProject(ctx)
  if (!isProjectAdmin(ctx.db, project, ctx.user)) forbidden()
  return project
}

function serveAsset(db: MockDb, id: string, ifNoneMatch: string | null): Response {
  const asset = db.brandAssets.find((a) => a.id === id.toLowerCase())
  if (!asset) notFound('Image not found.')
  const etag = `"${asset.id}"`
  const headers = {
    'Content-Type': asset.content_type,
    'X-Content-Type-Options': 'nosniff',
    'Content-Disposition': `inline; filename="${asset.kind}.${asset.content_type === 'image/png' ? 'png' : 'svg'}"`,
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    'Cache-Control': 'public, max-age=31536000, immutable',
    ETag: etag,
  }
  if (ifNoneMatch === etag) return new HttpResponse(null, { status: 304, headers })
  return new HttpResponse(asset.bytes.slice().buffer, { status: 200, headers })
}

export const brandingHandlers = [
  publicRoute('get', '/branding', (ctx) => effectiveBranding(ctx.db, null)),

  publicRoute('get', '/branding/assets/:assetId', (ctx) => {
    const id = typeof ctx.params.assetId === 'string' ? ctx.params.assetId : ''
    if (!UUID.test(id)) {
      failValidation([
        { loc: ['path', 'asset_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    return serveAsset(ctx.db, id, ctx.request.headers.get('If-None-Match'))
  }),

  route('get', '/admin/branding', (ctx) => {
    adminOnly(ctx)
    return brandingSettings(ctx.db, null)
  }),

  route('put', '/admin/branding', async (ctx) => {
    const update = parseUpdate(await readJson(ctx.request))
    adminOnly(ctx)
    const fields = saveProfile(ctx, null, update)
    if (fields.length) {
      recordAudit(ctx.db, ctx.user, 'branding.update', null, {
        rule: 'platform.edit_branding',
        fields,
      })
    }
    return brandingSettings(ctx.db, null)
  }),

  route('post', '/admin/branding/assets', async (ctx) => {
    adminOnly(ctx)
    return upload(ctx, null)
  }),

  route('get', '/projects/:slug/branding', (ctx) =>
    brandingSettings(ctx.db, editableProject(ctx).id),
  ),

  route('put', '/projects/:slug/branding', async (ctx) => {
    const update = parseUpdate(await readJson(ctx.request))
    const project = editableProject(ctx)
    ensureNotArchived(project)
    const fields = saveProfile(ctx, project.id, update)
    if (fields.length) {
      recordAudit(
        ctx.db,
        ctx.user,
        'project.update',
        { type: 'project', id: project.id },
        { fields: ['branding'] },
        project.id,
      )
    }
    return brandingSettings(ctx.db, project.id)
  }),

  route('post', '/projects/:slug/branding/assets', async (ctx) => {
    const project = editableProject(ctx)
    ensureNotArchived(project)
    return upload(ctx, project.id)
  }),
]
