import {
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  Download,
  FileText,
  Gavel,
  Lock,
  MoreHorizontal,
  Pencil,
  RotateCcw,
  Sparkles,
  Trash2,
  Users,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'

import {
  useBids,
  useChangeBidCallStatus,
  useExportBidReport,
  useRequestAiBidAssessments,
} from '@/api/bids'
import { describeError } from '@/api/errors'
import type { BidCallView } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { toast } from '@/components/ui/toaster'
import { BLOCKED_COPY } from '@/features/ai/ai-copy'
import { useIdeaPage } from '@/features/idea/idea-context'
import { formatDate } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'

import { AwardDialog } from './award-dialog'
import { AssessorsDialog } from './assessors-dialog'
import { CALL_STATUS, progressText } from './bid-copy'
import { useCallZone } from './call-dates'
import {
  CallSettingsDialog,
  CancelCallDialog,
  DeleteCallDialog,
  MoveCallDialog,
} from './call-dialogs'
import { TemplateCopySheet } from './template-copy-sheet'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

export type HeaderDialog =
  | 'settings'
  | 'template'
  | 'assessors'
  | 'open'
  | 'assessing'
  | 'reopen'
  | 'award'
  | 'cancel'
  | 'delete'

/**
 * The call's header: title, status and the facts (deadline, bids, progress, due date,
 * the AI assessor), the one next step for call managers (Open the call, Close to new
 * bids, Award) and the rest in a menu.
 */
/** The header's one next step (focus goes there after the call moves: UX review m1). */
export const CALL_PRIMARY_ID = 'bid-call-primary'

const focusPrimary = () =>
  focusWhenRendered(
    () => document.getElementById(CALL_PRIMARY_ID) ?? document.getElementById('bid-call-title'),
    { force: true },
  )

export function CallHeader({ view }: { view: CallWithView }) {
  const { ideaKey, idea, project, me, openDialog, setSearch } = useIdeaPage()
  const { call, permissions } = view
  const status = CALL_STATUS[call.status]
  const [dialog, setDialog] = useState<HeaderDialog | null>(null)
  const [settingsReason, setSettingsReason] = useState<string | undefined>()
  const move = useChangeBidCallStatus(ideaKey)
  const exportReport = useExportBidReport(ideaKey)
  const assessAll = useRequestAiBidAssessments(ideaKey)
  const manage = permissions.can_manage_call
  const locked = call.template.locked
  // Assessments you still owe here (a manager who assesses too: UX review m2).
  const owed = call.template.sections.reduce((sum, section) => {
    const mine = section.assessors.find((a) => a.user.id === me.id)
    return mine ? sum + Math.max(0, mine.progress.total - mine.progress.submitted) : sum
  }, 0)
  const bids = useBids(ideaKey, { enabled: permissions.can_assess && owed > 0 })
  const nextAssessment = (bids.data?.items ?? [])
    .filter((bid) => bid.status !== 'rejected')
    .flatMap((bid) => bid.my_sections.map((section) => ({ bid, section })))
    .find((row) => row.section.state !== 'submitted')
  const assessFirst = call.status === 'assessing' && permissions.can_assess && owed > 0
  const close = (open: boolean) => !open && setDialog(null)
  const zone = useCallZone()

  const runMove = (to: 'open' | 'assessing') =>
    move.mutate(to, {
      onSuccess: () => {
        setDialog(null)
        toast.success(
          to === 'assessing'
            ? 'Closed to new bids: the assessors can start'
            : call.status === 'assessing'
              ? 'Reopened to new bids'
              : 'The call is open to bids',
        )
        focusPrimary()
      },
      onError: () => setDialog(null),
    })

  const download = (format: 'markdown' | 'pdf') =>
    exportReport.mutate(format, {
      onError: (error) => {
        const { title, description } = describeError(error)
        toast.error(title, {
          description,
          action: { label: 'Retry', onClick: () => download(format) },
        })
      },
    })

  const primary = (() => {
    if (assessFirst && nextAssessment) {
      // You owe assessments: your next one comes first; Award waits in the menu.
      return (
        <Button
          id={CALL_PRIMARY_ID}
          variant="primary"
          onClick={() =>
            setSearch?.({
              tab: 'bids',
              bid: nextAssessment.bid.id,
              assess: nextAssessment.section.section.id,
            })
          }
        >
          Assess ({owed})
        </Button>
      )
    }
    if (!manage && !permissions.can_view_scores) return null
    if (manage && call.status === 'draft') {
      return (
        <Button
          id={CALL_PRIMARY_ID}
          variant="primary"
          onClick={() => {
            if (!call.deadline_at) {
              setSettingsReason('Set a deadline for bids to open the call.')
              setDialog('settings')
            } else setDialog('open')
          }}
        >
          Open the call
        </Button>
      )
    }
    if (manage && call.status === 'open') {
      return (
        <Button id={CALL_PRIMARY_ID} variant="primary" onClick={() => setDialog('assessing')}>
          Close to new bids
        </Button>
      )
    }
    if (call.status === 'assessing' && permissions.can_decide) {
      return (
        <Button id={CALL_PRIMARY_ID} variant="primary" onClick={() => setDialog('award')}>
          Award…
        </Button>
      )
    }
    if (call.status === 'awarded' && permissions.can_view_scores && call.bid_count > 0) {
      // Awarded: the report is what is left to do (UX review m7).
      return (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button id={CALL_PRIMARY_ID} variant="outline" loading={exportReport.isPending}>
              <Download /> Export the report
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => download('pdf')}>PDF</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => download('markdown')}>Markdown</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )
    }
    return null
  })()

  const facts = [
    call.deadline_at
      ? `Deadline ${zone.format(call.deadline_at)}${zone.suffix}`
      : 'No deadline yet',
    `${call.bid_count} ${call.bid_count === 1 ? 'bid' : 'bids'}`,
    call.status === 'assessing' || call.status === 'awarded' ? progressText(call.progress) : null,
    call.assessment_due_at && call.status !== 'awarded' && call.status !== 'cancelled'
      ? `Assessments due ${zone.format(call.assessment_due_at)}${zone.suffix}`
      : null,
  ].filter(Boolean)

  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2
              id="bid-call-title"
              tabIndex={-1}
              className="text-xl font-semibold text-pretty text-primary outline-none"
            >
              {call.title}
            </h2>
            <Badge variant={status.tone}>{status.label}</Badge>
          </div>
          <p className="text-sm text-secondary">{facts.join(' · ')}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {primary}
          {(manage || permissions.can_view_scores || permissions.can_delete_call) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="More for this call">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                {manage && (
                  <>
                    <DropdownMenuItem onSelect={() => setDialog('settings')}>
                      <Pencil /> Call details…
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setDialog('assessors')}>
                      <Users /> Assessors and due date…
                    </DropdownMenuItem>
                    {permissions.can_edit_template && (
                      <DropdownMenuItem onSelect={() => setDialog('template')}>
                        <FileText /> Evaluation template…
                      </DropdownMenuItem>
                    )}
                    {call.status === 'assessing' && !locked && (
                      <DropdownMenuItem onSelect={() => setDialog('reopen')}>
                        <RotateCcw /> Reopen to new bids…
                      </DropdownMenuItem>
                    )}
                  </>
                )}
                {manage && view.ai_agents.length > 0 && (
                  <DropdownMenuItem
                    disabled={!permissions.can_request_ai}
                    onSelect={() => {
                      const agent = view.ai_agents[0]
                      if (!agent) return
                      assessAll.mutate(agent.id, {
                        onSuccess: (batch) =>
                          toast.success(
                            batch.created > 0
                              ? `Asked ${agent.display_name} to assess ${batch.created} ${batch.created === 1 ? 'bid' : 'bids'}`
                              : 'Every bid is being assessed already',
                            batch.skipped > 0
                              ? {
                                  description: `${batch.skipped} more wait: you can ask AI agents 20 times an hour.`,
                                }
                              : undefined,
                          ),
                      })
                    }}
                  >
                    <Sparkles /> Assess all with AI
                    {!permissions.can_request_ai && permissions.request_ai_blocked_by && (
                      <span className="sr-only">
                        : {BLOCKED_COPY[permissions.request_ai_blocked_by]}
                      </span>
                    )}
                  </DropdownMenuItem>
                )}
                {assessFirst && nextAssessment && permissions.can_decide && (
                  <DropdownMenuItem onSelect={() => setDialog('award')}>
                    <Gavel /> Award…
                  </DropdownMenuItem>
                )}
                {permissions.can_view_scores && call.bid_count > 0 && call.status !== 'awarded' && (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <Download /> Export the report
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuItem onSelect={() => download('pdf')}>PDF</DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => download('markdown')}>
                        Markdown
                      </DropdownMenuItem>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                )}
                {(permissions.can_decide || permissions.can_delete_call) && (
                  <DropdownMenuSeparator />
                )}
                {permissions.can_decide && (
                  <DropdownMenuItem onSelect={() => setDialog('cancel')}>
                    <XCircle /> Cancel the call…
                  </DropdownMenuItem>
                )}
                {permissions.can_delete_call && (
                  <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}>
                    <Trash2 /> Delete the call…
                  </DropdownMenuItem>
                )}
                {!manage &&
                  permissions.can_view_scores &&
                  !permissions.can_delete_call &&
                  call.bid_count === 0 && (
                    <DropdownMenuLabel className="font-normal text-muted">
                      Nothing to do here
                    </DropdownMenuLabel>
                  )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
      {call.description && (
        <p className="max-w-3xl text-sm whitespace-pre-line text-secondary">{call.description}</p>
      )}
      {manage && call.status === 'draft' && (
        <DraftChecklist
          view={view}
          deadline={call.deadline_at ? `${zone.format(call.deadline_at)}${zone.suffix}` : null}
          onTemplate={() => setDialog('template')}
          onAssessors={() => setDialog('assessors')}
          onDeadline={() => setDialog('settings')}
        />
      )}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
        {call.ai_assessor && (
          <span className="flex items-center gap-1.5">
            <AiBadge /> {call.ai_assessor.display_name} pre-checks each bid
          </span>
        )}
        {locked && manage && (
          <span className="flex items-center gap-1.5">
            <Lock aria-hidden="true" className="size-3.5 shrink-0" />
            The evaluation template is locked: assessments have been submitted.
          </span>
        )}
        {call.status === 'awarded' && call.awarded_bid && (
          <span className="flex items-center gap-1.5 text-secondary">
            <CalendarClock aria-hidden="true" className="size-3.5 shrink-0" />
            Awarded to {call.awarded_bid.bidder}
            {call.awarded_at && ` on ${formatDate(call.awarded_at)}`}
            {call.award_reason && `: ${call.award_reason}`}
          </span>
        )}
        {call.status === 'awarded' &&
          idea.status === 'proposal' &&
          idea.permissions.can_change_status && (
            <span className="flex items-center gap-1.5">
              Next: when the work is under way, close the idea as accepted.
              <Button
                size="sm"
                variant="link"
                className="h-auto p-0"
                onClick={() => openDialog('status')}
              >
                Change status…
              </Button>
            </span>
          )}
        {call.status === 'cancelled' && (
          <span className="flex items-center gap-1.5">
            Cancelled{call.cancelled_at && ` on ${formatDate(call.cancelled_at)}`}
            {call.cancel_reason && `: ${call.cancel_reason}`}
          </span>
        )}
      </div>

      <CallSettingsDialog
        key={`${call.id}-${dialog === 'settings' ? 'open' : 'closed'}`}
        ideaKey={ideaKey}
        call={call}
        agents={view.ai_agents}
        open={dialog === 'settings'}
        reason={settingsReason}
        // Opened by "Open the call" for its deadline: saving opens it too (UX review m4).
        onSaved={settingsReason ? () => runMove('open') : undefined}
        onOpenChange={(open) => {
          if (!open) setSettingsReason(undefined)
          close(open)
        }}
      />
      <AssessorsDialog
        ideaKey={ideaKey}
        projectSlug={idea.project.slug}
        visibility={project?.visibility}
        call={call}
        meId={me.id}
        open={dialog === 'assessors'}
        onOpenChange={close}
      />
      <TemplateCopySheet
        ideaKey={ideaKey}
        call={call}
        open={dialog === 'template'}
        onOpenChange={close}
      />
      {(dialog === 'open' || dialog === 'assessing' || dialog === 'reopen') && (
        <MoveCallDialog
          move={dialog}
          open
          pending={move.isPending}
          onOpenChange={close}
          onConfirm={() => runMove(dialog === 'assessing' ? 'assessing' : 'open')}
        />
      )}
      <AwardDialog
        view={view}
        open={dialog === 'award'}
        onOpenChange={close}
        onAwarded={focusPrimary}
      />
      <CancelCallDialog ideaKey={ideaKey} open={dialog === 'cancel'} onOpenChange={close} />
      <DeleteCallDialog
        ideaKey={ideaKey}
        call={call}
        open={dialog === 'delete'}
        onOpenChange={close}
      />
    </header>
  )
}

/**
 * A draft's setup at a glance, right under the header (UX review m3): the template to
 * review, who assesses each section, the deadline; then the header's "Open the call".
 */
function DraftChecklist({
  view,
  deadline,
  onTemplate,
  onAssessors,
  onDeadline,
}: {
  view: CallWithView
  deadline: string | null
  onTemplate: () => void
  onAssessors: () => void
  onDeadline: () => void
}) {
  const sections = view.call.template.sections
  const staffed = sections.filter((s) => s.assessors.length > 0).length
  const steps = [
    {
      key: 'template',
      done: null,
      text: `Evaluation template: ${sections.length} ${sections.length === 1 ? 'section' : 'sections'}, ${view.call.template.must_haves.length} ${view.call.template.must_haves.length === 1 ? 'must-have' : 'must-haves'}`,
      action: view.permissions.can_edit_template ? 'Review…' : null,
      onClick: onTemplate,
    },
    {
      key: 'assessors',
      done: staffed === sections.length,
      text:
        staffed === sections.length
          ? 'Assessors for every section'
          : `Assessors for ${staffed} of ${sections.length} sections`,
      action: 'Assessors…',
      onClick: onAssessors,
    },
    {
      key: 'deadline',
      done: deadline !== null,
      text: deadline ? `Deadline ${deadline}` : 'No deadline yet: needed to open the call',
      action: deadline ? 'Change…' : 'Set the deadline…',
      onClick: onDeadline,
    },
  ]
  return (
    <ol
      aria-label="Before you open the call"
      className="flex flex-col divide-y divide-subtle rounded-lg border bg-surface text-sm sm:max-w-2xl"
    >
      {steps.map((step) => (
        <li key={step.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
          {step.done === true ? (
            <CheckCircle2 aria-hidden="true" className="size-4 shrink-0 text-success" />
          ) : step.done === false ? (
            <CircleDashed aria-hidden="true" className="size-4 shrink-0 text-muted" />
          ) : (
            <FileText aria-hidden="true" className="size-4 shrink-0 text-muted" />
          )}
          <span className="min-w-0 flex-1 text-secondary">
            {step.text}
            {step.done === true && <span className="sr-only"> (done)</span>}
          </span>
          {step.action && (
            <Button size="sm" variant="ghost" onClick={step.onClick}>
              {step.action}
            </Button>
          )}
        </li>
      ))}
    </ol>
  )
}
