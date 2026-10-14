import type {
  AiMustHaveFinding,
  BidCallStatus,
  BidDocumentExtraction,
  BidDocumentType,
  BidMustHaveCounts,
  BidStatus,
  ExtractionError,
  MustHaveResult,
} from '@/api/types'

/*
 * Words for calls for bids (contract-phase10): statuses, must-have results, documents
 * and their extraction, prices and sizes. Bid documents, bidder names, AI rationales and
 * quotes are data shown as plain text; these are Soundings' own words.
 */

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export const CALL_STATUS: Record<
  BidCallStatus,
  { label: string; tone: Tone; description: string }
> = {
  draft: {
    label: 'Draft',
    tone: 'neutral',
    description: 'Not open yet: set it up, then open it to bids.',
  },
  open: { label: 'Open', tone: 'info', description: 'Bids are being entered.' },
  assessing: {
    label: 'Assessing',
    tone: 'warning',
    description: 'Closed to new bids: the assessors are scoring.',
  },
  awarded: { label: 'Awarded', tone: 'success', description: 'Awarded: the call is read-only.' },
  cancelled: {
    label: 'Cancelled',
    tone: 'neutral',
    description: 'Cancelled: the call is read-only.',
  },
}

export const BID_STATUS: Record<BidStatus, { label: string; tone: Tone }> = {
  received: { label: 'Received', tone: 'neutral' },
  qualified: { label: 'Qualified', tone: 'info' },
  rejected: { label: 'Rejected', tone: 'danger' },
  awarded: { label: 'Awarded', tone: 'success' },
  unsuccessful: { label: 'Unsuccessful', tone: 'neutral' },
}

export const MUST_HAVE_RESULT: Record<MustHaveResult, { label: string; tone: Tone }> = {
  met: { label: 'Met', tone: 'success' },
  not_met: { label: 'Not met', tone: 'danger' },
  missing: { label: 'Missing', tone: 'danger' },
  unchecked: { label: 'To check', tone: 'warning' },
}

export const AI_FINDING: Record<AiMustHaveFinding, { label: string; tone: Tone }> = {
  met: { label: 'Suggests met', tone: 'neutral' },
  not_met: { label: 'Suggests not met', tone: 'warning' },
  unclear: { label: 'Couldn’t tell', tone: 'neutral' },
}

/** "1 missing · 1 to check", "All met", "No must-haves". */
export function mustHaveSummary(counts: BidMustHaveCounts): { text: string; flagged: boolean } {
  const total = counts.met + counts.not_met + counts.missing + counts.unchecked
  if (total === 0) return { text: 'No must-haves', flagged: false }
  const parts = [
    counts.missing && `${counts.missing} missing`,
    counts.not_met && `${counts.not_met} not met`,
    counts.unchecked && `${counts.unchecked} to check`,
  ].filter(Boolean)
  if (parts.length === 0) return { text: `All ${total} met`, flagged: false }
  return { text: parts.join(' · '), flagged: counts.missing > 0 || counts.not_met > 0 }
}

export const DOCUMENT_TYPE_LABEL: Record<BidDocumentType, string> = {
  pdf: 'PDF',
  docx: 'Word',
  xlsx: 'Excel',
  pptx: 'PowerPoint',
  odt: 'OpenDocument text',
  ods: 'OpenDocument spreadsheet',
  txt: 'Text',
  csv: 'CSV',
  png: 'PNG image',
  jpeg: 'JPEG image',
}

const EXTRACTION_ERROR: Record<ExtractionError, string> = {
  timeout: 'reading it took too long',
  memory: 'it was too big to read',
  damaged: 'the file looks damaged',
  encrypted: 'the file is password-protected',
  archive_limits: 'it unpacks to more than a document should',
  internal_error: 'something went wrong on our side',
}

/** "Reading text…", "1,204 characters of text", "No text (an image)", "Couldn't read: …". */
export function extractionText(extraction: BidDocumentExtraction, type: BidDocumentType): string {
  switch (extraction.state) {
    case 'pending':
      return 'Reading the text…'
    case 'done':
      return `${(extraction.chars ?? 0).toLocaleString('en')} characters of text${extraction.truncated ? ' (cut at 2,000,000)' : ''}`
    case 'no_text':
      return type === 'png' || type === 'jpeg' ? 'An image: no text to read' : 'No text in it'
    case 'failed':
      return `Couldn’t read the text: ${extraction.error ? EXTRACTION_ERROR[extraction.error] : 'it failed'}`
  }
}

/** "2.4 MB", "48 KB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** "£120,000.00" from "120000.00" and GBP (a label: no conversion). */
export function formatPrice(price: string | null, currency: string): string {
  if (price === null) return '—'
  const value = Number(price)
  if (!Number.isFinite(value)) return price
  try {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
    }).format(value)
  } catch {
    return `${currency} ${value.toLocaleString('en-GB', { minimumFractionDigits: 2 })}`
  }
}

/** 0-100 with one decimal ("86.7"); "—" while there is none. */
export function formatPoints(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toFixed(1)
}

/** "n of m assessed". */
export function progressText({ submitted, total }: { submitted: number; total: number }): string {
  return total === 0 ? 'No assessors yet' : `${submitted} of ${total} assessed`
}

/** The file picker and drop zone's words for what can be uploaded. */
export const UPLOAD_TYPES_TEXT =
  'PDF, Word, Excel, PowerPoint, OpenDocument, text, CSV, PNG or JPEG, up to 25 MB each'

/** Why a file can't be sent before it's tried (size only: the server reads the type). */
export function uploadProblem(
  file: File,
  maxBytes: number,
  name: string = file.name,
): string | null {
  if (file.size === 0) return `${name} is empty.`
  if (file.size > maxBytes)
    return `${name} is ${formatSize(file.size)}: files can be at most 25 MB.`
  return null
}
