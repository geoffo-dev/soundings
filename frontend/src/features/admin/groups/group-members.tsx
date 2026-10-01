import { Ellipsis, UsersRound } from 'lucide-react'
import { useRef, useState } from 'react'

import { useAddGroupMember, useGroupMembers, useRemoveGroupMember } from '@/api/admin'
import type { Group, GroupMember, UserSearchResult } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import { formatShortDate } from '@/lib/dates'
import { PersonPicker } from '@/features/project/settings/person-picker'

import { AdminSection } from '@/features/admin/settings-frame'
import { SearchField } from '@/features/admin/search-field'
import { ProvenanceBadges } from '@/features/admin/users/user-badges'

/**
 * A group's members with provenance (contract-phase2 §3.6): people added by
 * hand (Manual) can be removed with Undo; people added by sign-in sync
 * (Synced) follow the identity provider, so their rows are read-only apart
 * from a tucked-away "Remove until next sign-in" (the lever for an additive
 * group, or to cut access now). Deactivated members are listed, flagged.
 */
export function GroupMembers({ group }: { group: Group }) {
  const [q, setQ] = useState('')
  const query = useGroupMembers(group.id, q)
  const members = query.data?.pages.flatMap((page) => page.items) ?? []
  const add = useAddGroupMember(group.id)
  const remove = useRemoveGroupMember(group.id, group.name)
  const [person, setPerson] = useState<UserSearchResult | null>(null)
  const pickerRef = useRef<HTMLButtonElement>(null)
  const manualIds = members.filter((m) => m.manual).map((m) => m.user.id)

  const submit = () => {
    if (!person || add.isPending) return
    add.mutate(person.id, {
      onSuccess: (member) => {
        toast.success(`${member.user.display_name} added to ${group.name}`, {
          description: member.synced
            ? 'Already synced from the identity provider; now also added by hand.'
            : undefined,
        })
        setPerson(null)
        pickerRef.current?.focus()
      },
    })
  }

  const counts =
    group.member_count === 0
      ? 'Nobody yet.'
      : `${group.member_count} active ${group.member_count === 1 ? 'member' : 'members'}: ${group.manual_member_count} added by hand, ${group.synced_member_count} synced from the identity provider.`

  return (
    <AdminSection
      id="members"
      title="Members"
      description={`${counts} Deactivated people are listed but get no access.`}
    >
      <form
        className="flex flex-col gap-2 rounded-lg border bg-background p-3 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <Field label="Add a person by hand" className="min-w-0 flex-1">
          <PersonPicker
            ref={pickerRef}
            value={person}
            onChange={setPerson}
            exclude={manualIds}
            excludeHint="Already added"
            placeholder="Search by name or email…"
          />
        </Field>
        <Button type="submit" variant="secondary" disabled={!person} loading={add.isPending}>
          Add
        </Button>
      </form>
      <p className="text-sm text-muted">Sign-in sync never touches people added by hand.</p>

      {(group.member_count > 10 || q) && (
        <SearchField
          value={q || undefined}
          onChange={(next) => setQ(next ?? '')}
          label="Search members"
          placeholder="Search members…"
        />
      )}

      {query.isPending ? (
        <SkeletonGroup label="Loading members" className="overflow-hidden rounded-lg border">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="flex h-13 items-center gap-3 border-b border-subtle px-4 last:border-0"
            >
              <Skeleton className="size-7 rounded-full" />
              <div className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-3.5 w-36" />
                <Skeleton className="h-3 w-48" />
              </div>
            </div>
          ))}
        </SkeletonGroup>
      ) : query.isError && members.length === 0 ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<UsersRound />}
          title="Couldn’t load the members"
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : members.length === 0 ? (
        <EmptyState
          size="compact"
          className="rounded-lg border"
          icon={<UsersRound />}
          title={q ? `No members match “${q}”` : 'No members yet'}
          description={
            q
              ? undefined
              : group.idp_values.length > 0
                ? 'People in the mapped identity provider groups join at their next sign-in. You can also add people by hand.'
                : 'Add people by hand, or map the group to your identity provider.'
          }
        />
      ) : (
        <div className="flex flex-col gap-2">
          <ul
            aria-label="Members"
            className="divide-y divide-subtle overflow-hidden rounded-lg border"
          >
            {members.map((member) => (
              <MemberRow
                key={member.user.id}
                member={member}
                removing={remove.isPending && remove.variables.user.id === member.user.id}
                onRemove={() => remove.mutate(member)}
              />
            ))}
          </ul>
          {query.hasNextPage && (
            <Button
              variant="ghost"
              size="sm"
              className="self-center text-secondary"
              loading={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              Show more members
            </Button>
          )}
        </div>
      )}
    </AdminSection>
  )
}

function MemberRow({
  member,
  removing,
  onRemove,
}: {
  member: GroupMember
  removing: boolean
  onRemove: () => void
}) {
  const { user } = member
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5">
      <Avatar size="sm" name={user.display_name} src={user.avatar_url} decorative />
      <div className="flex min-w-0 flex-1 flex-col">
        <span
          className={
            member.is_active
              ? 'truncate text-sm font-medium text-primary'
              : 'truncate text-sm font-medium text-secondary'
          }
        >
          {user.display_name}
        </span>
        <span className="truncate text-xs text-muted">
          {member.email} · joined {formatShortDate(member.joined_at)}
        </span>
      </div>
      <span className="flex items-center gap-1">
        {!member.is_active && <Badge variant="outline">Deactivated</Badge>}
        <ProvenanceBadges manual={member.manual} synced={member.synced} />
      </span>
      {member.manual ? (
        <Button
          variant="ghost"
          size="sm"
          className="text-secondary"
          loading={removing}
          aria-label={`Remove ${user.display_name}`}
          onClick={onRemove}
        >
          Remove
        </Button>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`More for ${user.display_name} (synced from the identity provider)`}
            >
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="max-w-72">
            <p className="px-2 py-1.5 text-xs text-muted">
              Synced from the identity provider: change it there. Removing them here lasts until
              their next sign-in.
            </p>
            <DropdownMenuItem onSelect={onRemove}>Remove until next sign-in</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </li>
  )
}
