import { describe, expect, it } from 'vitest'

import {
  a2aUrlPreview,
  labelError,
  remoteMcpServerManifest,
  validateAgent,
  type AgentDraft,
} from './agent-rules'

const draft: AgentDraft = {
  display_name: 'Idea evaluator',
  description: '',
  namespace: 'soundings',
  name: 'idea-evaluator',
  protocol: 'kagent_v0_10',
  purposes: ['evaluate'],
  project_ids: ['p1'],
}

describe('agent rules', () => {
  it('accepts a complete registration', () => {
    expect(validateAgent(draft, { allowedNamespaces: ['soundings'], editing: false })).toEqual({})
  })

  it('takes only Kubernetes names, so no other host or path can be reached', () => {
    for (const bad of ['Idea', 'a/b', '../x', 'a.b', 'a:1', '-a', 'a-', 'a?b', 'a#b', 'a%2f']) {
      expect(labelError(bad, 'name')).toBeDefined()
    }
    expect(labelError('a'.repeat(64), 'name')).toBe('Use at most 63 characters')
    expect(labelError('idea-evaluator-2', 'name')).toBeUndefined()
  })

  it('names every gap, and the namespaces allowed', () => {
    const errors = validateAgent(
      { ...draft, display_name: ' ', namespace: 'kagent', purposes: [], project_ids: [] },
      { allowedNamespaces: ['soundings', 'agents'], editing: false },
    )
    expect(Object.keys(errors).sort()).toEqual([
      'display_name',
      'namespace',
      'project_ids',
      'purposes',
    ])
    expect(errors.namespace).toBe('Agents can run in soundings, agents')
    expect(
      validateAgent(
        { ...draft, display_name: 'Two\nlines' },
        { allowedNamespaces: [], editing: false },
      ).display_name,
    ).toBe('Use one line of text')
  })

  it('doesn’t check the fixed namespace and name when editing', () => {
    expect(
      validateAgent(
        { ...draft, namespace: 'Anything' },
        { allowedNamespaces: ['x'], editing: true },
      ),
    ).toEqual({})
  })

  it('previews the built A2A URL for both protocols', () => {
    expect(
      a2aUrlPreview('http://kagent-controller.kagent:8083', 'kagent_v0_10', 'soundings', 'x'),
    ).toBe('http://kagent-controller.kagent:8083/api/a2a/soundings/x/')
    expect(a2aUrlPreview('http://k:8083', 'kagent_v1_0', '', '')).toBe(
      'http://k:8083/agents/{namespace}/{name}',
    )
  })

  it('never previews a namespace or name the API would refuse', () => {
    expect(a2aUrlPreview('http://k:8083', 'kagent_v0_10', 'Soundings', 'idea.evaluator')).toBe(
      'http://k:8083/api/a2a/{namespace}/{name}/',
    )
    expect(a2aUrlPreview('http://k:8083', 'kagent_v0_10', 'soundings', '../x')).toBe(
      'http://k:8083/api/a2a/soundings/{name}/',
    )
  })

  it('writes the agent’s RemoteMCPServer with the Secret’s header and no key', () => {
    const yaml = remoteMcpServerManifest(
      { namespace: 'soundings', name: 'idea-evaluator' },
      'http://soundings.soundings.svc.cluster.local:80/mcp',
    )
    expect(yaml).toContain('kind: RemoteMCPServer')
    expect(yaml).toContain('url: http://soundings.soundings.svc.cluster.local:80/mcp')
    expect(yaml).toContain('name: soundings-agent-idea-evaluator')
    expect(yaml).toContain('key: authorization')
    expect(yaml).not.toMatch(/sdg_/)
  })
})
