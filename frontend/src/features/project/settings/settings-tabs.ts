/**
 * Tabs of /p/$slug/settings (`?tab=`); General is the default. Light: the route
 * definition imports it. Status labels are part of General, Branding part of Public
 * form (it only changes how the project faces outward). The old `?tab=statuses` and
 * `?tab=branding` still open the tab that holds them, scrolled to the section.
 * Phase 8 adds Research (the step and its checklist) and Proposal (the template):
 * six tabs, the most the settings take.
 */
export const SETTINGS_TABS = [
  'general',
  'members',
  'rubric',
  'research',
  'proposal-template',
  'public-form',
] as const
export type SettingsTab = (typeof SETTINGS_TABS)[number]

/** Tabs only project admins see (the others show non-admins a read-only summary). */
export const ADMIN_SETTINGS_TABS: readonly SettingsTab[] = ['public-form']

/** Pre-Phase 7 tabs: the tab that holds each now, and the section to show. */
export const MOVED_SETTINGS_TABS = {
  statuses: { tab: 'general', section: 'status-labels' },
  branding: { tab: 'public-form', section: 'branding' },
} as const satisfies Record<string, { tab: SettingsTab; section: string }>
