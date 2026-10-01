/**
 * Tabs of /p/$slug/settings (`?tab=`); General is the default. Light: the route
 * definition imports it. Status labels, Public form and Branding are for admins.
 */
export const SETTINGS_TABS = [
  'general',
  'members',
  'rubric',
  'statuses',
  'public-form',
  'branding',
] as const
export type SettingsTab = (typeof SETTINGS_TABS)[number]

/** Tabs only project admins see (the others show non-admins a read-only summary). */
export const ADMIN_SETTINGS_TABS: readonly SettingsTab[] = ['statuses', 'public-form', 'branding']
