/** Tabs of /p/$slug/settings (`?tab=`); General is the default. Light: the route definition imports it. */
export const SETTINGS_TABS = ['general', 'members', 'rubric', 'statuses'] as const
export type SettingsTab = (typeof SETTINGS_TABS)[number]
