import { ChevronsUpDown, UsersRound } from 'lucide-react'
import { useId, useState, type Ref } from 'react'

import { useGroupSearch } from '@/api/groups'
import { useDebouncedValue } from '@/api/search'
import type { GroupSearchResult } from '@/api/types'
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

import { peopleCount } from './access'

/**
 * Pick one group (server search by name, `search_groups`). Groups in `exclude`
 * are listed but can't be picked (with `excludeHint`). Groups are created and
 * mapped to the identity provider in Admin settings → Groups.
 */
export function GroupPicker({
  value,
  onChange,
  exclude = [],
  excludeHint = 'Already added',
  placeholder = 'Search groups…',
  className,
  ref,
}: {
  value: GroupSearchResult | null
  onChange: (group: GroupSearchResult | null) => void
  exclude?: string[]
  excludeHint?: string
  placeholder?: string
  className?: string
  ref?: Ref<HTMLButtonElement>
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const debounced = useDebouncedValue(q.trim())
  const groups = useGroupSearch(debounced, { enabled: open })
  const listId = useId()
  const aria = useFieldControl({})
  const highlight = useTopResult(
    (groups.data ?? []).filter((group) => !exclude.includes(group.id)).map((group) => group.id),
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
              <UsersRound aria-hidden="true" className="size-4 shrink-0 text-muted" />
              <span className="truncate">{value.name}</span>
            </span>
          ) : (
            <span className="truncate text-muted">{placeholder}</span>
          )}
          <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 shrink-0 text-muted" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-(--radix-popover-trigger-width) min-w-72 p-0"
        aria-label="Find a group"
      >
        <Command shouldFilter={false} {...highlight}>
          <CommandInput value={q} onValueChange={setQ} placeholder="Search groups by name…" />
          {groups.isPending && (
            <p role="status" className="px-3 py-6 text-center text-sm text-muted">
              Searching…
            </p>
          )}
          <CommandList
            id={listId}
            aria-label="Groups"
            empty={
              groups.isPending
                ? undefined
                : q
                  ? `No group matches “${q}”`
                  : 'No groups yet. A platform admin creates them in Admin settings.'
            }
          >
            <CommandGroup>
              {groups.data?.map((group) => {
                const taken = exclude.includes(group.id)
                return (
                  <CommandItem
                    key={group.id}
                    value={group.id}
                    disabled={taken}
                    onSelect={() => {
                      onChange(group)
                      setOpen(false)
                      setQ('')
                    }}
                    className="h-auto min-h-10 py-1.5 sm:h-auto"
                  >
                    <span
                      aria-hidden="true"
                      className="flex size-6 shrink-0 items-center justify-center rounded-md border bg-surface text-muted"
                    >
                      <UsersRound className="size-3.5" />
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">{group.name}</span>
                      <span className="truncate text-xs text-muted">
                        {peopleCount(group.member_count)}
                        {group.description ? ` · ${group.description}` : ''}
                      </span>
                    </span>
                    {taken && (
                      <span className="ml-auto shrink-0 pl-2 text-xs whitespace-nowrap text-muted">
                        {excludeHint}
                      </span>
                    )}
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
