/**
 * PHASE 0 PLACEHOLDER. The shell needs the signed-in user, their "My work"
 * count and project list. Replace with TanStack Query hooks on the real API
 * (e.g. GET /api/v1/me and /api/v1/projects) in Phase 1.
 */
export interface ShellProject {
  id: string
  name: string
}

export interface ShellData {
  user: { name: string; email: string; avatarUrl?: string | null }
  myWorkCount: number
  projects: ShellProject[]
}

const PLACEHOLDER: ShellData = {
  user: { name: 'Alex Morgan', email: 'alex.morgan@example.com' },
  myWorkCount: 4,
  projects: [
    { id: 'customer-innovation', name: 'Customer Innovation' },
    { id: 'internal-tools', name: 'Internal Tools' },
    { id: 'sustainability', name: 'Sustainability' },
  ],
}

export function useShellData(): ShellData {
  return PLACEHOLDER
}
