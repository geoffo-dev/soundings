import { FileText, TriangleAlert, Users } from 'lucide-react'
import { useState } from 'react'

import type { BidCallView } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useIdeaPage } from '@/features/idea/idea-context'

import { AssessorsDialog } from './assessors-dialog'
import { MUST_HAVE_KIND_LABELS, QUESTION_TYPE_LABELS } from './bid-template'
import { TemplateCopySheet } from './template-copy-sheet'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

/**
 * How bids are evaluated in this call: each section with its weight, questions and
 * assessors (with their progress), and the must-haves. Call managers change the
 * template (until it locks) and the assessors from here.
 */
export function EvaluationPanel({ view }: { view: CallWithView }) {
  const { ideaKey, idea, project, me } = useIdeaPage()
  const { call, permissions } = view
  const [dialog, setDialog] = useState<'template' | 'assessors' | null>(null)
  const assessing = call.status === 'assessing' || call.status === 'awarded'

  return (
    <section aria-labelledby="evaluation-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="evaluation-heading" className="text-lg font-semibold text-primary">
          Evaluation
        </h2>
        {permissions.can_manage_call && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={() => setDialog('assessors')}>
              <Users /> Assessors
            </Button>
            {permissions.can_edit_template && (
              <Button size="sm" variant="ghost" onClick={() => setDialog('template')}>
                <FileText /> Edit template
              </Button>
            )}
          </div>
        )}
      </div>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Sections">
        {call.template.sections.map((section) => (
          // Four rows shared across the cards (subgrid), so each card's questions and
          // assessors start on the same line as its neighbours' (P10-QA-N7).
          <li
            key={section.id}
            className="row-span-4 grid grid-rows-subgrid gap-3 rounded-lg border bg-surface p-4"
          >
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-semibold text-primary">{section.title}</h3>
              <span className="text-sm text-muted tabular-nums">{section.weight}%</span>
            </div>
            {section.guidance ? (
              <p className="text-sm text-muted">{section.guidance}</p>
            ) : (
              <span aria-hidden="true" />
            )}
            <ul className="flex flex-col gap-1 text-sm">
              {section.questions.map((q) => (
                <li key={q.id} className="flex items-baseline justify-between gap-3">
                  <span className="text-secondary">{q.text}</span>
                  <span className="shrink-0 text-xs text-muted">
                    {q.type === 'score'
                      ? `× ${q.weight}`
                      : q.type === 'price'
                        ? 'From the price'
                        : QUESTION_TYPE_LABELS[q.type]}
                  </span>
                </li>
              ))}
            </ul>
            <div className="flex flex-col gap-1.5 border-t border-subtle pt-3">
              <span className="text-xs font-medium text-muted">Assessors</span>
              {section.assessors.length === 0 ? (
                <span className="text-sm text-muted">Nobody yet</span>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {section.assessors.map((assessor) => (
                    <li key={assessor.user.id} className="flex items-center gap-2 text-sm">
                      <Avatar
                        name={assessor.user.display_name}
                        src={assessor.user.avatar_url}
                        size="xs"
                        decorative
                      />
                      <span className="min-w-0 flex-1 truncate text-primary">
                        {assessor.user.display_name}
                        {assessor.user.id === me.id && <span className="text-muted"> (you)</span>}
                      </span>
                      {!assessor.can_assess ? (
                        <Badge variant="warning">
                          <TriangleAlert aria-hidden="true" /> Can’t assess now
                        </Badge>
                      ) : (
                        assessing && (
                          <span className="text-xs text-muted tabular-nums">
                            {assessor.progress.submitted}/{assessor.progress.total}
                          </span>
                        )
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ul>
      {call.template.must_haves.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-primary">Must-haves</h3>
          <ul className="flex flex-wrap gap-2">
            {call.template.must_haves.map((m) => (
              <li key={m.id} className="rounded-md border px-2.5 py-1 text-sm text-secondary">
                {m.text}
                <span className="text-xs text-muted">
                  {' '}
                  · {MUST_HAVE_KIND_LABELS[m.kind].toLowerCase()}
                  {m.pricing && ', pricing'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <AssessorsDialog
        ideaKey={ideaKey}
        projectSlug={idea.project.slug}
        visibility={project?.visibility}
        call={call}
        meId={me.id}
        open={dialog === 'assessors'}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      <TemplateCopySheet
        ideaKey={ideaKey}
        call={call}
        open={dialog === 'template'}
        onOpenChange={(open) => !open && setDialog(null)}
      />
    </section>
  )
}
