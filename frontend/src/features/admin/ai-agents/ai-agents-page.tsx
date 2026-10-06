import { Link } from '@tanstack/react-router'
import {
  Bot,
  CircleAlert,
  CircleCheck,
  CloudOff,
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plug,
  Power,
  PowerOff,
} from 'lucide-react'
import { useState } from 'react'

import { useAiAgents, useRotateAiAgentKey, useTestAiAgent, useUpdateAiAgent } from '@/api/ai-agents'
import type { AiAgent, AiAgentTest, AiSettingsInEffect } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from '@/components/ui/toaster'
import { AdminPageHeader, AdminSection } from '@/features/admin/settings-frame'
import { useCurrentUser } from '@/features/auth/current-user'
import { KIND_COPY, PROTOCOL_COPY } from '@/features/ai/ai-copy'
import { CopyLine } from '@/features/api-keys/code-snippet'
import { focusWhenRendered } from '@/lib/focus'
import { ROW_ID_ATTRIBUTE } from '@/lib/return-to-row'

import { AgentFormSheet } from './agent-form-sheet'
import { AgentKeyDialog, type AgentKeyReveal } from './agent-key-dialog'

/**
 * Admin settings → AI agents (contract-phase6 §3.15, `platform.manage_agents`):
 * the AI settings in effect (read-only, from the Helm values; a banner while AI
 * assistance is off), every registered kagent agent with what it does, its
 * projects, its key and its runs, and Register / Test connection / Change /
 * Rotate key / Disable–Enable.
 */
export function AiAgentsPage() {
  const me = useCurrentUser()
  const query = useAiAgents()
  // The register sheet resets its own mutation as soon as it hands the key over.
  const rotate = useRotateAiAgentKey()
  const [registering, setRegistering] = useState(false)
  const [editing, setEditing] = useState<AiAgent | null>(null)
  const [reveal, setReveal] = useState<AgentKeyReveal | undefined>(undefined)
  const data = query.data
  const settings = data?.settings

  return (
    <>
      <AdminPageHeader
        title="AI agents"
        description="kagent agents that ideas’ owners can ask to evaluate, research or draft. Each acts through its own service account and key, only on the idea of a run someone asked for."
        actions={
          data && (
            <Button
              variant="primary"
              disabled={!data.can_register}
              onClick={() => setRegistering(true)}
            >
              <Bot />
              Register agent
            </Button>
          )
        }
      />
      {query.isPending ? (
        <SkeletonGroup label="Loading AI agents" className="flex flex-col gap-3">
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-40 w-full rounded-lg" />
        </SkeletonGroup>
      ) : query.isError || !data || !settings ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<CloudOff />}
          title="Couldn’t load the AI agents"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <>
          {!settings.enabled && (
            <Callout tone="warning" role="status" title="AI assistance is off">
              Agents can be registered, but no run starts and the idea page offers no AI actions
              until <code className="font-mono">features.ai</code> is on in the Helm values (
              <code className="font-mono">SOUNDINGS_AI_ENABLED</code>).
            </Callout>
          )}
          {!data.can_register && me.auth_method === 'break_glass' && (
            <Callout tone="neutral" title="The break-glass account can’t register agents">
              Registering creates the agent’s API key. Sign in with your own account to register one
              or rotate a key.
            </Callout>
          )}
          {!data.can_register && data.items.length >= data.max_agents && (
            <Callout
              tone="neutral"
              title={`Soundings has ${data.max_agents} agents, the most it allows`}
            >
              Disable agents you no longer use before registering another.
            </Callout>
          )}
          <AgentsList
            agents={data.items}
            settings={settings}
            onRegister={data.can_register ? () => setRegistering(true) : undefined}
            onEdit={setEditing}
            onRotated={(rotated) => setReveal({ ...rotated, rotated: true })}
            rotate={rotate}
          />
          <SettingsInEffect settings={settings} />
          <AgentFormSheet
            open={registering}
            onOpenChange={setRegistering}
            settings={settings}
            onRegistered={(created) => setReveal(created)}
          />
          <AgentFormSheet
            open={editing !== null}
            onOpenChange={(open) => !open && setEditing(null)}
            agent={editing ?? undefined}
            settings={settings}
            onRegistered={() => undefined}
          />
          <AgentKeyDialog
            reveal={reveal}
            mcpUrl={settings.mcp_url}
            onDone={() => {
              const agentId = reveal?.agent.id
              setReveal(undefined)
              // The rotated key leaves the cache with the mutation's result.
              rotate.reset()
              if (agentId) {
                focusWhenRendered(
                  () =>
                    document.querySelector<HTMLElement>(
                      `[${ROW_ID_ATTRIBUTE}="${CSS.escape(agentId)}"]`,
                    ),
                  { force: true },
                )
              }
            }}
          />
        </>
      )}
    </>
  )
}

function AgentsList({
  agents,
  settings,
  onRegister,
  onEdit,
  onRotated,
  rotate,
}: {
  agents: AiAgent[]
  settings: AiSettingsInEffect
  onRegister?: () => void
  onEdit: (agent: AiAgent) => void
  onRotated: (rotated: AgentKeyReveal) => void
  rotate: ReturnType<typeof useRotateAiAgentKey>
}) {
  const update = useUpdateAiAgent()
  const test = useTestAiAgent()
  const [rotating, setRotating] = useState<AiAgent | null>(null)
  const [disabling, setDisabling] = useState<AiAgent | null>(null)
  const [tested, setTested] = useState<{ agent: AiAgent; result: AiAgentTest } | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)

  if (agents.length === 0) {
    return (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<Bot />}
        title="No AI agents yet"
        description="Register a kagent agent so owners can ask it to evaluate ideas, research them or draft proposal sections."
        action={
          onRegister && (
            <Button variant="secondary" onClick={onRegister}>
              Register agent
            </Button>
          )
        }
      />
    )
  }

  const runTest = (agent: AiAgent) => {
    setTestingId(agent.id)
    test.mutate(agent.id, {
      onSuccess: (result) => setTested({ agent, result }),
      onSettled: () => setTestingId(null),
    })
  }
  const enable = (agent: AiAgent) =>
    update.mutate(
      { agentId: agent.id, body: { enabled: true } },
      {
        onSuccess: () =>
          toast.success(`${agent.display_name} is enabled`, {
            description: 'Disabling revoked its key: rotate it to give the agent a new one.',
            action: { label: 'Rotate key', onClick: () => setRotating(agent) },
          }),
      },
    )
  const disable = () => {
    if (!disabling) return
    const agent = disabling
    update.mutate(
      { agentId: agent.id, body: { enabled: false } },
      {
        onSuccess: () => {
          setDisabling(null)
          toast.success(`${agent.display_name} is disabled`, {
            description: 'Its runs stopped and its key no longer works.',
          })
        },
        onError: () => setDisabling(null),
      },
    )
  }
  const confirmRotate = () => {
    if (!rotating) return
    rotate.mutate(rotating.id, {
      onSuccess: (rotated) => {
        setRotating(null)
        onRotated(rotated)
      },
      onError: () => setRotating(null),
    })
  }

  return (
    <AdminSection
      id="ai-agents"
      title={agents.length === 1 ? '1 agent' : `${agents.length} agents`}
      actions={
        <Link
          to="/settings/audit"
          search={{ action: ['ai'] }}
          className="text-sm text-accent hover:underline"
        >
          Runs and changes in the audit log
        </Link>
      }
    >
      <div className="overflow-hidden rounded-lg border">
        <Table mobile="container-cards" aria-label="AI agents" className="@3xl:table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead className="w-44">Does</TableHead>
              <TableHead className="w-44">Projects</TableHead>
              <TableHead className="w-40">Key</TableHead>
              <TableHead className="w-28">State</TableHead>
              <TableHead className="w-14">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {agents.map((agent) => (
              <AgentRow
                key={agent.id}
                agent={agent}
                testing={testingId === agent.id}
                onTest={() => runTest(agent)}
                onEdit={() => onEdit(agent)}
                onRotate={() => setRotating(agent)}
                onDisable={() => setDisabling(agent)}
                onEnable={() => enable(agent)}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <TestResultDialog tested={tested} settings={settings} onClose={() => setTested(null)} />

      <Dialog open={rotating !== null} onOpenChange={(open) => !open && setRotating(null)}>
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader>
            <DialogTitle>Rotate {rotating?.display_name}’s key?</DialogTitle>
            <DialogDescription>
              Its current key stops working at once, and the agent stops until its Secret holds the
              new key. You’ll see the new key once.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-5">
            <Button variant="ghost" onClick={() => setRotating(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={rotate.isPending} onClick={confirmRotate}>
              Rotate key
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={disabling !== null} onOpenChange={(open) => !open && setDisabling(null)}>
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader>
            <DialogTitle>Disable {disabling?.display_name}?</DialogTitle>
            <DialogDescription>
              Its runs stop and its key is revoked. Its evaluations, notes and suggestions stay. To
              enable it again you’ll rotate its key and update its Secret.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-5">
            <Button variant="ghost" onClick={() => setDisabling(null)}>
              Cancel
            </Button>
            <Button variant="destructive" loading={update.isPending} onClick={disable}>
              Disable agent
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AdminSection>
  )
}

function AgentRow({
  agent,
  testing,
  onTest,
  onEdit,
  onRotate,
  onDisable,
  onEnable,
}: {
  agent: AiAgent
  testing: boolean
  onTest: () => void
  onEdit: () => void
  onRotate: () => void
  onDisable: () => void
  onEnable: () => void
}) {
  return (
    <TableRow className="@3xl:h-17">
      <TableCell primary className="min-w-0 py-2.5">
        <div className="flex min-w-0 items-start gap-3">
          <Avatar name={agent.display_name} isAgent size="md" decorative className="mt-0.5" />
          <div
            tabIndex={-1}
            {...{ [ROW_ID_ATTRIBUTE]: agent.id }}
            className="flex min-w-0 flex-col gap-0.5 rounded-sm outline-offset-2"
          >
            <span className="truncate font-medium text-primary">
              {agent.display_name}
              <span className="sr-only"> (AI agent)</span>
            </span>
            <span className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-xs text-muted">
              <code
                className="min-w-0 truncate font-mono text-secondary"
                // Cut to the column: the whole name on hover.
                title={`${agent.namespace}/${agent.name}`}
              >
                {agent.namespace}/{agent.name}
              </code>
              <span aria-hidden="true">·</span>
              <span>{PROTOCOL_COPY[agent.protocol].label}</span>
            </span>
            {agent.description && (
              <span className="line-clamp-1 text-xs text-muted" title={agent.description}>
                {agent.description}
              </span>
            )}
          </div>
        </div>
      </TableCell>
      <TableCell label="Does">
        <ul className="flex flex-wrap gap-1">
          {agent.purposes.map((kind) => (
            <li key={kind}>
              <Badge variant="neutral">{KIND_COPY[kind].noun}</Badge>
            </li>
          ))}
        </ul>
      </TableCell>
      <TableCell label="Projects" className="min-w-0">
        <ul className="flex flex-col gap-0.5 text-sm">
          {agent.projects.map((project) => (
            <li key={project.id} className="min-w-0">
              <span className={project.role === 'member' ? 'text-primary' : 'text-secondary'}>
                {project.name}
              </span>
              {project.role === null && (
                <span className="block text-xs text-warning">Removed: can’t work there</span>
              )}
              {project.role === 'viewer' && (
                <span className="block text-xs text-warning">Viewer: can’t work there</span>
              )}
            </li>
          ))}
        </ul>
      </TableCell>
      <TableCell label="Key">
        {agent.key ? (
          <span className="flex min-w-0 flex-col gap-0.5">
            <code className="truncate font-mono text-xs text-secondary">{agent.key.prefix}</code>
            <span className="text-xs text-muted">
              {agent.key.last_used_at ? (
                <>
                  Used <RelativeTime date={agent.key.last_used_at} />
                </>
              ) : (
                'Not used yet'
              )}
            </span>
          </span>
        ) : agent.enabled ? (
          <span className="flex items-center gap-1 text-xs text-warning">
            <KeyRound aria-hidden="true" className="size-3.5" />
            No key: rotate to issue one
          </span>
        ) : (
          // Disabling revoked it: expected, not a problem to fix.
          <span className="text-xs text-muted">Revoked when disabled</span>
        )}
      </TableCell>
      <TableCell label="State">
        <span className="flex flex-col items-start gap-1">
          {agent.enabled ? (
            <Badge variant="success">Enabled</Badge>
          ) : (
            <Badge variant="neutral">Disabled</Badge>
          )}
          {agent.active_run_count > 0 && (
            <span className="text-xs text-muted">
              {agent.active_run_count === 1
                ? '1 run active'
                : `${agent.active_run_count} runs active`}
            </span>
          )}
        </span>
      </TableCell>
      <TableCell className="@max-3xl:basis-full @3xl:text-right">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Actions for ${agent.display_name}`}
              className="@max-3xl:hidden"
            >
              {testing ? <Spinner /> : <MoreHorizontal />}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onTest}>
              <Plug /> Test connection
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil /> Change…
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onRotate}>
              <KeyRound /> Rotate key…
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {agent.enabled ? (
              <DropdownMenuItem variant="destructive" onSelect={onDisable}>
                <PowerOff /> Disable…
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={onEnable}>
                <Power /> Enable
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        {/* Phones: the actions as buttons on the card. */}
        <div className="flex flex-wrap gap-1 @3xl:hidden">
          <Button variant="ghost" size="sm" loading={testing} onClick={onTest}>
            <Plug /> Test
          </Button>
          <Button variant="ghost" size="sm" onClick={onEdit}>
            <Pencil /> Change
          </Button>
          <Button variant="ghost" size="sm" onClick={onRotate}>
            <KeyRound /> Rotate key
          </Button>
          {agent.enabled ? (
            <Button variant="ghost" size="sm" onClick={onDisable}>
              <PowerOff /> Disable
            </Button>
          ) : (
            <Button variant="ghost" size="sm" onClick={onEnable}>
              <Power /> Enable
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

/** What the agent card said through the controller (plain text: whoever configured it wrote it). */
function TestResultDialog({
  tested,
  settings,
  onClose,
}: {
  tested: { agent: AiAgent; result: AiAgentTest } | null
  settings: AiSettingsInEffect
  onClose: () => void
}) {
  const result = tested?.result
  return (
    <Dialog open={tested !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="lg">
        {tested && result && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {result.ok ? (
                  <CircleCheck aria-hidden="true" className="size-4 text-success" />
                ) : (
                  <CircleAlert aria-hidden="true" className="size-4 text-danger" />
                )}
                {result.ok
                  ? `${tested.agent.display_name} answered`
                  : `${tested.agent.display_name} didn’t answer`}
              </DialogTitle>
              <DialogDescription>
                {result.ok
                  ? `Its agent card came back in ${result.duration_ms} ms.`
                  : testFailureWords(tested.agent, result)}
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-4">
              <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                <dt className="text-muted">Card URL</dt>
                <dd className="min-w-0">
                  <code className="font-mono text-xs break-all text-secondary">{result.url}</code>
                </dd>
                <dt className="text-muted">HTTP status</dt>
                <dd className="tabular-nums">{result.http_status ?? 'No answer'}</dd>
                {result.card && (
                  <>
                    <dt className="text-muted">Name</dt>
                    <dd className="min-w-0 break-words">{result.card.name}</dd>
                    {result.card.description && (
                      <>
                        <dt className="text-muted">Description</dt>
                        <dd className="min-w-0 break-words text-secondary">
                          {result.card.description}
                        </dd>
                      </>
                    )}
                    <dt className="text-muted">A2A versions</dt>
                    <dd>{result.card.protocol_versions.join(', ') || 'Not stated'}</dd>
                    <dt className="text-muted">Streaming</dt>
                    <dd>{result.card.streaming ? 'Yes' : 'No: runs need streaming'}</dd>
                    <dt className="text-muted">Skills</dt>
                    <dd className="min-w-0">
                      {result.card.skills.length === 0 ? (
                        <span className="text-muted">None listed</span>
                      ) : (
                        <ul className="flex flex-col gap-0.5">
                          {result.card.skills.map((skill) => (
                            <li key={skill.id} className="break-words">
                              {skill.name}{' '}
                              <code className="font-mono text-xs text-muted">{skill.id}</code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </dd>
                  </>
                )}
              </dl>
              {!result.ok && (
                <Callout tone="neutral" title="What to check">
                  <ul className="mt-1 flex list-disc flex-col gap-1 pl-4">
                    {testChecks(tested.agent, result, settings).map((check) => (
                      <li key={check}>{check}</li>
                    ))}
                  </ul>
                </Callout>
              )}
              {result.ok && result.card && !result.card.streaming && (
                <Callout tone="warning" title="This agent can’t stream">
                  Soundings always streams a run’s progress; runs with this agent will fail.
                </Callout>
              )}
            </DialogBody>
            <DialogFooter className="pt-2">
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * Why Test connection failed, in words: the controller answering 404 means it is
 * there but has no such agent (not "couldn't reach"); no answer at all means it
 * couldn't be reached.
 */
function testFailureWords(agent: AiAgent, result: AiAgentTest): string {
  const where = `${agent.namespace}/${agent.name}`
  if (result.http_status === 404) {
    return `The kagent controller answered, but it has no ready agent ${where}.`
  }
  if (result.http_status === null) return 'Soundings couldn’t reach the kagent controller.'
  if (result.http_status === 401 || result.http_status === 403) {
    return `The kagent controller refused the request (HTTP ${result.http_status}).`
  }
  return result.error_message ?? 'The agent card couldn’t be read.'
}

/** The likely causes first, one per line (Test connection failed). */
function testChecks(agent: AiAgent, result: AiAgentTest, settings: AiSettingsInEffect): string[] {
  const where = `${agent.namespace}/${agent.name}`
  const deployed = `The Agent ${where} exists and is Ready (kubectl get agents -n ${agent.namespace}).`
  const secret = `Its Secret with the key is applied, and its RemoteMCPServer accepted.`
  const protocol = `The protocol matches your kagent: ${PROTOCOL_COPY[agent.protocol].label} calls ${PROTOCOL_COPY[agent.protocol].detail}.`
  const reachable = `Soundings can reach ${settings.kagent_url} (the NetworkPolicy egress to the controller).`
  const token = 'The controller token in the Helm values (kagent.existingTokenSecret) is right.'
  if (result.http_status === 404) return [deployed, secret, protocol]
  if (result.http_status === 401 || result.http_status === 403) return [token, deployed]
  if (result.http_status === null) return [reachable, deployed]
  return [protocol, deployed, reachable]
}

/** The read-only AI settings (Helm values), and the MCP URL to give agents. */
function SettingsInEffect({ settings }: { settings: AiSettingsInEffect }) {
  const minutes = Math.round(settings.run_timeout_seconds / 60)
  return (
    <AdminSection
      id="ai-settings"
      title="Settings in effect"
      description="From the Helm values (ai.*, kagent.*); change them there."
    >
      <dl className="grid gap-x-6 gap-y-3 rounded-lg border p-4 text-sm sm:grid-cols-[14rem_minmax(0,1fr)]">
        <dt className="text-muted">AI assistance</dt>
        <dd>{settings.enabled ? 'On' : 'Off'}</dd>
        <dt className="text-muted">kagent controller</dt>
        <dd className="min-w-0">
          <code className="font-mono text-xs break-all text-secondary">{settings.kagent_url}</code>
          <span className="text-muted">
            {' '}
            · {settings.kagent_token_set ? 'token set' : 'no token'}
          </span>
        </dd>
        <dt className="text-muted">Default protocol</dt>
        <dd>{PROTOCOL_COPY[settings.default_protocol].label}</dd>
        <dt className="text-muted">Run time limit</dt>
        <dd>
          {settings.run_timeout_seconds < 120
            ? `${settings.run_timeout_seconds} seconds`
            : `${minutes} minutes`}
        </dd>
        <dt className="text-muted">Runs at once</dt>
        <dd>{settings.max_concurrent_runs} per worker</dd>
        <dt className="text-muted">Namespaces</dt>
        <dd>{settings.agent_namespaces.join(', ')}</dd>
        <dt className="text-muted">MCP URL for agents</dt>
        <dd className="flex min-w-0 flex-col gap-1">
          <CopyLine value={settings.mcp_url} label="the MCP URL" />
          <span className="text-xs text-muted">
            Put it in each agent’s RemoteMCPServer. It is never sent to agents in a run.
          </span>
        </dd>
      </dl>
    </AdminSection>
  )
}
