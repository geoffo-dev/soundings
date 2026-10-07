import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { inflateSync } from 'node:zlib'

import type { Browser } from '@playwright/test'

/**
 * Reading exported proposals (Phase 4) without a PDF tool on the machine: text and
 * metadata through pdf.js (`pdfjs-dist`, its Node build), colours and embedded font names
 * from the PDF's own (Flate-compressed) streams, and pages rendered to PNG by pdf.js in
 * Chromium for the review screenshots.
 */

export interface PdfInfo {
  pages: string[]
  title: string
  author: string
  creator: string
}

const require = createRequire(import.meta.url)

/** The text of every page (lines joined with spaces) and the document's metadata. */
export async function readPdf(bytes: Buffer): Promise<PdfInfo> {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  // The loading task owns the document: destroying it frees both (pdf.js 5 and 6; 6
  // dropped `PDFDocumentProxy.destroy()`).
  const task = pdfjs.getDocument({
    data: new Uint8Array(bytes),
    useSystemFonts: false,
    disableFontFace: true,
    verbosity: 0,
  })
  const document = await task.promise
  try {
    const pages: string[] = []
    for (let number = 1; number <= document.numPages; number++) {
      const page = await document.getPage(number)
      const content = await page.getTextContent()
      const text = content.items
        .map((item) => ('str' in item ? item.str + (item.hasEOL ? '\n' : '') : ''))
        .join('')
      pages.push(text.replace(/[ \t]+/g, ' '))
    }
    const { info } = (await document.getMetadata()) as unknown as { info: Record<string, unknown> }
    const field = (name: string) => (typeof info[name] === 'string' ? (info[name] as string) : '')
    return { pages, title: field('Title'), author: field('Author'), creator: field('Creator') }
  } finally {
    await task.destroy()
  }
}

/** Every stream in the file, inflated where it is Flate-compressed (others as they are). */
function streams(bytes: Buffer): Buffer[] {
  const found: Buffer[] = []
  const source = bytes.toString('latin1')
  // `stream` after a dictionary, not the end of `endstream`.
  const pattern = /(?<!end)stream\r?\n/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(source))) {
    const start = match.index + match[0].length
    const end = source.indexOf('endstream', start)
    if (end < 0) break
    const raw = bytes.subarray(start, end)
    try {
      found.push(inflateSync(raw))
    } catch {
      found.push(raw)
    }
    pattern.lastIndex = end + 'endstream'.length
  }
  return found
}

/** RGB colours set with `r g b rg` / `RG` anywhere in the document, as `#rrggbb`. */
export function pdfColours(bytes: Buffer): Set<string> {
  const colours = new Set<string>()
  const number = String.raw`(-?\d*\.?\d+)`
  const operator = new RegExp(String.raw`${number}\s+${number}\s+${number}\s+(?:rg|RG)\b`, 'g')
  for (const stream of streams(bytes)) {
    for (const [, r, g, b] of stream.toString('latin1').matchAll(operator)) {
      const hex = [r, g, b]
        .map((value) =>
          Math.round(Number(value) * 255)
            .toString(16)
            .padStart(2, '0'),
        )
        .join('')
      colours.add(`#${hex}`)
    }
  }
  return colours
}

/**
 * Whether a font program embedded in the PDF names itself `family` (its name table, in
 * the UTF-16BE or 8-bit encoding): the PDF's own font names are the stylesheet's aliases.
 */
export function embedsFont(bytes: Buffer, family: string): boolean {
  const ascii = Buffer.from(family, 'latin1')
  const utf16 = Buffer.from(family, 'utf16le').swap16()
  return streams(bytes).some((stream) => stream.includes(utf16) || stream.includes(ascii))
}

/** How many images (XObjects of subtype Image) the PDF holds. */
export function pdfImageCount(bytes: Buffer): number {
  return (bytes.toString('latin1').match(/\/Subtype\s*\/Image\b/g) ?? []).length
}

/**
 * Renders `pages` (1-based) of the PDF to PNG files with pdf.js in a Chromium page:
 * nothing is fetched from the network (the library and the file are served by routes).
 */
export async function renderPdfPages(
  browser: Browser,
  bytes: Buffer,
  pages: { page: number; path: string }[],
  scale = 1.5,
): Promise<void> {
  const build = require.resolve('pdfjs-dist/legacy/build/pdf.mjs').replace(/pdf\.mjs$/, '')
  const context = await browser.newContext({ viewport: { width: 1000, height: 1400 } })
  const page = await context.newPage()
  try {
    await page.route('http://pdf.render/**', async (route) => {
      const name = new URL(route.request().url()).pathname.slice(1)
      if (name === 'document.pdf') {
        await route.fulfill({ body: bytes, contentType: 'application/pdf' })
      } else if (name === 'pdf.mjs' || name === 'pdf.worker.mjs') {
        await route.fulfill({
          body: readFileSync(build + name),
          contentType: 'text/javascript',
        })
      } else if (name === 'index.html') {
        await route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><html><body style="margin:0;background:#fff"><canvas id="c"></canvas></body></html>',
        })
      } else {
        await route.fulfill({ status: 404 })
      }
    })
    await page.goto('http://pdf.render/index.html')
    for (const target of pages) {
      const size = await page.evaluate(
        async ({ number, scale: zoom }) => {
          const pdfjs = await import('http://pdf.render/pdf.mjs' as string)
          pdfjs.GlobalWorkerOptions.workerSrc = 'http://pdf.render/pdf.worker.mjs'
          const loaded = await pdfjs.getDocument({ url: 'http://pdf.render/document.pdf' }).promise
          const pdfPage = await loaded.getPage(number)
          const viewport = pdfPage.getViewport({ scale: zoom })
          const canvas = document.getElementById('c') as HTMLCanvasElement
          canvas.width = viewport.width
          canvas.height = viewport.height
          await pdfPage.render({ canvas, canvasContext: canvas.getContext('2d'), viewport }).promise
          return { width: viewport.width, height: viewport.height }
        },
        { number: target.page, scale },
      )
      await page.setViewportSize({ width: Math.ceil(size.width), height: Math.ceil(size.height) })
      await page.locator('#c').screenshot({ path: target.path })
    }
  } finally {
    await context.close()
  }
}
