import { searchEnum, searchFlag } from '@/lib/search-params'

export const IDEA_TABS = ['overview', 'evaluations', 'proposal'] as const
export type IdeaTab = (typeof IDEA_TABS)[number]

/**
 * URL state of the idea page: `/ideas/CUST-12?tab=evaluations`, and
 * `?evaluate=1` opens the evaluate sheet (email links use it).
 */
export interface IdeaSearch {
  tab?: IdeaTab
  evaluate?: true
}

export function validateIdeaSearch(search: Record<string, unknown>): IdeaSearch {
  return {
    tab: searchEnum(search.tab, IDEA_TABS),
    evaluate: searchFlag(search.evaluate),
  }
}
