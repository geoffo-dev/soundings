/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" starts MSW in the browser (npm run dev:mock). */
  readonly VITE_API_MOCKS?: string
  /** "true" exposes /design in a production build. */
  readonly VITE_ENABLE_DESIGN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
