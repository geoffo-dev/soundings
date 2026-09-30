import { CircleAlert, CircleCheck, Info, TriangleAlert } from 'lucide-react'
import type { CSSProperties } from 'react'
import { Toaster as Sonner, toast as sonnerToast, type ExternalToast } from 'sonner'

import { Spinner } from '@/components/ui/spinner'
import { useTheme } from '@/components/theme-provider'

/** Mounted once in the root route. */
export function Toaster() {
  const { resolvedTheme } = useTheme()
  return (
    <Sonner
      theme={resolvedTheme}
      position="bottom-right"
      gap={8}
      visibleToasts={4}
      mobileOffset={16}
      containerAriaLabel="Notifications"
      icons={{
        success: <CircleCheck className="size-4 text-success" />,
        error: <CircleAlert className="size-4 text-danger" />,
        warning: <TriangleAlert className="size-4 text-warning" />,
        info: <Info className="size-4 text-info" />,
        loading: <Spinner className="text-muted" />,
      }}
      style={
        {
          '--normal-bg': 'var(--elevated)',
          '--normal-text': 'var(--fg-primary)',
          '--normal-border': 'var(--border)',
          '--border-radius': '0.5rem',
          fontFamily: 'var(--font-sans)',
        } as CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: 'shadow-overlay! text-sm! gap-2.5! py-3! px-3.5!',
          title: 'font-medium! text-primary!',
          description: 'text-muted! text-sm!',
          actionButton:
            'bg-subtle-hover! text-primary! font-medium! h-7! px-2.5! rounded-md! text-sm! hover:bg-subtle! transition-colors!',
          cancelButton: 'bg-transparent! text-muted! h-7! px-2! text-sm!',
          closeButton: 'bg-elevated! border! text-muted!',
        },
      }}
    />
  )
}

type ToastOptions = Omit<ExternalToast, 'action' | 'cancel'>

/** Thin, typed wrapper so screens don't reach for sonner directly. */
export const toast = {
  message: (title: string, options?: ToastOptions) => sonnerToast(title, options),
  success: (title: string, options?: ToastOptions) => sonnerToast.success(title, options),
  error: (title: string, options?: ToastOptions) => sonnerToast.error(title, options),
  info: (title: string, options?: ToastOptions) => sonnerToast.info(title, options),
  warning: (title: string, options?: ToastOptions) => sonnerToast.warning(title, options),
  promise: sonnerToast.promise,
  dismiss: sonnerToast.dismiss,
}

export interface UndoToastOptions extends ToastOptions {
  /** Revert the optimistic change. */
  onUndo: () => void
  /**
   * Optional: perform the real change only once the toast goes away without
   * Undo (deferred commit). Omit when the change was already persisted.
   */
  onCommit?: () => void
  undoLabel?: string
}

/**
 * Undo pattern for destructive-ish actions (SPEC §5): apply the change
 * optimistically, then offer Undo for a few seconds.
 *   toastUndo('Idea archived', { onUndo: () => restore(id) })
 */
export function toastUndo(
  title: string,
  { onUndo, onCommit, undoLabel = 'Undo', duration = 6000, ...options }: UndoToastOptions,
) {
  let undone = false
  let settled = false
  const commit = () => {
    if (settled || undone) return
    settled = true
    onCommit?.()
  }
  return sonnerToast(title, {
    duration,
    ...options,
    action: {
      label: undoLabel,
      onClick: () => {
        undone = true
        onUndo()
      },
    },
    onAutoClose: commit,
    onDismiss: commit,
  })
}
