import { ProposalPanel } from '@/features/proposal/proposal-panel'

import { useIdeaPage } from './idea-context'

/** The Proposal tab: the proposal editor (features/proposal) for the idea in view. */
export function ProposalTab() {
  const { ideaKey, idea, me, archived } = useIdeaPage()
  return <ProposalPanel ideaKey={ideaKey} idea={idea} me={me} archived={archived} />
}
