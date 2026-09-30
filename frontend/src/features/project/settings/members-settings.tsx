import { CloudOff, UserMinus, UsersRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { describeError } from '@/api/errors'
import {
  useAddProjectMember,
  useProjectMembers,
  useRemoveProjectMember,
  useUpdateProjectMember,
} from '@/api/projects'
import type { Member, Project, ProjectRole, UserSearchResult } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
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

import { PersonPicker } from './person-picker'
import { SettingsSection } from './settings-layout'

const ROLES: { value: ProjectRole; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
]

const roleLabel = (role: ProjectRole) => ROLES.find((r) => r.value === role)?.label ?? role

/**
 * Members (wireframe 07): add people with a role, change roles, remove
 * people (with Undo). The last admin can't be demoted or removed.
 */
export function MembersSettings({ project }: { project: Project }) {
  const members = useProjectMembers(project.slug)
  const canManage = project.permissions.can_manage
  const me = useCurrentUser()
  const admins = members.data?.filter((member) => member.role === 'admin').length ?? 0

  return (
    <SettingsSection
      title="Members"
      description={
        canManage
          ? 'Members submit, own and evaluate ideas; viewers can only read. Owners and evaluators must be members or admins.'
          : 'Who is in this project. Only project admins can change it.'
      }
    >
      <div className="flex max-w-3xl flex-col gap-4">
        {canManage && <AddMember project={project} members={members.data ?? []} />}
        {members.isPending ? (
          <SkeletonGroup
            label="Loading members"
            className="divide-y divide-subtle rounded-lg border"
          >
            {[0, 1, 2, 3].map((i) => (
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
        ) : members.isError ? (
          <div className="rounded-lg border">
            <EmptyState
              role="alert"
              size="compact"
              icon={<CloudOff />}
              title="We couldn’t load the members"
              description={describeError(members.error).description ?? 'Please try again.'}
              action={
                <Button variant="outline" onClick={() => void members.refetch()}>
                  Try again
                </Button>
              }
            />
          </div>
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
                  onlyAdmin={member.role === 'admin' && admins <= 1}
                  canManage={canManage}
                />
              ))}
            </ul>
            {members.data.length <= 1 && canManage && (
              <p className="flex items-center gap-2 text-sm text-muted">
                <UsersRound aria-hidden="true" className="size-4" />
                Add people to start collaborating: they can submit, own and evaluate ideas.
              </p>
            )}
          </>
        )}
      </div>
    </SettingsSection>
  )
}

function AddMember({ project, members }: { project: Project; members: Member[] }) {
  const add = useAddProjectMember(project.slug)
  const [person, setPerson] = useState<UserSearchResult | null>(null)
  const [role, setRole] = useState<ProjectRole>('member')

  const submit = () => {
    if (!person || add.isPending) return
    add.mutate(
      { user_id: person.id, role },
      {
        onSuccess: (member) => {
          toast.success(
            `${member.user.display_name} added as ${roleLabel(member.role).toLowerCase()}`,
          )
          setPerson(null)
        },
      },
    )
  }

  return (
    <form
      className="flex flex-col gap-2 rounded-lg border bg-background p-3 sm:flex-row sm:items-end"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <Field label="Add a person" className="min-w-0 flex-1">
        <PersonPicker
          value={person}
          onChange={setPerson}
          exclude={members.map((member) => member.user.id)}
          excludeHint="Already a member"
          placeholder="Search by name or email…"
        />
      </Field>
      <Field label="Role" className="sm:w-36">
        <Select value={role} onValueChange={(value) => setRole(value as ProjectRole)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROLES.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Button type="submit" variant="primary" disabled={!person} loading={add.isPending}>
        Add
      </Button>
    </form>
  )
}

function MemberRow({
  project,
  member,
  isMe,
  onlyAdmin,
  canManage,
}: {
  project: Project
  member: Member
  isMe: boolean
  onlyAdmin: boolean
  canManage: boolean
}) {
  const updateRole = useUpdateProjectMember(project.slug)
  const remove = useRemoveProjectMember(project.slug)
  const name = member.user.display_name
  const lockedReason = onlyAdmin ? 'A project needs at least one admin' : null

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
            <Select
              value={member.role}
              disabled={Boolean(lockedReason)}
              onValueChange={(value) =>
                updateRole.mutate({ userId: member.user.id, role: value as ProjectRole })
              }
            >
              <SelectTrigger aria-label={`Role of ${name}`} className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end">
                {ROLES.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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

/** Explains why a control is disabled (disabled controls get no hover, so the wrapper does). */
function Locked({ reason, children }: { reason: string | null; children: ReactNode }) {
  if (!reason) return children
  return (
    <WithTooltip content={reason}>
      <span>{children}</span>
    </WithTooltip>
  )
}
