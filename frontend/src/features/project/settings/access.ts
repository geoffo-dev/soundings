import type { ProjectAccessEntry, ProjectRole, RoleSource } from '@/api/types'

/**
 * Who has access and why (contract-phase2 §3.7): plain-language helpers for the
 * Members tab. Roles themselves always come from the API (`list_project_access`);
 * these only word them and predict c11 (the server is the authority: 409
 * `last_admin`).
 */

export const ROLE_OPTIONS: { value: ProjectRole; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
]

export function roleLabel(role: ProjectRole): string {
  return ROLE_OPTIONS.find((option) => option.value === role)?.label ?? role
}

/** "1 person", "14 people". */
export function peopleCount(count: number): string {
  return `${count.toLocaleString('en')} ${count === 1 ? 'person' : 'people'}`
}

/**
 * Why someone has their role: "Direct", "via Tools members", or several
 * ("Direct · via Tools members"). A source whose role differs from the
 * effective (highest) one says so: "Direct (viewer) · via Innovation admins".
 */
export function describeSources(sources: RoleSource[], role: ProjectRole): string {
  return sources
    .map((source) => {
      const label = source.kind === 'direct' ? 'Direct' : `via ${source.group?.name ?? 'a group'}`
      return source.role === role ? label : `${label} (${roleLabel(source.role).toLowerCase()})`
    })
    .join(' · ')
}

export type AdminSource = { kind: 'direct'; userId: string } | { kind: 'group'; groupId: string }

/**
 * c11 in the client, to explain disabled controls before the server says 409:
 * would taking `removed` away leave nobody with the admin role? `admins` are the
 * access entries with the effective role admin (`list_project_access?role=admin`).
 */
export function wouldLeaveNoAdmin(admins: ProjectAccessEntry[], removed: AdminSource): boolean {
  return !admins.some((entry) =>
    entry.sources.some((source) => {
      if (source.role !== 'admin') return false
      if (removed.kind === 'direct') {
        return !(source.kind === 'direct' && entry.user.id === removed.userId)
      }
      return !(source.kind === 'group' && source.group?.id === removed.groupId)
    }),
  )
}
