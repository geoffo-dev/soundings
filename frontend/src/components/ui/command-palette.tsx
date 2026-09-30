import { SearchX } from 'lucide-react'
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react'

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandLoading,
  CommandShortcut,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { VisuallyHidden } from '@/components/ui/visually-hidden'
import { isMac } from '@/lib/utils'

export interface CommandAction {
  id: string
  label: string
  icon?: ReactNode
  /** Secondary text, right of the label (e.g. project name). */
  hint?: string
  /** Shortcut hint, e.g. "n" or "g m". Display only — bind it with useShortcut. */
  shortcut?: string
  /** Extra words that should match this item. */
  keywords?: string[]
  onSelect: () => void
}

export interface CommandGroupData {
  heading: string
  actions: CommandAction[]
  /**
   * Results for an earlier query that are about to be replaced (server search in
   * flight): the highlight only rests here until the fresh results arrive.
   */
  pending?: boolean
}

export interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  groups: CommandGroupData[]
  placeholder?: string
  /** Controlled search, for server-side results (set `shouldFilter={false}`). */
  search?: string
  onSearchChange?: (search: string) => void
  shouldFilter?: boolean
  loading?: boolean
}

function itemValue(action: CommandAction): string {
  return `${action.label} ${action.id}`
}

/** The keys cmdk moves the highlight with (arrows, Home/End, Ctrl+N/P/J/K on macOS). */
function isNavigationKey(event: KeyboardEvent<HTMLDivElement>): boolean {
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return true
  return isMac && event.ctrlKey && ['n', 'p', 'j', 'k'].includes(event.key)
}

/** Data-driven ⌘K palette: pass groups of actions; filtering and keyboard nav come from cmdk. */
export function CommandPalette({
  open,
  onOpenChange,
  groups,
  placeholder = 'Type a command or search…',
  search,
  onSearchChange,
  shouldFilter = true,
  loading = false,
}: CommandPaletteProps) {
  const [localSearch, setLocalSearch] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  // Radix moves focus in only when the content mounts. Reopened while it is still
  // animating closed (⌘K straight after picking something, e.g. New idea then Esc), it
  // never unmounted, and focus would stay in the dialog closing behind it.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])
  const value = search ?? localSearch
  const setValue = onSearchChange ?? setLocalSearch
  const visibleGroups = groups.filter((group) => group.actions.length > 0)
  const settled = new Set(
    visibleGroups
      .filter((group) => !group.pending)
      .flatMap((group) => group.actions.map(itemValue)),
  )
  const firstValue = visibleGroups[0]?.actions[0]
  // Where the highlight belongs: the first result that won't be replaced, else the first.
  const target = [...settled][0] ?? (firstValue ? itemValue(firstValue) : '')
  const targetSettled = settled.has(target)

  // What you see highlighted is what Enter opens, so late server results never move
  // the highlight once it rests on a current item ("anchored"), or once you moved it
  // yourself ("picked"). While it rests on results that are about to be replaced, it
  // follows `target`. cmdk proposes highlights itself (the first match on a new query,
  // the next item when the highlighted one goes): we take them, then correct them
  // after commit, so cmdk's own state always follows the `value` prop.
  const [highlight, setHighlight] = useState({ value: target, anchored: false })
  const [picked, setPicked] = useState(false)
  const [lastSearch, setLastSearch] = useState(value)
  if (value !== lastSearch) {
    // A new query: cmdk proposes its first item (below), and the highlight follows
    // `target` again until it is anchored.
    setLastSearch(value)
    setPicked(false)
  }
  useLayoutEffect(() => {
    if (picked) return
    // Syncing with cmdk's store (it only re-reads `value` when the prop changes, so a
    // proposal can't be refused during render); before paint, so nothing flickers.
    // Functional: cmdk's proposal from this same commit is already queued.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHighlight((current) =>
      current.anchored || (current.value === target && !targetSettled)
        ? current
        : { value: target, anchored: targetSettled },
    )
  }, [picked, highlight, target, targetSettled])

  const reset = () => {
    setLocalSearch('')
    setPicked(false)
    setHighlight((current) => ({ ...current, anchored: false }))
  }

  const close = (then: () => void) => {
    onOpenChange(false)
    reset()
    // Let the dialog start closing before navigation/side effects run.
    requestAnimationFrame(then)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) reset()
      }}
    >
      <DialogContent position="top" size="lg" hideClose className="overflow-hidden p-0">
        <VisuallyHidden>
          <DialogTitle>Command palette</DialogTitle>
          <DialogDescription>
            Search for a command or page and press Enter to run it.
          </DialogDescription>
        </VisuallyHidden>
        <Command
          loop
          shouldFilter={shouldFilter}
          value={highlight.value}
          onValueChange={(next) => setHighlight({ value: next, anchored: settled.has(next) })}
          onKeyDown={(event) => {
            if (isNavigationKey(event)) setPicked(true)
          }}
        >
          <CommandInput
            ref={inputRef}
            placeholder={placeholder}
            value={value}
            onValueChange={setValue}
          />
          <CommandList onPointerMove={() => setPicked(true)}>
            {loading && (
              <CommandLoading>
                <div className="px-3 py-2 text-sm text-muted">Searching…</div>
              </CommandLoading>
            )}
            <CommandEmpty>
              <div className="flex flex-col items-center gap-2">
                <SearchX aria-hidden="true" className="size-5 text-muted" />
                <span>No results for “{value}”</span>
              </div>
            </CommandEmpty>
            {visibleGroups.map((group) => (
              <CommandGroup key={group.heading} heading={group.heading}>
                {group.actions.map((action) => (
                  <CommandItem
                    key={action.id}
                    value={itemValue(action)}
                    keywords={action.keywords}
                    onSelect={() => close(action.onSelect)}
                  >
                    {action.icon}
                    <span className="min-w-0 truncate">{action.label}</span>
                    {action.hint && (
                      // Gives way to the label first when the row is short (phones).
                      <span className="min-w-0 shrink-4 truncate text-sm text-muted">
                        {action.hint}
                      </span>
                    )}
                    {action.shortcut && <CommandShortcut keys={action.shortcut} />}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
          <div className="hidden items-center gap-4 border-t border-subtle px-3 py-2 text-xs text-muted sm:flex">
            <span className="inline-flex items-center gap-1.5">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> to navigate
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>↵</Kbd> to select
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>Esc</Kbd> to close
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
