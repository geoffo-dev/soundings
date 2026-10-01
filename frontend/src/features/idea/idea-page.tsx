import { Link, useNavigate } from '@tanstack/react-router'
import { Archive, ChevronRight, CloudOff, SearchX } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { isApiError } from '@/api/errors'
import {
  useCachedIdeaSummary,
  useIdea,
  useSetEvaluationClosed,
  useVolunteerAsOwner,
} from '@/api/ideas'
import { useProject } from '@/api/projects'
import type { IdeaDetail, IdeaSummary } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { EmptyState } from '@/components/ui/empty-state'
import { ariaKeys, ButtonShortcut, KbdShortcut } from '@/components/ui/kbd'
import { ScoreBadge } from '@/components/ui/score-badge'
import { Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup, SkeletonIdeaPage } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status-badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCurrentUser } from '@/features/auth/current-user'
import { SHORTCUTS } from '@/lib/shortcuts'

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

  if (idea.data) {
    return <LoadedIdeaPage key={idea.data.id} idea={idea.data} ideaKey={ideaKey} search={search} />
  }
  if (idea.isError) {
    if (isApiError(idea.error) && (idea.error.status === 404 || idea.error.status === 422)) {
      return <IdeaNotFound />
    }
    return <IdeaLoadError onRetry={() => void idea.refetch()} />
  }
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
  const project = useProject(idea.project.slug).data
  const archived = Boolean(project?.archived_at)
  const tab: IdeaTab = search.tab ?? 'overview'
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

  // Only evaluators have a sheet: the param is ignored (and dropped) for everyone else.
  const evaluateOpen = Boolean(search.evaluate && ownEvaluator)
  useEffect(() => {
    if (search.evaluate && !ownEvaluator) setSearch({ evaluate: undefined })
  }, [search.evaluate, ownEvaluator, setSearch])

  const openEvaluate = useCallback(() => {
    if (ownEvaluator) setSearch({ evaluate: true })
  }, [ownEvaluator, setSearch])

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
    statusLabel,
    openDialog,
    openEvaluate,
    focusComment,
    takeCommentFocus,
    commentFocusRequest,
    setTab,
  }

  useIdeaCommands(page)

  const volunteer = useVolunteerAsOwner(ideaKey)
  const setClosed = useSetEvaluationClosed(ideaKey)
  const action = primaryAction(idea, me.id)
  const runPrimary = (kind: PrimaryAction['kind']) => {
    if (kind === 'evaluate') openEvaluate()
    else if (kind === 'assign-owner') openDialog('owner')
    else if (kind === 'volunteer') volunteer.mutate({})
    else if (kind === 'invite') openDialog('invite')
    else if (kind === 'close-evaluation') setClosed.mutate({ closed: true })
    else openDialog('status')
  }
  const primaryShortcut =
    action?.kind === 'evaluate'
      ? SHORTCUTS.evaluate.keys
      : action?.kind === 'change-status'
        ? SHORTCUTS.changeStatus.keys
        : action?.kind === 'assign-owner'
          ? SHORTCUTS.assignOwner.keys
          : undefined

  const primaryButton = (className?: string) =>
    action && (
      <Button
        variant="primary"
        data-primary-action=""
        aria-keyshortcuts={primaryShortcut ? ariaKeys(primaryShortcut) : undefined}
        className={className}
        onClick={() => runPrimary(action.kind)}
      >
        {action.label}
        {primaryShortcut && <ButtonShortcut keys={primaryShortcut} />}
      </Button>
    )

  const { submitted, total } = idea.evaluator_progress

  return (
    <IdeaPageProvider value={page}>
      <div className="mx-auto flex w-full max-w-6xl flex-col px-4 pt-5 pb-28 sm:px-6 sm:pb-12 lg:px-10 lg:pt-8">
        {archived && (
          <p className="mb-5 flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2.5 text-sm text-secondary">
            <Archive aria-hidden="true" className="size-4 shrink-0 text-muted" />
            This project is archived, so its ideas are read-only.
          </p>
        )}
        <div className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_18rem] xl:gap-x-14">
          <div className="flex min-w-0 flex-col gap-5">
            <IdeaHeader primary={primaryButton()} />
            <MobileSummary onOpenDetails={() => setDetailsOpen(true)} />
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
                <TabsTrigger value="proposal">Proposal</TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="flex flex-col gap-10">
                <DescriptionSection />
                <ActivitySection />
              </TabsContent>
              <TabsContent value="evaluations">
                <EvaluationsTab />
              </TabsContent>
              <TabsContent value="proposal">
                <ProposalTab />
              </TabsContent>
            </Tabs>
          </div>
          <aside aria-label="Idea details" className="hidden lg:block">
            <IdeaProperties className="lg:border-l lg:border-subtle lg:pl-6" />
          </aside>
        </div>
      </div>

      {action && (
        // Phones: the primary action stays within thumb reach.
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
function MobileSummary({ onOpenDetails }: { onOpenDetails: () => void }) {
  const { idea } = useIdeaPage()
  const { submitted, total } = idea.evaluator_progress
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm lg:hidden">
      <StatusBadge status={idea.status} resolution={idea.resolution} label={idea.status_label} />
      {idea.owner ? (
        <span className="flex min-w-0 items-center gap-1.5 text-secondary">
          <Avatar name={idea.owner.display_name} src={idea.owner.avatar_url} size="xs" decorative />
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
      <Button variant="outline" size="sm" className="ml-auto max-sm:h-9" onClick={onOpenDetails}>
        Details
        <ChevronRight />
      </Button>
    </div>
  )
}

/** While the idea loads: its title and status from any list cache, skeletons for the rest. */
function IdeaPageLoading({ summary }: { summary: IdeaSummary | undefined }) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col px-4 pt-5 sm:px-6 lg:px-10 lg:pt-8">
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

export function IdeaPageSkeleton() {
  return (
    <SkeletonGroup
      label="Loading idea"
      className="mx-auto w-full max-w-6xl px-4 pt-5 sm:px-6 lg:px-10 lg:pt-8"
    >
      <SkeletonIdeaPage className="lg:grid-cols-[minmax(0,1fr)_18rem]" />
    </SkeletonGroup>
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

/** Same text whether the idea doesn't exist or is hidden, to avoid leaking (wireframe 03). */
export function IdeaNotFound() {
  return (
    <EmptyState
      headingLevel={1}
      icon={<SearchX />}
      title="This idea doesn’t exist or you don’t have access"
      description={
        <>
          Check the link, or search for it with{' '}
          <KbdShortcut keys="mod+k" className="align-middle" />.
        </>
      }
      action={
        <Button asChild variant="primary">
          <Link to="/">Go to My work</Link>
        </Button>
      }
    />
  )
}
