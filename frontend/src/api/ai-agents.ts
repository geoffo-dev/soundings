/**
 * Admin settings → AI agents (contract-phase6 §2, §3.1; platform admins,
 * session only).
 *
 *   useAiAgents()            the agents (disabled ones too), the settings in effect, can_register
 *   useRegisterAiAgent()     silent (the sheet shows errors inline); its `data.key.secret` and
 *                            `data.secret_manifest` are the only copies of the key: call
 *                            `reset()` once the key dialog has closed
 *   useUpdateAiAgent()       name, description, protocol, purposes, projects, enabled
 *   useRotateAiAgentKey()    a new key (shown once), the old one revoked; `reset()` after
 *   useTestAiAgent()         fetches the agent card through the configured controller
 */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { AiAgent, AiAgentCreate, AiAgentList, AiAgentUpdate } from '@/api/types'

export const aiAgentsQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.admin.aiAgents(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/admin/ai-agents', { signal })),
    // Runs change it from elsewhere (active runs, the key's "Used …"): every visit refetches,
    // and an open page refreshes every 30 s while any agent is working.
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data?.items.some((agent) => agent.active_run_count > 0) ? 30_000 : false,
  })

export function useAiAgents() {
  return useQuery(aiAgentsQueryOptions())
}

/** Puts the agent (never a secret) into the list, keeping it sorted by name. */
function storeAgent(queryClient: QueryClient, agent: AiAgent) {
  queryClient.setQueryData<AiAgentList>(queryKeys.admin.aiAgents(), (list) => {
    if (!list) return list
    const items = [...list.items.filter((item) => item.id !== agent.id), agent].sort((a, b) =>
      a.display_name.localeCompare(b.display_name),
    )
    return { ...list, items }
  })
}

/** What an agent change touches: its keys, its service account, idea pages' agents. */
function afterAgentChange(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiAgents() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.apiKeys() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ai.all })
}

export function useRegisterAiAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AiAgentCreate) => unwrap(api.POST('/api/v1/admin/ai-agents', { body })),
    onSuccess: (created) => {
      storeAgent(queryClient, created.agent)
      afterAgentChange(queryClient)
    },
    meta: { silent: true },
  })
}

export function useUpdateAiAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, body }: { agentId: string; body: AiAgentUpdate }) =>
      unwrap(
        api.PATCH('/api/v1/admin/ai-agents/{agent_id}', {
          params: { path: { agent_id: agentId } },
          body,
        }),
      ),
    onSuccess: (agent) => {
      storeAgent(queryClient, agent)
      afterAgentChange(queryClient)
    },
    meta: { errorTitle: 'Couldn’t change the agent' },
  })
}

export function useRotateAiAgentKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) =>
      unwrap(
        api.POST('/api/v1/admin/ai-agents/{agent_id}/key', {
          params: { path: { agent_id: agentId } },
        }),
      ),
    onSuccess: (rotated) => {
      storeAgent(queryClient, rotated.agent)
      afterAgentChange(queryClient)
    },
    meta: { errorTitle: 'Couldn’t rotate the key' },
  })
}

export function useTestAiAgent() {
  return useMutation({
    mutationFn: (agentId: string) =>
      unwrap(
        api.POST('/api/v1/admin/ai-agents/{agent_id}/test', {
          params: { path: { agent_id: agentId } },
        }),
      ),
    meta: { errorTitle: 'Couldn’t test the connection' },
  })
}
