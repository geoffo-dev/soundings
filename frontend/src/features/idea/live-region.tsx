import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * A polite live region for short announcements ("Draft saved", "Scores
 * revealed…"). Modal sheets hide the rest of the page from assistive tech, so
 * each surface renders its own `<LiveRegion>`.
 */
export function useLiveRegion() {
  const [message, setMessage] = useState('')
  const frame = useRef(0)
  useEffect(() => () => cancelAnimationFrame(frame.current), [])
  const announce = useCallback((text: string) => {
    // Clear first so the same text is announced again.
    setMessage('')
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(() => setMessage(text))
  }, [])
  return { message, announce }
}

export function LiveRegion({ message }: { message: string }) {
  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </div>
  )
}
