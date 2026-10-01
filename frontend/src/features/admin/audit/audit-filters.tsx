import { CalendarDays, FolderKanban, ListFilter, UserRound, X } from 'lucide-react'
import { useState } from 'react'

import { useAdminGroupName, useAdminUserName, useAdminUsers } from '@/api/admin'
import { useProjects } from '@/api/projects'
import { useDebouncedValue } from '@/api/search'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandList,
  useTopResult,
} from '@/components/ui/command'
import { DatePicker } from '@/components/ui/date-picker'
import { Field } from '@/components/ui/field'
import { FilterMenu, FilterMenuOption } from '@/components/ui/filter-menu'
import { useNow } from '@/components/ui/relative-time'
import { formatShortDate } from '@/lib/dates'

import { AUDIT_CATEGORIES, type AuditCategory } from './audit-categories'
import {
  DATE_PRESETS,
  hasAuditFilters,
  matchingPreset,
  parseTarget,
  presetFrom,
  type AuditSearch,
} from './audit-search'

/**
 * Audit log filters (contract-phase2 §3.11): who did it, what kind of action,
 * which project, which days, and (from a user's or group's page) what it was
 * about. All in the URL, so a filtered log is a shareable link.
 */
export function AuditFilters({
  search,
  onChange,
}: {
  search: AuditSearch
  /** Merged into the URL's current search. */
  onChange: (patch: Partial<AuditSearch>) => void
}) {
  const set = onChange
  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-1.5">
      <TargetChip target={search.target} onClear={() => set({ target: undefined })} />
      <ActorFilter value={search.actor} onChange={(actor) => set({ actor })} />
      <ActionFilter value={search.action} onChange={(action) => set({ action })} />
      <ProjectFilter value={search.project} onChange={(project) => set({ project })} />
      <DateFilter from={search.from} to={search.to} onChange={(from, to) => set({ from, to })} />
      {hasAuditFilters(search) && (
        <Button
          variant="ghost"
          size="sm"
          className="text-secondary"
          onClick={() =>
            onChange({
              actor: undefined,
              action: undefined,
              project: undefined,
              from: undefined,
              to: undefined,
              target: undefined,
            })
          }
        >
          Clear filters
        </Button>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */

function ActorFilter({
  value,
  onChange,
}: {
  value: string | undefined
  onChange: (value: string | undefined) => void
}) {
  const name = useAdminUserName(value)
  return (
    <FilterMenu
      label="Who"
      icon={<UserRound aria-hidden="true" />}
      value={value ? (name.data ?? (name.isPending ? '…' : 'A deleted user')) : undefined}
      onClear={() => onChange(undefined)}
    >
      {(close) => (
        <ActorOptions
          value={value}
          onSelect={(id) => {
            onChange(id === value ? undefined : id)
            close()
          }}
        />
      )}
    </FilterMenu>
  )
}

function ActorOptions({
  value,
  onSelect,
}: {
  value: string | undefined
  onSelect: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const debounced = useDebouncedValue(q.trim())
  // Every account, the break-glass admin and agents included (unlike people pickers).
  const users = useAdminUsers({ q: debounced }, { limit: 20 })
  const people = users.data?.pages[0]?.items ?? []
  const highlight = useTopResult(people.map((person) => person.id))
  return (
    <Command shouldFilter={false} {...highlight}>
      <CommandInput value={q} onValueChange={setQ} placeholder="Search people…" />
      <CommandList
        aria-label="People"
        empty={users.isFetching ? undefined : q ? `No one matches “${q}”` : 'No one yet'}
      >
        {people.length > 0 && (
          <CommandGroup>
            {people.map((person) => (
              <FilterMenuOption
                key={person.id}
                value={person.id}
                checked={person.id === value}
                onSelect={() => onSelect(person.id)}
              >
                <Avatar size="xs" name={person.display_name} src={person.avatar_url} decorative />
                <span className="truncate">{person.display_name}</span>
              </FilterMenuOption>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </Command>
  )
}

/* ------------------------------------------------------------------ */

function ActionFilter({
  value = [],
  onChange,
}: {
  value: AuditCategory[] | undefined
  onChange: (value: AuditCategory[] | undefined) => void
}) {
  const chosen = AUDIT_CATEGORIES.filter((category) => value.includes(category.id))
  const toggle = (id: AuditCategory) => {
    const next = value.includes(id) ? value.filter((v) => v !== id) : [...value, id]
    onChange(next.length ? next : undefined)
  }
  return (
    <FilterMenu
      label="What"
      icon={<ListFilter aria-hidden="true" />}
      value={
        chosen.length === 0
          ? undefined
          : chosen.length === 1
            ? chosen[0]?.label
            : `${chosen[0]?.label ?? ''} +${chosen.length - 1}`
      }
      onClear={() => onChange(undefined)}
      menuClassName="w-72"
    >
      {() => (
        <Command>
          <CommandList aria-label="Kinds of action">
            <CommandGroup>
              {AUDIT_CATEGORIES.map((category) => (
                <FilterMenuOption
                  key={category.id}
                  value={category.id}
                  keywords={[category.label]}
                  checked={value.includes(category.id)}
                  onSelect={() => toggle(category.id)}
                >
                  {category.label}
                </FilterMenuOption>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      )}
    </FilterMenu>
  )
}

/* ------------------------------------------------------------------ */

function ProjectFilter({
  value,
  onChange,
}: {
  value: string | undefined
  onChange: (value: string | undefined) => void
}) {
  const projects = useProjects(true)
  const current = projects.data?.find((project) => project.id === value)
  return (
    <FilterMenu
      label="Project"
      icon={<FolderKanban aria-hidden="true" />}
      value={
        value ? (current?.name ?? (projects.isPending ? '…' : 'A deleted project')) : undefined
      }
      onClear={() => onChange(undefined)}
    >
      {(close) => (
        <Command>
          {(projects.data?.length ?? 0) > 6 && <CommandInput placeholder="Search projects…" />}
          <CommandList aria-label="Projects" empty={projects.isPending ? undefined : 'No projects'}>
            <CommandGroup>
              {projects.data?.map((project) => (
                <FilterMenuOption
                  key={project.id}
                  value={project.id}
                  keywords={[project.name, project.key]}
                  checked={project.id === value}
                  onSelect={() => {
                    onChange(project.id === value ? undefined : project.id)
                    close()
                  }}
                >
                  <span className="truncate">{project.name}</span>
                </FilterMenuOption>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      )}
    </FilterMenu>
  )
}

/* ------------------------------------------------------------------ */

function DateFilter({
  from,
  to,
  onChange,
}: {
  from: string | undefined
  to: string | undefined
  onChange: (from: string | undefined, to: string | undefined) => void
}) {
  const day = (value: string) => formatShortDate(`${value}T12:00:00`)
  const now = useNow()
  const preset = matchingPreset(from, to, now)
  const label = preset
    ? preset.label
    : from && to
      ? from === to
        ? day(from)
        : `${day(from)} – ${day(to)}`
      : from
        ? `From ${day(from)}`
        : to
          ? `Until ${day(to)}`
          : undefined
  return (
    <FilterMenu
      label="When"
      icon={<CalendarDays aria-hidden="true" />}
      value={label}
      onClear={() => onChange(undefined, undefined)}
      menuClassName="w-auto p-3"
    >
      {(close) => (
        <div className="flex flex-col gap-3">
          <div role="group" aria-label="Quick ranges" className="flex flex-wrap gap-1.5">
            {DATE_PRESETS.map((option) => (
              <Button
                key={option.days}
                variant="outline"
                size="sm"
                aria-pressed={preset?.days === option.days}
                className="aria-pressed:border-accent/40 aria-pressed:bg-accent-subtle aria-pressed:text-accent"
                onClick={() => {
                  onChange(presetFrom(option.days, now), undefined)
                  close()
                }}
              >
                {option.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Field label="From">
              <DatePicker
                value={from ?? ''}
                max={to}
                onValueChange={(next) => onChange(next || undefined, to)}
              />
            </Field>
            <Field label="To (inclusive)">
              <DatePicker
                value={to ?? ''}
                min={from}
                onValueChange={(next) => onChange(from, next || undefined)}
              />
            </Field>
          </div>
          <p className="text-xs text-muted">Days in your time zone.</p>
        </div>
      )}
    </FilterMenu>
  )
}

/* ------------------------------------------------------------------ */

/** "About · Bob Brown ×": set from a user's or group's "Audit log" link. */
function TargetChip({ target, onClear }: { target: string | undefined; onClear: () => void }) {
  const parsed = parseTarget(target)
  const user = useAdminUserName(parsed?.type === 'user' ? parsed.id : undefined)
  const group = useAdminGroupName(parsed?.type === 'group' ? parsed.id : undefined)
  const projects = useProjects(true)
  if (!parsed) return null
  const name =
    parsed.type === 'user'
      ? user.data
      : parsed.type === 'group'
        ? group.data
        : parsed.type === 'project'
          ? projects.data?.find((p) => p.id === parsed.id)?.name
          : undefined
  const label = name ?? `this ${parsed.type}`
  return (
    <span className="inline-flex h-7 shrink-0 items-center overflow-hidden rounded-md border border-accent/40 bg-accent-subtle text-sm whitespace-nowrap text-accent">
      <span className="pr-2 pl-2.5 font-medium">
        About <span aria-hidden="true">·</span> <span className="max-w-40 truncate">{label}</span>
      </span>
      <button
        type="button"
        aria-label={`Remove “about ${label}” filter`}
        onClick={onClear}
        className="inline-flex h-full w-7 items-center justify-center border-l border-accent/25 transition-colors hover:bg-accent/10"
      >
        <X aria-hidden="true" className="size-3.5" />
      </button>
    </span>
  )
}
