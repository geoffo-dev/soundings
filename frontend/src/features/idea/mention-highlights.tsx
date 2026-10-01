import { useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react'

import type { MentionDraft } from '@/lib/mentions'

/** The text field's styles that decide where each character lands. */
const MIRRORED = [
  'fontFamily',
  'fontSize',
  'fontWeight',
  'fontStyle',
  'fontFeatureSettings',
  'fontVariationSettings',
  'letterSpacing',
  'wordSpacing',
  'lineHeight',
  'tabSize',
  'textIndent',
  'textTransform',
  'paddingTop',
  'paddingRight',
  'paddingBottom',
  'paddingLeft',
] as const

/**
 * Tints each mention ("@Ada Lovelace") in a plain text field, so people can
 * tell a real mention from text that only looks like one (an edited mention
 * turns back into plain text and loses its tint). A copy of the text with the
 * field's own metrics and invisible letters, laid over the field (render it
 * after the field, in a positioned parent); only the translucent tints show,
 * and clicks go through. It follows the field's size and scroll. Hidden from
 * assistive technology: the text itself is in the field.
 */
export function MentionHighlights({
  fieldRef,
  draft,
}: {
  fieldRef: RefObject<HTMLTextAreaElement | null>
  draft: MentionDraft
}) {
  const mirrorRef = useRef<HTMLDivElement>(null)
  const hasMentions = draft.mentions.length > 0

  // Size, place and scroll like the field: after every render (the text changed) …
  useLayoutEffect(() => {
    const field = fieldRef.current
    const mirror = mirrorRef.current
    if (field && mirror) follow(field, mirror)
  })

  // … and whenever the field resizes (it grows with its text) or scrolls.
  useLayoutEffect(() => {
    const field = fieldRef.current
    const mirror = mirrorRef.current
    if (!field || !mirror) return
    const sync = () => follow(field, mirror)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(sync)
    observer?.observe(field)
    field.addEventListener('scroll', sync, { passive: true })
    return () => {
      observer?.disconnect()
      field.removeEventListener('scroll', sync)
    }
  }, [fieldRef, hasMentions])

  if (!hasMentions) return null
  const parts: ReactNode[] = []
  let from = 0
  for (const mention of draft.mentions) {
    parts.push(draft.text.slice(from, mention.start))
    parts.push(
      <span key={mention.start} data-mention-tint={mention.userId} className="mention-tint">
        {draft.text.slice(mention.start, mention.end)}
      </span>,
    )
    from = mention.end
  }
  // A zero-width space keeps a trailing new line as tall as the field's.
  parts.push(`${draft.text.slice(from)}\u200b`)

  return (
    <div
      ref={mirrorRef}
      aria-hidden="true"
      data-slot="mention-highlights"
      className="pointer-events-none absolute overflow-hidden break-words whitespace-pre-wrap text-transparent select-none"
    >
      {parts}
    </div>
  )
}

function follow(field: HTMLTextAreaElement, mirror: HTMLDivElement) {
  const style = window.getComputedStyle(field)
  for (const name of MIRRORED) mirror.style[name] = style[name]
  mirror.style.top = `${field.offsetTop + field.clientTop}px`
  mirror.style.left = `${field.offsetLeft + field.clientLeft}px`
  // The client box leaves out the scroll bar, so lines wrap where the field's do.
  mirror.style.width = `${field.clientWidth}px`
  mirror.style.height = `${field.clientHeight}px`
  mirror.scrollTop = field.scrollTop
}
