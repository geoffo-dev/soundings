import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { useLocation, useRouter, type ErrorComponentProps } from '@tanstack/react-router'
import { CloudOff } from 'lucide-react'
import { useEffect } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'

/** What failed, by page, in the same words as the in-page error states. */
function titleFor(pathname: string): string {
  if (pathname === '/') return 'We couldn’t load your work'
  if (pathname.startsWith('/ideas/')) return 'We couldn’t load this idea'
  if (/^\/p\/[^/]+\/settings/.test(pathname)) return 'We couldn’t load the project settings'
  if (pathname.startsWith('/p/')) return 'We couldn’t load this project'
  if (pathname.startsWith('/settings')) return 'We couldn’t load your settings'
  return 'Something went wrong'
}

/** Default route error boundary: what failed, why in plain words, and a retry. */
export function RouteError({ error }: ErrorComponentProps) {
  const router = useRouter()
  const pathname = useLocation({ select: (location) => location.pathname })
  const { reset } = useQueryErrorResetBoundary()

  useEffect(() => {
    reset()
  }, [reset])

  const { title, description } = describeError(error)
  // A 403 or 404 already says what happened ("You can’t do that here"); otherwise
  // say what didn't load and why.
  const known = isApiError(error) && error.isClientError
  return (
    <EmptyState
      role="alert"
      icon={<CloudOff />}
      title={known ? title : titleFor(pathname)}
      description={
        known
          ? description
          : isApiError(error)
            ? [error.isNetworkError ? title : null, description].filter(Boolean).join('. ')
            : 'Try again, and if it keeps happening let an admin know.'
      }
      action={
        <Button variant="primary" onClick={() => void router.invalidate()}>
          Try again
        </Button>
      }
    />
  )
}
