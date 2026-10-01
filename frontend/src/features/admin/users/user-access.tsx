import { Link } from '@tanstack/react-router'

import type { AdminUser } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { ProjectTile } from '@/components/layout/project-tile'
import { describeSources, roleLabel } from '@/features/project/settings/access'

import { ProvenanceBadges } from './user-badges'

/**
 * Where a user's project access comes from (contract-phase2 §3.4, §3.7): each
 * project with the effective role and its sources (direct first, then each
 * granting group), and their groups with provenance (added by hand, synced from
 * the identity provider, or both).
 */
export function UserProjectAccess({ user }: { user: AdminUser }) {
  return (
    <section aria-labelledby="user-projects-heading" className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h3 id="user-projects-heading" className="text-base font-semibold text-primary">
          Project access
        </h3>
        <p className="text-sm text-muted">
          {user.is_platform_admin
            ? 'As a platform admin they can also see and manage every project.'
            : 'Roles held directly or through a group. The highest one counts.'}
        </p>
      </div>
      {user.project_roles.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted">
          No project roles. Add them to a project, or to a group that has a role in one.
        </p>
      ) : (
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border">
          {user.project_roles.map((entry) => (
            <li key={entry.project.id} className="flex items-center gap-3 px-4 py-2.5">
              <ProjectTile name={entry.project.name} />
              <div className="flex min-w-0 flex-1 flex-col">
                <Link
                  to="/p/$slug/settings"
                  params={{ slug: entry.project.slug }}
                  search={{ tab: 'members' }}
                  className="truncate text-sm font-medium text-primary hover:underline"
                >
                  {entry.project.name}
                </Link>
                <span className="truncate text-xs text-muted">
                  {describeSources(entry.sources, entry.role)}
                </span>
              </div>
              <Badge variant="outline">{roleLabel(entry.role)}</Badge>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function UserGroups({ user }: { user: AdminUser }) {
  return (
    <section aria-labelledby="user-groups-heading" className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h3 id="user-groups-heading" className="text-base font-semibold text-primary">
          Groups
        </h3>
        <p className="text-sm text-muted">
          Synced memberships follow the identity provider at each sign-in; manual ones stay until an
          admin removes them.
        </p>
      </div>
      {user.groups.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted">
          Not in any group.
        </p>
      ) : (
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border">
          {user.groups.map((membership) => (
            <li
              key={membership.group.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5"
            >
              <Link
                to="/settings/groups/$groupId"
                params={{ groupId: membership.group.id }}
                className="min-w-0 flex-1 truncate text-sm font-medium text-primary hover:underline"
              >
                {membership.group.name}
              </Link>
              <ProvenanceBadges manual={membership.manual} synced={membership.synced} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
