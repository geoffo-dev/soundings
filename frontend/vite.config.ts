import { createReadStream } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { createRequire } from 'node:module'
import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vitest/config'

const apiTarget = process.env.SOUNDINGS_API_URL ?? 'http://localhost:8000'

/**
 * Serves MSW's service worker from node_modules in dev/preview only, so the
 * worker always matches the installed msw version and never ships in dist/.
 */
function mswWorker(): Plugin {
  const workerPath = createRequire(import.meta.url).resolve('msw/mockServiceWorker.js')
  const handler = (_req: IncomingMessage, res: ServerResponse) => {
    res.setHeader('Content-Type', 'text/javascript')
    createReadStream(workerPath).pipe(res)
  }
  return {
    name: 'soundings:msw-worker',
    configureServer: (server) => void server.middlewares.use('/mockServiceWorker.js', handler),
    configurePreviewServer: (server) =>
      void server.middlewares.use('/mockServiceWorker.js', handler),
  }
}

const proxy = Object.fromEntries(
  ['/api', '/mcp', '/metrics'].map((path) => [path, { target: apiTarget, xfwd: true }]),
)

export default defineConfig({
  plugins: [
    !process.env.VITEST &&
      tanstackRouter({
        target: 'react',
        autoCodeSplitting: true,
        routesDirectory: './src/routes',
        generatedRouteTree: './src/routeTree.gen.ts',
        quoteStyle: 'single',
        semicolons: false,
      }),
    react(),
    tailwindcss(),
    mswWorker(),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy,
    // VITE_NO_HMR=1 (the Playwright page tests set it): saved files no longer reload
    // open pages, so tests don't flake while someone edits the shared tree.
    hmr: !process.env.VITE_NO_HMR,
  },
  preview: { proxy },
  build: {
    outDir: 'dist',
    // Production images must not ship source maps (they expose the source).
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    // Only tokens.css is needed (read as ?raw by a token test); skip other CSS.
    css: { include: [/tokens\.css/] },
    restoreMocks: true,
  },
})
