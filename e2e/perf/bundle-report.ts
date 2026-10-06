/**
 * Bundle analysis for the production SPA build (Phase 7, docs/test-plans/performance.md).
 *
 *   node --experimental-strip-types e2e/perf/bundle-report.ts [--build] [--json out.json]
 *     [--dir <a build with source maps>]
 *
 * --build builds frontend/ with source maps into e2e/perf/.stack/bundle (Vite, the
 * production config plus --sourcemap; frontend/dist is left alone). Then, for every
 * JavaScript chunk: raw and gzip size, whether the first page load fetches it (the entry
 * and its static imports: what index.html preloads), and which packages and source
 * folders its bytes come from (minified bytes attributed through the source map).
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '../..')
const args = process.argv.slice(2)
const dirArg = args.indexOf('--dir')
const out =
  dirArg >= 0 && args[dirArg + 1] ? resolve(args[dirArg + 1]!) : resolve(here, '.stack/bundle')

if (args.includes('--build') || !existsSync(join(out, 'index.html'))) {
  console.error(`[bundle] building frontend into ${out} (with source maps)`)
  execFileSync(
    join(repo, 'frontend/node_modules/.bin/vite'),
    ['build', '--outDir', out, '--emptyOutDir', '--sourcemap', '--logLevel', 'warn'],
    { cwd: join(repo, 'frontend'), stdio: 'inherit' },
  )
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
function decodeSegment(segment: string): number[] {
  const values: number[] = []
  let shift = 0
  let value = 0
  for (const char of segment) {
    const digit = B64.indexOf(char)
    value += (digit & 31) << shift
    if (digit & 32) shift += 5
    else {
      values.push(value & 1 ? -(value >>> 1) : value >>> 1)
      value = 0
      shift = 0
    }
  }
  return values
}

/** Minified bytes per source file, from a v3 source map. */
function bytesBySource(code: string, map: { sources: string[]; mappings: string }) {
  const lines = code.split('\n')
  const bytes = new Map<string, number>()
  let source = 0
  map.mappings.split(';').forEach((line, index) => {
    const segments: [number, number | null][] = []
    let column = 0
    for (const raw of line.split(',')) {
      if (!raw) continue
      const fields = decodeSegment(raw)
      column += fields[0] ?? 0
      if (fields.length >= 4) {
        source += fields[1] ?? 0
        // line and column deltas (fields 2, 3) are irrelevant for byte counts but keep state
        segments.push([column, source])
      } else segments.push([column, null])
    }
    const length = lines[index]?.length ?? 0
    segments.forEach(([start, src], i) => {
      const end = segments[i + 1]?.[0] ?? length
      const name = src === null ? '(no source)' : (map.sources[src] ?? '(unknown)')
      bytes.set(name, (bytes.get(name) ?? 0) + Math.max(0, end - start))
    })
  })
  return bytes
}

function group(source: string): string {
  const path = source.replace(/^(\.\.\/)+/, '')
  const modules = path.lastIndexOf('node_modules/')
  if (modules >= 0) {
    const rest = path.slice(modules + 'node_modules/'.length).split('/')
    return rest[0]!.startsWith('@') ? `${rest[0]}/${rest[1]}` : rest[0]!
  }
  const match = /^(?:frontend\/)?src\/([^/]+)(?:\/([^/]+))?/.exec(path)
  if (match)
    return match[1] === 'features' || match[1] === 'components'
      ? `src/${match[1]}/${match[2]}`
      : `src/${match[1]}`
  return path
}

const html = readFileSync(join(out, 'index.html'), 'utf8')
const initial = new Set(
  [...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.js)"/g)].map((m) => m[1]!),
)
const assets = readdirSync(join(out, 'assets'))
const chunks = assets
  .filter((file) => file.endsWith('.js'))
  .map((file) => {
    const code = readFileSync(join(out, 'assets', file), 'utf8')
    const mapFile = join(out, 'assets', `${file}.map`)
    const groups = new Map<string, number>()
    if (existsSync(mapFile)) {
      const map = JSON.parse(readFileSync(mapFile, 'utf8')) as {
        sources: string[]
        mappings: string
      }
      for (const [source, n] of bytesBySource(code, map)) {
        const key = group(source)
        groups.set(key, (groups.get(key) ?? 0) + n)
      }
    }
    const top = [...groups.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
    return {
      file,
      kb: Math.round(Buffer.byteLength(code) / 102.4) / 10,
      gzipKb: Math.round(gzipSync(code, { level: 9 }).length / 102.4) / 10,
      initial: initial.has(`assets/${file}`),
      top: top.map(([name, n]) => ({ name, kb: Math.round(n / 102.4) / 10 })),
    }
  })
  .sort((a, b) => b.kb - a.kb)

const css = assets
  .filter((file) => file.endsWith('.css'))
  .map((file) => {
    const code = readFileSync(join(out, 'assets', file))
    return {
      file,
      kb: Math.round(code.length / 102.4) / 10,
      gzipKb: Math.round(gzipSync(code).length / 102.4) / 10,
    }
  })
const sum = (list: { kb: number; gzipKb: number }[]) => ({
  kb: Math.round(list.reduce((n, c) => n + c.kb, 0)),
  gzipKb: Math.round(list.reduce((n, c) => n + c.gzipKb, 0)),
})
const initialChunks = chunks.filter((c) => c.initial)
const report = {
  chunks: chunks.length,
  allJs: sum(chunks),
  initialJs: { ...sum(initialChunks), files: initialChunks.map((c) => c.file) },
  css: sum(css),
  details: chunks,
}

console.log(`JS: ${report.chunks} chunks, ${report.allJs.kb} kB (${report.allJs.gzipKb} kB gzip)`)
console.log(
  `First load (index.html entry + preloads): ${report.initialJs.kb} kB (${report.initialJs.gzipKb} kB gzip) in ${initialChunks.length} files; CSS ${report.css.kb} kB (${report.css.gzipKb} kB gzip)`,
)
for (const chunk of chunks.slice(0, Number(process.env.BUNDLE_TOP ?? 15))) {
  console.log(
    `\n${chunk.initial ? '*' : ' '} ${chunk.file}: ${chunk.kb} kB (${chunk.gzipKb} kB gzip)\n    ` +
      chunk.top.map((t) => `${t.name} ${t.kb}`).join(', '),
  )
}
const json = args.indexOf('--json')
if (json >= 0 && args[json + 1])
  writeFileSync(args[json + 1]!, JSON.stringify(report, null, 2) + '\n')
