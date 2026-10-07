#!/usr/bin/env node
// Precompress the built SPA for `soundings api` (backend/app/spa.py; performance review
// B4): next to every compressible file of at least 1 KB, write <file>.br (Brotli,
// quality 11) and <file>.gz (gzip, level 9) when they are smaller. The API serves a
// twin to clients that accept it (Content-Encoding, Vary: Accept-Encoding) and the file
// itself to everyone else. Run by the Dockerfile after `npm run build`:
//
//   node scripts/precompress-assets.mjs frontend/dist
//
// Node's own zlib only: no dependency, works offline.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { extname, join } from 'node:path';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';

const COMPRESSIBLE = new Set(['.js', '.mjs', '.css', '.html', '.svg', '.json', '.txt', '.webmanifest', '.xml']);
const MIN_BYTES = 1024;

function* files(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* files(path);
    else if (entry.isFile()) yield path;
  }
}

const root = process.argv[2];
if (!root) {
  console.error('usage: precompress-assets.mjs <dist directory>');
  process.exit(2);
}
let written = 0;
let before = 0;
let after = 0;
for (const path of files(root)) {
  if (!COMPRESSIBLE.has(extname(path)) || statSync(path).size < MIN_BYTES) continue;
  const data = readFileSync(path);
  const brotli = brotliCompressSync(data, {
    params: {
      [constants.BROTLI_PARAM_QUALITY]: 11,
      [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
    },
  });
  const gzip = gzipSync(data, { level: 9 });
  before += data.length;
  after += Math.min(brotli.length, data.length);
  for (const [suffix, bytes] of [['.br', brotli], ['.gz', gzip]]) {
    if (bytes.length < data.length) {
      writeFileSync(path + suffix, bytes);
      written += 1;
    }
  }
}
console.log(
  `precompressed ${written} files in ${root}: ${Math.round(before / 1024)} kB -> ` +
    `${Math.round(after / 1024)} kB with Brotli`,
);
