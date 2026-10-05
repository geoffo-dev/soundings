import { describe, expect, it } from 'vitest'

import {
  canonicalScopes,
  expiresAt,
  expiryDateBounds,
  mcpWithoutTools,
  presetOf,
  readIsIncluded,
  toggleScope,
} from './key-rules'
import {
  authorizationHeader,
  claudeCodeCommand,
  curlExample,
  KEY_PLACEHOLDER,
  mcpServersConfig,
  mcpUrl,
} from './snippets'

describe('scopes', () => {
  it('orders canonically and adds read to write and evaluate', () => {
    expect(canonicalScopes(['mcp', 'read'])).toEqual(['read', 'mcp'])
    expect(canonicalScopes(['evaluate'])).toEqual(['read', 'evaluate'])
    expect(canonicalScopes(['mcp', 'write', 'write'])).toEqual(['read', 'write', 'mcp'])
    expect(canonicalScopes(['mcp'])).toEqual(['mcp'])
  })

  it('locks read while write or evaluate is ticked', () => {
    expect(readIsIncluded(['read', 'evaluate'])).toBe(true)
    expect(readIsIncluded(['read', 'mcp'])).toBe(false)
    // Unticking read is refused while it is included…
    expect(toggleScope(['read', 'write'], 'read', false)).toEqual(['read', 'write'])
    // …and ticking write ticks read.
    expect(toggleScope(['mcp'], 'write', true)).toEqual(['read', 'write', 'mcp'])
    // Unticking write leaves read ticked (no surprise removal).
    expect(toggleScope(['read', 'write'], 'write', false)).toEqual(['read'])
    expect(toggleScope(['read', 'mcp'], 'read', false)).toEqual(['mcp'])
  })

  it('names the preset the scopes are, if any', () => {
    expect(presetOf(['read'])).toBe('read')
    expect(presetOf(['mcp', 'read'])).toBe('mcp')
    expect(presetOf(['read', 'evaluate', 'mcp'])).toBe('evaluator')
    expect(presetOf(['read', 'write', 'evaluate', 'mcp'])).toBe('full')
    expect(presetOf(['read', 'write'])).toBeNull()
  })

  it('says when an MCP key has nothing for its tools to use', () => {
    expect(mcpWithoutTools(['mcp'])).toBe(true)
    expect(mcpWithoutTools(['read', 'mcp'])).toBe(false)
    expect(mcpWithoutTools(['read'])).toBe(false)
  })
})

describe('expiry', () => {
  const now = new Date(2026, 9, 2, 10, 30) // 2 Oct 2026, 10:30 local

  it('turns presets into an instant ahead, never into null', () => {
    expect(expiresAt('never', '', now)).toBeNull()
    const days = (iso: string | null | undefined) =>
      Math.round((Date.parse(iso ?? '') - now.getTime()) / 86_400_000)
    expect(days(expiresAt('30d', '', now))).toBe(30)
    expect(days(expiresAt('90d', '', now))).toBe(90)
    expect(days(expiresAt('1y', '', now))).toBe(365)
  })

  it('takes a date from tomorrow to a year ahead, to the end of that day', () => {
    const { min, max } = expiryDateBounds(now)
    expect(min).toBe('2026-10-03')
    expect(max).toBe('2027-10-02')
    expect(expiresAt('date', '2026-10-02', now)).toBeUndefined()
    expect(expiresAt('date', '2027-10-03', now)).toBeUndefined()
    expect(expiresAt('date', '', now)).toBeUndefined()
    const end = new Date(expiresAt('date', '2027-01-15', now) ?? '')
    expect([end.getFullYear(), end.getMonth(), end.getDate(), end.getHours()]).toEqual([
      2027, 0, 15, 23,
    ])
    // Within the API's 366 days even at the latest allowed date.
    const latest = Date.parse(expiresAt('date', max, now) ?? '')
    expect(latest - now.getTime()).toBeLessThan(366 * 86_400_000)
  })
})

describe('examples', () => {
  const key = 'sdg_Ab12Cd34Ef56_' + 'x'.repeat(40)

  it('builds the MCP config, header and Claude Code command', () => {
    const url = mcpUrl('https://ideas.example.com/')
    expect(url).toBe('https://ideas.example.com/mcp')
    expect(authorizationHeader()).toBe(`Authorization: Bearer ${KEY_PLACEHOLDER}`)
    expect(JSON.parse(mcpServersConfig(url, key))).toEqual({
      mcpServers: {
        soundings: {
          type: 'http',
          url: 'https://ideas.example.com/mcp',
          headers: { Authorization: `Bearer ${key}` },
        },
      },
    })
    expect(claudeCodeCommand(url, key)).toContain(
      `claude mcp add --transport http soundings https://ideas.example.com/mcp`,
    )
    expect(claudeCodeCommand(url, key)).toContain(`--header "Authorization: Bearer ${key}"`)
  })

  it('checks a read key on REST and an mcp-only key on the MCP server', () => {
    expect(curlExample('https://x.test', ['read', 'mcp'], key)).toContain(
      'https://x.test/api/v1/projects',
    )
    const mcpOnly = curlExample('https://x.test', ['mcp'], key)
    expect(mcpOnly).toContain('https://x.test/mcp')
    expect(mcpOnly).toContain('"method":"tools/list"')
    expect(mcpOnly).toContain('Accept: application/json')
  })
})
