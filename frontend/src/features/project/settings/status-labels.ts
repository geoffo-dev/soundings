import type { StatusLabels } from '@/api/types'
import { DEFAULT_RESOLUTION_LABELS, DEFAULT_STATUS_LABELS } from '@/lib/status'

export type LabelKey = keyof StatusLabels

export const DEFAULT_LABELS: StatusLabels = {
  ...DEFAULT_STATUS_LABELS,
  ...DEFAULT_RESOLUTION_LABELS,
}

/**
 * The `status_labels` PATCH for what changed (contract §3.1): a new name is a
 * string; an empty field or the default name is `null`, which resets the
 * label. Unchanged labels are left out.
 */
export function labelChanges(
  form: StatusLabels,
  saved: StatusLabels,
): Partial<Record<LabelKey, string | null>> {
  const body: Partial<Record<LabelKey, string | null>> = {}
  for (const key of Object.keys(DEFAULT_LABELS) as LabelKey[]) {
    const next = form[key].trim() || DEFAULT_LABELS[key]
    if (next === saved[key]) continue
    body[key] = next === DEFAULT_LABELS[key] ? null : next
  }
  return body
}
