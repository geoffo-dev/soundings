import {
  Check,
  ChevronDown,
  CircleDashed,
  Search,
  Tag,
  TriangleAlert,
  UserRound,
  UsersRound,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode, type Ref } from 'react'

import { useProjectMembers, useProjectTags } from '@/api/projects'
import { useDebouncedValue } from '@/api/search'
import type { IdeaStatus, Project, StatusLabels, UserRef } from '@/api/types'
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
  CommandSeparator,
} from '@/components/ui/command'
import { FilterChip } from '@/components/ui/filter-chip'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { StatusDot } from '@/components/ui/status-badge'
import { useCurrentUser } from '@/features/auth/current-user'
import { IDEA_STATUSES, statusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

import {
  clearFilters,
  hasActiveFilters,
  toggleValue,
  type ProjectSearch,
  type ProjectView,
} from './project-search'

export interface FilterBarProps {
  project: Project
  search: ProjectSearch
  view: ProjectView
  onChange: (next: ProjectSearch) => void
  /** Focused by the "f" shortcut. */
  searchRef?: Ref<HTMLInputElement>
  /** Names of owners seen in the loaded ideas, to label the owner chip before members load. */
  knownPeople?: UserRef[]
}

/**
 * Filter chips (wireframe 02): text search, status (List only), owner, tag,
 * "Needs evaluators", "High disagreement", and Clear. Everything lives in the
 * URL, so a filtered view is a shareable link.
 */
export function FilterBar({
  project,
  search,
  view,
  onChange,
  searchRef,
  knownPeople,
}: FilterBarProps) {
  const set = (patch: Partial<ProjectSearch>) => onChange({ ...search, ...patch })
  const active = hasActiveFilters(search, view)

  return (
    <div
      role="group"
      aria-label="Filters"
      className="-mx-4 scrollbar-none flex items-center gap-2 overflow-x-auto px-4 py-0.5 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
    >
      <SearchField value={search.q} onChange={(q) => set({ q })} inputRef={searchRef} />
      {view === 'list' && (
        <StatusFilter
          labels={project.status_labels}
          value={search.status}
          onChange={(status) => set({ status, resolution: undefined })}
        />
      )}
      <OwnerFilter
        slug={project.slug}
        value={search.owner}
        onChange={(owner) => set({ owner })}
        knownPeople={knownPeople}
      />
      <TagFilter slug={project.slug} value={search.tag} onChange={(tag) => set({ tag })} />
      <FilterChip
        pressed={Boolean(search.needs_evaluators)}
        onPressedChange={(on) => set({ needs_evaluators: on ? true : undefined })}
        icon={<UsersRound aria-hidden="true" />}
      >
        Needs evaluators
      </FilterChip>
      <FilterChip
        pressed={Boolean(search.high_disagreement)}
        onPressedChange={(on) => set({ high_disagreement: on ? true : undefined })}
        icon={<TriangleAlert aria-hidden="true" />}
      >
        High disagreement
      </FilterChip>
      {active && (
        <Button
          variant="ghost"
          size="sm"
          className="text-muted"
          onClick={() => onChange(clearFilters(search))}
        >
          Clear
        </Button>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Text search                                                         */
/* ------------------------------------------------------------------ */

const SEARCH_DELAY_MS = 250

/** Title, summary or key. Typing updates the URL after a short pause; Esc clears. */
function SearchField({
  value,
  onChange,
  inputRef,
}: {
  value: string | undefined
  onChange: (q: string | undefined) => void
  inputRef?: Ref<HTMLInputElement>
}) {
  const [text, setText] = useState(value ?? '')
  // The URL value this field last agreed with; a different one came from outside (Clear, Back).
  const [synced, setSynced] = useState(value ?? '')
  if ((value ?? '') !== synced) {
    setSynced(value ?? '')
    setText(value ?? '')
  }
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const push = (next: string) => {
    window.clearTimeout(timer.current)
    const q = next.trim()
    setSynced(q)
    if (q !== (value ?? '')) onChange(q || undefined)
  }

  return (
    <Input
      ref={inputRef}
      type="search"
      aria-label="Search ideas"
      placeholder="Search ideas…"
      startIcon={<Search />}
      value={text}
      maxLength={200}
      className="w-44 shrink-0 sm:w-52 [&_input]:h-7 sm:[&_input]:text-sm"
      onChange={(event) => {
        const next = event.target.value
        setText(next)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => push(next), SEARCH_DELAY_MS)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') push(text)
        if (event.key === 'Escape' && text) {
          event.preventDefault()
          setText('')
          push('')
        }
      }}
    />
  )
}

/* ------------------------------------------------------------------ */
/* Menu chips                                                          */
/* ------------------------------------------------------------------ */

const chip = cn(
  'inline-flex h-7 shrink-0 items-center rounded-md border text-sm whitespace-nowrap',
  'transition-[background-color,border-color,color] duration-150',
)

/**
 * A filter with a menu: "Owner ▾" when unset, "Owner  Alice Anders ▾ ×" when
 * set (the × clears it).
 */
function FilterMenu({
  label,
  icon,
  value,
  onClear,
  children,
}: {
  label: string
  icon: ReactNode
  /** Human-readable value; undefined when the filter is off. */
  value: ReactNode
  onClear: () => void
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const active = value !== undefined && value !== null
  return (
    <span
      className={cn(
        chip,
        active
          ? 'border-accent/40 bg-accent-subtle text-accent'
          : 'bg-surface text-secondary hover:border-strong hover:text-primary',
      )}
    >
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(
              'inline-flex h-full items-center gap-1.5 rounded-md pr-1.5 pl-2.5 font-medium',
              'data-[state=open]:bg-subtle [&_svg]:size-3.5 [&_svg]:shrink-0',
              active && 'rounded-r-none pr-2',
            )}
          >
            {icon}
            {label}
            {active && (
              <>
                <span aria-hidden="true" className="text-accent/60">
                  ·
                </span>
                <span className="max-w-40 truncate">{value}</span>
              </>
            )}
            <ChevronDown aria-hidden="true" className="opacity-60" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-64 p-0" align="start">
          {children(() => setOpen(false))}
        </PopoverContent>
      </Popover>
      {active && (
        <button
          type="button"
          aria-label={`Remove ${label.toLowerCase()} filter`}
          onClick={onClear}
          className="inline-flex h-full w-7 items-center justify-center rounded-r-md border-l border-accent/25 transition-colors hover:bg-accent/10"
        >
          <X aria-hidden="true" className="size-3.5" />
        </button>
      )}
    </span>
  )
}

/** A checkable row in a filter menu. */
function OptionItem({
  value,
  checked,
  onSelect,
  children,
  keywords,
}: {
  value: string
  checked: boolean
  onSelect: () => void
  children: ReactNode
  keywords?: string[]
}) {
  return (
    <CommandItem
      value={value}
      keywords={keywords}
      onSelect={onSelect}
      aria-checked={checked}
      className="gap-2"
    >
      {children}
      <Check
        aria-hidden="true"
        className={cn('ml-auto text-accent!', checked ? 'opacity-100' : 'opacity-0')}
      />
    </CommandItem>
  )
}

function summarise(values: string[]): string {
  const [first, ...rest] = values
  return rest.length === 0 ? (first ?? '') : `${first ?? ''} +${rest.length}`
}

/* ------------------------------------------------------------------ */
/* Status (List only)                                                  */
/* ------------------------------------------------------------------ */

function StatusFilter({
  labels,
  value,
  onChange,
}: {
  labels: StatusLabels
  value: IdeaStatus[] | undefined
  onChange: (value: IdeaStatus[] | undefined) => void
}) {
  const chosen = IDEA_STATUSES.filter((status) => value?.includes(status))
  return (
    <FilterMenu
      label="Status"
      icon={<CircleDashed aria-hidden="true" />}
      value={chosen.length ? summarise(chosen.map((status) => labels[status])) : undefined}
      onClear={() => onChange(undefined)}
    >
      {() => (
        <Command>
          <CommandList aria-label="Statuses">
            <CommandGroup>
              {IDEA_STATUSES.map((status) => (
                <OptionItem
                  key={status}
                  value={status}
                  keywords={[labels[status]]}
                  checked={chosen.includes(status)}
                  onSelect={() => onChange(toggleValue(value, status))}
                >
                  <StatusDot tone={statusTone(status, null)} />
                  {labels[status]}
                </OptionItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      )}
    </FilterMenu>
  )
}

/* ------------------------------------------------------------------ */
/* Owner: me, nobody, or a person                                      */
/* ------------------------------------------------------------------ */

function OwnerFilter({
  slug,
  value,
  onChange,
  knownPeople = [],
}: {
  slug: string
  value: string | undefined
  onChange: (value: string | undefined) => void
  knownPeople?: UserRef[]
}) {
  const me = useCurrentUser()
  const members = useProjectMembers(slug)
  const person =
    value && value !== 'me' && value !== 'none'
      ? (members.data?.find((m) => m.user.id === value)?.user ??
        knownPeople.find((p) => p.id === value))
      : undefined
  const label =
    value === 'me'
      ? 'Me'
      : value === 'none'
        ? 'No owner'
        : value
          ? (person?.display_name ?? 'Someone')
          : undefined

  return (
    <FilterMenu
      label="Owner"
      icon={<UserRound aria-hidden="true" />}
      value={label}
      onClear={() => onChange(undefined)}
    >
      {(close) => (
        <OwnerOptions
          slug={slug}
          meId={me.id}
          value={value}
          onSelect={(next) => {
            onChange(next === value ? undefined : next)
            close()
          }}
        />
      )}
    </FilterMenu>
  )
}

function OwnerOptions({
  slug,
  meId,
  value,
  onSelect,
}: {
  slug: string
  meId: string
  value: string | undefined
  onSelect: (value: string) => void
}) {
  const [q, setQ] = useState('')
  const debounced = useDebouncedValue(q.trim())
  const people = useUserSearch({ q: debounced, project: slug })
  const needle = q.trim().toLowerCase()
  const showMe = !needle || 'me'.includes(needle)
  const showNone = !needle || 'no owner unowned nobody'.includes(needle)
  const others = (people.data?.items ?? []).filter((person) => person.id !== meId)

  return (
    <Command shouldFilter={false}>
      <CommandInput value={q} onValueChange={setQ} placeholder="Search people…" />
      <CommandList aria-label="Owners">
        {(showMe || showNone) && (
          <CommandGroup>
            {showMe && (
              <OptionItem value="me" checked={value === 'me'} onSelect={() => onSelect('me')}>
                <UserRound aria-hidden="true" />
                Me
              </OptionItem>
            )}
            {showNone && (
              <OptionItem value="none" checked={value === 'none'} onSelect={() => onSelect('none')}>
                <CircleDashed aria-hidden="true" />
                No owner
              </OptionItem>
            )}
          </CommandGroup>
        )}
        {(showMe || showNone) && others.length > 0 && <CommandSeparator />}
        {others.length > 0 && (
          <CommandGroup heading="People">
            {others.map((person) => (
              <OptionItem
                key={person.id}
                value={person.id}
                checked={value === person.id}
                onSelect={() => onSelect(person.id)}
              >
                <Avatar size="xs" name={person.display_name} src={person.avatar_url} decorative />
                <span className="truncate">{person.display_name}</span>
              </OptionItem>
            ))}
          </CommandGroup>
        )}
        {!showMe && !showNone && others.length === 0 && !people.isFetching && (
          <CommandEmpty>No one matches</CommandEmpty>
        )}
      </CommandList>
    </Command>
  )
}

/* ------------------------------------------------------------------ */
/* Tags                                                                */
/* ------------------------------------------------------------------ */

function TagFilter({
  slug,
  value,
  onChange,
}: {
  slug: string
  value: string[] | undefined
  onChange: (value: string[] | undefined) => void
}) {
  const tags = useProjectTags(slug)
  const chosen = value ?? []
  const isChosen = (name: string) => chosen.some((t) => t.toLowerCase() === name.toLowerCase())
  const toggle = (name: string) => {
    const next = isChosen(name)
      ? chosen.filter((t) => t.toLowerCase() !== name.toLowerCase())
      : [...chosen, name]
    onChange(next.length ? next.slice(0, 10) : undefined)
  }

  return (
    <FilterMenu
      label="Tag"
      icon={<Tag aria-hidden="true" />}
      value={chosen.length ? summarise(chosen) : undefined}
      onClear={() => onChange(undefined)}
    >
      {() => (
        <Command>
          <CommandInput placeholder="Search tags…" />
          <CommandList aria-label="Tags">
            {tags.isPending ? (
              <p className="px-3 py-6 text-center text-sm text-muted">Loading tags…</p>
            ) : (
              <>
                <CommandEmpty>
                  {tags.data?.length ? 'No tags match' : 'No ideas are tagged yet'}
                </CommandEmpty>
                <CommandGroup>
                  {/* Chosen tags that no visible idea carries any more stay removable. */}
                  {chosen
                    .filter(
                      (name) =>
                        !tags.data?.some((t) => t.name.toLowerCase() === name.toLowerCase()),
                    )
                    .map((name) => (
                      <OptionItem key={name} value={name} checked onSelect={() => toggle(name)}>
                        <span className="truncate">{name}</span>
                      </OptionItem>
                    ))}
                  {tags.data?.map((tag) => (
                    <OptionItem
                      key={tag.id}
                      value={tag.name}
                      checked={isChosen(tag.name)}
                      onSelect={() => toggle(tag.name)}
                    >
                      <span className="truncate">{tag.name}</span>
                      <span className="text-xs text-muted tabular-nums">{tag.idea_count}</span>
                    </OptionItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      )}
    </FilterMenu>
  )
}
