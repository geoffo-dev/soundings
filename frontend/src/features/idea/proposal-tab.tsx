import { FileText } from 'lucide-react'

import { EmptyState } from '@/components/ui/empty-state'

import { useIdeaPage } from './idea-context'

/** Placeholder until the proposal editor (Phase 4). */
export function ProposalTab() {
  const { idea } = useIdeaPage()
  const ready = idea.status === 'shortlisted' || idea.status === 'proposal'
  return (
    <div className="rounded-lg border">
      <EmptyState
        size="compact"
        icon={<FileText />}
        title={
          ready ? 'The proposal editor is on its way' : 'Available once the idea is shortlisted'
        }
        description={
          ready
            ? 'Soon the owner will write this idea’s proposal here and export it as PDF or Markdown.'
            : 'Strong ideas get a proposal: a short document the owner writes here and exports as PDF or Markdown.'
        }
      />
    </div>
  )
}
