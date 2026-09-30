import { Command as CommandPrimitive } from 'cmdk'
import { Search } from 'lucide-react'
import type { ComponentProps } from 'react'

import { KbdShortcut } from '@/components/ui/kbd'
import { cn } from '@/lib/utils'

/** cmdk primitives styled for Soundings. Used by CommandPalette and Combobox. */
export function Command({ className, ...props }: ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn('flex size-full flex-col overflow-hidden text-primary', className)}
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

export function CommandList({ className, ...props }: ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn(
        'max-h-[min(24rem,60dvh)] scroll-py-1 overflow-x-hidden overflow-y-auto overscroll-contain p-1',
        className,
      )}
      {...props}
    />
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
