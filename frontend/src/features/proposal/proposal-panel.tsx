import { useQueryClient } from '@tanstack/react-query'
import { CloudOff, FilePlus2, FileText, Lock } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { queryKeys } from '@/api/keys'
import { useProject } from '@/api/projects'
import { useCreateProposal, useProposal } from '@/api/proposals'
import { useProposalTemplate } from '@/api/research'
import type { CurrentUser, IdeaDetail, ProposalPermissions } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { requestResearchFocus } from '@/features/research/research-focus'
import { useCommands } from '@/lib/command-registry'
import { focusWhenRendered } from '@/lib/focus'

import { ProposalEditor } from './proposal-editor'
import { ProposalSkeleton } from './proposal-skeleton'

export interface ProposalPanelProps {
  /** The upper-case key from the URL. */
  ideaKey: string
  idea: IdeaDetail
  me: CurrentUser
  /** The project is archived: everything is read-only. */
  archived: boolean
  /** Phase 8: shows the idea's Research panel (the Overview tab). */
  onOpenResearch?: () => void
}

/**
 * The idea page's Proposal tab (SPEC §5 screen 5, wireframe 05): nothing yet
 * ("Available once shortlisted", or "Start proposal" for the owner and
 * admins), else the editor — or a read-only view for everyone else.
 */
export function ProposalPanel({ ideaKey, idea, me, archived, onOpenResearch }: ProposalPanelProps) {
  const view = useProposal(ideaKey)
  useRefetchOnStatusChange(ideaKey, idea.status)

  if (view.isPending) return <ProposalSkeleton />
  if (view.isError) {
    return (
      <div role="alert" className="rounded-lg border">
        <EmptyState
          size="compact"
          headingLevel={2}
          icon={<CloudOff />}
          title="We couldn’t load the proposal"
          description="Check your connection and try again."
          action={
            <Button size="sm" onClick={() => void view.refetch()}>
              Try again
            </Button>
          }
        />
      </div>
    )
  }
  const { proposal, permissions } = view.data
  if (!proposal) {
    return (
      <NoProposal
        ideaKey={ideaKey}
        idea={idea}
        archived={archived}
        permissions={permissions}
        onOpenResearch={onOpenResearch}
      />
    )
  }
  return (
    <ProposalEditor
      key={proposal.id}
      onOpenResearch={onOpenResearch}
      ideaKey={ideaKey}
      idea={idea}
      me={me}
      proposal={proposal}
      permissions={permissions}
    />
  )
}

/** Permissions follow the idea's status (c7): refetch when it moves (board, dialog, Undo). */
function useRefetchOnStatusChange(ideaKey: string, status: IdeaDetail['status']) {
  const queryClient = useQueryClient()
  const previous = useRef(status)
  useEffect(() => {
    if (previous.current === status) return
    previous.current = status
    void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.view(ideaKey) })
  }, [queryClient, ideaKey, status])
}

function NoProposal({
  ideaKey,
  idea,
  archived,
  permissions,
  onOpenResearch,
}: {
  ideaKey: string
  idea: IdeaDetail
  archived: boolean
  permissions: ProposalPermissions
  onOpenResearch?: () => void
}) {
  const create = useCreateProposal(ideaKey)
  const project = useProject(idea.project.slug).data
  const ready =
    idea.status === 'shortlisted' ||
    idea.status === 'proposal' ||
    (idea.status === 'research' && project?.research_step === 'before_proposal')
  // Phase 8: starting would be refused for open research items. Admins keep the button
  // (the 409's dialog offers "Start anyway"); the owner is sent to the research first.
  const blocked = permissions.start_blocked_by_research
  const canOverride = project?.permissions.can_manage === true
  const openResearch = () => {
    requestResearchFocus(ideaKey)
    onOpenResearch?.()
  }
  // The button (or palette entry) is gone once the editor renders: start writing in Summary.
  const start = () =>
    create.mutate(undefined, {
      onSuccess: () =>
        focusWhenRendered(
          () =>
            document.querySelector<HTMLElement>(
              '[data-testid="proposal-editor"] textarea[data-section-text]',
            ),
          { force: true },
        ),
    })
  useCommands({
    id: 'proposal',
    heading: 'Proposal',
    actions:
      permissions.can_create && (!blocked || canOverride)
        ? [
            {
              id: 'proposal-start',
              label: 'Start proposal',
              icon: <FilePlus2 />,
              keywords: ['proposal', 'write', 'business case'],
              onSelect: start,
            },
          ]
        : [],
  })

  if (permissions.can_create) {
    return (
      <div className="rounded-lg border">
        {blocked && (
          <Callout
            tone="warning"
            role="status"
            className="m-4 mb-0"
            title="Finish the research checklist first"
          >
            Starting the proposal moves the idea past research.
            {canOverride ? ' As an admin you can start it anyway: you’ll be asked to confirm.' : ''}
          </Callout>
        )}
        <EmptyState
          headingLevel={2}
          icon={<FileText />}
          title="Write the proposal"
          description={
            <>
              A short document over this project’s outline, from the summary to the ask. It saves as
              you type and exports as PDF or Markdown.
              {idea.status !== 'proposal' && ' Starting it moves the idea to Proposal.'}
            </>
          }
          action={
            blocked && !canOverride ? (
              <Button variant="primary" onClick={openResearch} data-primary-action="">
                Open research
              </Button>
            ) : (
              <Button
                variant="primary"
                loading={create.isPending}
                onClick={start}
                data-primary-action=""
              >
                Start proposal
              </Button>
            )
          }
        />
        <TemplatePreview slug={idea.project.slug} />
      </div>
    )
  }

  const [title, description] = archived
    ? ['No proposal was written', 'This project is archived, so its ideas are read-only.']
    : idea.status === 'closed'
      ? [
          'No proposal was written for this idea',
          'It was closed without one. Ideas get a proposal while they’re shortlisted.',
        ]
      : !ready
        ? [
            'Available once the idea is shortlisted',
            'Strong ideas get a proposal: a short document the owner writes here and exports as PDF or Markdown.',
          ]
        : idea.owner
          ? [
              'The owner will write the proposal',
              // Phase 8: the research before the proposal comes first.
              project?.research_step === 'before_proposal' &&
              (idea.research?.required_open ?? 0) > 0
                ? `${idea.owner.display_name} can start it once the research checklist is done. It will appear here, and you can comment on it as it takes shape.`
                : `${idea.owner.display_name} can start it now. It will appear here, and you can comment on it as it takes shape.`,
            ]
          : [
              'The owner will write the proposal',
              'Once the idea has an owner, they can start it here.',
            ]
  return (
    <div className="rounded-lg border">
      <EmptyState
        size="compact"
        headingLevel={2}
        icon={archived ? <Lock /> : <FileText />}
        title={title}
        description={description}
      />
    </div>
  )
}

/** The outline the proposal will follow (the project's template), under "Start proposal". */
function TemplatePreview({ slug }: { slug: string }) {
  const template = useProposalTemplate(slug)
  const sections = template.data?.sections
  if (template.isError) return null
  return (
    <div className="border-t border-subtle px-6 py-5">
      <h3 className="mb-3 text-center text-xs font-medium text-muted">Sections</h3>
      <ol className="mx-auto grid max-w-lg grid-cols-1 gap-x-6 gap-y-1.5 text-sm text-secondary xs:grid-cols-2">
        {sections
          ? sections.map((section, index) => (
              <li key={section.key} className="flex gap-2">
                <span className="w-4 text-right text-muted tabular-nums">{index + 1}.</span>
                {section.title}
              </li>
            ))
          : [0, 1, 2, 3].map((index) => (
              <li key={index} aria-hidden="true">
                <Skeleton className="h-4 w-28" />
              </li>
            ))}
      </ol>
    </div>
  )
}
