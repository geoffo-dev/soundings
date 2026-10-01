import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { isApiError } from '@/api/errors'
import { ideaQueryOptions } from '@/api/ideas'
import { queryKeys } from '@/api/keys'
import type {
  AdminUser,
  AdminUserCreate,
  AdminUserUpdate,
  AuditAction,
  AuditTargetType,
  ExternalIdIn,
  Group,
  GroupCreate,
  GroupMappingUpdate,
  GroupMember,
  GroupUpdate,
  MappingTestRequest,
} from '@/api/types'
import { offerUndo } from '@/api/undo'
import { toast } from '@/components/ui/toaster'

/**
 * Admin settings (contract-phase2 §2 "Admin"): users, groups, the mapping test,
 * the audit log and the SSO view. Platform admins only; the screens live in
 * `features/admin`. Every write invalidates the admin caches and everything that
 * depends on who has access (project member lists, counts, the group picker).
 */

const PAGE_SIZE = 50

/** Who-has-access changed: admin lists and details, projects (counts, access), group search. */
function invalidateAccess(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.groups.all })
}

/* ------------------------------------------------------------------ */
/* Users (§3.4)                                                        */
/* ------------------------------------------------------------------ */

export interface AdminUserFilters {
  /** Part of a name or email. */
  q?: string
  /** true: active only; false: deactivated only. */
  active?: boolean
  platform_admin?: boolean
  /** false: never signed in with SSO (pre-created). */
  has_identity?: boolean
}

function userFilterKey({ q, active, platform_admin, has_identity }: AdminUserFilters) {
  return {
    q: q?.trim().toLowerCase() ?? '',
    active: active ?? null,
    platform_admin: platform_admin ?? null,
    has_identity: has_identity ?? null,
  }
}

/** Every account (people, agents, the break-glass admin) by name, keyset-paged. */
export const adminUsersInfiniteOptions = (filters: AdminUserFilters = {}, limit = PAGE_SIZE) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.admin.userList(userFilterKey(filters)), { limit }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/admin/users', {
          params: {
            query: {
              q: (filters.q ?? '').trim() || undefined,
              active: filters.active,
              platform_admin: filters.platform_admin,
              has_identity: filters.has_identity,
              cursor: pageParam ?? undefined,
              limit,
            },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })

export function useAdminUsers(
  filters: AdminUserFilters = {},
  options: { enabled?: boolean; limit?: number } = {},
) {
  return useInfiniteQuery({
    ...adminUsersInfiniteOptions(filters, options.limit),
    enabled: options.enabled ?? true,
  })
}

/** One user: identities, external IDs, groups with provenance, project roles with sources. */
export const adminUserQueryOptions = (userId: string) =>
  queryOptions({
    queryKey: queryKeys.admin.user(userId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/admin/users/{user_id}', {
          params: { path: { user_id: userId } },
          signal,
        }),
      ),
  })

export function useAdminUser(userId: string | undefined) {
  return useQuery({ ...adminUserQueryOptions(userId ?? ''), enabled: Boolean(userId) })
}

/**
 * A user's display name for the audit log (ids in `details`): cached for long,
 * `null` when the user no longer exists.
 */
export function useAdminUserName(userId: string | undefined) {
  return useQuery({
    ...adminUserQueryOptions(userId ?? ''),
    enabled: Boolean(userId),
    staleTime: 5 * 60_000,
    retry: false,
    select: (user) => user.display_name,
  })
}

/** Pre-create a user. 409 email_taken / external_id_taken; 422 field errors (shown inline). */
export function useCreateAdminUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AdminUserCreate) => unwrap(api.POST('/api/v1/admin/users', { body })),
    onSuccess: (user) => {
      queryClient.setQueryData(queryKeys.admin.user(user.id), user)
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
    meta: { silent: true },
  })
}

/**
 * Name, email, active, platform admin. Errors: 403 cannot_change_self; 409
 * email_taken, system_account, last_platform_admin. Pass `silent` when the
 * caller shows the error inline (the profile form).
 */
export function useUpdateAdminUser(userId: string, { silent = false }: { silent?: boolean } = {}) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AdminUserUpdate) =>
      unwrap(
        api.PATCH('/api/v1/admin/users/{user_id}', { params: { path: { user_id: userId } }, body }),
      ),
    onSuccess: (user) => {
      queryClient.setQueryData(queryKeys.admin.user(user.id), user)
      invalidateAccess(queryClient)
      // Your own name or email shows in the shell.
      void queryClient.invalidateQueries({ queryKey: queryKeys.auth.me() })
    },
    meta: silent ? { silent: true } : { errorTitle: 'Couldn’t change that' },
  })
}

/** Replace the user's external IDs (one per kind). 409 external_id_taken / system_account. */
export function useReplaceExternalIds(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (externalIds: ExternalIdIn[]) =>
      unwrap(
        api.PUT('/api/v1/admin/users/{user_id}/external-ids', {
          params: { path: { user_id: userId } },
          body: { external_ids: externalIds },
        }),
      ),
    onSuccess: (user) => {
      queryClient.setQueryData(queryKeys.admin.user(user.id), user)
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
    meta: { silent: true },
  })
}

/** Unlink an SSO account; also ends the user's SSO sessions (§3.4). */
export function useUnlinkIdentity(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (identityId: string) =>
      api.DELETE('/api/v1/admin/users/{user_id}/identities/{identity_id}', {
        params: { path: { user_id: userId, identity_id: identityId } },
      }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all }),
    meta: { errorTitle: 'Couldn’t unlink that account' },
  })
}

/** Sign the user out everywhere (idempotent). */
export function useEndUserSessions(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api.DELETE('/api/v1/admin/users/{user_id}/sessions', {
        params: { path: { user_id: userId } },
      }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all }),
    meta: { errorTitle: 'Couldn’t sign them out' },
  })
}

/* ------------------------------------------------------------------ */
/* Groups (§3.5, §3.6)                                                 */
/* ------------------------------------------------------------------ */

/** Groups by name (`GroupPage`), filtered by part of the name. */
export const adminGroupsInfiniteOptions = (q = '', limit = PAGE_SIZE) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.admin.groupList(q), { limit }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/admin/groups', {
          params: { query: { q: q.trim() || undefined, cursor: pageParam ?? undefined, limit } },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })

export function useAdminGroups(q = '') {
  return useInfiniteQuery(adminGroupsInfiniteOptions(q))
}

/** One group: mapping, counts by provenance and project grants. */
export const adminGroupQueryOptions = (groupId: string) =>
  queryOptions({
    queryKey: queryKeys.admin.group(groupId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/admin/groups/{group_id}', {
          params: { path: { group_id: groupId } },
          signal,
        }),
      ),
  })

export function useAdminGroup(groupId: string) {
  return useQuery(adminGroupQueryOptions(groupId))
}

/** A group's name for the audit log; `null` data (error) when it was deleted. */
export function useAdminGroupName(groupId: string | undefined) {
  return useQuery({
    ...adminGroupQueryOptions(groupId ?? ''),
    enabled: Boolean(groupId),
    staleTime: 5 * 60_000,
    retry: false,
    select: (group) => group.name,
  })
}

/**
 * An idea's key ("CUST-12") for the audit log, where an entry names the idea only by
 * id in `details` (evaluator changes target the evaluator). Error when it was deleted.
 */
export function useIdeaKey(ideaId: string | undefined) {
  return useQuery({
    ...ideaQueryOptions(ideaId ?? ''),
    enabled: Boolean(ideaId),
    staleTime: 5 * 60_000,
    retry: false,
    select: (idea) => idea.key,
  })
}

/** Create a group (optionally mapped). 409 group_name_taken; 422 shown inline. */
export function useCreateGroup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: GroupCreate) => unwrap(api.POST('/api/v1/admin/groups', { body })),
    onSuccess: (group) => {
      queryClient.setQueryData(queryKeys.admin.group(group.id), group)
      invalidateAccess(queryClient)
    },
    meta: { silent: true },
  })
}

/** Rename or describe a group. 409 group_name_taken (shown inline). */
export function useUpdateGroup(groupId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: GroupUpdate) =>
      unwrap(
        api.PATCH('/api/v1/admin/groups/{group_id}', {
          params: { path: { group_id: groupId } },
          body,
        }),
      ),
    onSuccess: (group) => {
      queryClient.setQueryData(queryKeys.admin.group(group.id), group)
      invalidateAccess(queryClient)
    },
    meta: { silent: true },
  })
}

/** Delete a group: its memberships, mapping and project grants go with it. */
export function useDeleteGroup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (groupId: string) =>
      api.DELETE('/api/v1/admin/groups/{group_id}', { params: { path: { group_id: groupId } } }),
    onSuccess: (_data, groupId) => {
      queryClient.removeQueries({ queryKey: queryKeys.admin.group(groupId) })
      invalidateAccess(queryClient)
    },
    meta: { errorTitle: 'Couldn’t delete the group' },
  })
}

/** Replace the IdP mapping; applies to each member at their next sign-in. */
export function useReplaceGroupMapping(groupId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: GroupMappingUpdate) =>
      unwrap(
        api.PUT('/api/v1/admin/groups/{group_id}/mapping', {
          params: { path: { group_id: groupId } },
          body,
        }),
      ),
    onSuccess: (group) => {
      queryClient.setQueryData(queryKeys.admin.group(group.id), group)
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
    meta: { silent: true },
  })
}

/** Members by name with provenance (deactivated members included, flagged). */
export const groupMembersInfiniteOptions = (groupId: string, q = '', limit = PAGE_SIZE) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.admin.groupMembers(groupId, q), { limit }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/admin/groups/{group_id}/members', {
          params: {
            path: { group_id: groupId },
            query: { q: q.trim() || undefined, cursor: pageParam ?? undefined, limit },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })

export function useGroupMembers(groupId: string, q = '') {
  return useInfiniteQuery(groupMembersInfiniteOptions(groupId, q))
}

/** Add a manual member (or mark a synced member manual too). 409 already_member. */
export function useAddGroupMember(groupId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.POST('/api/v1/admin/groups/{group_id}/members', {
          params: { path: { group_id: groupId } },
          body: { user_id: userId },
        }),
      ),
    onSettled: () => invalidateAccess(queryClient),
    meta: { errorTitle: 'Couldn’t add them to the group' },
  })
}

/**
 * Remove a membership (manual and synced). A manual-only member gets Undo (add
 * them back); a synced membership can't be restored by hand, so the toast says
 * when it comes back instead.
 */
export function useRemoveGroupMember(groupId: string, groupName: string) {
  const queryClient = useQueryClient()
  const add = useAddGroupMember(groupId)
  return useMutation({
    mutationFn: (member: GroupMember) =>
      api.DELETE('/api/v1/admin/groups/{group_id}/members/{user_id}', {
        params: { path: { group_id: groupId, user_id: member.user.id } },
      }),
    onSuccess: (_data, member) => {
      const title = `${member.user.display_name} removed from ${groupName}`
      if (member.synced) {
        toast.success(title, {
          description:
            'If the identity provider still lists them, they come back at their next sign-in.',
        })
      } else {
        offerUndo(title, () => add.mutate(member.user.id))
      }
    },
    onSettled: () => invalidateAccess(queryClient),
    meta: { errorTitle: 'Couldn’t remove them from the group' },
  })
}

/** The "Test mapping" box (§3.12): read-only, nothing stored or logged. 422 user_not_found. */
export function useTestGroupMapping() {
  return useMutation({
    mutationFn: (body: MappingTestRequest) =>
      unwrap(api.POST('/api/v1/admin/groups/test-mapping', { body })),
    meta: { silent: true },
  })
}

/* ------------------------------------------------------------------ */
/* Audit log (§3.11)                                                   */
/* ------------------------------------------------------------------ */

export interface AuditFilters {
  actor_id?: string
  action?: AuditAction[]
  target_type?: AuditTargetType
  target_id?: string
  project_id?: string
  /** ISO date-time with an offset, inclusive. */
  since?: string
  /** ISO date-time with an offset, exclusive. */
  until?: string
}

function auditFilterKey(filters: AuditFilters): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(filters) as [string, unknown][]) {
    if (value === undefined || value === '') continue
    if (Array.isArray(value)) {
      if (value.length > 0) out[key] = (value as unknown[]).map(String).sort()
    } else out[key] = value
  }
  return out
}

/** Newest first, keyset-paged; filters combine with AND, several actions with OR. */
export const auditInfiniteOptions = (filters: AuditFilters = {}, limit = PAGE_SIZE) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.admin.audit(auditFilterKey(filters)), { limit }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/admin/audit', {
          params: {
            query: {
              actor_id: filters.actor_id,
              action: filters.action?.length ? filters.action : undefined,
              target_type: filters.target_type,
              target_id: filters.target_id,
              project_id: filters.project_id,
              since: filters.since,
              until: filters.until,
              cursor: pageParam ?? undefined,
              limit,
            },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })

export function useAuditEntries(filters: AuditFilters = {}) {
  return useInfiniteQuery(auditInfiniteOptions(filters))
}

/* ------------------------------------------------------------------ */
/* Single sign-on (§3.10)                                              */
/* ------------------------------------------------------------------ */

/** The effective sign-in configuration, read-only (secrets never returned). */
export const ssoConfigQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.admin.sso(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/admin/sso', { signal })),
    staleTime: 60_000,
  })

export function useSsoConfig(options: { enabled?: boolean } = {}) {
  return useQuery({ ...ssoConfigQueryOptions(), enabled: options.enabled ?? true })
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

/** A 404 from a detail query: the user or group doesn't exist (any more). */
export function isNotFound(error: unknown): boolean {
  return isApiError(error) && (error.status === 404 || error.status === 422)
}

export type { AdminUser, Group }
