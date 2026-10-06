import type { ApiKeyScope } from '@/api/types'

/**
 * Ready-to-paste examples for a key (contract-phase5 §3.10 "Connect an MCP
 * client"): the server URL, the header, an `mcpServers` config, the Claude Code
 * command, Claude Desktop through `mcp-remote` and curl (docs/mcp.md has them all). With the new key's secret in the secret dialog, or a
 * placeholder on the page (the key is never shown again).
 */

export const KEY_PLACEHOLDER = '<your key>'

/** `<origin>/mcp`: the page's own origin (the API serves the SPA). */
export function mcpUrl(origin: string = window.location.origin): string {
  return `${origin.replace(/\/+$/, '')}/mcp`
}

export function authorizationHeader(key: string = KEY_PLACEHOLDER): string {
  return `Authorization: Bearer ${key}`
}

/**
 * A JSON `mcpServers` map for clients that take `type: "http"`, `url` and
 * `headers` (a project's `.mcp.json` for Claude Code, many editor assistants).
 */
export function mcpServersConfig(url: string, key: string = KEY_PLACEHOLDER): string {
  return JSON.stringify(
    {
      mcpServers: {
        soundings: { type: 'http', url, headers: { Authorization: `Bearer ${key}` } },
      },
    },
    null,
    2,
  )
}

/** Where the Claude Desktop example keeps the header line (the person picks the path). */
export const HEADER_FILE_PLACEHOLDER = '/Users/you/.config/soundings/mcp-headers.txt'

/** The `mcp-remote` release the Claude Desktop example pins (checked against `/mcp`). */
export const MCP_REMOTE = 'mcp-remote@0.14.3'

/**
 * Claude Desktop's `claude_desktop_config.json`. Its custom connectors only sign
 * in with OAuth, which Soundings doesn't offer (keys are made in the app), so it
 * runs the `mcp-remote` stdio bridge, which reads the header from a file (the key
 * stays out of the config and of process lists). `mcp-remote` takes plain http
 * only for localhost; any other server is https.
 */
export function claudeDesktopConfig(url: string, headerFile = HEADER_FILE_PLACEHOLDER): string {
  return JSON.stringify(
    {
      mcpServers: {
        soundings: { command: 'npx', args: ['-y', MCP_REMOTE, url, '--header-file', headerFile] },
      },
    },
    null,
    2,
  )
}

/** Claude Code's `claude mcp add` for a remote HTTP server with a header. */
export function claudeCodeCommand(url: string, key: string = KEY_PLACEHOLDER): string {
  return `claude mcp add --transport http soundings ${url} \\\n  --header "Authorization: Bearer ${key}"`
}

/**
 * A first request with the key: the REST API when it can read, else the MCP
 * server's tool list (an `mcp`-only key reads nothing through REST).
 */
export function curlExample(
  origin: string,
  scopes: readonly ApiKeyScope[],
  key: string = KEY_PLACEHOLDER,
): string {
  const base = origin.replace(/\/+$/, '')
  if (scopes.includes('read')) {
    return `curl ${base}/api/v1/projects \\\n  -H "Authorization: Bearer ${key}"`
  }
  return [
    `curl ${base}/mcp \\`,
    `  -H "Authorization: Bearer ${key}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -H "Accept: application/json, text/event-stream" \\`,
    `  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`,
  ].join('\n')
}
