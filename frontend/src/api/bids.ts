/**
 * Phase 10 (contract-phase10): calls for bids.
 *
 *   useBidTemplate(slug) · useReplaceBidTemplate(slug)       Project settings → Bids
 *   useBidCall(key)                                           the Bids tab (summary, call, permissions)
 *   useCreateBidCall · useUpdateBidCall · useChangeBidCallStatus · useCancelBidCall ·
 *     useDeleteBidCall · useReplaceBidCallTemplate · useSetBidAssessors · useAwardBidCall
 *   useBids(key) · useBid(key, bidId)                         bids (assessors never see rejected ones)
 *   useCreateBid · useUpdateBid · useDeleteBid · useRejectBid · useReinstateBid · useDecideMustHave
 *   uploadBidDocument(…) (raw body, progress) · useUpdateBidDocument · useDeleteBidDocument
 *   useBidDocumentText(key, bidId, documentId, page) · downloadBidDocument(…)
 *   useMyBidAssessment · useSaveMyBidAssessment · useSectionAssessments
 *   useBidComparison(key) · downloadBidReport(key, format)
 *   useBidAiAssessments · useRequestAiBidAssessment · useRequestAiBidAssessments · useSetBidAiInclusion
 *
 * Render what the API sends: blind cells come back `hidden`, prices `price_hidden`, pricing
 * documents as counts. Never compute scores in the client.
 */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api, unwrap, uploadRaw, type UploadOptions } from '@/api/client'
import { networkError, toApiError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { exportFilename } from '@/api/proposals'
import type {
  AiRun,
  AiRunBatch,
  BidAiAssessment,
  BidAssessorsUpdate,
  BidAwardIn,
  BidCallCreate,
  BidCallTemplateIn,
  BidCallUpdate,
  BidCallView,
  BidDocument,
  BidDocumentUpdate,
  BidIn,
  BidTemplate,
  BidTemplateIn,
  BidUpdate,
  MustHaveDecisionIn,
  MyBidAssessment,
  MyBidAssessmentIn,
} from '@/api/types'

const path = (idea: string) => ({ idea })

/* ------------------------------------------------------------------ */
/* The project's template                                              */
/* ------------------------------------------------------------------ */

export const bidTemplateQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.bidTemplate(slug),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/bid-template', { params: { path: { slug } }, signal }),
      ),
  })

export function useBidTemplate(slug: string) {
  return useQuery(bidTemplateQueryOptions(slug))
}

/** Saving replaces the whole template (422s inline); existing calls keep their copy. */
export function useReplaceBidTemplate(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidTemplateIn) =>
      unwrap(api.PUT('/api/v1/projects/{slug}/bid-template', { params: { path: { slug } }, body })),
    onSuccess: (template) =>
      queryClient.setQueryData<BidTemplate>(queryKeys.projects.bidTemplate(slug), template),
    meta: { silent: true },
  })
}

/* ------------------------------------------------------------------ */
/* The call                                                            */
/* ------------------------------------------------------------------ */

export const bidCallQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.bids.call(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}/bid-call', { params: { path: path(idea) }, signal })),
  })

export function useBidCall(idea: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...bidCallQueryOptions(idea), enabled })
}

/**
 * After any change to the call: the tab, its bids and scores, the idea (its `bid_call`
 * summary and permission flags), the feed (`bid_call_changed`), My work and the AI runs.
 */
export function settleCall(queryClient: QueryClient, idea: string, view?: BidCallView): void {
  if (view) queryClient.setQueryData(queryKeys.bids.call(idea), view)
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.idea(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) })
}

export function useCreateBidCall(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidCallCreate) =>
      unwrap(api.POST('/api/v1/ideas/{idea}/bid-call', { params: { path: path(idea) }, body })),
    onSuccess: (view) => settleCall(queryClient, idea, view),
    meta: { silent: true },
  })
}

export function useUpdateBidCall(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidCallUpdate) =>
      unwrap(api.PUT('/api/v1/ideas/{idea}/bid-call', { params: { path: path(idea) }, body })),
    onSuccess: (view) => settleCall(queryClient, idea, view),
    meta: { silent: true },
  })
}

export function useDeleteBidCall(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/v1/ideas/{idea}/bid-call', { params: { path: path(idea) } })),
    onSuccess: () => settleCall(queryClient, idea),
  })
}

export function useChangeBidCallStatus(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (status: 'open' | 'assessing') =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/bid-call/status', {
          params: { path: path(idea) },
          body: { status },
        }),
      ),
    onSuccess: (view) => settleCall(queryClient, idea, view),
  })
}

export function useCancelBidCall(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (reason: string) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/bid-call/cancellation', {
          params: { path: path(idea) },
          body: { reason },
        }),
      ),
    onSuccess: (view) => settleCall(queryClient, idea, view),
  })
}

export function useReplaceBidCallTemplate(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidCallTemplateIn) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/template', { params: { path: path(idea) }, body }),
      ),
    onSuccess: () => settleCall(queryClient, idea),
    meta: { silent: true },
  })
}

export function useSetBidAssessors(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidAssessorsUpdate) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/assessors', { params: { path: path(idea) }, body }),
      ),
    onSuccess: (view) => settleCall(queryClient, idea, view),
    meta: { silent: true },
  })
}

export function useAwardBidCall(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidAwardIn) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/bid-call/award', { params: { path: path(idea) }, body }),
      ),
    onSuccess: (view) => settleCall(queryClient, idea, view),
    meta: { silent: true },
  })
}

/* ------------------------------------------------------------------ */
/* Bids                                                                */
/* ------------------------------------------------------------------ */

export const bidsQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.bids.list(idea),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/bids', { params: { path: path(idea) }, signal }),
      ),
  })

export function useBids(idea: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...bidsQueryOptions(idea), enabled })
}

export const bidQueryOptions = (idea: string, bidId: string) =>
  queryOptions({
    queryKey: queryKeys.bids.bid(idea, bidId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}', {
          params: { path: { idea, bid_id: bidId } },
          signal,
        }),
      ),
  })

/**
 * One bid. While one of its documents is still being read, it is fetched again every
 * few seconds (the extraction runs in the worker), and stops once nothing is pending.
 */
export function useBid(idea: string, bidId: string | null, { enabled = true } = {}) {
  return useQuery({
    ...bidQueryOptions(idea, bidId ?? ''),
    enabled: enabled && Boolean(bidId),
    refetchInterval: (query) =>
      query.state.data?.documents.some((doc) => doc.extraction.state === 'pending') ? 2500 : false,
  })
}

/** A bid's write: read it again, then refresh the call's lists and scores. */
function settleBid(queryClient: QueryClient, idea: string, bidId?: string): void {
  if (bidId) void queryClient.invalidateQueries({ queryKey: queryKeys.bids.bid(idea, bidId) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.call(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.list(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.comparison(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
}

export function useCreateBid(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BidIn) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/bid-call/bids', { params: { path: path(idea) }, body }),
      ),
    onSuccess: (bid) => settleBid(queryClient, idea, bid.id),
    meta: { silent: true },
  })
}

export function useUpdateBid(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bidId, body }: { bidId: string; body: BidUpdate }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}', {
          params: { path: { idea, bid_id: bidId } },
          body,
        }),
      ),
    onSuccess: (bid) => settleBid(queryClient, idea, bid.id),
    meta: { silent: true },
  })
}

export function useDeleteBid(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (bidId: string) =>
      unwrap(
        api.DELETE('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}', {
          params: { path: { idea, bid_id: bidId } },
        }),
      ),
    onSuccess: (_data, bidId) => {
      queryClient.removeQueries({ queryKey: queryKeys.bids.bid(idea, bidId) })
      settleBid(queryClient, idea)
    },
  })
}

export function useRejectBid(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bidId, reason }: { bidId: string; reason: string }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/rejection', {
          params: { path: { idea, bid_id: bidId } },
          body: { reason },
        }),
      ),
    onSuccess: (bid) => settleBid(queryClient, idea, bid.id),
    meta: { silent: true },
  })
}

export function useReinstateBid(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (bidId: string) =>
      unwrap(
        api.DELETE('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/rejection', {
          params: { path: { idea, bid_id: bidId } },
        }),
      ),
    onSuccess: (bid) => settleBid(queryClient, idea, bid.id),
  })
}

export function useDecideMustHave(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      bidId,
      mustHaveId,
      body,
    }: {
      bidId: string
      mustHaveId: string
      body: MustHaveDecisionIn
    }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/must-haves/{must_have_id}', {
          params: { path: { idea, bid_id: bidId, must_have_id: mustHaveId } },
          body,
        }),
      ),
    onSuccess: (_state, { bidId }) => settleBid(queryClient, idea, bidId),
  })
}

/* ------------------------------------------------------------------ */
/* Documents                                                           */
/* ------------------------------------------------------------------ */

/** Files a bid may take, by size (contract-phase10 §6.1): 25 MiB each, 30 per bid. */
export const BID_DOCUMENT_MAX_BYTES = 25 * 1024 * 1024
export const BID_DOCUMENTS_PER_BID_MAX = 30
/** What the file picker offers (the server decides by the bytes, never by the name). */
export const BID_DOCUMENT_ACCEPT =
  '.pdf,.docx,.xlsx,.pptx,.odt,.ods,.txt,.csv,.png,.jpg,.jpeg,application/pdf,text/plain,text/csv,image/png,image/jpeg'

export interface UploadTarget {
  idea: string
  bidId: string
  file: File
  /** The name to send (default: the file's own). */
  filename?: string
  mustHaveId?: string | null
  pricing?: boolean
}

/**
 * Uploads one file as the raw body (`application/octet-stream`), reporting progress. The
 * file's name travels percent-encoded in `X-Filename`, never in the query string, so it
 * stays out of proxies' access logs (contract-phase10 §21, review N2).
 */
export function uploadBidDocument(
  { idea, bidId, file, filename, mustHaveId, pricing }: UploadTarget,
  options: UploadOptions = {},
): Promise<BidDocument> {
  const query = new URLSearchParams()
  if (mustHaveId) query.set('must_have_id', mustHaveId)
  if (pricing !== undefined) query.set('pricing', String(pricing))
  const search = query.toString()
  const url = `/api/v1/ideas/${encodeURIComponent(idea)}/bid-call/bids/${encodeURIComponent(bidId)}/documents${search ? `?${search}` : ''}`
  return uploadRaw<BidDocument>(url, file, {
    ...options,
    headers: { ...options.headers, 'X-Filename': encodeURIComponent(filename ?? file.name) },
  })
}

/** After an upload: the bid (documents and must-haves) and the call's lists. */
export function documentUploaded(queryClient: QueryClient, idea: string, bidId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.bid(idea, bidId) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.list(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.bids.call(idea) })
}

export function useUpdateBidDocument(idea: string, bidId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ documentId, body }: { documentId: string; body: BidDocumentUpdate }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/documents/{document_id}', {
          params: { path: { idea, bid_id: bidId, document_id: documentId } },
          body,
        }),
      ),
    onSuccess: () => documentUploaded(queryClient, idea, bidId),
  })
}

export function useDeleteBidDocument(idea: string, bidId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      unwrap(
        api.DELETE('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/documents/{document_id}', {
          params: { path: { idea, bid_id: bidId, document_id: documentId } },
        }),
      ),
    onSuccess: () => documentUploaded(queryClient, idea, bidId),
  })
}

export const bidDocumentTextQueryOptions = (
  idea: string,
  bidId: string,
  documentId: string,
  page: number,
) =>
  queryOptions({
    queryKey: queryKeys.bids.text(idea, bidId, documentId, page),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/documents/{document_id}/text', {
          params: {
            path: { idea, bid_id: bidId, document_id: documentId },
            query: { page },
          },
          signal,
        }),
      ),
  })

/** One page of a document's extracted text (untrusted: shown as plain text). */
export function useBidDocumentText(
  idea: string,
  bidId: string,
  documentId: string | null,
  page: number,
) {
  return useQuery({
    ...bidDocumentTextQueryOptions(idea, bidId, documentId ?? '', page),
    enabled: Boolean(documentId),
  })
}

/**
 * The page of a document's text that holds an AI quote (UX review m13): its pages are
 * read in order until one has it (whitespace and case aside, as the server checks
 * quotes); null when none does. Each page read is cached for the reader.
 */
export function useQuotePage(
  idea: string,
  bidId: string,
  document: Pick<BidDocument, 'id' | 'extraction'> | null,
  quote: string | null,
  find: (text: string, quote: string) => unknown,
) {
  const queryClient = useQueryClient()
  const pages = Math.max(1, document?.extraction.page_count ?? 1)
  return useQuery({
    queryKey: [...queryKeys.bids.bid(idea, bidId), 'quote', document?.id ?? '', quote ?? ''],
    queryFn: async () => {
      if (!document || !quote) return null
      for (let page = 1; page <= pages; page++) {
        const text = await queryClient.query(
          bidDocumentTextQueryOptions(idea, bidId, document.id, page),
        )
        if (find(text.text, quote)) return page
      }
      return null
    },
    enabled: Boolean(document && quote && document.extraction.state === 'done'),
    staleTime: Infinity,
  })
}

/** Starts a browser download (never shown inline: contract-phase10 §6.2). */
async function download(url: string, fallback: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(url, { credentials: 'same-origin' })
  } catch (error) {
    throw networkError(error)
  }
  if (!response.ok) throw await toApiError(response)
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = exportFilename(response, fallback)
  link.rel = 'noopener'
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

export function downloadBidDocument(
  idea: string,
  bidId: string,
  document: Pick<BidDocument, 'id' | 'filename'>,
): Promise<void> {
  const url = `/api/v1/ideas/${encodeURIComponent(idea)}/bid-call/bids/${encodeURIComponent(bidId)}/documents/${encodeURIComponent(document.id)}/content`
  // The name is the server's (Content-Disposition); this one only when it can't be read.
  const safe = document.filename.replace(/[^\w.-]+/g, '_') || 'document'
  return download(url, safe)
}

export type BidReportFormat = 'markdown' | 'pdf'

export function downloadBidReport(idea: string, format: BidReportFormat): Promise<void> {
  const url = `/api/v1/ideas/${encodeURIComponent(idea)}/bid-call/report/${format}`
  return download(url, `${idea.toUpperCase()}-bid-evaluation.${format === 'pdf' ? 'pdf' : 'md'}`)
}

export function useExportBidReport(idea: string) {
  return useMutation({
    mutationFn: (format: BidReportFormat) => downloadBidReport(idea, format),
    meta: { silent: true },
  })
}

/* ------------------------------------------------------------------ */
/* Assessments                                                         */
/* ------------------------------------------------------------------ */

export function useMyBidAssessment(
  idea: string,
  bidId: string | null,
  sectionId: string | null,
  { enabled = true } = {},
) {
  return useQuery({
    queryKey: queryKeys.bids.mine(idea, bidId ?? '', sectionId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessment', {
          params: { path: { idea, bid_id: bidId ?? '', section_id: sectionId ?? '' } },
          signal,
        }),
      ),
    enabled: enabled && Boolean(bidId && sectionId),
  })
}

export function useSaveMyBidAssessment(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      bidId,
      sectionId,
      body,
    }: {
      bidId: string
      sectionId: string
      body: MyBidAssessmentIn
    }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessment', {
          params: { path: { idea, bid_id: bidId, section_id: sectionId } },
          body,
        }),
      ),
    onSuccess: (assessment: MyBidAssessment, { bidId, sectionId }) => {
      queryClient.setQueryData(queryKeys.bids.mine(idea, bidId, sectionId), assessment)
      if (assessment.state === 'submitted') {
        // Submitting ends the blindness for that bid and section, and moves the progress.
        void queryClient.invalidateQueries({
          queryKey: queryKeys.bids.section(idea, bidId, sectionId),
        })
        void queryClient.invalidateQueries({ queryKey: queryKeys.bids.bid(idea, bidId) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.bids.list(idea) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.bids.call(idea) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.bids.comparison(idea) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
      }
    },
    meta: { silent: true },
  })
}

export function useSectionAssessments(
  idea: string,
  bidId: string | null,
  sectionId: string | null,
  { enabled = true } = {},
) {
  return useQuery({
    queryKey: queryKeys.bids.section(idea, bidId ?? '', sectionId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessments', {
          params: { path: { idea, bid_id: bidId ?? '', section_id: sectionId ?? '' } },
          signal,
        }),
      ),
    enabled: enabled && Boolean(bidId && sectionId),
  })
}

/* ------------------------------------------------------------------ */
/* The comparison                                                      */
/* ------------------------------------------------------------------ */

export function useBidComparison(idea: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.bids.comparison(idea),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/comparison', {
          params: { path: path(idea) },
          signal,
        }),
      ),
    enabled,
  })
}

/* ------------------------------------------------------------------ */
/* The AI assessor                                                     */
/* ------------------------------------------------------------------ */

export function useBidAiAssessments(
  idea: string,
  bidId: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.bids.ai(idea, bidId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/ai-assessments', {
          params: { path: { idea, bid_id: bidId ?? '' } },
          signal,
        }),
      ),
    enabled: enabled && Boolean(bidId),
  })
}

export function useRequestAiBidAssessment(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bidId, agentId }: { bidId: string; agentId: string }): Promise<AiRun> =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/ai-assessment', {
          params: { path: { idea, bid_id: bidId } },
          body: { agent_id: agentId },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) }),
  })
}

export function useRequestAiBidAssessments(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string): Promise<AiRunBatch> =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/bid-call/ai-assessments', {
          params: { path: path(idea) },
          body: { agent_id: agentId },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) }),
  })
}

export function useSetBidAiInclusion(idea: string, bidId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ assessmentId, include }: { assessmentId: string; include: boolean }) =>
      unwrap(
        api.PUT(
          '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/ai-assessments/{ai_assessment_id}/include-in-totals',
          {
            params: { path: { idea, bid_id: bidId, ai_assessment_id: assessmentId } },
            body: { include },
          },
        ),
      ),
    onSuccess: (assessment: BidAiAssessment) => {
      queryClient.setQueryData<{ items: BidAiAssessment[]; can_include: boolean }>(
        queryKeys.bids.ai(idea, bidId),
        (current) =>
          current && {
            ...current,
            items: current.items.map((item) => (item.id === assessment.id ? assessment : item)),
          },
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.bids.comparison(idea) })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bids.bid(idea, bidId),
        predicate: (query) => query.queryKey.includes('section'),
      })
    },
  })
}
