import { Link } from '@tanstack/react-router'
import { ChevronRight, CloudOff, Search, UserMinus, UsersRound } from 'lucide-react'
import { useId, useRef, useState, type ReactNode } from 'react'

import { describeError } from '@/api/errors'
import {
  useAddProjectGroupGrant,
  useAddProjectMember,
  useProjectAccess,
  useProjectGroupGrants,
  useProjectMembers,
  useRemoveProjectGroupGrant,
  useRemoveProjectMember,
  useUpdateProjectGroupGrant,
  useUpdateProjectMember,
} from '@/api/projects'
import { useDebouncedValue } from '@/api/search'
import type {
  GroupSearchResult,
  Member,
  Project,
  ProjectAccessEntry,
  ProjectGroupGrant,
  ProjectRole,
  UserSearchResult,
} from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import { useCurrentUser } from '@/features/auth/current-user'
import { cn } from '@/lib/utils'

import {
  describeSources,
  peopleCount,
  ROLE_OPTIONS,
  roleLabel,
  wouldLeaveNoAdmin,
  type AdminSource,
} from './access'
import { GroupPicker } from './group-picker'
import { PersonPicker } from './person-picker'
import { SettingsSection } from './settings-layout'

const LAST_ADMIN = 'A project needs at least one admin'

/**
 * Members (wireframe 07, contract-phase2 §3.7): who has a role here and why.
 * Groups with a role first (each covers many people), then people with a role
 * of their own; "Everyone with access" (each person's highest role and its
 * source) is folded away while it would mostly repeat those people. Admins add
 * people or groups, change roles and remove them (with Undo); the last admin,
 * direct or through a group, can't be demoted or removed.
 */
export function MembersSettings({ project }: { project: Project }) {
  const canManage = project.permissions.can_manage
  const members = useProjectMembers(project.slug)
  const grants = useProjectGroupGrants(project.slug)
  const admins = useProjectAccess(project.slug, { role: 'admin' })
  const adminEntries = admins.data?.pages.flatMap((page) => page.items) ?? []
  const adminsKnown = admins.isSuccess && !admins.hasNextPage
  /** Why a control is disabled: it would leave the project without an admin. */
  const lockReason = (source: AdminSource) =>
    adminsKnown && wouldLeaveNoAdmin(adminEntries, source) ? LAST_ADMIN : null

  return (
    <SettingsSection
      title="Members"
      description={
        canManage
          ? 'Who can work in this project. Members submit, own and evaluate ideas; viewers can only read. Owners and evaluators must be members or admins.'
          : 'Who can work in this project and why.'
      }
    >
      <div className="flex max-w-3xl flex-col gap-8">
        {canManage && (
          <AddAccess project={project} members={members.data ?? []} grants={grants.data ?? []} />
        )}
        <GroupsSection
          project={project}
          grants={grants}
          canManage={canManage}
          lockReason={lockReason}
        />
        <PeopleSection
          project={project}
          members={members}
          canManage={canManage}
          lockReason={lockReason}
          hasGroups={(grants.data?.length ?? 0) > 0}
        />
        <AccessSection
          project={project}
          // Without groups it would list exactly the people above. Shown once both lists
          // have loaded, so whether it starts unfolded is settled when it appears.
          show={members.isSuccess && grants.isSuccess && grants.data.length > 0}
          openAtFirst={members.data?.length === 0}
        />
      </div>
    </SettingsSection>
  )
}

/* ------------------------------------------------------------------ */
/* Add a person or a group                                             */
/* ------------------------------------------------------------------ */

type AddKind = 'person' | 'group'

function AddAccess({
  project,
  members,
  grants,
}: {
  project: Project
  members: Member[]
  grants: ProjectGroupGrant[]
}) {
  const addMember = useAddProjectMember(project.slug)
  const addGroup = useAddProjectGroupGrant(project.slug)
  const [kind, setKind] = useState<AddKind>('person')
  const [person, setPerson] = useState<UserSearchResult | null>(null)
  const [group, setGroup] = useState<GroupSearchResult | null>(null)
  const [role, setRole] = useState<ProjectRole>('member')
  const pickerRef = useRef<HTMLButtonElement>(null)
  const pending = addMember.isPending || addGroup.isPending

  const submit = () => {
    if (pending) return
    if (kind === 'person' && person) {
      addMember.mutate(
        { user_id: person.id, role },
        {
          onSuccess: (member) => {
            toast.success(
              `${member.user.display_name} added as ${roleLabel(member.role).toLowerCase()}`,
            )
            setPerson(null)
            // "Add" is disabled again: ready for the next person instead of losing focus.
            pickerRef.current?.focus()
          },
        },
      )
    }
    if (kind === 'group' && group) {
      addGroup.mutate(
        { group_id: group.id, role },
        {
          onSuccess: (grant) => {
            toast.success(`${grant.group.name} added as ${roleLabel(grant.role).toLowerCase()}`, {
              description: `${peopleCount(grant.group.member_count)} in the group get this role.`,
            })
            setGroup(null)
            pickerRef.current?.focus()
          },
        },
      )
    }
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-lg border bg-background p-3"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <SegmentedControl
        aria-label="What to add"
        size="sm"
        value={kind}
        onValueChange={(next) => setKind(next)}
        options={[
          { value: 'person', label: 'Person' },
          { value: 'group', label: 'Group' },
        ]}
        className="self-start"
      />
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        {kind === 'person' ? (
          <Field label="Add a person" className="min-w-0 flex-1">
            <PersonPicker
              ref={pickerRef}
              value={person}
              onChange={setPerson}
              exclude={members.map((member) => member.user.id)}
              excludeHint="Already a member"
              placeholder="Search by name or email…"
            />
          </Field>
        ) : (
          <Field label="Add a group" className="min-w-0 flex-1">
            <GroupPicker
              ref={pickerRef}
              value={group}
              onChange={setGroup}
              exclude={grants.map((grant) => grant.group.id)}
              excludeHint="Already has a role"
            />
          </Field>
        )}
        <Field label="Role" className="sm:w-36">
          <Select value={role} onValueChange={(value) => setRole(value as ProjectRole)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Button
          type="submit"
          variant="primary"
          disabled={kind === 'person' ? !person : !group}
          loading={pending}
        >
          Add
        </Button>
      </div>
      {kind === 'group' && (
        <p className="text-xs text-muted">
          Everyone in the group gets the role, including people who join it later.
        </p>
      )}
    </form>
  )
}

/* ------------------------------------------------------------------ */
/* People with a direct role                                           */
/* ------------------------------------------------------------------ */

function PeopleSection({
  project,
  members,
  canManage,
  lockReason,
  hasGroups,
}: {
  project: Project
  members: ReturnType<typeof useProjectMembers>
  canManage: boolean
  lockReason: (source: AdminSource) => string | null
  hasGroups: boolean
}) {
  const me = useCurrentUser()
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <SubHeading id={headingId} title="People" hint="A role given to one person." />
      {members.isPending ? (
        <RowsSkeleton label="Loading members" />
      ) : members.isError ? (
        <LoadError what="members" error={members.error} retry={() => void members.refetch()} />
      ) : members.data.length === 0 ? (
        <p className="rounded-lg border px-4 py-6 text-center text-sm text-muted">
          Nobody has a role of their own here: everyone gets access through a group.
        </p>
      ) : (
        <>
          <ul
            aria-label={`${members.data.length} members`}
            className="divide-y divide-subtle rounded-lg border"
          >
            {members.data.map((member) => (
              <MemberRow
                key={member.user.id}
                project={project}
                member={member}
                isMe={member.user.id === me.id}
                lockedReason={
                  member.role === 'admin'
                    ? lockReason({ kind: 'direct', userId: member.user.id })
                    : null
                }
                canManage={canManage}
              />
            ))}
          </ul>
          {members.data.length <= 1 && !hasGroups && canManage && (
            <p className="flex items-center gap-2 text-sm text-muted">
              <UsersRound aria-hidden="true" className="size-4" />
              Add people or a group to start collaborating.
            </p>
          )}
        </>
      )}
    </section>
  )
}

function MemberRow({
  project,
  member,
  isMe,
  lockedReason,
  canManage,
}: {
  project: Project
  member: Member
  isMe: boolean
  lockedReason: string | null
  canManage: boolean
}) {
  const updateRole = useUpdateProjectMember(project.slug)
  const remove = useRemoveProjectMember(project.slug)
  const name = member.user.display_name

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
      <Avatar name={name} src={member.user.avatar_url} size="md" decorative />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-2 truncate text-sm font-medium text-primary">
          {name}
          {isMe && <Badge variant="outline">You</Badge>}
        </span>
        <span className="truncate text-xs text-muted">{member.email}</span>
      </div>
      {canManage ? (
        <div className="flex items-center gap-1">
          <Locked reason={lockedReason}>
            <RoleSelect
              label={`Role of ${name}`}
              value={member.role}
              disabled={Boolean(lockedReason)}
              onChange={(role) => updateRole.mutate({ userId: member.user.id, role })}
            />
          </Locked>
          <Locked reason={lockedReason}>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${name}`}
              disabled={Boolean(lockedReason)}
              onClick={() => remove.mutate({ userId: member.user.id })}
            >
              <UserMinus />
            </Button>
          </Locked>
        </div>
      ) : (
        <span className="text-sm text-secondary">{roleLabel(member.role)}</span>
      )}
    </li>
  )
}

/* ------------------------------------------------------------------ */
/* Groups with a role                                                  */
/* ------------------------------------------------------------------ */

function GroupsSection({
  project,
  grants,
  canManage,
  lockReason,
}: {
  project: Project
  grants: ReturnType<typeof useProjectGroupGrants>
  canManage: boolean
  lockReason: (source: AdminSource) => string | null
}) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <SubHeading
        id={headingId}
        title="Groups"
        hint="Everyone in a group gets its role. Group members are managed by platform admins and your identity provider."
      />
      {grants.isPending ? (
        <RowsSkeleton label="Loading groups" rows={2} />
      ) : grants.isError ? (
        <LoadError what="groups" error={grants.error} retry={() => void grants.refetch()} />
      ) : grants.data.length === 0 ? (
        <div className="rounded-lg border">
          <EmptyState
            size="compact"
            icon={<UsersRound />}
            title="No groups have a role here"
            description={
              canManage
                ? 'Add a group to give everyone in it a role, including people who join it later.'
                : 'Everyone here has a role of their own.'
            }
          />
        </div>
      ) : (
        <ul
          aria-label={`${grants.data.length} ${grants.data.length === 1 ? 'group' : 'groups'}`}
          className="divide-y divide-subtle rounded-lg border"
        >
          {grants.data.map((grant) => (
            <GroupRow
              key={grant.group.id}
              project={project}
              grant={grant}
              canManage={canManage}
              lockedReason={
                grant.role === 'admin'
                  ? lockReason({ kind: 'group', groupId: grant.group.id })
                  : null
              }
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function GroupRow({
  project,
  grant,
  canManage,
  lockedReason,
}: {
  project: Project
  grant: ProjectGroupGrant
  canManage: boolean
  lockedReason: string | null
}) {
  const me = useCurrentUser()
  const updateRole = useUpdateProjectGroupGrant(project.slug)
  const remove = useRemoveProjectGroupGrant(project.slug)
  const { name } = grant.group

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
      <span
        aria-hidden="true"
        className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-background text-muted"
      >
        <UsersRound className="size-4" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        {me.is_platform_admin ? (
          // Its members and identity-provider mapping are on the group's page.
          <Link
            to="/settings/groups/$groupId"
            params={{ groupId: grant.group.id }}
            className="truncate text-sm font-medium text-primary hover:underline"
          >
            {name}
          </Link>
        ) : (
          <span className="truncate text-sm font-medium text-primary">{name}</span>
        )}
        <span className="truncate text-xs text-muted">
          Group · {peopleCount(grant.group.member_count)}
        </span>
      </div>
      {canManage ? (
        <div className="flex items-center gap-1">
          <Locked reason={lockedReason}>
            <RoleSelect
              label={`Role of the group ${name}`}
              value={grant.role}
              disabled={Boolean(lockedReason)}
              onChange={(role) => updateRole.mutate({ groupId: grant.group.id, role })}
            />
          </Locked>
          <Locked reason={lockedReason}>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove the group ${name}`}
              disabled={Boolean(lockedReason)}
              onClick={() => remove.mutate({ groupId: grant.group.id })}
            >
              <UserMinus />
            </Button>
          </Locked>
        </div>
      ) : (
        <span className="text-sm text-secondary">{roleLabel(grant.role)}</span>
      )}
    </li>
  )
}

/* ------------------------------------------------------------------ */
/* Everyone with access, and why                                       */
/* ------------------------------------------------------------------ */

const SEARCH_FROM = 9

function AccessSection({
  project,
  show,
  openAtFirst,
}: {
  project: Project
  /** False: the list would repeat People exactly (no group has a role), so only the note shows. */
  show: boolean
  /** Unfolded on arrival (nobody has a role of their own: this is the only list of people). */
  openAtFirst: boolean
}) {
  const note = (
    <p className="text-xs text-muted">
      Platform admins can see and manage every project without a role here.
      {project.visibility === 'internal' &&
        ' Everyone signed in can view this project, because it is internal.'}
    </p>
  )
  if (!show) return note
  return <AccessDisclosure project={project} openAtFirst={openAtFirst} note={note} />
}

function AccessDisclosure({
  project,
  openAtFirst,
  note,
}: {
  project: Project
  openAtFirst: boolean
  note: ReactNode
}) {
  const [expanded, setExpanded] = useState(openAtFirst)
  const headingId = useId()
  const listId = useId()

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h3 id={headingId} className="text-base font-semibold text-primary">
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={listId}
            onClick={() => setExpanded(!expanded)}
            className="-ml-1 inline-flex items-center gap-1 rounded-sm px-1 transition-colors hover:bg-subtle"
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                'size-4 text-muted transition-transform duration-150',
                expanded && 'rotate-90',
              )}
            />
            Everyone with access
            <span className="font-normal text-muted">({project.member_count})</span>
          </button>
        </h3>
        <p className="text-sm text-muted">
          {peopleCount(project.member_count)}, each with the highest of their roles and where it
          comes from.
        </p>
      </div>
      <div id={listId} hidden={!expanded} className="flex flex-col gap-3">
        {expanded && <AccessList project={project} />}
      </div>
      {note}
    </section>
  )
}

function AccessList({ project }: { project: Project }) {
  const me = useCurrentUser()
  const [q, setQ] = useState('')
  const debounced = useDebouncedValue(q.trim())
  const access = useProjectAccess(project.slug, { q: debounced })
  const entries = access.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <>
      {(project.member_count >= SEARCH_FROM || q) && (
        <Input
          aria-label="Find someone with access"
          placeholder="Find by name or email"
          startIcon={<Search />}
          value={q}
          onChange={(event) => setQ(event.target.value)}
          className="sm:max-w-xs"
        />
      )}
      {access.isPending ? (
        <RowsSkeleton label="Loading everyone with access" />
      ) : access.isError ? (
        <LoadError
          what="everyone with access"
          error={access.error}
          retry={() => void access.refetch()}
        />
      ) : entries.length === 0 ? (
        <p className="rounded-lg border px-4 py-6 text-center text-sm text-muted">
          {debounced ? `Nobody with access matches “${debounced}”.` : 'Nobody has a role here yet.'}
        </p>
      ) : (
        <ul
          aria-label="Everyone with access"
          aria-busy={access.isFetching || undefined}
          className="divide-y divide-subtle rounded-lg border"
        >
          {entries.map((entry) => (
            <AccessRow key={entry.user.id} entry={entry} isMe={entry.user.id === me.id} />
          ))}
        </ul>
      )}
      {access.hasNextPage && (
        <Button
          variant="ghost"
          className="self-start"
          loading={access.isFetchingNextPage}
          onClick={() => void access.fetchNextPage()}
        >
          Show more
        </Button>
      )}
    </>
  )
}

function AccessRow({ entry, isMe }: { entry: ProjectAccessEntry; isMe: boolean }) {
  const name = entry.user.display_name
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
      <Avatar name={name} src={entry.user.avatar_url} size="md" decorative />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-2 truncate text-sm font-medium text-primary">
          {name}
          {isMe && <Badge variant="outline">You</Badge>}
        </span>
        <span className="truncate text-xs text-muted">{entry.email}</span>
      </div>
      <div className="flex min-w-0 basis-full flex-col items-start pl-10 sm:basis-auto sm:items-end sm:pl-0 sm:text-right">
        <span className="text-sm text-primary">{roleLabel(entry.role)}</span>
        <span className="text-xs text-muted">{describeSources(entry.sources, entry.role)}</span>
      </div>
    </li>
  )
}

/* ------------------------------------------------------------------ */
/* Pieces                                                              */
/* ------------------------------------------------------------------ */

function SubHeading({ id, title, hint }: { id: string; title: string; hint: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <h3 id={id} className="text-base font-semibold text-primary">
        {title}
      </h3>
      <p className="text-sm text-muted">{hint}</p>
    </div>
  )
}

function RoleSelect({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string
  value: ProjectRole
  disabled: boolean
  onChange: (role: ProjectRole) => void
}) {
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next as ProjectRole)}
    >
      <SelectTrigger aria-label={label} className="w-28">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        {ROLE_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function RowsSkeleton({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <SkeletonGroup label={label} className="divide-y divide-subtle rounded-lg border">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-14 items-center gap-3 px-4">
          <Skeleton className="size-7 rounded-full" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-3 w-44" />
          </div>
          <Skeleton className="ml-auto h-7 w-28" />
        </div>
      ))}
    </SkeletonGroup>
  )
}

function LoadError({ what, error, retry }: { what: string; error: unknown; retry: () => void }) {
  return (
    <div className="rounded-lg border">
      <EmptyState
        role="alert"
        size="compact"
        icon={<CloudOff />}
        title={`We couldn’t load ${what}`}
        description={describeError(error).description ?? 'Please try again.'}
        action={
          <Button variant="outline" onClick={retry}>
            Try again
          </Button>
        }
      />
    </div>
  )
}

/** Explains why a control is disabled (disabled controls get no hover, so the wrapper does). */
function Locked({ reason, children }: { reason: string | null; children: ReactNode }) {
  if (!reason) return children
  return (
    <WithTooltip content={reason}>
      <span>{children}</span>
    </WithTooltip>
  )
}
