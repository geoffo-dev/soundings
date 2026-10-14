import { afterEach, describe, expect, it, vi } from 'vitest'

import { uploadBidDocument } from '@/api/bids'

/** A stand-in XMLHttpRequest that records what the upload sends and answers 201. */
class RecordingXhr {
  static last: RecordingXhr | null = null
  method = ''
  url = ''
  headers: Record<string, string> = {}
  body: unknown = null
  status = 201
  statusText = 'Created'
  responseText = JSON.stringify({ id: 'doc-1', filename: 'Pricing schedule – é.pdf' })
  withCredentials = false
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    RecordingXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  getAllResponseHeaders() {
    return 'content-type: application/json\r\n'
  }
  send(body: unknown) {
    this.body = body
    queueMicrotask(() => this.onload?.())
  }
  abort() {
    this.onabort?.()
  }
}

describe('uploadBidDocument', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    RecordingXhr.last = null
  })

  it('sends the file name percent-encoded in X-Filename, never in the query (review N2)', async () => {
    vi.stubGlobal('XMLHttpRequest', RecordingXhr)
    const file = new File(['%PDF-1.7'], 'ignored.pdf')
    const document = await uploadBidDocument({
      idea: 'TOOLS-3',
      bidId: 'bid 1',
      file,
      filename: 'Pricing schedule – é.pdf',
      mustHaveId: 'mh-1',
      pricing: true,
    })
    const xhr = RecordingXhr.last
    expect(xhr?.method).toBe('POST')
    expect(xhr?.url).toBe(
      '/api/v1/ideas/TOOLS-3/bid-call/bids/bid%201/documents?must_have_id=mh-1&pricing=true',
    )
    expect(xhr?.url).not.toContain('filename')
    expect(xhr?.headers['X-Filename']).toBe('Pricing%20schedule%20%E2%80%93%20%C3%A9.pdf')
    expect(decodeURIComponent(xhr?.headers['X-Filename'] ?? '')).toBe('Pricing schedule – é.pdf')
    expect(xhr?.headers['Content-Type']).toBe('application/octet-stream')
    expect(xhr?.body).toBe(file)
    expect(document).toMatchObject({ id: 'doc-1' })
  })

  it("defaults to the file's own name and sends no query string without options", async () => {
    vi.stubGlobal('XMLHttpRequest', RecordingXhr)
    await uploadBidDocument({ idea: 'TOOLS-3', bidId: 'b1', file: new File(['x'], 'notes.txt') })
    expect(RecordingXhr.last?.url).toBe('/api/v1/ideas/TOOLS-3/bid-call/bids/b1/documents')
    expect(RecordingXhr.last?.headers['X-Filename']).toBe('notes.txt')
  })
})
