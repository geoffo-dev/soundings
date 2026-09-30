import { useNavigate } from '@tanstack/react-router'
import { useCallback } from 'react'

import { useLogout } from '@/api/auth'

/** Signs out and returns to the login page (from the user menu or the palette). */
export function useSignOut(): () => void {
  const navigate = useNavigate()
  const logout = useLogout()
  return useCallback(() => {
    logout.mutate(undefined, {
      onSettled: () => void navigate({ to: '/login', search: {}, replace: true }),
    })
  }, [logout, navigate])
}
