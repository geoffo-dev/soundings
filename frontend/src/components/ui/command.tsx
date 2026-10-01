import { Command as CommandPrimitive } from 'cmdk'
import { Search } from 'lucide-react'
import { useState, type ComponentProps, type ReactNode } from 'react'

import { KbdShortcut } from '@/components/ui/kbd'
import { cn, isMac } from '@/lib/utils'

/**
 * cmdk primitives styled for Soundings. Used by CommandPalette and Combobox.
 *
 * cmdk's Ctrl+N/P/J/K bindings are on for macOS only: elsewhere Ctrl+K is the command
 * palette's shortcut (mod+k), which cmdk would swallow as "move up".
 *
 * Inside a form, ⌘/Ctrl+Enter submits the form (the app-wide "submit" shortcut)
 * instead of picking the highlighted item, which is what cmdk does with any Enter.
 */
export function Command({
  className,
  vimBindings = isMac,
  onKeyDown,
  ...props
}: ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      vimBindings={vimBindings}
      className={cn('flex size-full flex-col overflow-hidden text-primary', className)}
      onKeyDown={(event) => {
        onKeyDown?.(event)
        const mod = isMac ? event.metaKey : event.ctrlKey
        const form = event.currentTarget.closest('form')
        if (event.defaultPrevented || event.key !== 'Enter' || !mod || !form) return
        // cmdk skips a handled event; the form's own submit handler takes it from here.
        event.preventDefault()
        form.requestSubmit()
      }}
      {...props}
    />
  )
}

export function CommandInput({
  className,
  ...props
}: ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex items-center gap-2 border-b border-subtle px-3">
      <Search aria-hidden="true" className="size-4 shrink-0 text-muted" />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          'h-11 w-full min-w-0 bg-transparent text-lg text-primary outline-none placeholder:text-muted sm:text-base',
          className,
        )}
        {...props}
      />
    </div>
  )
}

export interface CommandListProps extends ComponentProps<typeof CommandPrimitive.List> {
  /**
   * Shown when nothing matches, below the list. Keep this and any loading or error
   * message outside the list: a listbox may only hold options (axe).
   */
  empty?: ReactNode
}

export function CommandList({ className, empty, ...props }: CommandListProps) {
  return (
    <>
      <CommandPrimitive.List
        data-slot="command-list"
        className={cn(
          'max-h-[min(24rem,60dvh)] scroll-py-1 overflow-x-hidden overflow-y-auto overscroll-contain',
          // No padding without rows, so an empty list takes no room above its message.
          'has-[[cmdk-item]]:p-1',
          className,
        )}
        {...props}
      />
      {empty !== undefined && <CommandEmpty>{empty}</CommandEmpty>}
    </>
  )
}

export function CommandEmpty({
  className,
  ...props
}: ComponentProps<typeof CommandPrimitive.Empty>) {
  return (
    <CommandPrimitive.Empty
      className={cn('px-3 py-8 text-center text-sm text-muted', className)}
      {...props}
    />
  )
}

export function CommandGroup({
  className,
  ...props
}: ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      className={cn(
        '[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1',
        '[&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted',
        className,
      )}
      {...props}
    />
  )
}

export function CommandItem({ className, ...props }: ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        'relative flex h-10 cursor-default items-center gap-2.5 rounded-md px-2 text-base outline-none select-none sm:h-9',
        'data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 data-[selected=true]:bg-subtle-hover',
        "[&_svg]:shrink-0 [&_svg]:text-muted [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  )
}

export function CommandSeparator({
  className,
  ...props
}: ComponentProps<typeof CommandPrimitive.Separator>) {
  return (
    <CommandPrimitive.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...props} />
  )
}

export function CommandShortcut({ keys }: { keys: string }) {
  return <KbdShortcut keys={keys} className="ml-auto" />
}

export const CommandLoading = CommandPrimitive.Loading

/**
 * For lists the server filters (`shouldFilter={false}`): keeps the highlight on the
 * first pickable result whenever the results change, so typing a name and pressing
 * Enter picks the top match. (cmdk picks a highlight when the query changes, before
 * the new results arrive, which left nothing or an old row highlighted.) ↑/↓ still
 * move it. Pass the values of the enabled items, in the order they're shown.
 *
 *   const highlight = useTopResult(people.map((person) => person.id))
 *   <Command shouldFilter={false} {...highlight}>
 */
export function useTopResult(values: readonly string[]): {
  value: string
  onValueChange: (value: string) => void
} {
  const key = values.join('\n')
  const [state, setState] = useState({ key, value: values[0] ?? '' })
  if (state.key !== key) setState({ key, value: values[0] ?? '' })
  return {
    value: state.key === key ? state.value : (values[0] ?? ''),
    onValueChange: (value) => setState({ key, value }),
  }
}
