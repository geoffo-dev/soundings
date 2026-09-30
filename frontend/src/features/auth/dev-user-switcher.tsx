import { useRouter } from '@tanstack/react-router'
import { Check, Database, UsersRound } from 'lucide-react'

import { useDevLogin, useDevUsers } from '@/api/auth'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from '@/components/ui/dropdown-menu'
import { toast } from '@/components/ui/toaster'
import { apiMocksEnabled } from '@/lib/env'

const DATASET_KEY = 'soundings-mock-dataset'

function readDataset(): string {
  try {
    return localStorage.getItem(DATASET_KEY) ?? 'default'
  } catch {
    return 'default'
  }
}

/**
 * Dev builds only (the user menu renders it behind `import.meta.env.DEV`):
 * sign in as someone else in one click — works with the MSW mocks and with a
 * backend that has dev login enabled. With mocks, also switch the dataset.
 */
export function DevUserSwitcher({ currentUserId }: { currentUserId: string }) {
  const router = useRouter()
  const users = useDevUsers()
  const login = useDevLogin()

  if (users.isError) return null

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <UsersRound /> Switch user
        <Badge variant="outline" className="ml-auto">
          Dev
        </Badge>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="max-h-(--radix-dropdown-menu-content-available-height) w-64 overflow-y-auto">
        {(users.data ?? []).map((user) => (
          <DropdownMenuItem
            key={user.id}
            disabled={login.isPending}
            onSelect={() => {
              if (user.id === currentUserId) return
              // Not mutate()'s onSuccess: the menu (and this component) is gone by the
              // time the sign-in answers, and those callbacks don't run after unmount.
              login.mutateAsync(user.id).then(
                () => {
                  void router.invalidate()
                  toast.success(`Signed in as ${user.display_name}`)
                },
                () => undefined, // the mutation's own error toast covers it
              )
            }}
          >
            <Avatar name={user.display_name} src={user.avatar_url} size="xs" decorative />
            <span className="truncate">{user.display_name}</span>
            {user.is_platform_admin && (
              <span className="text-xs text-muted" aria-label="Platform admin">
                admin
              </span>
            )}
            {user.id === currentUserId && <Check className="ml-auto" aria-label="Current user" />}
          </DropdownMenuItem>
        ))}
        {apiMocksEnabled && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="flex items-center gap-1.5">
              <Database className="size-3.5" aria-hidden="true" /> Mock data
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={readDataset()}
              onValueChange={(value) => {
                try {
                  localStorage.setItem(DATASET_KEY, value)
                } catch {
                  return
                }
                window.location.reload()
              }}
            >
              <DropdownMenuRadioItem value="default">Normal (40 ideas)</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="large">Large (10,000 ideas)</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </>
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  )
}
