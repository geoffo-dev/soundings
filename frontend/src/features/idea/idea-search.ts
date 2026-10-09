import { searchEnum, searchFlag } from '@/lib/search-params'

export const IDEA_TABS = ['overview', 'evaluations', 'proposal'] as const
export type IdeaTab = (typeof IDEA_TABS)[number]

/**
 * URL state of the idea page: `/ideas/CUST-12?tab=evaluations`, `?evaluate=1`
 * opens the evaluate sheet and (Phase 8b) `?research=1` the Research panel
 * (email and inbox links use them).
 */
export interface IdeaSearch {
  tab?: IdeaTab
  evaluate?: true
  research?: true
}

export function validateIdeaSearch(search: Record<string, unknown>): IdeaSearch {
  return {
    tab: searchEnum(search.tab, IDEA_TABS),
    evaluate: searchFlag(search.evaluate),
    research: searchFlag(search.research),
  }
}
