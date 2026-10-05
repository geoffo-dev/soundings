import { useState } from 'react'

import type { ApiKeyScope } from '@/api/types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AdminSection } from '@/features/admin/settings-frame'

import { CodeSnippet, CopyLine } from './code-snippet'
import {
  authorizationHeader,
  claudeCodeCommand,
  curlExample,
  KEY_PLACEHOLDER,
  mcpServersConfig,
  mcpUrl,
} from './snippets'

type Example = 'json' | 'claude' | 'curl'

/**
 * The examples for a key: an `mcpServers` config, the Claude Code command and
 * curl. With the new key filled in (the secret dialog) or a placeholder (the
 * page). Without the `mcp` scope only curl is offered.
 */
export function KeyExamples({
  secret,
  scopes,
}: {
  secret?: string
  scopes: readonly ApiKeyScope[]
}) {
  const origin = window.location.origin
  const url = mcpUrl(origin)
  const key = secret ?? KEY_PLACEHOLDER
  const mcp = scopes.includes('mcp')
  const [tab, setTab] = useState<Example>(mcp ? 'json' : 'curl')
  return (
    <Tabs value={tab} onValueChange={(value) => setTab(value as Example)} className="min-w-0">
      <TabsList aria-label="Examples">
        {mcp && (
          <>
            <TabsTrigger value="json">MCP config</TabsTrigger>
            <TabsTrigger value="claude">Claude Code</TabsTrigger>
          </>
        )}
        <TabsTrigger value="curl">curl</TabsTrigger>
      </TabsList>
      {mcp && (
        <>
          <TabsContent value="json" className="flex flex-col gap-2 pt-3">
            <p className="text-sm text-muted">
              For clients that take an <code className="font-mono text-secondary">mcpServers</code>{' '}
              map (Claude Desktop, IDE assistants and others).
            </p>
            <CodeSnippet code={mcpServersConfig(url, key)} label="the MCP config" />
          </TabsContent>
          <TabsContent value="claude" className="flex flex-col gap-2 pt-3">
            <p className="text-sm text-muted">Run it in a terminal where you use Claude Code.</p>
            <CodeSnippet code={claudeCodeCommand(url, key)} label="the Claude Code command" />
          </TabsContent>
        </>
      )}
      <TabsContent value="curl" className="flex flex-col gap-2 pt-3">
        <p className="text-sm text-muted">
          {scopes.includes('read')
            ? 'Lists the projects the key can see: a quick way to check it works.'
            : 'Lists the MCP server’s tools: a quick way to check the key works.'}
        </p>
        <CodeSnippet code={curlExample(origin, scopes, key)} label="the curl example" />
      </TabsContent>
    </Tabs>
  )
}

/**
 * Settings → API keys, "Connect an MCP client" (contract-phase5 §3.10): the
 * server URL, the header and ready-to-paste examples with a placeholder key.
 */
export function ConnectMcpSection() {
  const url = mcpUrl()
  return (
    <AdminSection
      id="connect-mcp"
      title="Connect an MCP client"
      description="An MCP client, such as Claude Desktop, Claude Code or an assistant in your editor, can search ideas, read proposals, comment and submit your evaluations as you. Create a key with the MCP scope (and Read, Write or Evaluate for its tools), then give the client:"
    >
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)] sm:items-center">
        <dt className="text-muted">Server URL</dt>
        <dd className="min-w-0">
          <CopyLine value={url} label="the server URL" />
        </dd>
        <dt className="text-muted">Header</dt>
        <dd className="min-w-0">
          <CopyLine value={authorizationHeader()} label="the header" />
        </dd>
        <dt className="text-muted">Transport</dt>
        <dd className="text-secondary">
          Streamable HTTP, stateless: no session to keep open. Every tool call is recorded in the
          audit log.
        </dd>
      </dl>
      <KeyExamples scopes={['read', 'mcp']} />
    </AdminSection>
  )
}
