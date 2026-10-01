import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import { Input, type InputProps } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/**
 * A password field with a "Show password" toggle, for long secrets that are
 * easy to mistype (the break-glass password comes from a Kubernetes Secret).
 * The toggle is a real button after the field (Tab reaches it, it never
 * submits) with a fixed name and `aria-pressed`. Use it inside a `Field` like
 * `Input`.
 */
export function PasswordInput({ className, ...props }: Omit<InputProps, 'type' | 'startIcon'>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className={cn('relative w-full', className)}>
      <Input
        type={visible ? 'text' : 'password'}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        className="pr-10"
        {...props}
      />
      <button
        type="button"
        aria-label="Show password"
        aria-pressed={visible}
        onClick={() => setVisible((shown) => !shown)}
        className="absolute inset-y-0 right-0 inline-flex w-9 items-center justify-center rounded-r-md text-muted transition-colors hover:text-primary [&_svg]:size-4"
      >
        {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
      </button>
    </div>
  )
}
