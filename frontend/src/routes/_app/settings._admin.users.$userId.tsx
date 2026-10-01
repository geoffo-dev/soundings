import { createFileRoute } from '@tanstack/react-router'

import { UserSheet } from '@/features/admin/users/user-sheet'

/** /settings/users/$userId — one user, in a sheet over the list (filters kept). */
export const Route = createFileRoute('/_app/settings/_admin/users/$userId')({
  component: UserSheetRoute,
})

function UserSheetRoute() {
  const { userId } = Route.useParams()
  const navigate = Route.useNavigate()
  return (
    <UserSheet
      userId={userId}
      onClose={() => void navigate({ to: '/settings/users', search: true })}
    />
  )
}
