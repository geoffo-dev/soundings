import { describe, expect, it } from 'vitest'

import {
  abilitiesPhrase,
  accessLabel,
  accessSummary,
  canonicalScopes,
  expiresAt,
  expiresSoon,
  expiryDateBounds,
  mcpWithoutTools,
  presetOf,
  readIsIncluded,
  toggleScope,
} from './key-rules'
import {
  authorizationHeader,
  claudeCodeCommand,
  claudeDesktopConfig,
  curlExample,
  HEADER_FILE_PLACEHOLDER,
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

  it('connects Claude Desktop through mcp-remote with the header in a file, never the key', () => {
    const url = mcpUrl('https://ideas.example.com')
    const config = claudeDesktopConfig(url)
    expect(JSON.parse(config)).toEqual({
      mcpServers: {
        soundings: {
          command: 'npx',
          args: ['-y', 'mcp-remote@0.14.3', url, '--header-file', HEADER_FILE_PLACEHOLDER],
        },
      },
    })
    expect(config).not.toContain('Bearer')
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

describe('what a key can do, in plain words', () => {
  it('names the scopes as abilities, stronger for keys that change things', () => {
    expect(accessLabel(['read'])).toEqual({ label: 'Read only', assistants: false, changes: false })
    expect(accessLabel(['read', 'evaluate', 'mcp'])).toEqual({
      label: 'Read and evaluate',
      assistants: true,
      changes: true,
    })
    expect(accessLabel(['read', 'write', 'evaluate', 'mcp']).label).toBe(
      'Read, change and evaluate',
    )
    expect(accessLabel(['mcp']).label).toBe('Nothing yet')
  })

  it('says it as a sentence: what, where and until when', () => {
    expect(abilitiesPhrase(['read', 'write', 'evaluate', 'mcp'])).toBe(
      'read everything you can see, change ideas, comments and proposals, and submit your evaluations, also through AI assistants',
    )
    expect(abilitiesPhrase(['mcp'])).toBe('connect an AI assistant, but do nothing else')
    expect(
      accessSummary({
        scopes: ['read', 'evaluate'],
        restricted: true,
        projects: [{ name: 'Customer Innovation' }],
        expires_at: null,
      }),
    ).toBe(
      'read everything you can see and submit your evaluations, only in Customer Innovation, until you revoke it',
    )
    expect(
      accessSummary(
        { scopes: ['read'], restricted: true, projects: [], expires_at: undefined },
        { noProjects: 'only in the projects you choose' },
      ),
    ).toBe(
      'read everything you can see, only in the projects you choose, until the date you choose',
    )
    expect(
      accessSummary({
        scopes: ['read'],
        restricted: true,
        projects: [{ name: 'A' }, { name: 'B' }, { name: 'C' }],
        expires_at: null,
      }),
    ).toContain('only in 3 projects')
  })

  it('warns within a week of the expiry, not after it', () => {
    const now = Date.parse('2026-10-06T12:00:00Z')
    expect(expiresSoon('2026-10-08T12:00:00Z', now)).toBe(true)
    expect(expiresSoon('2026-10-20T12:00:00Z', now)).toBe(false)
    expect(expiresSoon('2026-10-05T12:00:00Z', now)).toBe(false)
    expect(expiresSoon(null, now)).toBe(false)
  })
})
