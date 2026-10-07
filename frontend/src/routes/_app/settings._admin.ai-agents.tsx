import { createFileRoute } from '@tanstack/react-router'

import { AiAgentsPage } from '@/features/admin/ai-agents/ai-agents-page'

/** /settings/ai-agents — registered kagent agents and the AI settings in effect (platform admins). */
export const Route = createFileRoute('/_app/settings/_admin/ai-agents')({
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'AI agents' }),
  head: () => ({ meta: [{ title: 'AI agents · Admin · Soundings' }] }),
  component: AiAgentsPage,
})
