import { draftKey } from '@/lib/drafts'

/**
 * The New idea draft, kept in this browser for the signed-in user (not synced) so
 * closing the dialog by accident loses nothing (wireframe 06). Cleared after a
 * successful submit, and with every other draft when the session ends (lib/drafts).
 */
export interface IdeaDraft {
  projectSlug?: string
  title: string
  summary: string
  description: string
  tags: string[]
}

const draftKeyFor = (userId: string) => draftKey(userId, 'new-idea')
const lastProjectKey = (userId: string) => draftKey(userId, 'new-idea-project')

export const EMPTY_DRAFT: IdeaDraft = { title: '', summary: '', description: '', tags: [] }

export function hasContent(draft: IdeaDraft): boolean {
  return Boolean(
    draft.title.trim() || draft.summary.trim() || draft.description.trim() || draft.tags.length,
  )
}

export function readDraft(userId: string): IdeaDraft {
  try {
    const raw = localStorage.getItem(draftKeyFor(userId))
    if (!raw) return EMPTY_DRAFT
    const value = JSON.parse(raw) as Partial<IdeaDraft>
    return {
      projectSlug: typeof value.projectSlug === 'string' ? value.projectSlug : undefined,
      title: typeof value.title === 'string' ? value.title : '',
      summary: typeof value.summary === 'string' ? value.summary : '',
      description: typeof value.description === 'string' ? value.description : '',
      tags: Array.isArray(value.tags) ? value.tags.filter((t) => typeof t === 'string') : [],
    }
  } catch {
    return EMPTY_DRAFT
  }
}

export function writeDraft(userId: string, draft: IdeaDraft): void {
  try {
    if (hasContent(draft)) localStorage.setItem(draftKeyFor(userId), JSON.stringify(draft))
    else localStorage.removeItem(draftKeyFor(userId))
  } catch {
    // Storage unavailable: the draft just isn't kept.
  }
}

export function clearDraft(userId: string): void {
  try {
    localStorage.removeItem(draftKeyFor(userId))
  } catch {
    // ignore
  }
}

/** The project last submitted to (the picker's default outside a project). */
export function readLastProject(userId: string): string | undefined {
  try {
    return localStorage.getItem(lastProjectKey(userId)) ?? undefined
  } catch {
    return undefined
  }
}

export function writeLastProject(userId: string, slug: string): void {
  try {
    localStorage.setItem(lastProjectKey(userId), slug)
  } catch {
    // ignore
  }
}
