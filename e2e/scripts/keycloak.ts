/**
 * Keycloak admin REST API helper for the SSO end-to-end tests and the stack scripts.
 *
 * In a spec:
 *
 *   import { KeycloakAdmin } from '../scripts/keycloak.ts'
 *   const kc = await KeycloakAdmin.connect()          // E2E_KC_URL, admin/admin
 *   await kc.removeFromGroup('carol', '/tools/members')
 *   ...
 *   await kc.addToGroup('carol', '/tools/members')    // always restore what you change
 *
 * From a shell (Node 22.18+ runs TypeScript as is; 22.12-22.17 need
 * --experimental-strip-types):
 *
 *   node e2e/scripts/keycloak.ts group-remove carol /tools/members
 *   node e2e/scripts/keycloak.ts reset-realm http://localhost:8100   # fresh dev realm
 *
 * The realm is the dev realm (dev/keycloak/realm-soundings.json; users and groups in
 * dev/README.md). Users have fixed ids, so their `sub` stays the same across resets.
 */
import { readFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'

export const REALM = 'soundings'
export const CLIENT_ID = 'soundings'
export const PASSWORD = 'password' // every dev realm user
export const REALM_FILE = new URL('../../dev/keycloak/realm-soundings.json', import.meta.url)

/** Keycloak's base URL: E2E_KC_URL, else http://localhost:$E2E_KC_PORT (8180). */
export function keycloakUrl(): string {
  const url = process.env.E2E_KC_URL ?? `http://localhost:${process.env.E2E_KC_PORT ?? 8180}`
  return url.replace(/\/$/, '')
}

/** The issuer the app is configured with: `<Keycloak>/realms/soundings`. */
export function issuer(baseUrl = keycloakUrl()): string {
  return `${baseUrl}/realms/${REALM}`
}

interface Named {
  id: string
}
type Json = Record<string, unknown>

export class KeycloakAdmin {
  readonly baseUrl: string
  readonly realm: string
  #token: string

  constructor(baseUrl: string, token: string, realm = REALM) {
    this.baseUrl = baseUrl
    this.realm = realm
    this.#token = token
  }

  /** Signs in to the master realm as the bootstrap admin (admin/admin in dev). */
  static async connect(
    baseUrl = keycloakUrl(),
    username = process.env.E2E_KC_ADMIN_USER ?? 'admin',
    password = process.env.E2E_KC_ADMIN_PASSWORD ?? 'admin',
  ): Promise<KeycloakAdmin> {
    let response: Response
    try {
      response = await fetch(`${baseUrl}/realms/master/protocol/openid-connect/token`, {
        method: 'POST',
        body: new URLSearchParams({
          grant_type: 'password',
          client_id: 'admin-cli',
          username,
          password,
        }),
      })
    } catch {
      throw new Error(`Keycloak is unreachable at ${baseUrl} (set E2E_KC_URL)`)
    }
    if (!response.ok) throw new Error(`Keycloak admin sign-in failed: ${response.status}`)
    const { access_token } = (await response.json()) as { access_token: string }
    return new KeycloakAdmin(baseUrl, access_token)
  }

  /** An admin API call for the realm: `path` is relative to /admin/realms/<realm>. */
  api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
    return this.request<T>(method, `/${this.realm}${path}`, body)
  }

  /** Any admin API call: `path` is relative to /admin/realms (e.g. '' to create a realm). */
  async request<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}/admin/realms${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.#token}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!response.ok) {
      throw new Error(`Keycloak ${method} ${path}: ${response.status} ${await response.text()}`)
    }
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  async userId(username: string): Promise<string> {
    const users = await this.api<Named[]>(
      'GET',
      `/users?exact=true&username=${encodeURIComponent(username)}`,
    )
    const user = users[0]
    if (!user) throw new Error(`no Keycloak user ${username}`)
    return user.id
  }

  async groupId(path: string): Promise<string> {
    return (await this.api<Named>('GET', `/group-by-path${encodeURI(path)}`)).id
  }

  /** Full paths of the user's groups, e.g. ['/innovation/members', '/tools/members']. */
  async groupsOf(username: string): Promise<string[]> {
    const groups = await this.api<{ path: string }[]>(
      'GET',
      `/users/${await this.userId(username)}/groups`,
    )
    return groups.map((group) => group.path).sort()
  }

  async addToGroup(username: string, groupPath: string): Promise<void> {
    const [user, group] = await Promise.all([this.userId(username), this.groupId(groupPath)])
    await this.api('PUT', `/users/${user}/groups/${group}`)
  }

  async removeFromGroup(username: string, groupPath: string): Promise<void> {
    const [user, group] = await Promise.all([this.userId(username), this.groupId(groupPath)])
    await this.api('DELETE', `/users/${user}/groups/${group}`)
  }

  /** Sets (or with `null` removes) a user attribute such as employee_no. */
  async setAttribute(username: string, name: string, value: string | null): Promise<void> {
    const id = await this.userId(username)
    const user = await this.api<Json & { attributes?: Record<string, string[]> }>(
      'GET',
      `/users/${id}`,
    )
    const attributes = { ...user.attributes }
    if (value === null) delete attributes[name]
    else attributes[name] = [value]
    await this.api('PUT', `/users/${id}`, { ...user, attributes })
  }

  async setEmailVerified(username: string, verified: boolean): Promise<void> {
    const id = await this.userId(username)
    const user = await this.api<Json>('GET', `/users/${id}`)
    await this.api('PUT', `/users/${id}`, { ...user, emailVerified: verified })
  }

  /** Ends the user's Keycloak sessions: the next sign-in asks for the password again. */
  async logout(username: string): Promise<void> {
    await this.api('POST', `/users/${await this.userId(username)}/logout`)
  }

  /** Allows `<origin>/*` as redirect and post-logout redirect URI (idempotent). */
  async addRedirectOrigin(...origins: string[]): Promise<void> {
    const [client] = await this.api<Named[]>('GET', `/clients?clientId=${CLIENT_ID}`)
    if (!client) throw new Error(`no Keycloak client ${CLIENT_ID}`)
    const rep = await this.api<Json & { redirectUris?: string[]; attributes?: Json }>(
      'GET',
      `/clients/${client.id}`,
    )
    const uris = origins.map((origin) => `${origin.replace(/\/$/, '')}/*`)
    const redirects = [...new Set([...(rep.redirectUris ?? []), ...uris])]
    const attributes = rep.attributes ?? {}
    const logout = String(attributes['post.logout.redirect.uris'] ?? '')
      .split('##')
      .filter(Boolean)
    const logouts = [...new Set([...logout, ...uris])]
    await this.api('PUT', `/clients/${client.id}`, {
      ...rep,
      redirectUris: redirects,
      attributes: { ...attributes, 'post.logout.redirect.uris': logouts.join('##') },
    })
  }

  /**
   * Replaces the realm with a fresh copy of the dev realm file (users, groups and
   * attributes as committed; Keycloak sessions gone), plus `origins` as redirect URIs.
   * The signing keys change: the app re-fetches them (unknown `kid`).
   */
  async resetRealm(...origins: string[]): Promise<void> {
    const realm = JSON.parse(await readFile(REALM_FILE, 'utf8')) as Json
    const exists = await fetch(`${this.baseUrl}/realms/${this.realm}`)
    if (exists.ok) await this.request('DELETE', `/${this.realm}`)
    await this.request('POST', '', realm)
    if (origins.length) await this.addRedirectOrigin(...origins)
  }
}

/** Waits until the realm's discovery document answers (Keycloak started and imported). */
export async function waitForKeycloak(
  baseUrl = keycloakUrl(),
  seconds = 180,
  realm = REALM,
): Promise<void> {
  const deadline = Date.now() + seconds * 1000
  for (;;) {
    try {
      const discovery = `${baseUrl}/realms/${realm}/.well-known/openid-configuration`
      if ((await fetch(discovery)).ok) return
    } catch {
      // not listening yet
    }
    if (Date.now() > deadline) throw new Error(`Keycloak at ${baseUrl} is not ready`)
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
}

const USAGE = `usage: node e2e/scripts/keycloak.ts <command> [args]   (Keycloak: E2E_KC_URL)
  wait [seconds] [realm]             until the realm answers (180 s, soundings)
  add-redirect-origin <origin>...    allow <origin>/* as (post-logout) redirect URI
  reset-realm [<origin>...]          fresh dev realm, plus those redirect origins
  group-add <username> <group-path>  e.g. group-add carol /tools/members
  group-remove <username> <group-path>
  groups <username>                  print the user's group paths
  set-attribute <username> <name> [<value>]   no value: remove it
  logout <username>                  end the user's Keycloak sessions`

async function main(argv: string[]): Promise<void> {
  const [command, ...args] = argv
  if (command === 'wait') return waitForKeycloak(keycloakUrl(), Number(args[0] ?? 180), args[1])
  const need = (count: number) => {
    if (args.length < count) throw new Error(USAGE)
  }
  const commands = USAGE.split('\n').map((line) => line.trim().split(' ')[0])
  if (!command || !commands.slice(1).includes(command)) throw new Error(USAGE)
  const kc = await KeycloakAdmin.connect()
  switch (command) {
    case 'add-redirect-origin':
      need(1)
      return kc.addRedirectOrigin(...args)
    case 'reset-realm':
      return kc.resetRealm(...args)
    case 'group-add':
      need(2)
      return kc.addToGroup(args[0]!, args[1]!)
    case 'group-remove':
      need(2)
      return kc.removeFromGroup(args[0]!, args[1]!)
    case 'groups':
      need(1)
      console.log((await kc.groupsOf(args[0]!)).join('\n'))
      return
    case 'set-attribute':
      need(2)
      return kc.setAttribute(args[0]!, args[1]!, args[2] ?? null)
    case 'logout':
      need(1)
      return kc.logout(args[0]!)
    default:
      throw new Error(USAGE)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  })
}
