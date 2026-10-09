import { useCallback, useId, useMemo, useState, type KeyboardEvent, type RefObject } from 'react'
import { flushSync } from 'react-dom'

import { useDebouncedValue } from '@/api/search'
import type { UserRef, UserSearchResult } from '@/api/types'
import { useUserSearch } from '@/api/users'
import { Avatar } from '@/components/ui/avatar'
import { Spinner } from '@/components/ui/spinner'
import {
  activeShownQuery,
  insertMention,
  type MentionDraft,
  type MentionQuery,
} from '@/lib/mentions'
import { cn } from '@/lib/utils'

/** How many people the picker offers at once. */
const PICKER_LIMIT = 8

export interface MentionOptions {
  /**
   * The idea's project slug: the picker offers people with a role in it (contract-phase3
   * §3.8). Undefined (a guest researcher, who can't read the project's people): the people
   * directory; mentioning someone who can't view the idea notifies nobody (Phase 8b §6.4).
   */
  project?: string
  /** Left out of the list (you don't mention yourself). */
  excludeUserId?: string
  /** Phase 8b: also offered (the idea's researcher, who may have no role in the project). */
  extra?: readonly UserRef[]
}

/**
 * @mentions in a Markdown text field: typing "@" (at the start or after a
 * space) opens a list of the project's people; ↑/↓ choose, Enter or Tab
 * insert "@Name" (stored as `@[Name](user:<id>)`, lib/mentions), Esc closes
 * it. The text field keeps focus (`aria-activedescendant` points at the
 * highlighted person).
 */
export function useMentionPicker({
  draft,
  onDraftChange,
  textareaRef,
  options,
}: {
  /** The text as shown, and where its mentions are. */
  draft: MentionDraft
  onDraftChange: (draft: MentionDraft) => void
  textareaRef: RefObject<HTMLTextAreaElement | null>
  options: MentionOptions | undefined
}) {
  const listId = useId()
  const [query, setQuery] = useState<MentionQuery | null>(null)
  const [dismissedAt, setDismissedAt] = useState<number | null>(null)
  const [active, setActive] = useState(0)
  const enabled = Boolean(options) && query !== null && dismissedAt !== query.start
  const debounced = useDebouncedValue(query?.query.trim() ?? '', 120)
  const search = useUserSearch(
    { q: debounced, project: options?.project, limit: PICKER_LIMIT + 1 },
    { enabled },
  )
  const typed = query?.query.trim().toLowerCase() ?? ''
  const extra = options?.extra
  const people = useMemo(
    () =>
      [
        ...(search.data?.items ?? []),
        ...(extra ?? [])
          .filter((person) => !search.data?.items.some((found) => found.id === person.id))
          .map((person): UserSearchResult => ({ ...person, email: '', project_role: null })),
      ]
        .filter((person) => person.id !== options?.excludeUserId)
        // Narrow the last results to what is typed now, so Enter never picks a stale match
        // while the next search is still on its way (the server matches the same way).
        .filter(
          (person) =>
            person.display_name.toLowerCase().includes(typed) ||
            person.email.toLowerCase().includes(typed),
        )
        .slice(0, PICKER_LIMIT),
    [search.data, extra, options?.excludeUserId, typed],
  )
  const loading = search.isFetching && people.length === 0
  // A space after "@word" with nobody matching: probably not a mention after all.
  const open = enabled && (people.length > 0 || loading || !/\s/.test(query.query))
  const highlighted = open ? people[Math.min(active, people.length - 1)] : undefined

  /** Re-read the caret (after typing, clicking or moving with the keyboard); `null` closes. */
  const sync = useCallback(
    (current: MentionDraft | null = draft) => {
      const field = textareaRef.current
      if (!options || !field) return
      const caret = field.selectionStart
      const next = current && field.selectionEnd === caret ? activeShownQuery(current, caret) : null
      setQuery((current) =>
        current?.start === next?.start && current?.query === next?.query ? current : next,
      )
      if (!next) setDismissedAt(null)
      setActive(0)
    },
    [options, textareaRef, draft],
  )

  const choose = useCallback(
    (person: UserSearchResult) => {
      const field = textareaRef.current
      if (!query || !field) return
      const result = insertMention(
        draft,
        { start: query.start, caret: field.selectionStart },
        person,
      )
      // Render the new text now, so the caret can go straight after the name.
      flushSync(() => {
        onDraftChange(result.draft)
        setQuery(null)
      })
      field.focus()
      field.setSelectionRange(result.caret, result.caret)
    },
    [onDraftChange, query, textareaRef, draft],
  )

  /** Returns true when the key was for the picker (the editor should ignore it). */
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!open) return false
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setDismissedAt(query.start)
      return true
    }
    if (people.length === 0) return false
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((index) => (index + step + people.length) % people.length)
      return true
    }
    if ((event.key === 'Enter' && !event.metaKey && !event.ctrlKey) || event.key === 'Tab') {
      if (event.shiftKey) return false
      event.preventDefault()
      if (highlighted) choose(highlighted)
      return true
    }
    return false
  }

  const optionId = (person: UserSearchResult) => `${listId}-${person.id}`

  return {
    open,
    sync,
    onKeyDown,
    /** Spread onto the text field. */
    fieldProps: options
      ? {
          'aria-autocomplete': 'list' as const,
          'aria-controls': open ? listId : undefined,
          'aria-activedescendant': highlighted ? optionId(highlighted) : undefined,
        }
      : {},
    picker: open ? (
      <div
        className="absolute bottom-full left-0 z-30 mb-1 w-72 max-w-full overflow-hidden rounded-lg border bg-elevated shadow-overlay"
        data-slot="mention-picker"
      >
        <p className="border-b border-subtle px-3 py-1.5 text-xs text-muted">
          Mention someone in this project
        </p>
        <ul
          id={listId}
          role="listbox"
          aria-label="People to mention"
          className="max-h-64 overflow-y-auto p-1"
        >
          {people.map((person) => {
            const selected = person.id === highlighted?.id
            return (
              // The keyboard stays in the text field (↑/↓, Enter, Tab via aria-activedescendant);
              // the mouse can pick an option directly.
              // eslint-disable-next-line jsx-a11y/click-events-have-key-events
              <li
                key={person.id}
                id={optionId(person)}
                role="option"
                aria-selected={selected}
                // Keep focus (and the caret) in the text field.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(person)}
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm',
                  selected
                    ? 'bg-subtle-hover text-primary highlight-ring'
                    : 'text-secondary hover:bg-subtle',
                )}
              >
                <Avatar name={person.display_name} src={person.avatar_url} size="xs" decorative />
                <span className="min-w-0 flex-1 truncate font-medium text-primary">
                  {person.display_name}
                </span>
                {person.project_role && (
                  <span className="shrink-0 text-xs text-muted">{person.project_role}</span>
                )}
              </li>
            )
          })}
          {people.length === 0 && (
            <li
              role="presentation"
              className="flex items-center gap-2 px-2 py-1.5 text-sm text-muted"
            >
              {loading ? (
                <>
                  <Spinner className="size-3.5" /> Searching…
                </>
              ) : (
                `No one in this project matches “${query.query}”`
              )}
            </li>
          )}
        </ul>
      </div>
    ) : null,
    /** For a live region that is always rendered (the editor's). */
    announcement:
      open && !loading
        ? `${people.length} ${people.length === 1 ? 'person' : 'people'} to mention. Up and down to choose, Enter to insert, Escape to close.`
        : '',
  }
}
