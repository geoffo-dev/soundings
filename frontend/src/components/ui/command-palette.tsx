import { SearchX } from 'lucide-react'
import { useState, type ReactNode } from 'react'

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
  const value = search ?? localSearch
  const setValue = onSearchChange ?? setLocalSearch
  const visibleGroups = groups.filter((group) => group.actions.length > 0)
  const firstValue = visibleGroups[0]?.actions[0]
  const firstKey = firstValue ? itemValue(firstValue) : ''
  // Keep the highlight on the best match as results arrive (server search is async).
  const [selected, setSelected] = useState(firstKey)
  const [lastFirst, setLastFirst] = useState(firstKey)
  if (firstKey !== lastFirst) {
    setLastFirst(firstKey)
    setSelected(firstKey)
  }

  const close = (then: () => void) => {
    onOpenChange(false)
    setLocalSearch('')
    // Let the dialog start closing before navigation/side effects run.
    requestAnimationFrame(then)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) setLocalSearch('')
      }}
    >
      <DialogContent position="top" size="lg" hideClose className="overflow-hidden p-0">
        <VisuallyHidden>
          <DialogTitle>Command palette</DialogTitle>
          <DialogDescription>
            Search for a command or page and press Enter to run it.
          </DialogDescription>
        </VisuallyHidden>
        <Command loop shouldFilter={shouldFilter} value={selected} onValueChange={setSelected}>
          <CommandInput placeholder={placeholder} value={value} onValueChange={setValue} />
          <CommandList>
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
                    <span className="truncate">{action.label}</span>
                    {action.hint && (
                      <span className="truncate text-sm text-muted">{action.hint}</span>
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
