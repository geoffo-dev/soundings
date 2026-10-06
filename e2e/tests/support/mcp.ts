import { expect, request, type APIRequestContext, type APIResponse } from '@playwright/test'

/**
 * A key's view of the app, the way an MCP client or a script sees it (contract-phase5
 * §3.2, §3.5, §4): `Authorization: Bearer <key>` and nothing else (no cookies, no CSRF
 * header). `/mcp` is JSON-RPC over streamable HTTP, stateless and JSON-only, so each call
 * is one POST; `initialize` is optional per request but `KeyClient.connect()` does it,
 * like a real client, and checks the server says who it is.
 *
 * Every client claims its own address with `X-Forwarded-For` (the local stack trusts
 * loopback as its proxy, `e2e/scripts/stack-env.sh`): refused keys count towards a
 * per-address limit of 30 a minute (§3.2) and the whole run shares 127.0.0.1. Against
 * `E2E_BASE_URL` the header is ignored, which is harmless.
 */

export const PROTOCOL_VERSION = '2025-11-25'
export const TOOL_NAMES = [
  'add_comment',
  'create_idea',
  'get_idea',
  'get_proposal',
  'get_rubric',
  'list_projects',
  'propose_proposal_section',
  'search_ideas',
  'submit_evaluation',
]

/** A random IPv6 address in its own /64 (the throttle's unit for IPv6). */
export function randomAddress(): string {
  const group = () => Math.floor(Math.random() * 0x10000).toString(16)
  return `2001:db8:${group()}:${group()}::${group()}`
}

export interface ToolResult {
  /** The HTTP status of the POST (200 for tool results, errors included). */
  status: number
  isError: boolean
  /** `structuredContent`: the tool's output, or `{code, message}` for a tool error. */
  data: Record<string, unknown> & { code?: string; message?: string }
  /** The response body as received (for leak checks). */
  text: string
}

export class KeyClient {
  private constructor(
    readonly baseURL: string,
    readonly context: APIRequestContext,
    readonly secret: string,
  ) {}

  /** A client with `secret` as its key (`null`: no Authorization header at all). */
  static async open(
    baseURL: string,
    secret: string | null,
    headers: Record<string, string> = {},
  ): Promise<KeyClient> {
    const extraHTTPHeaders: Record<string, string> = {
      'X-Forwarded-For': randomAddress(),
      ...headers,
    }
    if (secret !== null) extraHTTPHeaders.Authorization = `Bearer ${secret}`
    const context = await request.newContext({ baseURL, extraHTTPHeaders })
    return new KeyClient(baseURL, context, secret ?? '')
  }

  dispose() {
    return this.context.dispose()
  }

  // --- REST -------------------------------------------------------------------------------
  rest(method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, data?: unknown) {
    return this.context.fetch(`/api/v1${path}`, { method, data })
  }

  async restJson<T>(path: string): Promise<T> {
    const response = await this.rest('GET', path)
    const body = await response.text()
    expect(response.status(), `${path}: ${body}`).toBe(200)
    return JSON.parse(body) as T
  }

  // --- MCP --------------------------------------------------------------------------------
  /** One JSON-RPC message to `/mcp` (with the headers a streamable HTTP client sends). */
  post(message: unknown, headers: Record<string, string> = {}): Promise<APIResponse> {
    return this.context.post('/mcp', {
      data: JSON.stringify(message),
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        'MCP-Protocol-Version': PROTOCOL_VERSION,
        ...headers,
      },
    })
  }

  rpc(method: string, params?: unknown, headers: Record<string, string> = {}) {
    return this.post({ jsonrpc: '2.0', id: 1, method, ...(params ? { params } : {}) }, headers)
  }

  /** `initialize` + `notifications/initialized`; returns the server's `InitializeResult`. */
  async connect(): Promise<{
    serverInfo: { name: string; version: string }
    instructions: string
    protocolVersion: string
  }> {
    const response = await this.rpc('initialize', {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: 'soundings-e2e', version: '1' },
    })
    const body = await response.text()
    expect(response.status(), body).toBe(200)
    expect(response.headers()['mcp-session-id'], 'stateless: no session id').toBeUndefined()
    const notified = await this.post({ jsonrpc: '2.0', method: 'notifications/initialized' })
    expect(notified.status()).toBe(202)
    return (JSON.parse(body) as { result: never }).result
  }

  async toolNames(): Promise<string[]> {
    const response = await this.rpc('tools/list')
    const body = (await response.json()) as { result: { tools: { name: string }[] } }
    return body.result.tools.map((tool) => tool.name).sort()
  }

  /** `tools/call`; the HTTP status and, when there is one, the tool result. */
  async call(tool: string, args: Record<string, unknown> = {}): Promise<ToolResult> {
    const response = await this.rpc('tools/call', { name: tool, arguments: args })
    const text = await response.text()
    if (response.status() !== 200)
      return { status: response.status(), isError: true, data: {}, text }
    const body = JSON.parse(text) as {
      result?: { isError?: boolean; structuredContent?: ToolResult['data'] }
      error?: { code: number; message: string }
    }
    if (!body.result) {
      return { status: 200, isError: true, data: { code: 'jsonrpc', message: text }, text }
    }
    return {
      status: 200,
      isError: body.result.isError ?? false,
      data: body.result.structuredContent ?? {},
      text,
    }
  }

  /** A successful tool call's structured content (fails the test otherwise). */
  async ok<T = Record<string, unknown>>(tool: string, args: Record<string, unknown> = {}) {
    const result = await this.call(tool, args)
    expect(result.isError, `${tool}: ${result.text}`).toBe(false)
    return result.data as T
  }

  /** The error code of a tool call that must fail as a tool error. */
  async fails(tool: string, args: Record<string, unknown> = {}): Promise<string> {
    const result = await this.call(tool, args)
    expect(result.status, `${tool}: ${result.text}`).toBe(200)
    expect(result.isError, `${tool}: ${result.text}`).toBe(true)
    return result.data.code ?? ''
  }
}

/** The one 401 every refused key gets (§3.2), on REST or `/mcp`. */
export async function expectRefusedKey(response: APIResponse) {
  expect(response.status()).toBe(401)
  expect(response.headers()['www-authenticate']).toBe('Bearer realm="soundings"')
  expect(response.headers()['content-type']).toMatch(/^application\/problem\+json/)
  expect(((await response.json()) as { code: string }).code).toBe('unauthorized')
}
