import { ExternalLink } from 'lucide-react'
import { useId } from 'react'

import type { Citation } from '@/api/types'
import { safeWebUrl, urlHost } from '@/components/ui/markdown'
import { cn } from '@/lib/utils'
import { visibleText } from '@/lib/visible-text'

export const SOURCES_LABEL = 'Cited by AI, not checked'

/**
 * The sources an AI agent cited (contract-phase6 §3.7, §3.8): plain links that
 * open in a new tab without a referrer or ranking credit, each with its host
 * (ASCII, so a look-alike name can't pass for another site), under "Cited by
 * AI, not checked": an agent without a web tool may invent them. Only http and
 * https URLs are links; anything else shows its title as text.
 */
export function SourceList({
  sources,
  numbered = false,
  compact = false,
  className,
}: {
  sources: readonly Citation[]
  /** Research notes cite them as [1], [2]…: number the list. */
  numbered?: boolean
  /**
   * One wrapping line labelled "Sources" (an evaluation's criteria: the card says
   * once that they are cited by AI and not checked; assistive tech hears it each time).
   */
  compact?: boolean
  className?: string
}) {
  const labelId = useId()
  if (sources.length === 0) return null
  if (compact) {
    return (
      <div className={cn('flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm', className)}>
        <span aria-hidden="true" className="text-xs font-medium text-muted">
          Sources
        </span>
        <ul
          aria-label="Sources cited by AI, not checked"
          className="flex min-w-0 flex-wrap gap-x-3 gap-y-1"
        >
          {sources.map((source, index) => (
            <li key={`${source.url}-${index}`} className="min-w-0">
              <SourceLink source={source} />
            </li>
          ))}
        </ul>
      </div>
    )
  }
  const List = numbered ? 'ol' : 'ul'
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <p id={labelId} className="text-xs font-medium text-muted">
        {SOURCES_LABEL}
      </p>
      <List
        aria-labelledby={labelId}
        className={cn(
          'flex flex-col gap-1 text-sm',
          numbered && 'list-decimal pl-5 marker:text-muted marker:tabular-nums',
        )}
      >
        {sources.map((source, index) => (
          <li key={`${source.url}-${index}`} className={cn('min-w-0', numbered && 'pl-1')}>
            <SourceLink source={source} />
          </li>
        ))}
      </List>
    </div>
  )
}

function SourceLink({ source }: { source: Citation }) {
  const href = safeWebUrl(source.url)
  // The browser's reading of the URL (punycode), not a host the agent wrote.
  const host = href ? urlHost(href) : null
  // An agent wrote the title: nothing invisible, and isolated so it can't turn the host.
  const title = visibleText(source.title)
  if (!href || !host) {
    return (
      <span className="[overflow-wrap:anywhere] text-secondary">
        <bdi>{title}</bdi>
      </span>
    )
  }
  return (
    <span className="inline [overflow-wrap:anywhere]">
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="font-medium text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent"
      >
        <bdi>{title}</bdi>
        <ExternalLink aria-hidden="true" className="ml-1 inline size-3 align-baseline" />
        <span className="sr-only"> (opens in a new tab)</span>
      </a>{' '}
      <bdi dir="ltr" className="text-xs text-muted">
        {host}
      </bdi>
    </span>
  )
}
