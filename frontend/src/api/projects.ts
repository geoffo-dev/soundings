import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { snapshot } from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type {
  Member,
  Project,
  ProjectCreate,
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

export function useProject(slug: string) {
  return useQuery(projectQueryOptions(slug))
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

function invalidateMembership(queryClient: ReturnType<typeof useQueryClient>, slug: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.members(slug) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(slug), exact: true })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.lists() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.users.all })
}

function roleLabel(role: ProjectRole): string {
  return role === 'admin' ? 'an admin' : role === 'member' ? 'a member' : 'a viewer'
}
