import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type {
  AltchaChallenge,
  EmailVerified,
  PublicSubmissionCreate,
  PublicSubmissionReceipt,
  TrackedSubmission,
} from '@/api/types'

/**
 * The public pages (contract-phase4 §2 "Public submission", §3.5–3.7): the form
 * at /{slug}/submit, the private tracking page (/track#<token>) and the address
 * confirmation page (/verify#<token>). No session and no CSRF token: the
 * project's setting or the token in the body is the authority. Tokens travel
 * only in JSON bodies, never in a URL the server sees (openapi-fetch sends
 * `Content-Type: application/json`, which the API requires: 415 otherwise).
 *
 * Every mutation here is `silent`: the pages show their own, friendlier errors.
 */

export const publicProjectQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.public.project(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/public/projects/{slug}', { params: { path: { slug } }, signal })),
    staleTime: 5 * 60_000,
  })

/** What the form shows (name, intro, branding) and asks for; 404 = "This form isn't available". */
export function usePublicProject(slug: string) {
  return useQuery(publicProjectQueryOptions(slug))
}

/** A fresh ALTCHA challenge for this form (signed, bound to the project, expires). */
export function fetchAltchaChallenge(slug: string, signal?: AbortSignal): Promise<AltchaChallenge> {
  return unwrap(
    api.GET('/api/v1/public/projects/{slug}/altcha', { params: { path: { slug } }, signal }),
  )
}

/** Send the idea. 201 → the receipt with the private tracking link (shown once). */
export function useSubmitPublicIdea(slug: string) {
  return useMutation<PublicSubmissionReceipt, Error, PublicSubmissionCreate>({
    mutationFn: (body) =>
      unwrap(
        api.POST('/api/v1/public/projects/{slug}/submissions', {
          params: { path: { slug } },
          body,
        }),
      ),
    meta: { silent: true },
  })
}

export const trackedSubmissionQueryOptions = (token: string) =>
  queryOptions({
    queryKey: queryKeys.public.tracking(token),
    // A read sent as POST: the token stays out of URLs (contract-phase4 §1).
    queryFn: ({ signal }) => unwrap(api.POST('/api/v1/public/track', { body: { token }, signal })),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  })

/** The tracking page: status, history and the submitter's own settings. 404 = unknown or erased. */
export function useTrackedSubmission(token: string | undefined) {
  return useQuery({
    ...trackedSubmissionQueryOptions(token ?? ''),
    enabled: Boolean(token),
  })
}

/** Status emails on or off (`false` stops them at once). */
export function useSetSubmissionUpdates(token: string) {
  const queryClient = useQueryClient()
  return useMutation<TrackedSubmission, Error, boolean>({
    mutationFn: (wantsUpdates) =>
      unwrap(
        api.PUT('/api/v1/public/track/updates', {
          body: { token, wants_updates: wantsUpdates },
        }),
      ),
    onSuccess: (tracked) => {
      queryClient.setQueryData(queryKeys.public.tracking(token), tracked)
    },
    meta: { silent: true },
  })
}

/** Send the confirmation email again (at most 3 a day). */
export function useResendVerificationEmail(token: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (): Promise<TrackedSubmission> =>
      unwrap(api.POST('/api/v1/public/track/verification-email', { body: { token } })),
    onSuccess: (tracked) => {
      queryClient.setQueryData(queryKeys.public.tracking(token), tracked)
    },
    meta: { silent: true },
  })
}

/** "Delete my details": the link stops working at once; the idea stays with the team. */
export function useEraseTrackedSubmission(token: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (): Promise<null> => {
      await api.POST('/api/v1/public/track/erase', { body: { token } })
      return null
    },
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.public.tracking(token) })
    },
    meta: { silent: true },
  })
}

/** Confirm the address (posted only on the person's click, never on load). Idempotent. */
export function useVerifySubmissionEmail() {
  return useMutation<EmailVerified, Error, string>({
    mutationFn: (token) => unwrap(api.POST('/api/v1/public/verify-email', { body: { token } })),
    meta: { silent: true },
  })
}
