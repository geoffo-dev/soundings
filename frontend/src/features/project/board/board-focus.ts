import { createContext, use } from 'react'

/**
 * A card moved with the keyboard re-mounts in its new column, so the browser
 * drops focus. The board asks for focus by id; the card takes it on mount.
 */
export interface BoardFocus {
  request: (ideaId: string) => void
  /** True once for the requested id (the card then focuses itself). */
  take: (ideaId: string) => boolean
}

export function createBoardFocus(): BoardFocus {
  let pending: string | null = null
  let timer: number | undefined
  return {
    request: (ideaId) => {
      pending = ideaId
      // Forget stale requests (e.g. the move failed and nothing re-mounted).
      window.clearTimeout(timer)
      timer = window.setTimeout(() => (pending = null), 3000)
    },
    take: (ideaId) => {
      if (pending !== ideaId) return false
      pending = null
      return true
    },
  }
}

const noFocus: BoardFocus = { request: () => undefined, take: () => false }

export const BoardFocusContext = createContext<BoardFocus>(noFocus)

export function useBoardFocus(): BoardFocus {
  return use(BoardFocusContext)
}
