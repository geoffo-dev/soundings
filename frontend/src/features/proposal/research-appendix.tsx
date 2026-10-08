import { useId } from 'react'

import { useIdeaResearch } from '@/api/research'
import { formatDate } from '@/lib/dates'

/**
 * "Research and consultation" (contract-phase8 §3.8): after the template's sections,
 * while the project's research step is on, each answered checklist item as the
 * exports print it (plain text, who answered and when). Nothing while no item has an
 * answer; editing the answers happens on the idea's Research panel.
 */
export function ResearchAppendix({ ideaKey }: { ideaKey: string }) {
  const answered = useAnsweredResearch(ideaKey)
  const headingId = useId()
  if (!answered) return null
  return (
    <section
      id={RESEARCH_APPENDIX_ID}
      aria-labelledby={headingId}
      // The sections' grid, so the appendix keeps to the text column (the margin is empty).
      className="grid scroll-mt-16 gap-x-8 border-t border-subtle py-7 lg:grid-cols-[minmax(0,1fr)_17rem] lg:py-8"
    >
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2
            id={headingId}
            data-appendix-heading=""
            tabIndex={-1}
            className="rounded-sm text-lg font-semibold text-primary"
          >
            Research and consultation
          </h2>
          <p className="text-sm text-muted">
            From the idea’s research checklist; the exports end with it too.
          </p>
        </div>
        <dl className="flex flex-col gap-4">
          {answered.map((item) => {
            const answer = item.answer
            if (!answer) return null
            const edited = answer.updated_at !== answer.answered_at
            return (
              <div key={item.item_id} className="flex flex-col gap-1">
                <dt className="text-base font-medium text-primary">{item.title}</dt>
                <dd className="flex flex-col gap-1">
                  <p className="text-base break-words whitespace-pre-wrap text-secondary">
                    {answer.answer}
                  </p>
                  <p className="text-xs text-muted">
                    Answered by {answer.answered_by?.display_name ?? 'someone'} on{' '}
                    {formatDate(answer.answered_at)}
                    {edited &&
                      `, updated by ${answer.updated_by?.display_name ?? 'someone'} on ${formatDate(answer.updated_at)}`}
                  </p>
                </dd>
              </div>
            )
          })}
        </dl>
      </div>
    </section>
  )
}

/** The appendix's element id (the outline links to it). */
export const RESEARCH_APPENDIX_ID = 'proposal-research-appendix'

/** The answered checklist items the appendix lists, or null when it isn't shown. */
export function useAnsweredResearch(ideaKey: string) {
  const data = useIdeaResearch(ideaKey).data
  if (!data || data.step === 'off') return null
  const answered = data.items.filter((item) => item.answer !== null)
  return answered.length > 0 ? answered : null
}

/** Moves to the appendix (the outline's last link): scrolled into view, its heading focused. */
export function focusResearchAppendix() {
  const appendix = document.getElementById(RESEARCH_APPENDIX_ID)
  if (!appendix) return
  appendix.scrollIntoView({ block: 'start', behavior: 'smooth' })
  appendix.querySelector<HTMLElement>('[data-appendix-heading]')?.focus({ preventScroll: true })
}
