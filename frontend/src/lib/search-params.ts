/**
 * Readable URLs for filters: `?view=list&status=new,evaluating&needs_evaluators=true`
 * instead of TanStack Router's default JSON encoding. The router hands every
 * value to `validateSearch` as a raw string; the helpers below turn them into
 * typed values and drop defaults, so links stay short and shareable.
 */

type RawSearch = Record<string, unknown>

export function parseSearch(searchString: string): RawSearch {
  const query = searchString.startsWith('?') ? searchString.slice(1) : searchString
  const out: RawSearch = {}
  for (const [key, value] of new URLSearchParams(query)) out[key] = value
  return out
}

export function stringifySearch(search: RawSearch): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(search)) {
    if (value === undefined || value === null || value === '' || value === false) continue
    if (Array.isArray(value)) {
      if (value.length > 0) params.set(key, value.map(String).join(','))
    } else if (value === true) {
      // Flags read as "1" (?evaluate=1, as in email links).
      params.set(key, '1')
    } else if (typeof value === 'string' || typeof value === 'number') {
      params.set(key, String(value))
    } else if (typeof value === 'object') {
      params.set(key, JSON.stringify(value))
    }
  }
  const text = params.toString().replace(/%2C/gi, ',')
  return text ? `?${text}` : ''
}

/* ------------------------------------------------------------------ */
/* Validators for `validateSearch`                                     */
/* ------------------------------------------------------------------ */

export function searchString(value: unknown, max = 200): string | undefined {
  if (typeof value !== 'string' && typeof value !== 'number') return undefined
  const text = String(value).trim().slice(0, max)
  return text || undefined
}

export function searchEnum<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return typeof value === 'string' && allowed.includes(value as T) ? (value as T) : undefined
}

/** Comma-separated (or repeated/array) values, filtered to `allowed` when given. */
export function searchList<T extends string = string>(
  value: unknown,
  allowed?: readonly T[],
): T[] | undefined {
  const raw = Array.isArray(value)
    ? value.map(String)
    : typeof value === 'string'
      ? value.split(',')
      : []
  const items = [...new Set(raw.map((item) => item.trim()).filter(Boolean))]
  const valid = allowed
    ? items.filter((item): item is T => allowed.includes(item as T))
    : (items as T[])
  return valid.length > 0 ? valid : undefined
}

/** `true`, `1`, `yes` → true; anything else → undefined (the default, omitted from the URL). */
export function searchFlag(value: unknown): true | undefined {
  if (value === true) return true
  return typeof value === 'string' && ['true', '1', 'yes'].includes(value.toLowerCase())
    ? true
    : undefined
}
