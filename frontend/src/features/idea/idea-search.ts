import { searchEnum, searchFlag, searchString } from '@/lib/search-params'

export const IDEA_TABS = ['overview', 'evaluations', 'proposal', 'bids'] as const
export type IdeaTab = (typeof IDEA_TABS)[number]

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function searchUuid(value: unknown): string | undefined {
  const text = searchString(value, 36)
  return text && UUID.test(text) ? text.toLowerCase() : undefined
}

/**
 * URL state of the idea page: `/ideas/CUST-12?tab=evaluations`, `?evaluate=1`
 * opens the evaluate sheet and (Phase 8b) `?research=1` the Research panel
 * (email and inbox links use them). Phase 10: `?tab=bids&bid=<id>` opens a bid,
 * and `&assess=<section id>` your assessment of that section of it.
 */
export interface IdeaSearch {
  tab?: IdeaTab
  evaluate?: true
  research?: true
  bid?: string
  assess?: string
}

export function validateIdeaSearch(search: Record<string, unknown>): IdeaSearch {
  const bid = searchUuid(search.bid)
  return {
    tab: searchEnum(search.tab, IDEA_TABS),
    evaluate: searchFlag(search.evaluate),
    research: searchFlag(search.research),
    bid,
    assess: bid ? searchUuid(search.assess) : undefined,
  }
}
