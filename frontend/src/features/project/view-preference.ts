import type { ProjectView } from './project-search'

/**
 * Board or List, remembered per project in this browser. The URL's `view`
 * wins when present (shared links open the same view); without it the page
 * shows what you used last in that project, else the Board on wide screens
 * and the List on phones (wireframe 02).
 */
const storageKey = (slug: string) => `soundings-project-view:${slug}`

export function readViewPreference(slug: string): ProjectView | undefined {
  try {
    const value = localStorage.getItem(storageKey(slug))
    return value === 'board' || value === 'list' ? value : undefined
  } catch {
    return undefined
  }
}

export function writeViewPreference(slug: string, view: ProjectView): void {
  try {
    localStorage.setItem(storageKey(slug), view)
  } catch {
    // Storage unavailable (private mode): the URL still carries the view.
  }
}

const PHONE_QUERY = '(max-width: 767px)'

function isPhone(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(PHONE_QUERY).matches
}

/** The view to show: URL, then this project's last choice, then the default for the screen. */
export function resolveView(slug: string, fromUrl: ProjectView | undefined): ProjectView {
  return fromUrl ?? readViewPreference(slug) ?? (isPhone() ? 'list' : 'board')
}
