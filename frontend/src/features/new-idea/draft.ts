/**
 * The New idea draft, kept per browser (not synced) so closing the dialog by
 * accident loses nothing (wireframe 06). Cleared after a successful submit.
 */
export interface IdeaDraft {
  projectSlug?: string
  title: string
  summary: string
  description: string
  tags: string[]
}

const DRAFT_KEY = 'soundings-new-idea-draft'
const LAST_PROJECT_KEY = 'soundings-new-idea-project'

export const EMPTY_DRAFT: IdeaDraft = { title: '', summary: '', description: '', tags: [] }

export function hasContent(draft: IdeaDraft): boolean {
  return Boolean(
    draft.title.trim() || draft.summary.trim() || draft.description.trim() || draft.tags.length,
  )
}

export function readDraft(): IdeaDraft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
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

export function writeDraft(draft: IdeaDraft): void {
  try {
    if (hasContent(draft)) localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
    else localStorage.removeItem(DRAFT_KEY)
  } catch {
    // Storage unavailable: the draft just isn't kept.
  }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(DRAFT_KEY)
  } catch {
    // ignore
  }
}

/** The project last submitted to (the picker's default outside a project). */
export function readLastProject(): string | undefined {
  try {
    return localStorage.getItem(LAST_PROJECT_KEY) ?? undefined
  } catch {
    return undefined
  }
}

export function writeLastProject(slug: string): void {
  try {
    localStorage.setItem(LAST_PROJECT_KEY, slug)
  } catch {
    // ignore
  }
}
