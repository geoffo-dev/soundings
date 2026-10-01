import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type {
  BrandAsset,
  BrandAssetKind,
  BrandingSettings,
  BrandingUpdate,
  EffectiveBranding,
} from '@/api/types'

/**
 * Branding (contract-phase4 §2 "Branding", §3.10–3.11). The signed-in app
 * always shows the global branding (`GET /branding`, public); a project's
 * override applies only where it faces outward (its public pages, its emails to
 * submitters and exported proposals). Settings: the global profile for platform
 * admins (/settings/branding), a project's override for its admins (project
 * settings → Branding). Images are uploaded as the raw file (PNG or SVG).
 */

/** Refetched on window focus at most every 5 minutes (contract §3.10). */
const EFFECTIVE_STALE_MS = 5 * 60_000

export const effectiveBrandingQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.branding.effective(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/branding', { signal })),
    staleTime: EFFECTIVE_STALE_MS,
    refetchOnWindowFocus: true,
  })

/** What the app shows: name, colours, font, logo, favicon (global). */
export function useEffectiveBranding() {
  return useQuery(effectiveBrandingQueryOptions())
}

export const globalBrandingQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.branding.global(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/admin/branding', { signal })),
  })

export function useGlobalBranding() {
  return useQuery(globalBrandingQueryOptions())
}

export const projectBrandingQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.branding.project(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/projects/{slug}/branding', { params: { path: { slug } }, signal })),
  })

export function useProjectBranding(slug: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...projectBrandingQueryOptions(slug), enabled: options.enabled ?? true })
}

/** Where a branding profile lives: the global one, or one project's override. */
export type BrandingScope = { kind: 'global' } | { kind: 'project'; slug: string }

function settingsKey(scope: BrandingScope) {
  return scope.kind === 'global'
    ? queryKeys.branding.global()
    : queryKeys.branding.project(scope.slug)
}

/** Save the complete profile (null = inherit; an empty body resets it). Errors are shown inline. */
export function useUpdateBranding(scope: BrandingScope) {
  const queryClient = useQueryClient()
  return useMutation<BrandingSettings, Error, BrandingUpdate>({
    mutationFn: (body) =>
      scope.kind === 'global'
        ? unwrap(api.PUT('/api/v1/admin/branding', { body }))
        : unwrap(
            api.PUT('/api/v1/projects/{slug}/branding', {
              params: { path: { slug: scope.slug } },
              body,
            }),
          ),
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsKey(scope), settings)
      if (scope.kind === 'global') {
        // The shell re-themes at once; project settings inherit from it.
        queryClient.setQueryData<EffectiveBranding>(
          queryKeys.branding.effective(),
          settings.effective,
        )
        void queryClient.invalidateQueries({ queryKey: queryKeys.branding.all })
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.public.all })
    },
    meta: { silent: true },
  })
}

/** The request's Content-Type: the bytes decide on the server, the type is a hint. */
export function imageContentType(file: File): 'image/png' | 'image/svg+xml' | null {
  const name = file.name.toLowerCase()
  if (file.type === 'image/png' || name.endsWith('.png')) return 'image/png'
  if (file.type === 'image/svg+xml' || name.endsWith('.svg')) return 'image/svg+xml'
  return null
}

/** Upload a logo or favicon for this profile (the raw file as the body). */
export function uploadBrandAsset(
  scope: BrandingScope,
  kind: BrandAssetKind,
  file: File,
): Promise<BrandAsset> {
  const contentType = imageContentType(file) ?? 'image/png'
  // A raw body, not JSON (contract-phase4 §1 "Raw bodies").
  const raw = {
    body: file as unknown as string,
    bodySerializer: (body: unknown) => body as BodyInit,
    headers: { 'Content-Type': contentType },
  }
  return scope.kind === 'global'
    ? unwrap(api.POST('/api/v1/admin/branding/assets', { params: { query: { kind } }, ...raw }))
    : unwrap(
        api.POST('/api/v1/projects/{slug}/branding/assets', {
          params: { path: { slug: scope.slug }, query: { kind } },
          ...raw,
        }),
      )
}

export function useUploadBrandAsset(scope: BrandingScope) {
  return useMutation<BrandAsset, Error, { kind: BrandAssetKind; file: File }>({
    mutationFn: ({ kind, file }) => uploadBrandAsset(scope, kind, file),
    meta: { silent: true },
  })
}
