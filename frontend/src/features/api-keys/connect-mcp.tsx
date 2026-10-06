import { ChevronRight, ExternalLink } from 'lucide-react'
import { useId, useState } from 'react'

import type { ApiKeyScope } from '@/api/types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

import { CodeSnippet, CopyLine } from './code-snippet'
import {
  authorizationHeader,
  claudeCodeCommand,
  claudeDesktopConfig,
  curlExample,
  KEY_PLACEHOLDER,
  mcpServersConfig,
  mcpUrl,
} from './snippets'

type Example = 'json' | 'claude' | 'desktop' | 'curl'

/**
 * The examples for a key: an `mcpServers` config, the Claude Code command,
 * Claude Desktop (through `mcp-remote`) and curl. With the new key filled in (the
 * secret dialog) or a placeholder (the page). Without the `mcp` scope only curl
 * is offered.
 */
export function KeyExamples({
  secret,
  scopes,
  onCopied,
}: {
  secret?: string
  scopes: readonly ApiKeyScope[]
  /** After any example was copied (with the key filled in, it copies the key too). */
  onCopied?: (value: string) => void
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
            <TabsTrigger value="desktop">Claude Desktop</TabsTrigger>
          </>
        )}
        <TabsTrigger value="curl">curl</TabsTrigger>
      </TabsList>
      {mcp && (
        <>
          <TabsContent value="json" className="flex flex-col gap-2 pt-3">
            <p className="text-sm text-muted">
              For clients that take an <code className="font-mono text-secondary">mcpServers</code>{' '}
              map of HTTP servers, such as a project’s{' '}
              <code className="font-mono text-secondary">.mcp.json</code> and many editor
              assistants.
            </p>
            <CodeSnippet
              code={mcpServersConfig(url, key)}
              label="the MCP config"
              onCopied={onCopied}
            />
          </TabsContent>
          <TabsContent value="claude" className="flex flex-col gap-2 pt-3">
            <p className="text-sm text-muted">Run it in a terminal where you use Claude Code.</p>
            <CodeSnippet
              code={claudeCodeCommand(url, key)}
              label="the Claude Code command"
              onCopied={onCopied}
            />
          </TabsContent>
          <TabsContent value="desktop" className="flex flex-col gap-2 pt-3">
            <p className="text-sm text-muted">
              Claude Desktop connects through the{' '}
              <code className="font-mono text-secondary">mcp-remote</code> bridge (it needs
              Node.js). Add this to{' '}
              <code className="font-mono text-secondary">claude_desktop_config.json</code>:
            </p>
            <CodeSnippet code={claudeDesktopConfig(url)} label="the Claude Desktop config" />
            <p className="text-sm text-muted">
              Then save this line in that header file, readable only by you:
            </p>
            <CopyLine
              value={authorizationHeader(key)}
              label="the header line"
              wrap
              onCopied={onCopied}
            />
          </TabsContent>
        </>
      )}
      <TabsContent value="curl" className="flex flex-col gap-2 pt-3">
        <p className="text-sm text-muted">
          {scopes.includes('read')
            ? 'Lists the projects the key can see: a quick way to check it works.'
            : 'Lists the MCP server’s tools: a quick way to check the key works.'}
        </p>
        <CodeSnippet
          code={curlExample(origin, scopes, key)}
          label="the curl example"
          onCopied={onCopied}
        />
      </TabsContent>
    </Tabs>
  )
}

/**
 * Settings → API keys, "For developers and AI assistants" (contract-phase5
 * §3.10 "Connect an MCP client"): folded away by default, because most people
 * only need the key itself. Open: the MCP server URL, the header, a link to the
 * API reference and ready-to-paste examples with a placeholder key.
 */
export function ConnectMcpSection() {
  const url = mcpUrl()
  const [open, setOpen] = useState(false)
  const contentId = useId()
  return (
    <section aria-labelledby="connect-mcp-heading" className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h3 id="connect-mcp-heading" className="text-base font-semibold text-primary">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={contentId}
            onClick={() => setOpen((value) => !value)}
            className="-ml-1 inline-flex items-center gap-1.5 rounded-sm px-1 hover:text-secondary"
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                'size-4 text-muted transition-transform duration-150',
                open && 'rotate-90',
              )}
            />
            For developers and AI assistants
          </button>
        </h3>
        <p className="max-w-2xl pl-6 text-sm text-muted">
          Connect an MCP client, such as Claude Desktop or Claude Code, or call the API with a key.
        </p>
      </div>
      {open && (
        <div id={contentId} className="flex flex-col gap-3 pl-6">
          <p className="max-w-2xl text-sm text-muted">
            An assistant can search ideas, read proposals, comment and submit your evaluations as
            you, as far as its key allows. Create a key with “AI assistants (MCP)” and Read, Write
            or Evaluate, then give the assistant:
          </p>
          <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)] sm:items-center">
            <dt className="text-muted">Server URL</dt>
            <dd className="min-w-0">
              <CopyLine value={url} label="the server URL" />
            </dd>
            <dt className="text-muted">Header</dt>
            <dd className="min-w-0">
              <CopyLine value={authorizationHeader()} label="the header" />
            </dd>
            <dt className="text-muted">API reference</dt>
            <dd className="text-secondary">
              <a
                href="/api/docs"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-accent hover:underline"
              >
                Every endpoint, with examples
                <ExternalLink aria-hidden="true" className="size-3.5" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </dd>
          </dl>
          <KeyExamples scopes={['read', 'mcp']} />
          <p className="text-sm text-muted">
            Every assistant’s tool call is recorded in the audit log.
          </p>
        </div>
      )}
    </section>
  )
}
