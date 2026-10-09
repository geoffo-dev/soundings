import { useNavigate } from '@tanstack/react-router'
import { Archive, ChevronRight, CloudOff, FileSearch } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { isApiError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import {
  useCachedIdeaSummary,
  useChangeIdeaStatus,
  useIdea,
  useSetEvaluationClosed,
  useVolunteerAsOwner,
} from '@/api/ideas'
import { useMarkIdeaNotificationsRead } from '@/api/notifications'
import { proposalQueryOptions, useCreateProposal, useProposalSuggestions } from '@/api/proposals'
import { useProject } from '@/api/projects'
import { forgetIdea, useIdeaResearch } from '@/api/research'
import type { IdeaDetail, IdeaSummary } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { EmptyState } from '@/components/ui/empty-state'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { ScoreBadge } from '@/components/ui/score-badge'
import { Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { IdeaNotFound, IdeaPageSkeleton } from '@/features/idea/idea-page-states'
import { StatusBadge } from '@/components/ui/status-badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from '@/components/ui/toaster'
import { AiRunsSection } from '@/features/ai/ai-runs-section'
import { AiMenu, submittedEvaluatorIds, useAiCommands } from '@/features/ai/idea-ai'
import { useCurrentUser } from '@/features/auth/current-user'
import { HeldIdeaBanner } from '@/features/moderation/idea-submission'
import { HandBackDialog, ResearchAssignmentDialog } from '@/features/research/research-assignment'
import { requestResearchFocus } from '@/features/research/research-focus'
import { ResearchPanel } from '@/features/research/research-panel'
import { focusWhenRendered, useTyping } from '@/lib/focus'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { ActivitySection } from './activity-feed'
import { DeleteIdeaDialog } from './delete-idea-dialog'
import { DescriptionSection } from './description-section'
import { EvaluateSheet } from './evaluate-sheet'
import { EvaluationsTab } from './evaluations-tab'
import { IdeaHeader } from './idea-header'
import { useIdeaCommands } from './idea-commands'
import {
  IdeaPageProvider,
  statusLabeller,
  useIdeaPage,
  type IdeaDialog,
  type IdeaPageContextValue,
} from './idea-context'
import type { IdeaSearch, IdeaTab } from './idea-search'
import { IdeaProperties } from './idea-sidebar'
import { InviteDialog } from './invite-dialog'
import { OwnerDialog } from './owner-dialog'
import { primaryAction, type PrimaryAction } from './primary-action'
import { ProposalTab } from './proposal-tab'
import { StatusDialog } from './status-dialog'

/**
 * The idea page (SPEC §5 screen 3, wireframe 03): content and conversation on
 * the left, state and people on the right; tabs only for Overview /
 * Evaluations / Proposal. `?evaluate=1` opens the evaluate sheet.
 */
export function IdeaPage({ ideaKey, search }: { ideaKey: string; search: IdeaSearch }) {
  const idea = useIdea(ideaKey)
  const cached = useCachedIdeaSummary(ideaKey)
  const queryClient = useQueryClient()
  const gone =
    idea.isError &&
    isApiError(idea.error) &&
    (idea.error.status === 404 || idea.error.status === 422)
  // Access ended (a guest researcher unassigned, the idea deleted): nothing of it stays
  // cached, and My work and the sidebar's counts drop it too.
  useEffect(() => {
    if (!gone) return
    forgetIdea(queryClient, ideaKey)
    void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
  }, [gone, queryClient, ideaKey])

  // Before the data: a refetch that 404s keeps the old data, and a guest researcher
  // whose access ended (or anyone after a delete) must not keep reading it.
  if (gone) return <IdeaNotFound />
  if (idea.data) {
    return <LoadedIdeaPage key={idea.data.id} idea={idea.data} ideaKey={ideaKey} search={search} />
  }
  if (idea.isError) return <IdeaLoadError onRetry={() => void idea.refetch()} />
  return <IdeaPageLoading summary={cached} />
}

function LoadedIdeaPage({
  idea,
  ideaKey,
  search,
}: {
  idea: IdeaDetail
  ideaKey: string
  search: IdeaSearch
}) {
  const me = useCurrentUser()
  const navigate = useNavigate()
  // Visiting an idea reads its notifications (contract-phase3 §3.2).
  useMarkIdeaNotificationsRead(ideaKey, idea.id)
  // Phase 8b: a guest researcher (column R) reads this idea only: never its project.
  const guest = !idea.permissions.can_view_project
  const project = useProject(idea.project.slug, { enabled: !guest }).data
  const guestResearch = useIdeaResearch(ideaKey, { enabled: guest })
  const researchStep = project?.research_step ?? guestResearch.data?.step ?? 'off'
  const archived = Boolean(project?.archived_at)
  // A guest has the Overview only (no Evaluations or Proposal: no dead tabs).
  const tab: IdeaTab = guest ? 'overview' : (search.tab ?? 'overview')
  // The Proposal tab spans the page; the details fold into the summary line and sheet.
  const wide = tab === 'proposal'
  const [dialog, setDialog] = useState<IdeaDialog | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const handingOff = useRef(false)
  const ownEvaluator = idea.evaluators.find((evaluator) => evaluator.user.id === me.id)
  const statusLabels = project?.status_labels
  const statusLabel = useMemo(() => statusLabeller(statusLabels), [statusLabels])
  const [commentFocusRequest, setCommentFocusRequest] = useState(0)
  const wantCommentFocus = useRef(false)

  const setSearch = useCallback(
    (patch: IdeaSearch) =>
      void navigate({
        from: '/ideas/$ideaKey',
        to: '/ideas/$ideaKey',
        params: { ideaKey },
        search: (previous) => ({ ...previous, ...patch }),
        replace: true,
        resetScroll: false,
      }),
    [navigate, ideaKey],
  )

  const setTab = useCallback(
    (next: IdeaTab) => setSearch({ tab: next === 'overview' ? undefined : next }),
    [setSearch],
  )

  // Only evaluators have a sheet: the param is dropped for everyone else, with a word
  // why (an old email's link after the owner removed you, say).
  const evaluateOpen = Boolean(search.evaluate && ownEvaluator)
  useEffect(() => {
    if (!search.evaluate || ownEvaluator) return
    setSearch({ evaluate: undefined })
    toast.info('You’re not evaluating this idea', {
      id: `not-evaluating:${ideaKey}`,
      description: 'Its owner may have removed you as an evaluator.',
    })
  }, [search.evaluate, ownEvaluator, setSearch, ideaKey])

  const openEvaluate = useCallback(() => {
    if (ownEvaluator) setSearch({ evaluate: true })
  }, [ownEvaluator, setSearch])

  // `?research=1` (the "Asked to research" email and inbox links): the Research panel.
  useEffect(() => {
    if (!search.research) return
    setSearch({ research: undefined, tab: undefined })
    requestResearchFocus(ideaKey)
  }, [search.research, setSearch, ideaKey])

  const openDialog = useCallback(
    (next: IdeaDialog) => {
      // From the phone details sheet: close it first and let the dialog take focus.
      if (detailsOpen) handingOff.current = true
      setDetailsOpen(false)
      setDialog(next)
    },
    [detailsOpen],
  )

  const focusComment = useCallback(() => {
    wantCommentFocus.current = true
    if (tab !== 'overview') setTab('overview')
    setCommentFocusRequest((n) => n + 1)
  }, [tab, setTab])

  const takeCommentFocus = useCallback(() => {
    const want = wantCommentFocus.current
    wantCommentFocus.current = false
    return want
  }, [])

  const page: IdeaPageContextValue = {
    ideaKey,
    idea,
    project,
    me,
    ownEvaluator,
    archived,
    guest,
    researchStep,
    statusLabel,
    openDialog,
    openEvaluate,
    focusComment,
    takeCommentFocus,
    commentFocusRequest,
    setTab,
    tab,
  }

  useIdeaCommands(page)
  const submittedIds = submittedEvaluatorIds(idea.evaluators)
  useAiCommands(ideaKey, setTab, submittedIds, !guest)

  const volunteer = useVolunteerAsOwner(ideaKey)
  const setClosed = useSetEvaluationClosed(ideaKey)
  const createProposal = useCreateProposal(ideaKey)
  const changeStatus = useChangeIdeaStatus(ideaKey)
  // Shortlisted or in Proposal (or in Research before the proposal), the owner's next step
  // is the proposal: ask whether one exists (the Proposal tab's own query, so it's shared)
  // to say Start or Open.
  const proposalStage =
    idea.status === 'shortlisted' ||
    idea.status === 'proposal' ||
    (idea.status === 'research' && researchStep === 'before_proposal')
  const proposalView = useQuery({
    ...proposalQueryOptions(ideaKey),
    enabled: proposalStage && idea.permissions.can_change_status,
  })
  const proposalState = proposalView.data && {
    exists: proposalView.data.proposal !== null,
    canCreate: proposalView.data.permissions.can_create,
  }
  // On the Proposal tab the editor (or its Start button) is the primary action.
  const statusAction = primaryAction(idea, me.id, proposalState, researchStep)
  const action =
    tab === 'proposal' &&
    (statusAction?.kind === 'open-proposal' || statusAction?.kind === 'start-proposal')
      ? null
      : statusAction
  const typing = useTyping()
  const runPrimary = (kind: PrimaryAction['kind']) => {
    if (kind === 'evaluate') openEvaluate()
    else if (kind === 'assign-owner') openDialog('owner')
    else if (kind === 'volunteer') volunteer.mutate({})
    else if (kind === 'invite') openDialog('invite')
    else if (kind === 'close-evaluation') setClosed.mutate({ closed: true })
    else if (kind === 'open-proposal') setTab('proposal')
    // Phase 8b: who does the research and by when, then the move (lead decision on S3).
    else if (kind === 'start-research') openDialog('start-research')
    else if (kind === 'start-evaluation') {
      // Evaluation needs evaluators: invite them, and the invite moves the idea on (p7).
      if (idea.evaluator_progress.total === 0 && idea.permissions.can_invite_evaluators) {
        openDialog('invite')
      } else changeStatus.mutate({ status: 'evaluating' })
    } else if (kind === 'finish-research') {
      requestResearchFocus(ideaKey)
      setTab('overview')
    } else if (kind === 'start-proposal') {
      setTab('proposal')
      createProposal.mutate(undefined, {
        // Start writing in Summary, as the Proposal tab's own Start does.
        onSuccess: () =>
          focusWhenRendered(
            () =>
              document.querySelector<HTMLElement>(
                '[data-testid="proposal-editor"] textarea[data-section-text]',
              ),
            { force: true },
          ),
      })
    } else openDialog('status')
  }
  const primaryShortcut =
    action?.kind === 'evaluate'
      ? SHORTCUTS.evaluate.keys
      : action?.kind === 'change-status'
        ? SHORTCUTS.changeStatus.keys
        : action?.kind === 'assign-owner'
          ? SHORTCUTS.assignOwner.keys
          : action?.kind === 'open-proposal'
            ? SHORTCUTS.proposalTab.keys
            : undefined

  const primaryButton = (className?: string) =>
    action && (
      <Button
        variant="primary"
        data-primary-action=""
        aria-keyshortcuts={primaryShortcut ? ariaKeys(primaryShortcut) : undefined}
        className={className}
        loading={
          (action.kind === 'start-proposal' && createProposal.isPending) ||
          (action.kind === 'start-evaluation' && changeStatus.isPending)
        }
        onClick={() => runPrimary(action.kind)}
      >
        {action.label}
        {primaryShortcut && <ButtonShortcut keys={primaryShortcut} />}
      </Button>
    )

  const { submitted, total } = idea.evaluator_progress
  const pendingSuggestions = usePendingSuggestionCount(
    ideaKey,
    idea,
    me.id,
    project?.permissions.can_manage,
    proposalStage,
  )

  return (
    <IdeaPageProvider value={page}>
      <div
        // One width for every tab (the proposal editor needs the room: outline, text and
        // margin comments), so the header doesn't jump when switching (UX review m7).
        className="mx-auto flex w-full max-w-7xl flex-col px-4 pt-5 pb-28 sm:px-6 sm:pb-12 lg:px-10 lg:pt-8"
      >
        {archived && (
          <p className="mb-5 flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2.5 text-sm text-secondary">
            <Archive aria-hidden="true" className="size-4 shrink-0 text-muted" />
            This project is archived, so its ideas are read-only.
          </p>
        )}
        <HeldIdeaBanner idea={idea} ideaKey={ideaKey} />
        {guest && (
          <p className="mb-5 flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2.5 text-sm text-secondary">
            <FileSearch aria-hidden="true" className="size-4 shrink-0 text-muted" />
            You can see this idea because you’re researching it.
          </p>
        )}
        <div
          className={cn(
            'grid gap-x-10 gap-y-6',
            !wide && 'lg:grid-cols-[minmax(0,1fr)_18rem] xl:gap-x-14',
          )}
        >
          <div className="flex min-w-0 flex-col gap-5">
            <IdeaHeader
              primary={primaryButton()}
              ai={
                guest ? undefined : (
                  <AiMenu ideaKey={ideaKey} setTab={setTab} submittedIds={submittedIds} />
                )
              }
            />
            <MobileSummary onOpenDetails={() => setDetailsOpen(true)} always={wide} />
            {guest ? (
              <div className="flex flex-col gap-10">
                <DescriptionSection />
                <ResearchPanel />
                <ActivitySection />
              </div>
            ) : (
              <Tabs value={tab} onValueChange={(value) => setTab(value as IdeaTab)}>
                <TabsList aria-label="Idea sections">
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="evaluations">
                    Evaluations
                    {total > 0 && (
                      <>
                        <CountBadge aria-hidden="true">
                          {submitted}/{total}
                        </CountBadge>
                        <span className="sr-only">
                          , {submitted} of {total} submitted
                        </span>
                      </>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="proposal">
                    Proposal
                    {pendingSuggestions > 0 && (
                      <>
                        <CountBadge aria-hidden="true">{pendingSuggestions}</CountBadge>
                        <span className="sr-only">
                          , {pendingSuggestions}{' '}
                          {pendingSuggestions === 1 ? 'suggestion' : 'suggestions'} to decide on
                        </span>
                      </>
                    )}
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="overview" className="flex flex-col gap-10">
                  <DescriptionSection />
                  <ResearchPanel />
                  <AiRunsSection />
                  <ActivitySection />
                </TabsContent>
                <TabsContent value="evaluations">
                  <EvaluationsTab />
                </TabsContent>
                <TabsContent value="proposal">
                  <ProposalTab />
                </TabsContent>
              </Tabs>
            )}
          </div>
          {!wide && (
            <aside aria-label="Idea details" className="hidden lg:block">
              <IdeaProperties className="lg:border-l lg:border-subtle lg:pl-6" />
            </aside>
          )}
        </div>
      </div>

      {action && !typing && (
        // Phones: the primary action stays within thumb reach, and steps aside while
        // you type (a comment, the proposal) so the keyboard and the text get the room.
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-subtle bg-surface px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:hidden">
          {primaryButton('h-11 w-full text-base')}
        </div>
      )}

      <Sheet open={detailsOpen} onOpenChange={setDetailsOpen}>
        <SheetContent
          size="sm"
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // Focus the sheet itself so no control's tooltip pops up on open.
            event.preventDefault()
            ;(event.currentTarget as HTMLElement | null)?.focus()
          }}
          onCloseAutoFocus={(event) => {
            if (!handingOff.current) return
            handingOff.current = false
            event.preventDefault()
          }}
        >
          <SheetHeader>
            <SheetTitle>Details</SheetTitle>
          </SheetHeader>
          <SheetBody>
            <IdeaProperties />
          </SheetBody>
        </SheetContent>
      </Sheet>

      <StatusDialog open={dialog === 'status'} onOpenChange={(open) => !open && setDialog(null)} />
      <OwnerDialog open={dialog === 'owner'} onOpenChange={(open) => !open && setDialog(null)} />
      <InviteDialog open={dialog === 'invite'} onOpenChange={(open) => !open && setDialog(null)} />
      <DeleteIdeaDialog
        open={dialog === 'delete'}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      <ResearchAssignmentDialog
        mode={dialog === 'start-research' ? 'start' : 'change'}
        open={dialog === 'researcher' || dialog === 'start-research'}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      <HandBackDialog
        open={dialog === 'hand-back'}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      {ownEvaluator && (
        <EvaluateSheet
          open={evaluateOpen}
          onOpenChange={(open) => setSearch({ evaluate: open ? true : undefined })}
        />
      )}
    </IdeaPageProvider>
  )
}

/**
 * Below `lg` the sidebar folds into one line (status · owner · evaluators ·
 * due · score) and a Details sheet with every control.
 */
function MobileSummary({
  onOpenDetails,
  always = false,
}: {
  onOpenDetails: () => void
  /** Also on wide screens (the Proposal tab hides the sidebar). */
  always?: boolean
}) {
  const { idea } = useIdeaPage()
  const { submitted, total } = idea.evaluator_progress
  return (
    // The facts wrap among themselves; Details keeps its place at the end of the first
    // line, never on a line of its own (UX review p5).
    <div className={cn('flex items-start gap-3 text-sm', !always && 'lg:hidden')}>
      <div className="flex min-h-9 min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2 sm:min-h-8">
        <StatusBadge status={idea.status} resolution={idea.resolution} label={idea.status_label} />
        {idea.owner ? (
          <span className="flex min-w-0 items-center gap-1.5 text-secondary">
            <Avatar
              name={idea.owner.display_name}
              src={idea.owner.avatar_url}
              size="xs"
              decorative
            />
            <span className="truncate">{idea.owner.display_name}</span>
          </span>
        ) : (
          <span className="text-muted">No owner</span>
        )}
        {total > 0 && (
          <span className="text-muted tabular-nums">
            {submitted}/{total} evaluated
          </span>
        )}
        {submitted < total && idea.evaluation_open && (
          <DueDateLabel value={idea.evaluation_due_at} hideWhenNone />
        )}
        {total > 0 && (
          // "2/3 evaluated" sits beside it, so no "· 2" count on the chip.
          <ScoreBadge score={idea.score?.overall ?? null} hidden={idea.score_hidden} size="sm" />
        )}
      </div>
      <Button variant="outline" size="sm" className="shrink-0 max-sm:h-9" onClick={onOpenDetails}>
        Details
        <ChevronRight />
      </Button>
    </div>
  )
}

/** While the idea loads: its title and status from any list cache, skeletons for the rest. */
function IdeaPageLoading({ summary }: { summary: IdeaSummary | undefined }) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col px-4 pt-5 sm:px-6 lg:px-10 lg:pt-8">
      {summary ? (
        <SkeletonGroup
          label="Loading idea"
          className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_18rem]"
        >
          <div className="flex min-w-0 flex-col gap-5">
            <div className="flex flex-col gap-2">
              <p className="flex min-h-8 items-center text-sm font-medium text-secondary tabular-nums">
                {summary.key}
              </p>
              <h1 className="text-2xl font-semibold text-primary">{summary.title}</h1>
              <p className="text-lg text-secondary">{summary.summary}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusBadge
                status={summary.status}
                resolution={summary.resolution}
                label={summary.status_label}
              />
            </div>
            <div className="flex gap-4 border-b pb-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-16" />
            </div>
            <div className="flex flex-col gap-2.5">
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-11/12" />
              <Skeleton className="h-3.5 w-4/5" />
            </div>
          </div>
          <div className="hidden flex-col gap-5 border-l border-subtle pl-6 lg:flex">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-6 w-32" />
              </div>
            ))}
          </div>
        </SkeletonGroup>
      ) : (
        <IdeaPageSkeleton />
      )}
    </div>
  )
}

function IdeaLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <EmptyState
      role="alert"
      icon={<CloudOff />}
      title="We couldn’t load this idea"
      description="Check your connection and try again."
      action={
        <Button variant="primary" onClick={onRetry}>
          Try again
        </Button>
      }
    />
  )
}

/**
 * Pending proposal suggestions for whoever decides on them (contract-phase5
 * §3.4: the owner and admins, while the idea is Shortlisted or in Proposal), for
 * the Proposal tab's count: an assistant's suggestion shouldn't sit unseen.
 * Asked only of people who may decide; 0 for everyone else, and while the idea
 * has no proposal (the list is 404 then).
 */
function usePendingSuggestionCount(
  ideaKey: string,
  idea: IdeaDetail,
  meId: string,
  managesProject: boolean | undefined,
  /** Shortlisted, in Proposal, or (Phase 8) in Research before the proposal (c7). */
  open: boolean,
): number {
  const mayDecide = open && (idea.owner?.id === meId || managesProject === true)
  const suggestions = useProposalSuggestions(ideaKey, { enabled: mayDecide })
  const data = suggestions.data
  return mayDecide && data?.permissions.can_decide ? data.items.length : 0
}
