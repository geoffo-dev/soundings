import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { useRouter, type ErrorComponentProps } from '@tanstack/react-router'
import { CloudOff } from 'lucide-react'
import { useEffect } from 'react'

import { isApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'

/** Default route error boundary: friendly message plus a retry that refetches. */
export function RouteError({ error }: ErrorComponentProps) {
  const router = useRouter()
  const { reset } = useQueryErrorResetBoundary()

  useEffect(() => {
    reset()
  }, [reset])

  const title = isApiError(error) ? error.title : 'Something went wrong'
  const description = isApiError(error)
    ? (error.detail ?? 'Please try again in a moment.')
    : 'An unexpected error occurred. Try again, and if it keeps happening let an admin know.'

  return (
    <EmptyState
      role="alert"
      icon={<CloudOff />}
      title={title}
      description={description}
      action={
        <Button variant="primary" onClick={() => void router.invalidate()}>
          Try again
        </Button>
      }
    />
  )
}
