import { ChevronsUpDown } from 'lucide-react'
import { useId, useState, type Ref } from 'react'

import { useDebouncedValue } from '@/api/search'
import type { UserSearchResult } from '@/api/types'
import { useUserSearch } from '@/api/users'
import { Avatar } from '@/components/ui/avatar'
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  useTopResult,
} from '@/components/ui/command'
import { useFieldControl } from '@/components/ui/field'
import { controlStyles } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

/**
 * Pick one person from everyone who can sign in (server search by name or
 * email). People in `exclude` are listed but can't be picked (with `excludeHint`).
 */
export function PersonPicker({
  value,
  onChange,
  exclude = [],
  excludeHint = 'Already added',
  placeholder = 'Add a person…',
  className,
  ref,
}: {
  value: UserSearchResult | null
  onChange: (person: UserSearchResult | null) => void
  exclude?: string[]
  excludeHint?: string
  placeholder?: string
  className?: string
  /** The trigger button (e.g. to focus it again after adding someone). */
  ref?: Ref<HTMLButtonElement>
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const debounced = useDebouncedValue(q.trim())
  const people = useUserSearch({ q: debounced }, { enabled: open })
  const listId = useId()
  const aria = useFieldControl({})
  const highlight = useTopResult(
    (people.data?.items ?? [])
      .filter((person) => !exclude.includes(person.id))
      .map((person) => person.id),
  )

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setQ('')
      }}
    >
      <PopoverTrigger asChild>
        <button
          ref={ref}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-haspopup="listbox"
          {...aria}
          className={cn(
            controlStyles,
            'flex h-9 items-center gap-2 px-2.5 text-left sm:h-8',
            className,
          )}
        >
          {value ? (
            <span className="flex min-w-0 items-center gap-2">
              <Avatar size="xs" name={value.display_name} src={value.avatar_url} decorative />
              <span className="truncate">{value.display_name}</span>
            </span>
          ) : (
            <span className="truncate text-muted">{placeholder}</span>
          )}
          <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 shrink-0 text-muted" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-(--radix-popover-trigger-width) min-w-72 p-0"
        aria-label="Find a person"
      >
        <Command shouldFilter={false} {...highlight}>
          <CommandInput value={q} onValueChange={setQ} placeholder="Search by name or email…" />
          {people.isPending && (
            <p role="status" className="px-3 py-6 text-center text-sm text-muted">
              Searching…
            </p>
          )}
          <CommandList
            id={listId}
            aria-label="People"
            empty={people.isPending ? undefined : `No one matches “${q}”`}
          >
            <CommandGroup>
              {people.data?.items.map((person) => {
                const taken = exclude.includes(person.id)
                return (
                  <CommandItem
                    key={person.id}
                    value={person.id}
                    disabled={taken}
                    onSelect={() => {
                      onChange(person)
                      setOpen(false)
                      setQ('')
                    }}
                    className="h-auto min-h-10 py-1.5 sm:h-auto"
                  >
                    <Avatar
                      size="sm"
                      name={person.display_name}
                      src={person.avatar_url}
                      decorative
                    />
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">{person.display_name}</span>
                      <span className="truncate text-xs text-muted">{person.email}</span>
                    </span>
                    {taken && <span className="ml-auto text-xs text-muted">{excludeHint}</span>}
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
