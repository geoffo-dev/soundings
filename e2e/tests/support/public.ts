import { pbkdf2 } from 'node:crypto'
import { promisify } from 'node:util'
import { crc32, deflateSync } from 'node:zlib'

import {
  expect,
  request,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from '@playwright/test'

import {
  createTeamProject,
  type AltchaChallenge,
  type Api,
  type BrandingUpdate,
  type EmailVerified,
  type Person,
  type Project,
  type ProjectRole,
  type PublicFormSettingsUpdate,
  type PublicProject,
  type PublicSubmissionCreate,
  type PublicSubmissionReceipt,
  type TrackedSubmission,
} from './api'

/**
 * Helpers for the Phase 4 public-form specs (docs/test-plans/phase-4.md).
 *
 * `Visitor` is someone without an account: an API client with no session, no CSRF
 * token and its own cookie jar, posting JSON as the public pages do. `solveAltcha` does
 * the proof of work exactly as the widget does (PBKDF2/SHA-256 over the nonce and a
 * big-endian counter until the derived key starts with the prefix), so API-level
 * submissions pass the same server checks as the browser's. The browser specs solve
 * through the SPA's own worker instead.
 *
 * Every request comes from 127.0.0.1, so the per-address limits are shared by the whole
 * run: the stack allows E2E_PUBLIC_PER_IP submissions an hour (1000), and challenges
 * are throttled at 30 a minute per address (constant). Specs that exhaust a throttle
 * on purpose are tagged @serial and wait it out.
 */

const pbkdf2Async = promisify(pbkdf2)

/** The widget's payload for `challenge` (base64 JSON of the challenge and solution). */
export async function solveAltcha(challenge: AltchaChallenge): Promise<string> {
  const parameters = challenge.parameters
  const digest = parameters.algorithm
    .replace(/^PBKDF2\//, '')
    .replace('-', '')
    .toLowerCase()
  const nonce = Buffer.from(parameters.nonce, 'hex')
  const salt = Buffer.from(parameters.salt, 'hex')
  const batch = 8
  for (let start = 0; start < 5_000_000; start += batch) {
    const keys = await Promise.all(
      Array.from({ length: batch }, (_, offset) => {
        const counter = Buffer.alloc(4)
        counter.writeUInt32BE(start + offset)
        return pbkdf2Async(
          Buffer.concat([nonce, counter]),
          salt,
          parameters.cost,
          parameters.keyLength,
          digest,
        )
      }),
    )
    const found = keys.findIndex((key) => key.toString('hex').startsWith(parameters.keyPrefix))
    if (found >= 0) {
      const solution = { counter: start + found, derivedKey: keys[found]!.toString('hex') }
      return Buffer.from(JSON.stringify({ challenge, solution })).toString('base64')
    }
  }
  throw new Error('ALTCHA: no solution found')
}

const PUBLIC = '/api/v1/public'

async function json<T>(response: APIResponse, status = 200): Promise<T> {
  const body = await response.text()
  expect(response.status(), `${response.url()}: ${body}`).toBe(status)
  return (body ? JSON.parse(body) : null) as T
}

/** Someone without an account, using the public API as the public pages do. */
export class Visitor {
  private constructor(readonly context: APIRequestContext) {}

  /** `address`: the client address to claim (X-Forwarded-For; the stack trusts loopback). */
  static async open(baseURL: string, address?: string): Promise<Visitor> {
    const extraHTTPHeaders = address ? { 'X-Forwarded-For': address } : undefined
    return new Visitor(await request.newContext({ baseURL, extraHTTPHeaders }))
  }

  dispose() {
    return this.context.dispose()
  }

  project(slug: string) {
    return this.context.get(`${PUBLIC}/projects/${slug}`)
  }

  async publicProject(slug: string): Promise<PublicProject> {
    return json<PublicProject>(await this.project(slug))
  }

  challenge(slug: string) {
    return this.context.get(`${PUBLIC}/projects/${slug}/altcha`)
  }

  /** A solved payload for the form of `slug` (one challenge fetch). */
  async solve(slug: string): Promise<string> {
    return solveAltcha(await json<AltchaChallenge>(await this.challenge(slug)))
  }

  /** Posts a submission; solves a fresh challenge unless `altcha` is given. */
  async submit(
    slug: string,
    fields: Partial<PublicSubmissionCreate> & { title: string; summary: string },
  ): Promise<APIResponse> {
    const body = { ...fields, altcha: fields.altcha ?? (await this.solve(slug)) }
    return this.context.post(`${PUBLIC}/projects/${slug}/submissions`, { data: body })
  }

  async submitted(
    slug: string,
    fields: Partial<PublicSubmissionCreate> & { title: string; summary: string },
  ): Promise<PublicSubmissionReceipt> {
    return json<PublicSubmissionReceipt>(await this.submit(slug, fields), 201)
  }

  track(token: string) {
    return this.context.post(`${PUBLIC}/track`, { data: { token } })
  }

  async tracked(token: string): Promise<TrackedSubmission> {
    return json<TrackedSubmission>(await this.track(token))
  }

  async verify(token: string): Promise<EmailVerified> {
    return json<EmailVerified>(
      await this.context.post(`${PUBLIC}/verify-email`, { data: { token } }),
    )
  }

  erase(token: string) {
    return this.context.post(`${PUBLIC}/track/erase`, { data: { token } })
  }
}

/**
 * A fresh private project (Alice is its admin) with `members`, its public form on
 * (moderated unless said otherwise) and, optionally, a branding override.
 */
export async function projectWithPublicForm(
  admin: Api,
  name: string,
  members: Partial<Record<Person, ProjectRole>>,
  options: { form?: PublicFormSettingsUpdate; branding?: Partial<BrandingUpdate> } = {},
): Promise<Project> {
  const project = await createTeamProject(admin, name, members)
  await admin.updatePublicForm(project.slug, {
    enabled: true,
    moderation_required: true,
    intro_md: 'Tell us how to make shopping with us better. We read every idea.',
    ...options.form,
  })
  if (options.branding)
    await admin.setProjectBranding(project.slug, brandingUpdate(options.branding))
  return project
}

/** A complete `BrandingUpdate` (the PUT replaces the whole profile): unset fields null. */
export function brandingUpdate(fields: Partial<BrandingUpdate>): BrandingUpdate {
  return {
    app_name: null,
    primary_color: null,
    accent_color: null,
    font: null,
    email_footer: null,
    logo_asset_id: null,
    favicon_asset_id: null,
    ...fields,
  }
}

/** A solid-colour PNG (`width` x `height`), made here so no image file is needed. */
export function solidPng(width: number, height: number, [r, g, b]: [number, number, number]) {
  const chunk = (type: string, data: Buffer) => {
    const length = Buffer.alloc(4)
    length.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(crc32(body))
    return Buffer.concat([length, body, crc])
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header.set([8, 2, 0, 0, 0], 8) // 8-bit RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array(width).fill([r, g, b]).flat())])
  const pixels = deflateSync(Buffer.concat(Array(height).fill(row)))
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', pixels),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

/** A clean SVG wordmark (passes the upload allow-list: shapes, a gradient, text). */
export function svgLogo(label: string, colour: string): Buffer {
  return Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40" viewBox="0 0 200 40">` +
      `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
      `<stop offset="0" stop-color="${colour}"/><stop offset="1" stop-color="#111827"/>` +
      `</linearGradient></defs>` +
      `<rect width="40" height="40" rx="8" fill="url(#g)"/>` +
      `<text x="50" y="26" font-family="Arial" font-size="16" fill="#111827">${label}</text></svg>`,
  )
}

/** A CSS custom property as computed on <html>. */
export function rootVar(page: Page, name: string): Promise<string> {
  return page.evaluate(
    (property) => getComputedStyle(document.documentElement).getPropertyValue(property).trim(),
    name,
  )
}

/** The phone context the public form must be great on (SPEC: "great on phones"). */
export const PHONE = {
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 3,
} as const

/** The token after `#` in a `/track#…` or `/verify#…` link. */
export function fragmentToken(url: string): string {
  const token = new URL(url).hash.slice(1)
  if (!token) throw new Error(`no token in ${url}`)
  return token
}

/** Fills the public form on `page` (already at /{slug}/submit) as a visitor would type. */
export async function fillPublicForm(
  page: Page,
  fields: {
    title: string
    summary: string
    description?: string
    name?: string
    email?: string
    updates?: boolean
  },
) {
  const form = page.getByRole('form', { name: 'Your idea' })
  await form.getByRole('textbox', { name: 'Title' }).fill(fields.title)
  await form.getByRole('textbox', { name: 'Summary' }).fill(fields.summary)
  if (fields.description) {
    await form.getByRole('textbox', { name: 'Description (optional)' }).fill(fields.description)
  }
  if (fields.name)
    await form.getByRole('textbox', { name: 'Your name (optional)' }).fill(fields.name)
  if (fields.email) await form.getByRole('textbox', { name: /^Your email/ }).fill(fields.email)
  if (fields.updates) {
    await form.getByRole('checkbox', { name: 'Email me when the status changes' }).check()
  }
}

/** Waits for the SPA's proof of work to finish ("Verified you're human"). */
export async function humanCheckDone(page: Page) {
  await expect(page.getByText('Verified you’re human')).toBeVisible({ timeout: 30_000 })
}
