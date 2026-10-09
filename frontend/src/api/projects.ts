import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { snapshot } from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type {
  Member,
  Project,
  ProjectCreate,
  ProjectGroupGrant,
  ProjectRole,
  ProjectUpdate,
  RubricUpdate,
} from '@/api/types'
import { offerUndo } from '@/api/undo'

/* ------------------------------------------------------------------ */
/* Queries                                                             */
/* ------------------------------------------------------------------ */

/** Projects the user can see (sidebar, pickers), by name. */
export const projectsQueryOptions = (includeArchived = false) =>
  queryOptions({
    queryKey: queryKeys.projects.list(includeArchived),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects', {
          params: { query: includeArchived ? { include_archived: true } : {} },
          signal,
        }),
      ),
    staleTime: 60_000,
  })

export function useProjects(includeArchived = false) {
  return useQuery(projectsQueryOptions(includeArchived))
}

/** One project: settings, resolved status labels, rubric and `permissions`. */
export const projectQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.detail(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/projects/{slug}', { params: { path: { slug } }, signal })),
    staleTime: 60_000,
  })

/** `enabled: false` for a guest researcher, who may read the idea but never its project. */
export function useProject(slug: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...projectQueryOptions(slug), enabled: options.enabled ?? true })
}

export const projectMembersQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.members(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/projects/{slug}/members', { params: { path: { slug } }, signal })),
  })

export function useProjectMembers(slug: string) {
  return useQuery(projectMembersQueryOptions(slug))
}

/** Groups granted a role in the project (contract-phase2 §3.7), admins first, then by name. */
export const projectGroupGrantsQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.groupGrants(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/projects/{slug}/groups', { params: { path: { slug } }, signal })),
  })

export function useProjectGroupGrants(slug: string) {
  return useQuery(projectGroupGrantsQueryOptions(slug))
}

export interface ProjectAccessParams {
  /** Part of a name or email. */
  q?: string
  /** Only this effective role. */
  role?: ProjectRole
  limit?: number
}

/**
 * Everyone with an effective role and why (`list_project_access`): direct and
 * group sources, by name, paged ("Show more").
 */
export const projectAccessInfiniteOptions = (
  slug: string,
  { q = '', role, limit = 50 }: ProjectAccessParams = {},
) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.projects.access(slug, { q, role }), { limit }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/access', {
          params: {
            path: { slug },
            query: { q: q.trim() || undefined, role, cursor: pageParam ?? undefined, limit },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })

export function useProjectAccess(slug: string, params: ProjectAccessParams = {}) {
  return useInfiniteQuery(projectAccessInfiniteOptions(slug, params))
}

/** Tags in use (filter chips, tag autocomplete). */
export const projectTagsQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.tags(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/projects/{slug}/tags', { params: { path: { slug } }, signal })),
    staleTime: 60_000,
  })

export function useProjectTags(slug: string | undefined) {
  return useQuery({ ...projectTagsQueryOptions(slug ?? ''), enabled: Boolean(slug) })
}

/* ------------------------------------------------------------------ */
/* Mutations                                                           */
/* ------------------------------------------------------------------ */

/** Platform admins: create a project. Errors: 409 slug_taken / key_taken, 422 user_not_found. */
export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectCreate) => unwrap(api.POST('/api/v1/projects', { body })),
    onSuccess: (project) => {
      queryClient.setQueryData(queryKeys.projects.detail(project.slug), project)
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.lists() })
    },
    // Field errors are shown inline by the form.
    meta: { silent: true },
  })
}

/**
 * Settings (name, visibility, labels, archive…). Optimistic for the fields
 * that map 1:1; the response replaces the cache. Archiving offers Undo
 * (`update_project {archived: false}`) unless `undo: false`.
 */
export function useUpdateProject(slug: string, { undo = true }: { undo?: boolean } = {}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (body: ProjectUpdate & { isUndo?: boolean }) => {
      const { isUndo: _isUndo, ...request } = body
      return unwrap(
        api.PATCH('/api/v1/projects/{slug}', { params: { path: { slug } }, body: request }),
      )
    },
    onMutate: async (body) => {
      const rollback = await snapshot(queryClient, [queryKeys.projects.detail(slug)])
      queryClient.setQueryData<Project>(queryKeys.projects.detail(slug), (project) => {
        if (!project) return project
        const next: Project = { ...project }
        if (body.name != null) next.name = body.name
        if (body.description != null) next.description = body.description
        if (body.visibility != null) next.visibility = body.visibility
        if (body.allow_volunteer_owners != null) {
          next.allow_volunteer_owners = body.allow_volunteer_owners
        }
        if (body.default_evaluation_days != null) {
          next.default_evaluation_days = body.default_evaluation_days
        }
        if (body.archived === true) next.archived_at ??= new Date().toISOString()
        if (body.archived === false) next.archived_at = null
        return next
      })
      return { rollback }
    },
    onError: (_error, _body, context) => context?.rollback(),
    onSuccess: (project, body) => {
      queryClient.setQueryData(queryKeys.projects.detail(slug), project)
      if (undo && !body.isUndo && typeof body.archived === 'boolean') {
        const archived = body.archived
        offerUndo(archived ? `${project.name} archived` : `${project.name} restored`, () =>
          mutation.mutate({ archived: !archived, isUndo: true }),
        )
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.lists() })
      // Archiving changes what My work, lists and search show.
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
    },
    meta: { errorTitle: 'Couldn’t save the project settings' },
  })
  return mutation
}

export function useAddProjectMember(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { user_id: string; role?: ProjectRole }) =>
      unwrap(
        api.POST('/api/v1/projects/{slug}/members', {
          params: { path: { slug } },
          body: { user_id: body.user_id, role: body.role ?? 'member' },
        }),
      ),
    onSuccess: (member) => {
      queryClient.setQueryData<Member[]>(queryKeys.projects.members(slug), (members) =>
        members
          ? sortMembers([...members.filter((m) => m.user.id !== member.user.id), member])
          : members,
      )
    },
    onSettled: () => invalidateMembership(queryClient, slug),
    meta: { errorTitle: 'Couldn’t add that person' },
  })
}

/** Change a member's role, optimistically, with Undo (the previous role). */
export function useUpdateProjectMember(slug: string, { undo = true }: { undo?: boolean } = {}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: ProjectRole; isUndo?: boolean }) =>
      unwrap(
        api.PATCH('/api/v1/projects/{slug}/members/{user_id}', {
          params: { path: { slug, user_id: userId } },
          body: { role },
        }),
      ),
    onMutate: async ({ userId, role }) => {
      const rollback = await snapshot(queryClient, [queryKeys.projects.members(slug)])
      const previous = queryClient
        .getQueryData<Member[]>(queryKeys.projects.members(slug))
        ?.find((m) => m.user.id === userId)
      queryClient.setQueryData<Member[]>(queryKeys.projects.members(slug), (members) =>
        members?.map((m) => (m.user.id === userId ? { ...m, role } : m)),
      )
      return { rollback, previous }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (member, vars, context) => {
      const previous = context.previous
      if (undo && !vars.isUndo && previous && previous.role !== vars.role) {
        offerUndo(`${member.user.display_name} is now ${roleLabel(vars.role)}`, () =>
          mutation.mutate({ userId: vars.userId, role: previous.role, isUndo: true }),
        )
      }
    },
    onSettled: () => invalidateMembership(queryClient, slug),
    meta: { errorTitle: 'Couldn’t change the role' },
  })
  return mutation
}

/** Remove a member, optimistically, with Undo (re-add with the previous role). */
export function useRemoveProjectMember(slug: string, { undo = true }: { undo?: boolean } = {}) {
  const queryClient = useQueryClient()
  const add = useAddProjectMember(slug)
  return useMutation({
    mutationFn: ({ userId }: { userId: string }) =>
      api.DELETE('/api/v1/projects/{slug}/members/{user_id}', {
        params: { path: { slug, user_id: userId } },
      }),
    onMutate: async ({ userId }) => {
      const rollback = await snapshot(queryClient, [queryKeys.projects.members(slug)])
      const previous = queryClient
        .getQueryData<Member[]>(queryKeys.projects.members(slug))
        ?.find((m) => m.user.id === userId)
      queryClient.setQueryData<Member[]>(queryKeys.projects.members(slug), (members) =>
        members?.filter((m) => m.user.id !== userId),
      )
      return { rollback, previous }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (_data, { userId }, context) => {
      const previous = context.previous
      if (undo && previous) {
        offerUndo(`${previous.user.display_name} removed`, () =>
          add.mutate({ user_id: userId, role: previous.role }),
        )
      }
    },
    onSettled: () => invalidateMembership(queryClient, slug),
    meta: { errorTitle: 'Couldn’t remove that person' },
  })
}

/** Give a group a role in the project. Errors: 409 already_granted, 422 group_not_found. */
export function useAddProjectGroupGrant(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { group_id: string; role?: ProjectRole }) =>
      unwrap(
        api.POST('/api/v1/projects/{slug}/groups', {
          params: { path: { slug } },
          body: { group_id: body.group_id, role: body.role ?? 'member' },
        }),
      ),
    onSuccess: (grant) => {
      queryClient.setQueryData<ProjectGroupGrant[]>(
        queryKeys.projects.groupGrants(slug),
        (grants) =>
          grants
            ? sortGrants([...grants.filter((g) => g.group.id !== grant.group.id), grant])
            : grants,
      )
    },
    onSettled: () => invalidateMembership(queryClient, slug),
    meta: { errorTitle: 'Couldn’t add that group' },
  })
}

/** Change a group's role, optimistically, with Undo (the previous role). 409 last_admin. */
export function useUpdateProjectGroupGrant(slug: string, { undo = true }: { undo?: boolean } = {}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ groupId, role }: { groupId: string; role: ProjectRole; isUndo?: boolean }) =>
      unwrap(
        api.PATCH('/api/v1/projects/{slug}/groups/{group_id}', {
          params: { path: { slug, group_id: groupId } },
          body: { role },
        }),
      ),
    onMutate: async ({ groupId, role }) => {
      const rollback = await snapshot(queryClient, [queryKeys.projects.groupGrants(slug)])
      const previous = queryClient
        .getQueryData<ProjectGroupGrant[]>(queryKeys.projects.groupGrants(slug))
        ?.find((g) => g.group.id === groupId)
      queryClient.setQueryData<ProjectGroupGrant[]>(
        queryKeys.projects.groupGrants(slug),
        (grants) =>
          grants && sortGrants(grants.map((g) => (g.group.id === groupId ? { ...g, role } : g))),
      )
      return { rollback, previous }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (grant, vars, context) => {
      const previous = context.previous
      if (undo && !vars.isUndo && previous && previous.role !== vars.role) {
        offerUndo(`Everyone in ${grant.group.name} is now ${roleLabel(vars.role)}`, () =>
          mutation.mutate({ groupId: vars.groupId, role: previous.role, isUndo: true }),
        )
      }
    },
    onSettled: () => invalidateMembership(queryClient, slug),
    meta: { errorTitle: 'Couldn’t change the group’s role' },
  })
  return mutation
}

/** Take a group's role away, optimistically, with Undo (grant it again). 409 last_admin. */
export function useRemoveProjectGroupGrant(slug: string, { undo = true }: { undo?: boolean } = {}) {
  const queryClient = useQueryClient()
  const add = useAddProjectGroupGrant(slug)
  return useMutation({
    mutationFn: ({ groupId }: { groupId: string }) =>
      api.DELETE('/api/v1/projects/{slug}/groups/{group_id}', {
        params: { path: { slug, group_id: groupId } },
      }),
    onMutate: async ({ groupId }) => {
      const rollback = await snapshot(queryClient, [queryKeys.projects.groupGrants(slug)])
      const previous = queryClient
        .getQueryData<ProjectGroupGrant[]>(queryKeys.projects.groupGrants(slug))
        ?.find((g) => g.group.id === groupId)
      queryClient.setQueryData<ProjectGroupGrant[]>(
        queryKeys.projects.groupGrants(slug),
        (grants) => grants?.filter((g) => g.group.id !== groupId),
      )
      return { rollback, previous }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (_data, { groupId }, context) => {
      const previous = context.previous
      if (undo && previous) {
        offerUndo(`${previous.group.name} removed`, () =>
          add.mutate({ group_id: groupId, role: previous.role }),
        )
      }
    },
    onSettled: () => invalidateMembership(queryClient, slug),
    meta: { errorTitle: 'Couldn’t remove that group' },
  })
}

/** Replace the rubric (3–6 criteria). Recomputes every aggregate, so ideas refetch. */
export function useReplaceRubric(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: RubricUpdate) =>
      unwrap(api.PUT('/api/v1/projects/{slug}/rubric', { params: { path: { slug } }, body })),
    onSuccess: (rubric) => {
      queryClient.setQueryData<Project>(queryKeys.projects.detail(slug), (project) =>
        project ? { ...project, rubric: rubric.criteria } : project,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
    },
    meta: { silent: true },
  })
}

/* ------------------------------------------------------------------ */

function sortMembers(members: Member[]): Member[] {
  return [...members].sort(
    (a, b) =>
      Number(b.role === 'admin') - Number(a.role === 'admin') ||
      a.user.display_name.localeCompare(b.user.display_name),
  )
}

function sortGrants(grants: ProjectGroupGrant[]): ProjectGroupGrant[] {
  return [...grants].sort(
    (a, b) =>
      Number(b.role === 'admin') - Number(a.role === 'admin') ||
      a.group.name.localeCompare(b.group.name),
  )
}

/** Direct members, group grants and the access list all change together. */
function invalidateMembership(queryClient: ReturnType<typeof useQueryClient>, slug: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.members(slug) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.groupGrants(slug) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.accessAll(slug) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(slug), exact: true })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.lists() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.users.all })
}

function roleLabel(role: ProjectRole): string {
  return role === 'admin' ? 'an admin' : role === 'member' ? 'a member' : 'a viewer'
}
