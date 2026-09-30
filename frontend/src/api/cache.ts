/**
 * Helpers for optimistic updates: snapshot the affected queries, patch an
 * idea wherever it is cached (detail, list pages, board columns, My work),
 * and roll back if the request fails.
 *
 *   const rollback = await snapshot(queryClient, [queryKeys.ideas.all, queryKeys.work.all])
 *   patchIdea(queryClient, 'CUST-12', (idea) => ({ ...idea, has_voted: true }))
 *   // onError: rollback()
 */
import type { InfiniteData, QueryClient, QueryKey } from '@tanstack/react-query'

import { ideaCacheId, queryKeys } from '@/api/keys'
import type {
  Board,
  IdeaDetail,
  IdeaPage,
  IdeaStatus,
  IdeaSummary,
  Project,
  Resolution,
  StatusLabels,
  Work,
} from '@/api/types'

export type Rollback = () => void

/**
 * Cancels in-flight fetches for the given key prefixes (so they can't
 * overwrite the optimistic state) and returns a function that restores them.
 */
export async function snapshot(queryClient: QueryClient, prefixes: QueryKey[]): Promise<Rollback> {
  await Promise.all(prefixes.map((queryKey) => queryClient.cancelQueries({ queryKey })))
  const saved = prefixes.flatMap((queryKey) => queryClient.getQueriesData({ queryKey }))
  return () => {
    for (const [key, data] of saved) queryClient.setQueryData(key, data)
  }
}

type IdeaLike = IdeaSummary | IdeaDetail

/** Fields shared by IdeaSummary and IdeaDetail, so one updater can patch both. */
export type IdeaPatch = (idea: IdeaSummary) => Partial<IdeaSummary>

function matches(idea: { key: string; id: string }, ref: string): boolean {
  const id = ideaCacheId(ref)
  return idea.key.toUpperCase() === id || idea.id === id
}

function apply<T extends IdeaLike>(idea: T, ref: string, patch: IdeaPatch): T {
  return matches(idea, ref) ? { ...idea, ...patch(idea) } : idea
}

/** Patches an idea in every cache that holds it. */
export function patchIdea(queryClient: QueryClient, ref: string, patch: IdeaPatch): void {
  queryClient.setQueryData<IdeaDetail>(queryKeys.ideas.detail(ref), (idea) =>
    idea ? apply(idea, ref, patch) : idea,
  )
  queryClient.setQueriesData<InfiniteData<IdeaPage>>(
    { queryKey: queryKeys.ideas.lists() },
    (data) => mapPages(data, (item) => apply(item, ref, patch)),
  )
  queryClient.setQueriesData<InfiniteData<IdeaPage>>(
    { queryKey: [...queryKeys.work.all, 'owned'] },
    (data) => mapPages(data, (item) => apply(item, ref, patch)),
  )
  queryClient.setQueriesData<Board>({ queryKey: queryKeys.ideas.boards() }, (data) =>
    data
      ? {
          columns: data.columns.map((column) => ({
            ...column,
            items: column.items.map((item) => apply(item, ref, patch)),
          })),
        }
      : data,
  )
  queryClient.setQueryData<Work>(queryKeys.work.summary(), (work) =>
    work
      ? {
          ...work,
          owned: work.owned.map((group) => ({
            ...group,
            ideas: group.ideas.map((item) => apply(item, ref, patch)),
          })),
          recent: work.recent.map((entry) => ({ ...entry, idea: apply(entry.idea, ref, patch) })),
        }
      : work,
  )
}

/** Patches only the idea detail (fields that summaries don't have). */
export function patchIdeaDetail(
  queryClient: QueryClient,
  ref: string,
  patch: (idea: IdeaDetail) => Partial<IdeaDetail>,
): void {
  queryClient.setQueryData<IdeaDetail>(queryKeys.ideas.detail(ref), (idea) =>
    idea ? { ...idea, ...patch(idea) } : idea,
  )
}

function mapPages(
  data: InfiniteData<IdeaPage> | undefined,
  map: (idea: IdeaSummary) => IdeaSummary,
): InfiniteData<IdeaPage> | undefined {
  if (!data) return data
  return { ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.map(map) })) }
}

/** Moves a card between board columns (status change), keeping counts right. */
export function moveOnBoards(
  queryClient: QueryClient,
  ref: string,
  to: { status: IdeaStatus; resolution: Resolution | null; status_label: string },
): void {
  queryClient.setQueriesData<Board>({ queryKey: queryKeys.ideas.boards() }, (data) => {
    if (!data) return data
    const card = data.columns.flatMap((column) => column.items).find((item) => matches(item, ref))
    if (!card) return data
    const moved: IdeaSummary = { ...card, ...to, last_activity_at: new Date().toISOString() }
    return {
      columns: data.columns.map((column) => {
        const had = column.items.some((item) => matches(item, ref))
        const gets = column.status === to.status
        let items = had ? column.items.filter((item) => !matches(item, ref)) : column.items
        if (gets) items = [moved, ...items]
        const count = column.count - (had ? 1 : 0) + (gets ? 1 : 0)
        let resolutionCounts = column.resolution_counts
        if (resolutionCounts && column.status === 'closed') {
          resolutionCounts = { ...resolutionCounts }
          if (had && card.resolution) resolutionCounts[card.resolution] -= 1
          if (gets && to.resolution) resolutionCounts[to.resolution] += 1
        }
        return { ...column, items, count, resolution_counts: resolutionCounts }
      }),
    }
  })
}

/** Finds an idea's summary in any list, board or My work cache (for instant titles). */
export function findCachedIdea(queryClient: QueryClient, ref: string): IdeaSummary | undefined {
  const detail = queryClient.getQueryData<IdeaDetail>(queryKeys.ideas.detail(ref))
  if (detail) return detail
  for (const [, data] of queryClient.getQueriesData<InfiniteData<IdeaPage>>({
    queryKey: queryKeys.ideas.lists(),
  })) {
    const found = data?.pages.flatMap((page) => page.items).find((item) => matches(item, ref))
    if (found) return found
  }
  for (const [, data] of queryClient.getQueriesData<Board>({
    queryKey: queryKeys.ideas.boards(),
  })) {
    const found = data?.columns.flatMap((column) => column.items).find((item) => matches(item, ref))
    if (found) return found
  }
  const work = queryClient.getQueryData<Work>(queryKeys.work.summary())
  return (
    work?.owned.flatMap((group) => group.ideas).find((item) => matches(item, ref)) ??
    work?.recent.map((entry) => entry.idea).find((item) => matches(item, ref))
  )
}

const DEFAULT_LABELS: StatusLabels = {
  new: 'New',
  evaluating: 'Evaluating',
  shortlisted: 'Shortlisted',
  proposal: 'Proposal',
  closed: 'Closed',
  accepted: 'Accepted',
  rejected: 'Rejected',
  parked: 'Parked',
}

/** The label an idea will show after a status change (project labels when cached). */
export function statusLabelFor(
  queryClient: QueryClient,
  projectSlug: string | undefined,
  status: IdeaStatus,
  resolution: Resolution | null,
): string {
  const labels =
    (projectSlug
      ? queryClient.getQueryData<Project>(queryKeys.projects.detail(projectSlug))?.status_labels
      : undefined) ?? DEFAULT_LABELS
  return status === 'closed' && resolution ? labels[resolution] : labels[status]
}
