import { useCallback, useLayoutEffect, useRef, type ComponentProps } from 'react'

import { useFieldControl } from '@/components/ui/field'
import { controlStyles } from '@/components/ui/input'
import { cn, mergeRefs } from '@/lib/utils'

export interface TextareaProps extends ComponentProps<'textarea'> {
  /** Grow with the content between minRows and maxRows. Default true. */
  autoGrow?: boolean
  minRows?: number
  maxRows?: number
}

export function Textarea({
  className,
  autoGrow = true,
  minRows = 3,
  maxRows = 14,
  onInput,
  ref,
  ...props
}: TextareaProps) {
  const fieldProps = useFieldControl(props)
  const innerRef = useRef<HTMLTextAreaElement>(null)

  const resize = useCallback(() => {
    const el = innerRef.current
    if (!el || !autoGrow) return
    const style = window.getComputedStyle(el)
    const lineHeight = Number.parseFloat(style.lineHeight) || 22
    const border =
      Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth)
    const chrome =
      Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom) + border
    const min = minRows * lineHeight + chrome
    const max = maxRows * lineHeight + chrome
    el.style.height = 'auto'
    const wanted = el.scrollHeight + border
    el.style.height = `${Math.min(Math.max(wanted, min), max)}px`
    el.style.overflowY = wanted > max ? 'auto' : 'hidden'
  }, [autoGrow, minRows, maxRows])

  // Re-measure when a controlled value changes from outside (e.g. reset).
  useLayoutEffect(resize, [resize, props.value])

  return (
    <textarea
      ref={mergeRefs(innerRef, ref)}
      rows={minRows}
      data-slot="textarea"
      onInput={(event) => {
        resize()
        onInput?.(event)
      }}
      className={cn(
        controlStyles,
        'block resize-none px-2.5 py-1.5',
        !autoGrow && 'resize-y',
        className,
      )}
      {...fieldProps}
    />
  )
}
