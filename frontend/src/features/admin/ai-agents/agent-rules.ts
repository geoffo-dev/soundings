import type { AiAgent, AiAgentProtocol, AiRunKind } from '@/api/types'

/*
 * Admin settings → AI agents: the form's rules (as the API's request models,
 * contract-phase6 §3.1) and the manifests shown with a new key.
 */

/** A Kubernetes name (DNS label): what `KUBERNETES_LABEL_PATTERN` accepts. */
export const KUBERNETES_LABEL = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/
export const DISPLAY_NAME_MAX = 80
export const DESCRIPTION_MAX = 500

export interface AgentDraft {
  display_name: string
  description: string
  namespace: string
  name: string
  protocol: AiAgentProtocol
  purposes: AiRunKind[]
  project_ids: string[]
}

export type AgentErrors = Partial<Record<keyof AgentDraft | 'form', string>>

/** `SingleLine`: no line breaks or other control characters. */
function singleLine(value: string): boolean {
  return !Array.from(value).some((char) => {
    const code = char.charCodeAt(0)
    return code < 0x20 || code === 0x7f || code === 0x2028 || code === 0x2029
  })
}

export function labelError(value: string, what: 'namespace' | 'name'): string | undefined {
  if (!value) return `Enter the kagent Agent’s ${what}`
  if (value.length > 63) return 'Use at most 63 characters'
  if (!KUBERNETES_LABEL.test(value)) {
    return 'Use lower-case letters, digits and hyphens, starting and ending with a letter or digit'
  }
  return undefined
}

/** The checks the API makes on the shape, so most mistakes show before sending. */
export function validateAgent(
  draft: AgentDraft,
  options: { allowedNamespaces: readonly string[]; editing: boolean },
): AgentErrors {
  const name = draft.display_name.trim()
  const found: [keyof AgentErrors, string | undefined][] = [
    [
      'display_name',
      !name
        ? 'Give it a name people will see, e.g. “Idea evaluator”'
        : name.length > DISPLAY_NAME_MAX
          ? `Use at most ${DISPLAY_NAME_MAX} characters`
          : !singleLine(name)
            ? 'Use one line of text'
            : undefined,
    ],
    [
      'description',
      draft.description.length > DESCRIPTION_MAX
        ? `Use at most ${DESCRIPTION_MAX} characters`
        : undefined,
    ],
  ]
  if (!options.editing) {
    const namespace = labelError(draft.namespace, 'namespace')
    const allowed = options.allowedNamespaces
    found.push([
      'namespace',
      namespace ??
        (allowed.length > 0 && !allowed.includes(draft.namespace)
          ? `Agents can run in ${allowed.join(', ')}`
          : undefined),
    ])
    found.push(['name', labelError(draft.name, 'name')])
  }
  if (draft.purposes.length === 0) found.push(['purposes', 'Choose at least one thing it does'])
  if (draft.project_ids.length === 0) found.push(['project_ids', 'Choose at least one project'])
  const errors: AgentErrors = Object.fromEntries(
    found.filter(([, message]) => message !== undefined),
  )
  return errors
}

/**
 * What `agent_a2a_url` builds (shown while typing: URLs are built, never given).
 * A namespace or name the API would refuse shows as its placeholder, never as
 * typed: the preview only ever shows a URL Soundings could call.
 */
export function a2aUrlPreview(
  kagentUrl: string,
  protocol: AiAgentProtocol,
  namespace: string,
  name: string,
): string {
  const ns = KUBERNETES_LABEL.test(namespace) ? namespace : '{namespace}'
  const agent = KUBERNETES_LABEL.test(name) ? name : '{name}'
  return protocol === 'kagent_v1_0'
    ? `${kagentUrl}/agents/${ns}/${agent}`
    : `${kagentUrl}/api/a2a/${ns}/${agent}/`
}

/** Purposes and projects an edit takes away (their active runs are cancelled). */
export function narrowing(agent: AiAgent, draft: Pick<AgentDraft, 'purposes' | 'project_ids'>) {
  return {
    purposes: agent.purposes.filter((kind) => !draft.purposes.includes(kind)),
    projects: agent.projects.filter((project) => !draft.project_ids.includes(project.id)),
  }
}

/** The Secret's name `agent_secret_manifest` uses (never cut). */
export function agentSecretName(name: string): string {
  return `soundings-agent-${name}`
}

/**
 * The agent's own RemoteMCPServer, pointing at Soundings' MCP URL with the
 * Secret's header (kagent v1alpha2; `headersFrom` as verified in Phase 5). No
 * key in it: the Secret holds that.
 */
export function remoteMcpServerManifest(
  agent: Pick<AiAgent, 'namespace' | 'name'>,
  mcpUrl: string,
): string {
  return [
    'apiVersion: kagent.dev/v1alpha2',
    'kind: RemoteMCPServer',
    'metadata:',
    `  name: soundings-${agent.name}`,
    `  namespace: ${agent.namespace}`,
    'spec:',
    "  description: Soundings ideas pipeline (this agent's own key)",
    '  protocol: STREAMABLE_HTTP',
    `  url: ${mcpUrl}`,
    '  timeout: 30s',
    '  headersFrom:',
    '    - name: Authorization',
    '      valueFrom:',
    '        type: Secret',
    `        name: ${agentSecretName(agent.name)}`,
    '        key: authorization',
    '',
  ].join('\n')
}
