import { Link } from '@tanstack/react-router'
import { FlaskConical, Plus, UsersRound } from 'lucide-react'
import { useRef, useState } from 'react'

import { useAdminGroups } from '@/api/admin'
import type { GroupSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { NAV_ITEM_ATTRIBUTE, useListNavigation } from '@/lib/list-navigation'
import { ROW_ID_ATTRIBUTE, useReturnToRow } from '@/lib/return-to-row'
import { useShortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'
import { peopleCount } from '@/features/project/settings/access'

import { SearchField } from '@/features/admin/search-field'
import { AdminPageHeader } from '@/features/admin/settings-frame'
import { CreateGroupDialog } from './create-group-dialog'
import { EMPTY_MAPPING_TEST } from './mapping-test-panel'
import { MappingTestSheet } from './mapping-test-sheet'
import { syncModeLabel } from './mapping'

/**
 * Admin settings → Groups (contract-phase2 §3.5–3.7): every group with its
 * member count, how it is mapped to the identity provider, and how many
 * projects grant it a role. "Test mapping" checks a claim set against all of
 * them; "New group" creates one.
 */
export function GroupsPage() {
  const [creating, setCreating] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testDraft, setTestDraft] = useState(EMPTY_MAPPING_TEST)
  const [q, setQ] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  useShortcut('focusFilters', () => searchRef.current?.focus())

  return (
    <>
      <AdminPageHeader
        title="Groups"
        description="Give many people a project role at once."
        actions={
          <>
            <Button variant="outline" onClick={() => setTesting(true)}>
              <FlaskConical />
              Test mapping
            </Button>
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus />
              New group
            </Button>
          </>
        }
      />
      <SearchField
        value={q || undefined}
        onChange={(next) => setQ(next ?? '')}
        label="Search groups"
        placeholder="Search groups…"
        inputRef={searchRef}
      />
      <GroupsList q={q} onCreate={() => setCreating(true)} onClear={() => setQ('')} />
      <CreateGroupDialog open={creating} onOpenChange={setCreating} />
      <MappingTestSheet
        open={testing}
        onOpenChange={setTesting}
        draft={testDraft}
        onDraftChange={setTestDraft}
      />
    </>
  )
}

function GroupsList({
  q,
  onCreate,
  onClear,
}: {
  q: string
  onCreate: () => void
  onClear: () => void
}) {
  const query = useAdminGroups(q)
  const groups = query.data?.pages.flatMap((page) => page.items) ?? []
  const { listRef } = useListNavigation()
  // Back from a group's page ("All groups", the breadcrumb, Back): to its row.
  useReturnToRow('groups', groups.length > 0)

  if (query.isPending) {
    return (
      <SkeletonGroup label="Loading groups" className="overflow-hidden rounded-lg border">
        {Array.from({ length: 4 }, (_, i) => (
          <div
            key={i}
            className="flex h-14 items-center gap-4 border-b border-subtle px-4 last:border-0"
          >
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="h-3 w-64" />
            </div>
            <Skeleton className="hidden h-3 w-16 sm:block" />
            <Skeleton className="hidden h-5 w-32 sm:block" />
          </div>
        ))}
      </SkeletonGroup>
    )
  }

  if (query.isError && groups.length === 0) {
    return (
      <EmptyState
        role="alert"
        size="compact"
        className="rounded-lg border"
        icon={<UsersRound />}
        title="Couldn’t load groups"
        description="Check your connection and try again."
        action={
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Try again
          </Button>
        }
      />
    )
  }

  if (groups.length === 0) {
    return q ? (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<UsersRound />}
        title={`No groups match “${q}”`}
        action={
          <Button variant="secondary" onClick={onClear}>
            Clear search
          </Button>
        }
      />
    ) : (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<UsersRound />}
        title="No groups yet"
        description="Create a group to give a project role to many people at once, and map it to your identity provider."
        action={
          <Button variant="secondary" onClick={onCreate}>
            New group
          </Button>
        }
      />
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={listRef}
        className={cn(
          'overflow-hidden rounded-lg border transition-opacity duration-150',
          query.isPlaceholderData && 'opacity-60',
        )}
        aria-busy={query.isPlaceholderData || undefined}
      >
        <Table
          mobile="container-cards"
          cardFields="inline"
          aria-label="Groups"
          className="@3xl:table-fixed"
        >
          <TableHeader>
            <TableRow>
              <TableHead>Group</TableHead>
              <TableHead className="w-28">Members</TableHead>
              <TableHead className="w-64">Identity provider</TableHead>
              <TableHead className="w-24 text-right">Projects</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((group) => (
              <GroupRow key={group.id} group={group} />
            ))}
          </TableBody>
        </Table>
      </div>
      {query.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="self-center text-secondary"
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          Show more groups
        </Button>
      )}
    </div>
  )
}

function GroupRow({ group }: { group: GroupSummary }) {
  const mapped = group.idp_values.length > 0
  const shown = group.idp_values.slice(0, 2)
  const more = group.idp_values.length - shown.length
  return (
    <TableRow className="relative @3xl:h-14">
      <TableCell primary className="min-w-0">
        <Link
          to="/settings/groups/$groupId"
          params={{ groupId: group.id }}
          {...{ [NAV_ITEM_ATTRIBUTE]: '', [ROW_ID_ATTRIBUTE]: group.id }}
          className={cn(
            'flex min-w-0 flex-col outline-none',
            'after:absolute after:inset-0 after:rounded-sm',
            'focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-focus',
          )}
        >
          <span className="truncate font-medium text-primary">{group.name}</span>
          {group.description && (
            <span className="truncate text-xs text-muted">{group.description}</span>
          )}
        </Link>
      </TableCell>
      <TableCell label="Members" className="text-sm text-secondary tabular-nums">
        {peopleCount(group.member_count)}
      </TableCell>
      <TableCell label="Identity provider" className="min-w-0">
        {mapped ? (
          <span className="flex min-w-0 flex-wrap items-center gap-1">
            <span className="text-xs text-muted">{syncModeLabel(group.sync_mode)}:</span>
            {shown.map((value) => (
              <code
                key={value}
                className="max-w-40 truncate rounded-sm bg-subtle px-1.5 font-mono text-xs leading-5 text-secondary"
              >
                {value}
              </code>
            ))}
            {more > 0 && <span className="text-xs text-muted">+{more}</span>}
          </span>
        ) : (
          <span className="text-sm text-muted">Not mapped</span>
        )}
      </TableCell>
      <TableCell label="Projects" className="text-sm text-secondary tabular-nums @3xl:text-right">
        {group.project_count === 0 ? (
          <span className="text-muted">
            <span className="@max-3xl:hidden">None</span>
            <span className="@3xl:hidden">No projects</span>
          </span>
        ) : (
          <span>
            {group.project_count}
            <span className="@3xl:hidden">
              {group.project_count === 1 ? ' project' : ' projects'}
            </span>
          </span>
        )}
      </TableCell>
    </TableRow>
  )
}
