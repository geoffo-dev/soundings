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
  /**
   * The agent's corner "AI" badge (default on). Off where an `AiBadge` pill sits next
   * to it: one AI marker per row.
   */
  agentBadge?: boolean
  className?: string
  /** Show the name in a tooltip on hover/focus. */
  tooltip?: boolean
  /** The name is already written next to it: hide the avatar from assistive tech. */
  decorative?: boolean
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
  agentBadge = true,
  className,
  tooltip = false,
  decorative = false,
}: AvatarProps) {
  const style = { '--avatar-hue': avatarHue(name) } as CSSProperties
  const node = (
    <span
      data-slot="avatar"
      className={cn(avatar({ size }), className)}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : isAgent ? `${name} (AI agent)` : name}
      aria-hidden={decorative || undefined}
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
      {isAgent && agentBadge && size !== 'xs' && (
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
  /** The background the group sits on, so the separating ring matches it. */
  on?: 'surface' | 'background' | 'elevated'
  className?: string
}

/**
 * Overlap per size, small enough that the next avatar (plus its 2px ring)
 * never covers two-letter initials such as "MW".
 */
const GROUP_OVERLAP: Record<AvatarSize, string> = {
  xs: 'space-x-0',
  sm: '-space-x-px',
  md: '-space-x-0.5',
  lg: '-space-x-1',
  xl: '-space-x-2',
}

const RING: Record<NonNullable<AvatarGroupProps['on']>, string> = {
  surface: 'ring-2 ring-surface',
  background: 'ring-2 ring-background',
  elevated: 'ring-2 ring-elevated',
}

export function AvatarGroup({
  people,
  max = 4,
  size = 'sm',
  on = 'surface',
  className,
}: AvatarGroupProps) {
  const visible = people.slice(0, max)
  const hidden = people.slice(max)
  return (
    <div
      data-slot="avatar-group"
      className={cn('flex items-center', GROUP_OVERLAP[size], className)}
    >
      {visible.map((person) => (
        <Avatar
          key={person.id ?? person.name}
          name={person.name}
          src={person.src}
          isAgent={person.isAgent}
          size={size}
          tooltip
          className={RING[on]}
        />
      ))}
      {hidden.length > 0 && (
        <WithTooltip content={hidden.map((person) => person.name).join(', ')}>
          <span
            role="img"
            aria-label={`${hidden.length} more: ${hidden.map((person) => person.name).join(', ')}`}
            className={cn(avatar({ size }), 'bg-subtle-hover font-medium text-secondary', RING[on])}
          >
            +{hidden.length}
          </span>
        </WithTooltip>
      )}
    </div>
  )
}
