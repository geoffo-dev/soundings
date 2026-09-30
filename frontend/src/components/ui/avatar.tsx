import { cva, type VariantProps } from 'class-variance-authority'
import { Sparkles } from 'lucide-react'
import { Avatar as AvatarPrimitive } from 'radix-ui'
import type { CSSProperties } from 'react'

import { WithTooltip } from '@/components/ui/tooltip'
import { cn, hashString, initials } from '@/lib/utils'

const avatar = cva(
  'relative inline-flex shrink-0 items-center justify-center rounded-full align-middle select-none',
  {
    variants: {
      size: {
        xs: 'size-5 text-[0.5625rem]',
        sm: 'size-6 text-[0.625rem]',
        md: 'size-7 text-xs',
        lg: 'size-9 text-sm',
        xl: 'size-14 text-xl',
      },
    },
    defaultVariants: { size: 'md' },
  },
)

export type AvatarSize = NonNullable<VariantProps<typeof avatar>['size']>

export interface AvatarProps extends VariantProps<typeof avatar> {
  name: string
  src?: string | null
  /** An AI agent (kagent): sparkle glyph and an "AI" badge. */
  isAgent?: boolean
  className?: string
  /** Show the name in a tooltip on hover/focus. */
  tooltip?: boolean
}

/** Deterministic hue so the same person always gets the same colour. */
export function avatarHue(name: string): number {
  return hashString(name.trim().toLowerCase()) % 360
}

export function Avatar({
  name,
  src,
  size,
  isAgent = false,
  className,
  tooltip = false,
}: AvatarProps) {
  const style = { '--avatar-hue': avatarHue(name) } as CSSProperties
  const node = (
    <span
      data-slot="avatar"
      className={cn(avatar({ size }), className)}
      role="img"
      aria-label={isAgent ? `${name} (AI agent)` : name}
    >
      <AvatarPrimitive.Root className="flex size-full overflow-hidden rounded-full">
        {src && !isAgent && (
          <AvatarPrimitive.Image src={src} alt="" className="size-full object-cover" />
        )}
        <AvatarPrimitive.Fallback
          delayMs={src ? 300 : 0}
          style={isAgent ? undefined : style}
          className={cn(
            'flex size-full items-center justify-center rounded-full font-semibold tracking-tight',
            isAgent ? 'bg-accent-subtle text-accent' : 'avatar-tint',
          )}
        >
          {isAgent ? <Sparkles aria-hidden="true" className="size-[55%]" /> : initials(name)}
        </AvatarPrimitive.Fallback>
      </AvatarPrimitive.Root>
      {isAgent && size !== 'xs' && (
        <span
          aria-hidden="true"
          className="absolute -right-1.5 -bottom-1 rounded-[3px] bg-accent px-[3px] text-[0.5rem] leading-3 font-semibold text-accent-foreground ring-2 ring-surface"
        >
          AI
        </span>
      )}
    </span>
  )
  if (!tooltip) return node
  return <WithTooltip content={isAgent ? `${name} · AI agent` : name}>{node}</WithTooltip>
}

export interface AvatarGroupProps {
  people: { id?: string; name: string; src?: string | null; isAgent?: boolean }[]
  /** Visible avatars before collapsing into "+N". */
  max?: number
  size?: AvatarSize
  className?: string
}

export function AvatarGroup({ people, max = 4, size = 'sm', className }: AvatarGroupProps) {
  const visible = people.slice(0, max)
  const hidden = people.slice(max)
  return (
    <div data-slot="avatar-group" className={cn('flex items-center -space-x-1.5', className)}>
      {visible.map((person) => (
        <Avatar
          key={person.id ?? person.name}
          name={person.name}
          src={person.src}
          isAgent={person.isAgent}
          size={size}
          tooltip
          className="ring-2 ring-surface"
        />
      ))}
      {hidden.length > 0 && (
        <WithTooltip content={hidden.map((person) => person.name).join(', ')}>
          <span
            role="img"
            aria-label={`${hidden.length} more: ${hidden.map((person) => person.name).join(', ')}`}
            className={cn(
              avatar({ size }),
              'bg-subtle-hover font-medium text-secondary ring-2 ring-surface',
            )}
          >
            +{hidden.length}
          </span>
        </WithTooltip>
      )}
    </div>
  )
}
