import { VisuallyHidden as VisuallyHiddenPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

/** Content for assistive technology only (e.g. icon-button labels, dialog descriptions). */
export function VisuallyHidden(props: ComponentProps<typeof VisuallyHiddenPrimitive.Root>) {
  return <VisuallyHiddenPrimitive.Root {...props} />
}
