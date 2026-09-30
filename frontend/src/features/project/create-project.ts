/**
 * Suggestions and checks for the create-project form (contract `ProjectCreate`):
 * the slug is the URL name (`customer-innovation`), the key prefixes idea keys
 * (`CUST-12`). Both are suggested from the name and can't change later.
 */
export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/
export const KEY_PATTERN = /^[A-Z][A-Z0-9]{1,5}$/
export const LIMITS = { name: 80, slug: 48, description: 1000 } as const

/** Letters without accents, so "Café Ideas" suggests `cafe-ideas` / `CAFE`. */
function fold(text: string): string {
  return text.normalize('NFKD').replace(/[̀-ͯ]/g, '')
}

export function suggestSlug(name: string): string {
  const slug = fold(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (slug.length <= LIMITS.slug) return slug
  // Cut at a word boundary when possible.
  const cut = slug.slice(0, LIMITS.slug)
  if (slug[LIMITS.slug] === '-') return cut
  const lastDash = cut.lastIndexOf('-')
  return (lastDash > 1 ? cut.slice(0, lastDash) : cut).replace(/-+$/, '')
}

/**
 * One word → its first four letters ("Sustainability" → SUST); three or more
 * words → initials ("New Product Ideas" → NPI); two words → the first word's
 * first four letters ("Customer Innovation" → CUST). Empty when nothing fits.
 */
export function suggestKey(name: string): string {
  const words = fold(name)
    .toUpperCase()
    .split(/[^A-Z0-9]+/)
    .filter(Boolean)
  const first = words[0] ?? ''
  const raw = words.length >= 3 ? words.map((word) => word[0]).join('') : first
  const key = raw.replace(/^[0-9]+/, '').slice(0, words.length >= 3 ? 6 : 4)
  return KEY_PATTERN.test(key) ? key : ''
}

export interface CreateProjectForm {
  name: string
  slug: string
  key: string
  description: string
}

export type CreateProjectErrors = Partial<Record<keyof CreateProjectForm | 'form', string>>

export function validateCreateProject(form: CreateProjectForm): CreateProjectErrors {
  const errors: CreateProjectErrors = {}
  const name = form.name.trim()
  if (!name) errors.name = 'Give the project a name.'
  else if (name.length > LIMITS.name) errors.name = `At most ${LIMITS.name} characters.`
  const slug = form.slug.trim()
  if (slug.length < 2) errors.slug = 'Use at least 2 characters.'
  else if (slug.length > LIMITS.slug) errors.slug = `At most ${LIMITS.slug} characters.`
  else if (!SLUG_PATTERN.test(slug)) {
    errors.slug = 'Use lower-case letters, digits and single dashes.'
  }
  if (!KEY_PATTERN.test(form.key.trim())) {
    errors.key = 'Use 2–6 capital letters or digits, starting with a letter.'
  }
  if (form.description.length > LIMITS.description) {
    errors.description = `At most ${LIMITS.description.toLocaleString('en')} characters.`
  }
  return errors
}
