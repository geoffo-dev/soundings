import { Link } from '@tanstack/react-router'
import { CircleDashed, CloudOff, KeyRound, UserRound } from 'lucide-react'
import { useRef, useState } from 'react'

import { useAdminUserName } from '@/api/admin'
import {
  containsWholeKey,
  keySearchTerm,
  useAdminApiKeys,
  useRevokeAdminApiKey,
} from '@/api/api-keys'
import type { AdminApiKey } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandGroup, CommandList } from '@/components/ui/command'
import { EmptyState } from '@/components/ui/empty-state'
import { FilterValueChip } from '@/components/ui/filter-chip'
import { FilterMenu, FilterMenuOption } from '@/components/ui/filter-menu'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import { SearchField } from '@/features/admin/search-field'
import { AdminPageHeader } from '@/features/admin/settings-frame'
import { formatDateTime, formatShortDate } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'
import { ROW_ID_ATTRIBUTE } from '@/lib/return-to-row'
import { useShortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import {
  hasAdminKeyFilters,
  KEY_STATES,
  STATE_LABELS,
  toAdminKeyFilters,
  type AdminKeysSearch,
} from './admin-keys-search'
import { KeyExpiry, KeyLastUsed, KeyProjects, KeyStateBadge, ScopeBadges } from './key-parts'
import { RevokeKeyDialog } from './revoke-key-dialog'

/**
 * Admin settings → API keys (contract-phase5 §3.10, `api_key.manage_any`):
 * every key that isn't revoked, of every person and agent, newest first, with
 * search (a name, an owner, or a key's prefix: a pasted whole key is cut to its
 * prefix before anything is sent), a state filter, one owner's keys
 * (`?user_id=`), and Revoke (confirmed: no undo).
 */
export function AdminApiKeysPage({
  search,
  onSearchChange,
}: {
  search: AdminKeysSearch
  onSearchChange: (patch: Partial<AdminKeysSearch>) => void
}) {
  const searchRef = useRef<HTMLInputElement>(null)
  useShortcut('focusFilters', () => searchRef.current?.focus())
  const owner = useAdminUserName(search.user_id)
  // A whole key was pasted: say that only its prefix was searched (until the next search).
  const [cutKey, setCutKey] = useState(false)

  return (
    <>
      <AdminPageHeader
        title="All API keys"
        description="Every key people and AI agents use with the API and MCP. A key acts as its owner and stops working the moment it is revoked."
      />
      <div
        role="group"
        aria-label="Filters"
        className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-1.5"
      >
        <SearchField
          value={search.q}
          // A pasted whole key never reaches the URL or the API: only its prefix.
          onChange={(q) => {
            setCutKey(q !== undefined && containsWholeKey(q))
            onSearchChange({ q: q === undefined ? undefined : keySearchTerm(q) })
          }}
          label="Search API keys"
          placeholder="Name, owner or sdg_ prefix…"
          inputRef={searchRef}
          className="sm:w-64"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          <FilterMenu
            label="State"
            icon={<CircleDashed aria-hidden="true" />}
            value={search.state ? STATE_LABELS[search.state].label : undefined}
            onClear={() => onSearchChange({ state: undefined })}
            menuClassName="w-64"
          >
            {(close) => (
              <Command>
                <CommandList aria-label="States">
                  <CommandGroup>
                    {KEY_STATES.map((state) => (
                      <FilterMenuOption
                        key={state}
                        value={state}
                        checked={search.state === state}
                        onSelect={() => {
                          onSearchChange({ state: search.state === state ? undefined : state })
                          close()
                        }}
                      >
                        <span className="flex flex-col">
                          <span>{STATE_LABELS[state].label}</span>
                          <span className="text-xs text-muted">
                            {STATE_LABELS[state].description}
                          </span>
                        </span>
                      </FilterMenuOption>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            )}
          </FilterMenu>
          {search.user_id && (
            <FilterValueChip
              field="Owner"
              icon={<UserRound aria-hidden="true" />}
              value={owner.data ?? (owner.isPending ? '…' : 'Unknown user')}
              onRemove={() => onSearchChange({ user_id: undefined })}
            />
          )}
        </div>
      </div>
      {cutKey && search.q && (
        <p role="status" className="-mt-2 text-sm text-muted">
          You pasted a whole key: only its prefix, <code className="font-mono">{search.q}</code>,
          was searched. The secret part never left this page.
        </p>
      )}
      <KeysList
        search={search}
        onClear={() => onSearchChange({ q: undefined, state: undefined, user_id: undefined })}
      />
    </>
  )
}

function KeysList({ search, onClear }: { search: AdminKeysSearch; onClear: () => void }) {
  const query = useAdminApiKeys(toAdminKeyFilters(search))
  const revoke = useRevokeAdminApiKey()
  const [revoking, setRevoking] = useState<AdminApiKey | null>(null)
  const keys = query.data?.pages.flatMap((page) => page.items) ?? []
  const total = query.data?.pages[0]?.total ?? 0

  const confirm = () => {
    if (!revoking) return
    const index = keys.findIndex((key) => key.id === revoking.id)
    const next = keys[index + 1] ?? keys[index - 1]
    const { name, owner } = revoking
    revoke.mutate(revoking.id, {
      onSuccess: () => {
        setRevoking(null)
        toast.success(`${owner.display_name}’s key “${name}” revoked`, {
          description: 'It stopped working immediately.',
        })
        focusWhenRendered(
          () =>
            (next &&
              document.querySelector<HTMLElement>(
                `[${ROW_ID_ATTRIBUTE}="${CSS.escape(next.id)}"]`,
              )) ??
            document.querySelector<HTMLElement>('input[type="search"]'),
          { force: true },
        )
      },
      onError: () => setRevoking(null),
    })
  }

  if (query.isPending) {
    return (
      <SkeletonGroup label="Loading API keys" className="overflow-hidden rounded-lg border">
        {Array.from({ length: 5 }, (_, i) => (
          <div
            key={i}
            className="flex h-15 items-center gap-3 border-b border-subtle px-4 last:border-0"
          >
            <Skeleton className="size-7 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="h-3 w-56" />
            </div>
            <Skeleton className="hidden h-5 w-28 sm:block" />
            <Skeleton className="hidden h-3 w-16 sm:block" />
          </div>
        ))}
      </SkeletonGroup>
    )
  }

  if (query.isError && keys.length === 0) {
    return (
      <EmptyState
        role="alert"
        size="compact"
        className="rounded-lg border"
        icon={<CloudOff />}
        title="Couldn’t load API keys"
        description="Check your connection and try again."
        action={
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Try again
          </Button>
        }
      />
    )
  }

  if (keys.length === 0) {
    return hasAdminKeyFilters(search) ? (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<KeyRound />}
        title="No keys match"
        description="A prefix must match exactly (sdg_ and 12 characters). Try a name or an owner, or clear the filters."
        action={
          <Button variant="secondary" onClick={onClear}>
            Clear filters
          </Button>
        }
      />
    ) : (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<KeyRound />}
        title="No API keys yet"
        description="People create their own in Settings → API keys. They will all be listed here."
      />
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted" aria-live="polite">
        {total === 1 ? '1 key' : `${total.toLocaleString()} keys`}
      </p>
      <div
        className={cn(
          'overflow-hidden rounded-lg border transition-opacity duration-150',
          query.isPlaceholderData && 'opacity-60',
        )}
        aria-busy={query.isPlaceholderData || undefined}
      >
        <Table mobile="container-cards" aria-label="API keys" className="@3xl:table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead>Key and owner</TableHead>
              <TableHead className="w-44">Scopes</TableHead>
              <TableHead className="w-36">Projects</TableHead>
              <TableHead className="w-28">Last used</TableHead>
              <TableHead className="w-28">Expires</TableHead>
              <TableHead className="w-20">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys.map((key) => (
              <KeyRow key={key.id} apiKey={key} onRevoke={() => setRevoking(key)} />
            ))}
          </TableBody>
        </Table>
        {query.hasNextPage && (
          <div className="flex justify-center border-t border-subtle py-2">
            <Button
              variant="ghost"
              size="sm"
              loading={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              Show more keys
            </Button>
          </div>
        )}
      </div>
      <RevokeKeyDialog
        apiKey={revoking}
        ownerName={revoking?.owner.display_name}
        pending={revoke.isPending}
        onCancel={() => setRevoking(null)}
        onConfirm={confirm}
      />
    </div>
  )
}

function KeyRow({ apiKey, onRevoke }: { apiKey: AdminApiKey; onRevoke: () => void }) {
  const owner = apiKey.owner
  const agent = apiKey.owner_is_service_account
  const createdBySomeoneElse = apiKey.created_by && apiKey.created_by.id !== owner.id
  return (
    <TableRow className="@3xl:h-15">
      <TableCell primary className="min-w-0">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar
            size="sm"
            name={owner.display_name}
            src={owner.avatar_url}
            isAgent={agent}
            decorative
          />
          <div
            tabIndex={-1}
            {...{ [ROW_ID_ATTRIBUTE]: apiKey.id }}
            className="flex min-w-0 flex-col gap-0.5 rounded-sm outline-offset-2"
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-medium text-primary">{apiKey.name}</span>
              {apiKey.state === 'dormant' && <KeyStateBadge state="dormant" audience="admin" />}
            </span>
            <span className="flex min-w-0 items-center gap-1 overflow-hidden text-xs text-muted">
              <Link
                to="/settings/users/$userId"
                params={{ userId: owner.id }}
                title={apiKey.owner_email || undefined}
                className="shrink-0 text-secondary hover:text-primary hover:underline"
              >
                {owner.display_name}
              </Link>
              {agent && (
                <Badge variant="accent" className="h-4 px-1">
                  AI agent
                </Badge>
              )}
              <span aria-hidden="true">·</span>
              <code className="min-w-0 truncate font-mono">{apiKey.prefix}</code>
            </span>
            <span className="truncate text-xs text-muted">
              {createdBySomeoneElse && apiKey.created_by
                ? `Created by ${apiKey.created_by.display_name}, `
                : 'Created '}
              <WithTooltip content={formatDateTime(apiKey.created_at)}>
                <time dateTime={apiKey.created_at}>{formatShortDate(apiKey.created_at)}</time>
              </WithTooltip>
            </span>
          </div>
        </div>
      </TableCell>
      <TableCell label="Scopes">
        <ScopeBadges scopes={apiKey.scopes} />
      </TableCell>
      <TableCell label="Projects" className="min-w-0">
        <KeyProjects apiKey={apiKey} />
      </TableCell>
      <TableCell label="Last used">
        <KeyLastUsed at={apiKey.last_used_at} />
      </TableCell>
      <TableCell label="Expires">
        <KeyExpiry apiKey={apiKey} />
      </TableCell>
      <TableCell className="@max-3xl:basis-full @max-3xl:items-start @3xl:text-right">
        <Button
          variant="ghost"
          size="sm"
          className="@max-3xl:-ml-2.5"
          aria-label={`Revoke ${owner.display_name}’s key ${apiKey.name}`}
          onClick={onRevoke}
        >
          Revoke
        </Button>
      </TableCell>
    </TableRow>
  )
}
