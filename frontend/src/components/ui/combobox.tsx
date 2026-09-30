import { Check, ChevronsUpDown } from 'lucide-react'
import { useId, useState } from 'react'

import { Avatar, AvatarGroup } from '@/components/ui/avatar'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { useFieldControl } from '@/components/ui/field'
import { controlStyles } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

export interface ComboboxOption {
  value: string
  label: string
  /** Secondary line, e.g. an email or role. */
  description?: string
  /** Render an avatar (makes this a user picker). */
  avatar?: { name: string; src?: string | null; isAgent?: boolean }
  keywords?: string[]
  disabled?: boolean
}

interface ComboboxBaseProps {
  options: ComboboxOption[]
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  disabled?: boolean
  className?: string
  id?: string
  'aria-label'?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}

interface SingleComboboxProps extends ComboboxBaseProps {
  multiple?: false
  value: string | null
  onValueChange: (value: string | null) => void
}

interface MultiComboboxProps extends ComboboxBaseProps {
  multiple: true
  value: string[]
  onValueChange: (value: string[]) => void
}

export type ComboboxProps = SingleComboboxProps | MultiComboboxProps

/**
 * Searchable single/multi select (cmdk inside a Popover). With `avatar` on the
 * options it is the user picker for owners and evaluators; data comes via props.
 */
export function Combobox(props: ComboboxProps) {
  const {
    options,
    placeholder = 'Select…',
    searchPlaceholder = 'Search…',
    emptyText = 'No matches',
    className,
  } = props
  const [open, setOpen] = useState(false)
  const listId = useId()
  const { id, disabled, ...aria } = useFieldControl({
    id: props.id,
    disabled: props.disabled,
    'aria-describedby': props['aria-describedby'],
    'aria-invalid': props['aria-invalid'],
  })
  const selectedValues = props.multiple ? props.value : props.value ? [props.value] : []
  const selected = options.filter((option) => selectedValues.includes(option.value))

  const toggle = (value: string) => {
    if (props.multiple) {
      const next = props.value.includes(value)
        ? props.value.filter((v) => v !== value)
        : [...props.value, value]
      props.onValueChange(next)
    } else {
      props.onValueChange(props.value === value ? null : value)
      setOpen(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          id={id}
          disabled={disabled}
          aria-expanded={open}
          aria-controls={listId}
          aria-haspopup="listbox"
          aria-label={props['aria-label']}
          {...aria}
          className={cn(
            controlStyles,
            'flex min-h-9 items-center gap-2 px-2.5 py-1 text-left sm:min-h-8',
            className,
          )}
        >
          <ComboboxValue selected={selected} placeholder={placeholder} multiple={props.multiple} />
          <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 shrink-0 text-muted" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) min-w-60 p-0">
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList id={listId}>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const isSelected = selectedValues.includes(option.value)
                return (
                  <CommandItem
                    key={option.value}
                    value={`${option.label} ${option.value}`}
                    keywords={[
                      ...(option.keywords ?? []),
                      ...(option.description ? [option.description] : []),
                    ]}
                    disabled={option.disabled}
                    onSelect={() => toggle(option.value)}
                    aria-selected={isSelected}
                    className="h-auto min-h-9 py-1.5 sm:h-auto"
                  >
                    {option.avatar && (
                      <Avatar
                        size="sm"
                        name={option.avatar.name}
                        src={option.avatar.src}
                        isAgent={option.avatar.isAgent}
                      />
                    )}
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">{option.label}</span>
                      {option.description && (
                        <span className="truncate text-xs text-muted">{option.description}</span>
                      )}
                    </span>
                    <Check
                      aria-hidden="true"
                      className={cn(
                        'ml-auto text-accent!',
                        isSelected ? 'opacity-100' : 'opacity-0',
                      )}
                    />
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function ComboboxValue({
  selected,
  placeholder,
  multiple,
}: {
  selected: ComboboxOption[]
  placeholder: string
  multiple?: boolean
}) {
  if (selected.length === 0) return <span className="truncate text-muted">{placeholder}</span>
  const first = selected[0]
  if (!multiple && first) {
    return (
      <span className="flex min-w-0 items-center gap-2">
        {first.avatar && (
          <Avatar
            size="xs"
            name={first.avatar.name}
            src={first.avatar.src}
            isAgent={first.avatar.isAgent}
          />
        )}
        <span className="truncate">{first.label}</span>
      </span>
    )
  }
  const withAvatars = selected.filter((option) => option.avatar)
  return (
    <span className="flex min-w-0 items-center gap-2">
      {withAvatars.length > 0 && (
        <AvatarGroup
          size="xs"
          max={3}
          people={withAvatars.map((option) => ({
            id: option.value,
            name: option.avatar?.name ?? option.label,
            src: option.avatar?.src,
            isAgent: option.avatar?.isAgent,
          }))}
        />
      )}
      <span className="truncate">
        {selected.length === 1 ? first?.label : `${selected.length} selected`}
      </span>
    </span>
  )
}
