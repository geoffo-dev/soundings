import { useQueryClient } from '@tanstack/react-query'
import { CloudOff, FilePlus2, FileText, Lock } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { queryKeys } from '@/api/keys'
import { useCreateProposal, useProposal } from '@/api/proposals'
import type { CurrentUser, IdeaDetail, ProposalPermissions } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { useCommands } from '@/lib/command-registry'

import { ProposalEditor } from './proposal-editor'
import { PROPOSAL_SECTIONS } from './text'

export interface ProposalPanelProps {
  /** The upper-case key from the URL. */
  ideaKey: string
  idea: IdeaDetail
  me: CurrentUser
  /** The project is archived: everything is read-only. */
  archived: boolean
}

/**
 * The idea page's Proposal tab (SPEC §5 screen 5, wireframe 05): nothing yet
 * ("Available once shortlisted", or "Start proposal" for the owner and
 * admins), else the editor — or a read-only view for everyone else.
 */
export function ProposalPanel({ ideaKey, idea, me, archived }: ProposalPanelProps) {
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
      <NoProposal ideaKey={ideaKey} idea={idea} archived={archived} permissions={permissions} />
    )
  }
  return (
    <ProposalEditor
      key={proposal.id}
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
}: {
  ideaKey: string
  idea: IdeaDetail
  archived: boolean
  permissions: ProposalPermissions
}) {
  const create = useCreateProposal(ideaKey)
  const ready = idea.status === 'shortlisted' || idea.status === 'proposal'
  useCommands({
    id: 'proposal',
    heading: 'Proposal',
    actions: permissions.can_create
      ? [
          {
            id: 'proposal-start',
            label: 'Start proposal',
            icon: <FilePlus2 />,
            keywords: ['proposal', 'write', 'business case'],
            onSelect: () => create.mutate(),
          },
        ]
      : [],
  })

  if (permissions.can_create) {
    return (
      <div className="rounded-lg border">
        <EmptyState
          headingLevel={2}
          icon={<FileText />}
          title="Write the proposal"
          description={
            <>
              A short document over a fixed outline, from the summary to the ask. It saves as you
              type and exports as PDF or Markdown.
              {idea.status === 'shortlisted' && ' Starting it moves the idea to Proposal.'}
            </>
          }
          action={
            <Button
              variant="primary"
              loading={create.isPending}
              onClick={() => create.mutate()}
              data-primary-action=""
            >
              Start proposal
            </Button>
          }
        />
        <TemplatePreview />
      </div>
    )
  }

  const [title, description] = archived
    ? ['No proposal was written', 'This project is archived, so its ideas are read-only.']
    : !ready
      ? [
          'Available once the idea is shortlisted',
          'Strong ideas get a proposal: a short document the owner writes here and exports as PDF or Markdown.',
        ]
      : idea.owner
        ? [
            'The owner will write the proposal',
            `${idea.owner.display_name} can start it now. It will appear here, and you can comment on it as it takes shape.`,
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

/** The outline the proposal will follow, under "Start proposal". */
function TemplatePreview() {
  return (
    <div className="border-t border-subtle px-6 py-5">
      <h3 className="mb-3 text-center text-xs font-medium text-muted">Sections</h3>
      <ol className="mx-auto grid max-w-lg grid-cols-1 gap-x-6 gap-y-1.5 text-sm text-secondary xs:grid-cols-2">
        {PROPOSAL_SECTIONS.map((section, index) => (
          <li key={section.key} className="flex gap-2">
            <span className="w-4 text-right text-muted tabular-nums">{index + 1}.</span>
            {section.title}
          </li>
        ))}
      </ol>
    </div>
  )
}

/** Outline and headings first; section bodies as skeleton lines (wireframe 05). */
export function ProposalSkeleton() {
  return (
    <SkeletonGroup label="Loading proposal" className="flex flex-col">
      <div className="flex items-center justify-between border-b border-subtle pb-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="grid gap-x-10 xl:grid-cols-[12rem_minmax(0,1fr)]">
        <ol className="hidden flex-col gap-1 pt-8 xl:flex">
          {PROPOSAL_SECTIONS.map((section) => (
            <li
              key={section.key}
              className="flex items-center gap-2 px-2 py-1.5 text-sm text-muted"
            >
              <Skeleton className="size-4 rounded-full" />
              {section.title}
            </li>
          ))}
        </ol>
        <div className="flex flex-col">
          {PROPOSAL_SECTIONS.slice(0, 3).map((section, index) => (
            <div key={section.key} className="flex flex-col gap-3 border-b border-subtle py-8">
              <p className="text-lg font-semibold text-primary">
                <span className="text-muted tabular-nums">{index + 1}.</span> {section.title}
              </p>
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-11/12" />
              <Skeleton className="h-3.5 w-3/5" />
            </div>
          ))}
        </div>
      </div>
    </SkeletonGroup>
  )
}
