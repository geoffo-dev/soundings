/** Build-time flags. Vite inlines these, so disabled branches are tree-shaken. */
export const designPageEnabled: boolean =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_DESIGN === 'true'

export const apiMocksEnabled: boolean = import.meta.env.VITE_API_MOCKS === 'true'
