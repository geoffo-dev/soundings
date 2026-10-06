/**
 * Phase 5 API keys in the mock API (contract-phase5 §3.1–3.3): records mirror
 * the `api_keys` table (only a stand-in for the hash is kept: the mock never
 * needs the secret again), and the functions here turn them into the shapes of
 * Settings → API keys and Admin settings → API keys. The backend is the
 * authority; this follows its rules closely enough to build and test screens.
 */
import type { AdminApiKey, ApiKey, ApiKeyScope, ApiKeyState, ProjectRef } from '@/api/types'

import { recordAudit } from './access'
import type { MockDb, MockUser } from './db'
import { canViewProject, findUser, projectRef, userRef, userRefById } from './domain'
import type { MockAuthMethod } from './session'

export interface MockApiKey {
  id: string
  user_id: string
  name: string
  /** The 12-character public lookup id (`prefix` = `sdg_` + this). */
  lookup_id: string
  /** Canonical order, `read` included with `write` / `evaluate`. */
  scopes: ApiKeyScope[]
  /** null = every project the owner can access. */
  project_ids: string[] | null
  expires_at: string | null
  created_at: string
  created_by_id: string | null
  created_auth_method: MockAuthMethod
  last_used_at: string | null
  revoked_at: string | null
  revoked_by_id: string | null
}

export const API_KEY_PREFIX = 'sdg_'
export const API_KEY_LOOKUP_LENGTH = 12
export const API_KEY_SECRET_LENGTH = 40
/** The whole key (`API_KEY_PATTERN`). */
export const API_KEY_PATTERN = /^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/
export const MAX_API_KEYS_PER_USER = 25
export const MAX_KEY_PROJECTS = 50
export const API_KEY_NAME_MAX_LENGTH = 80
export const API_KEY_MIN_LIFETIME_MS = 3_600_000
export const API_KEY_MAX_LIFETIME_MS = 366 * 24 * 3_600_000
/** A person's key pauses after 30 days without a session (`API_KEY_OWNER_IDLE_LIMIT`). */
export const API_KEY_OWNER_IDLE_LIMIT_MS = 30 * 24 * 3_600_000
export const API_KEY_SCOPES: readonly ApiKeyScope[] = ['read', 'write', 'evaluate', 'mcp']

/** Distinct scopes in canonical order; `write` and `evaluate` include `read`. */
export function canonicalScopes(scopes: readonly ApiKeyScope[]): ApiKeyScope[] {
  const wanted = new Set(scopes)
  if (wanted.has('write') || wanted.has('evaluate')) wanted.add('read')
  return API_KEY_SCOPES.filter((scope) => wanted.has(scope))
}

export function keyPrefix(key: Pick<MockApiKey, 'lookup_id'>): string {
  return `${API_KEY_PREFIX}${key.lookup_id}`
}

const BASE62 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'

/** `length` base62 characters from the CSPRNG (as the API's `secrets`). */
export function randomBase62(length: number): string {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => BASE62[byte % 62] ?? 'A').join('')
}

/** A key's state now (revoked keys are never listed, so never asked about). */
export function keyState(db: MockDb, key: MockApiKey, now = Date.now()): ApiKeyState {
  if (key.expires_at && Date.parse(key.expires_at) <= now) return 'expired'
  const owner = findUser(db, key.user_id)
  if (owner && !owner.is_service_account) {
    const seen = owner.last_seen_at ? Date.parse(owner.last_seen_at) : null
    if (seen === null || now - seen > API_KEY_OWNER_IDLE_LIMIT_MS) return 'dormant'
  }
  return 'active'
}

/** Restricted projects that still exist, by name, and whether the owner can view each. */
function keyProjects(
  db: MockDb,
  key: MockApiKey,
  owner: MockUser | undefined,
): { project: ProjectRef; ownerCanView: boolean }[] {
  if (key.project_ids === null) return []
  return db.projects
    .filter((project) => key.project_ids?.includes(project.id))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((project) => ({
      project: projectRef(project),
      ownerCanView: owner ? canViewProject(db, project, owner) : false,
    }))
}

export function apiKeyOut(db: MockDb, key: MockApiKey): ApiKey {
  const owner = findUser(db, key.user_id)
  const projects = keyProjects(db, key, owner)
  return {
    id: key.id,
    name: key.name,
    prefix: keyPrefix(key),
    scopes: key.scopes,
    restricted: key.project_ids !== null,
    projects: projects.filter((p) => p.ownerCanView).map((p) => p.project),
    unavailable_project_count: projects.filter((p) => !p.ownerCanView).length,
    expires_at: key.expires_at,
    state: keyState(db, key),
    created_at: key.created_at,
    last_used_at: key.last_used_at,
  }
}

export function adminApiKeyOut(db: MockDb, key: MockApiKey): AdminApiKey {
  const owner = findUser(db, key.user_id)
  return {
    ...apiKeyOut(db, key),
    projects: keyProjects(db, key, owner).map((p) => ({
      ...p.project,
      owner_can_view: p.ownerCanView,
    })),
    owner: owner
      ? userRef(owner)
      : { id: key.user_id, display_name: 'A deleted user', avatar_url: null, initials: '?' },
    owner_email: owner?.email ?? '',
    owner_is_service_account: owner?.is_service_account ?? false,
    created_by: userRefById(db, key.created_by_id),
  }
}

/** Keys that aren't revoked, newest first. */
export function liveKeys(db: MockDb, userId?: string): MockApiKey[] {
  return db.apiKeys
    .filter((key) => key.revoked_at === null && (!userId || key.user_id === userId))
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
}

/** Revokes one key (idempotent) and audits it; `rule` says who could. */
export function revokeKey(
  db: MockDb,
  key: MockApiKey,
  actor: MockUser,
  rule: 'api_key.manage_own' | 'api_key.manage_any' | 'platform.manage_users',
  reason?: 'deactivated',
): void {
  if (key.revoked_at !== null) return
  key.revoked_at = new Date().toISOString()
  key.revoked_by_id = actor.id
  recordAudit(
    db,
    actor,
    'api_key.revoke',
    { type: 'user', id: key.user_id },
    { rule, key_id: key.id, prefix: keyPrefix(key), ...(reason ? { reason } : {}) },
  )
}

/** Deactivating someone revokes every key they hold (contract-phase5 §2). */
export function revokeAllKeys(db: MockDb, actor: MockUser, owner: MockUser): void {
  for (const key of liveKeys(db, owner.id)) {
    revokeKey(db, key, actor, 'platform.manage_users', 'deactivated')
  }
}
