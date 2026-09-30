import { Check } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { useDebouncedValue } from '@/api/search'
import type { UserSearchResult } from '@/api/types'
import { useUserSearch } from '@/api/users'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** Owners and evaluators need a member or admin role in the project (contract c4). */
export function isEligible(person: UserSearchResult): boolean {
  return person.project_role === 'member' || person.project_role === 'admin'
}

const ROLE_NAMES = { admin: 'Admin', member: 'Member', viewer: 'Viewer' } as const

export interface PeopleListProps {
  projectSlug: string
  /** Selected user ids (checked rows). */
  selected: readonly string[]
  onSelect: (person: UserSearchResult) => void
  /** Rows that can't be picked, with the reason shown in place of the role. */
  unavailable?: ReadonlyMap<string, string>
  /** Your own id: "(you)" after your name. */
  meId?: string
  placeholder?: string
  /** Label for the search field and the list. */
  label: string
  /** Extra rows above the people (e.g. "Remove owner"). */
  before?: ReactNode
}

/**
 * Searchable list of the project's people (server-side search). Viewers are
 * shown but disabled so it's clear why someone can't be picked.
 */
export function PeopleList({
  projectSlug,
  selected,
  onSelect,
  unavailable,
  meId,
  placeholder = 'Search people…',
  label,
  before,
}: PeopleListProps) {
  const [search, setSearch] = useState('')
  const q = useDebouncedValue(search, 150)
  const people = useUserSearch({ q, project: projectSlug, limit: 50 })
  const items = people.data?.items ?? []

  return (
    <Command shouldFilter={false} label={label} className="min-h-0">
      <CommandInput
        value={search}
        onValueChange={setSearch}
        placeholder={placeholder}
        aria-label={label}
      />
      <CommandList aria-label={label}>
        {before}
        {people.isPending ? (
          <div role="status" aria-label="Loading people" className="flex flex-col gap-1 p-1">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex h-10 items-center gap-2.5 px-2">
                <Skeleton className="size-6 rounded-full" />
                <Skeleton className="h-3.5 w-40" />
              </div>
            ))}
          </div>
        ) : people.isError ? (
          <div role="alert" className="flex flex-col items-center gap-2 px-3 py-6 text-center">
            <p className="text-sm text-muted">We couldn’t load people.</p>
            <Button size="sm" onClick={() => void people.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <>
            <CommandEmpty>
              {q ? `No one in this project matches “${q}”.` : 'No people in this project yet.'}
            </CommandEmpty>
            <CommandGroup>
              {items.map((person) => {
                const reason =
                  unavailable?.get(person.id) ??
                  (isEligible(person) ? undefined : 'Viewer · can’t be assigned')
                const isSelected = selected.includes(person.id)
                return (
                  <CommandItem
                    key={person.id}
                    value={person.id}
                    disabled={Boolean(reason)}
                    onSelect={() => onSelect(person)}
                    className="h-auto min-h-11 py-1.5 sm:h-auto sm:min-h-10"
                  >
                    <Avatar
                      name={person.display_name}
                      src={person.avatar_url}
                      size="sm"
                      decorative
                    />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">
                        {person.display_name}
                        {person.id === meId && <span className="text-muted"> (you)</span>}
                        {/* cmdk owns aria-selected (the highlight), so say "chosen" in words. */}
                        {isSelected && <span className="sr-only">, chosen</span>}
                      </span>
                      <span className="truncate text-xs text-muted">
                        {reason ??
                          [
                            person.project_role ? ROLE_NAMES[person.project_role] : null,
                            person.email,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                      </span>
                    </span>
                    <Check
                      aria-hidden="true"
                      className={cn('text-accent!', isSelected ? 'opacity-100' : 'opacity-0')}
                    />
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </Command>
  )
}
