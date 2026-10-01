import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft, FlaskConical, History, UsersRound } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  useAdminGroup,
  useDeleteGroup,
  useReplaceGroupMapping,
  useSsoConfig,
  useUpdateGroup,
} from '@/api/admin'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import type { Group, GroupSyncMode } from '@/api/types'
import { ProjectTile } from '@/components/layout/project-tile'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { peopleCount, roleLabel } from '@/features/project/settings/access'
import { rememberRow } from '@/lib/return-to-row'

import { ConfirmDialog } from '@/features/admin/confirm-dialog'
import { AdminPageHeader, AdminSection } from '@/features/admin/settings-frame'
import { GroupMembers } from './group-members'
import { IdpValuesInput, SyncModeField } from './mapping-fields'
import { GroupPageSkeleton } from './group-page-skeleton'
import { EMPTY_MAPPING_TEST } from './mapping-test-panel'
import { MappingTestSheet } from './mapping-test-sheet'

function BackToGroups() {
  return (
    <Button asChild variant="ghost" size="sm" className="-ml-2.5 self-start text-secondary">
      <Link to="/settings/groups">
        <ArrowLeft />
        All groups
      </Link>
    </Button>
  )
}

/**
 * One group (contract-phase2 §3.5–3.7, §3.12), in the order people come here
 * for: its members with provenance, the identity-provider mapping (values and
 * managed/additive, with "Test mapping" in a sheet), the project roles it
 * grants, then name, description and delete. One column, one width.
 */
export function GroupPage({ groupId }: { groupId: string }) {
  const query = useAdminGroup(groupId)
  const group = query.data
  if (!group) {
    if (query.isError) {
      return (
        <>
          <BackToGroups />
          <EmptyState
            role="alert"
            icon={<UsersRound />}
            title="Couldn’t load this group"
            description={describeError(query.error).title}
            action={
              <Button variant="secondary" onClick={() => void query.refetch()}>
                Try again
              </Button>
            }
          />
        </>
      )
    }
    return <GroupPageSkeleton />
  }
  return <GroupDetail key={group.id} group={group} />
}

function GroupDetail({ group }: { group: Group }) {
  const sso = useSsoConfig()
  const [mappingDirty, setMappingDirty] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testDraft, setTestDraft] = useState(EMPTY_MAPPING_TEST)
  // "All groups", the breadcrumb or Back then return focus to this group's row.
  useEffect(() => rememberRow('groups', group.id), [group.id])
  const summary = [
    peopleCount(group.member_count),
    group.idp_values.length > 0
      ? `${group.sync_mode === 'managed' ? 'managed' : 'additive'} sync`
      : 'not mapped',
    group.project_grants.length === 1
      ? 'a role in 1 project'
      : `roles in ${group.project_grants.length} projects`,
  ].join(' · ')

  return (
    <div className="flex max-w-3xl flex-col gap-10">
      <AdminPageHeader
        back={<BackToGroups />}
        title={group.name}
        description={
          <>
            {group.description && <span className="block">{group.description}</span>}
            <span className="block">{summary}</span>
          </>
        }
        actions={
          <Button asChild variant="ghost" size="sm" className="text-secondary">
            <Link to="/settings/audit" search={{ target: `group:${group.id}` }}>
              <History />
              Audit log
            </Link>
          </Button>
        }
      />

      <GroupMembers group={group} />

      <AdminSection
        id="mapping"
        title="Identity provider"
        description="People in any of these groups join at their next sign-in."
        actions={
          <Button variant="outline" size="sm" onClick={() => setTesting(true)}>
            <FlaskConical />
            Test mapping
          </Button>
        }
      >
        {sso.data && !sso.data.groups_claim && (
          <Callout tone="warning" title="Group sync is off">
            No groups claim is configured (Helm value{' '}
            <code className="font-mono">oidc.groupsClaim</code>), so these values are never matched.
            Members can still be added by hand.
          </Callout>
        )}
        <MappingForm group={group} onDirtyChange={setMappingDirty} />
      </AdminSection>

      <ProjectGrants group={group} />
      <DetailsForm group={group} />
      <DeleteGroup group={group} />

      <MappingTestSheet
        open={testing}
        onOpenChange={setTesting}
        draft={testDraft}
        onDraftChange={setTestDraft}
        highlightGroupId={group.id}
        notice={
          mappingDirty && (
            <Callout tone="info" title="Save the mapping to test it">
              The test uses the saved mappings of every group.
            </Callout>
          )
        }
      />
    </div>
  )
}

function MappingForm({
  group,
  onDirtyChange,
}: {
  group: Group
  onDirtyChange: (dirty: boolean) => void
}) {
  const replace = useReplaceGroupMapping(group.id)
  const [values, setValues] = useState(group.idp_values)
  const [mode, setMode] = useState<GroupSyncMode>(group.sync_mode)
  const [error, setError] = useState<string | null>(null)
  const savedKey = `${group.sync_mode}|${group.idp_values.join('\n')}`
  const [seen, setSeen] = useState(savedKey)
  if (seen !== savedKey) {
    setSeen(savedKey)
    setValues(group.idp_values)
    setMode(group.sync_mode)
  }
  const dirty = mode !== group.sync_mode || values.join('\n') !== group.idp_values.join('\n')
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange])

  const save = () => {
    if (!dirty || replace.isPending) return
    setError(null)
    replace.mutate(
      { sync_mode: mode, idp_values: values },
      {
        onSuccess: () =>
          toast.success('Mapping saved', {
            description: 'It applies to each person at their next sign-in.',
          }),
        onError: (err) => {
          const field = isApiError(err)
            ? err.problem?.errors?.find((e) => e.loc.includes('idp_values'))?.msg
            : undefined
          const { title, description } = describeError(err)
          setError(field ?? (description ? `${title}. ${description}` : title))
        },
      },
    )
  }

  return (
    <form
      noValidate
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault()
        save()
      }}
    >
      <Field
        label="Identity provider groups"
        description={
          values.length === 0
            ? 'Not mapped: sign-in never adds anyone. Type a group path or ID and press Enter.'
            : 'Keycloak paths work with or without the leading slash. A subgroup needs its own entry.'
        }
        error={error}
      >
        <IdpValuesInput value={values} onChange={setValues} />
      </Field>
      <Field label="Sync">
        <SyncModeField value={mode} onChange={setMode} idPrefix={`group-${group.id}-sync`} />
      </Field>
      {dirty && (
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={replace.isPending}>
            Save mapping
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setValues(group.idp_values)
              setMode(group.sync_mode)
              setError(null)
            }}
          >
            Discard
          </Button>
        </div>
      )}
    </form>
  )
}

function ProjectGrants({ group }: { group: Group }) {
  return (
    <AdminSection
      id="project-roles"
      title="Project roles"
      description="Everyone in the group gets these roles. Change them in each project’s Members settings."
    >
      {group.project_grants.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted">
          No project roles yet. Give the group a role from a project’s Members settings.
        </p>
      ) : (
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border">
          {group.project_grants.map((grant) => (
            <li key={grant.project.id} className="flex items-center gap-3 px-4 py-2.5">
              <ProjectTile name={grant.project.name} />
              <Link
                to="/p/$slug/settings"
                params={{ slug: grant.project.slug }}
                search={{ tab: 'members' }}
                className="min-w-0 flex-1 truncate text-sm font-medium text-primary hover:underline"
              >
                {grant.project.name}
              </Link>
              <Badge variant="outline">{roleLabel(grant.role)}</Badge>
            </li>
          ))}
        </ul>
      )}
    </AdminSection>
  )
}

function DetailsForm({ group }: { group: Group }) {
  const update = useUpdateGroup(group.id)
  const [name, setName] = useState(group.name)
  const [description, setDescription] = useState(group.description)
  const [errors, setErrors] = useState<{ name?: string; form?: string }>({})
  const savedKey = `${group.name}|${group.description}`
  const [seen, setSeen] = useState(savedKey)
  if (seen !== savedKey) {
    setSeen(savedKey)
    setName(group.name)
    setDescription(group.description)
  }
  const dirty = name.trim() !== group.name || description.trim() !== group.description

  const save = () => {
    if (!dirty || update.isPending) return
    if (!name.trim()) {
      setErrors({ name: 'Give the group a name' })
      return
    }
    setErrors({})
    update.mutate(
      {
        name: name.trim() !== group.name ? name.trim() : undefined,
        description: description.trim() !== group.description ? description.trim() : undefined,
      },
      {
        onSuccess: () => toast.success('Group saved'),
        onError: (error) => {
          if (hasErrorCode(error, 'group_name_taken')) {
            setErrors({ name: 'A group with this name already exists.' })
          } else {
            const { title, description: detail } = describeError(error)
            setErrors({ form: detail ? `${title}. ${detail}` : title })
          }
        },
      },
    )
  }

  return (
    <AdminSection id="details" title="Name and description">
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {errors.form && <Callout role="alert" tone="danger" title={errors.form} />}
        <Field label="Name" required error={errors.name}>
          <Input
            value={name}
            maxLength={80}
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field label="Description">
          <Textarea
            value={description}
            rows={2}
            maxLength={500}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        {dirty && (
          <div className="flex gap-2">
            <Button type="submit" variant="secondary" loading={update.isPending}>
              Save
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setName(group.name)
                setDescription(group.description)
                setErrors({})
              }}
            >
              Discard
            </Button>
          </div>
        )}
      </form>
    </AdminSection>
  )
}

function DeleteGroup({ group }: { group: Group }) {
  const navigate = useNavigate()
  const remove = useDeleteGroup()
  const [open, setOpen] = useState(false)
  const projects = group.project_grants.length
  return (
    <AdminSection
      id="delete"
      title="Delete group"
      description="Its members, mapping and project roles go with it. People keep any access they have directly or through other groups."
    >
      <Button variant="outline" className="self-start text-danger" onClick={() => setOpen(true)}>
        Delete group…
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete ${group.name}?`}
        description={`${peopleCount(group.member_count)} lose the roles it grants${projects ? ` in ${projects === 1 ? '1 project' : `${projects} projects`}` : ''}. This can’t be undone.`}
        confirmLabel="Delete group"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(group.id, {
            onSuccess: () => {
              setOpen(false)
              toast.success(`${group.name} deleted`)
              void navigate({ to: '/settings/groups' })
            },
            onError: () => setOpen(false),
          })
        }
      />
    </AdminSection>
  )
}
