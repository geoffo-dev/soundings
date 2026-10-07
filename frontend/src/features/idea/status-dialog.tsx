import { ArrowLeft, Check, ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { useChangeIdeaStatus } from '@/api/ideas'
import type { IdeaStatus, Resolution } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { StatusDot } from '@/components/ui/status-badge'
import { CLOSED_RESOLUTIONS, IDEA_STATUSES, statusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

import { useIdeaPage } from './idea-context'

/**
 * "Change status" (S, the sidebar, the palette): any status to any status for
 * the owner and admins (contract §3.3). Closed asks for a resolution first.
 * The change is instant with an Undo toast.
 */
export function StatusDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { idea } = useIdeaPage()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm" position="top" className="overflow-hidden">
        <DialogHeader className="pb-3">
          <DialogTitle>Change status</DialogTitle>
          <DialogDescription className="truncate">
            {idea.key} · {idea.title}
          </DialogDescription>
        </DialogHeader>
        {/* Mounted per opening so it always starts on the first step. */}
        {open && <StatusPicker onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function StatusPicker({ onDone }: { onDone: () => void }) {
  const { idea, ideaKey, statusLabel } = useIdeaPage()
  const change = useChangeIdeaStatus(ideaKey)
  const [step, setStep] = useState<'status' | 'resolution'>('status')
  const [search, setSearch] = useState('')

  const choose = (status: IdeaStatus, resolution: Resolution | null = null) => {
    onDone()
    if (status === idea.status && resolution === idea.resolution) return
    change.mutate({ status, resolution })
  }

  if (step === 'resolution') {
    return (
      <Command
        label="Close as"
        // Starts on the current resolution: Enter right away changes nothing.
        defaultValue={
          idea.status === 'closed' && idea.resolution
            ? statusLabel('closed', idea.resolution)
            : undefined
        }
        className="border-t border-subtle"
        onKeyDown={(event) => {
          if (event.key === 'Backspace' && !search) {
            event.preventDefault()
            setStep('status')
          }
        }}
      >
        <div className="flex items-center gap-1 px-2 pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setStep('status')}
            aria-label="Back to all statuses"
          >
            <ArrowLeft />
            Back
          </Button>
          <span className="text-sm text-muted">Close as…</span>
        </div>
        <CommandInput
          value={search}
          onValueChange={setSearch}
          placeholder="Accepted, rejected or parked?"
          aria-label="Resolution"
          // The second step of the picker: typing filters right away.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
        />
        <CommandList>
          <CommandGroup>
            {CLOSED_RESOLUTIONS.map((resolution) => {
              const current = idea.status === 'closed' && idea.resolution === resolution
              return (
                <CommandItem
                  key={resolution}
                  value={statusLabel('closed', resolution)}
                  keywords={[resolution]}
                  onSelect={() => choose('closed', resolution)}
                >
                  <StatusDot tone={resolution} />
                  {statusLabel('closed', resolution)}
                  <Check
                    aria-hidden="true"
                    className={cn('ml-auto text-accent!', current ? 'opacity-100' : 'opacity-0')}
                  />
                  {current && <span className="sr-only">(current)</span>}
                </CommandItem>
              )
            })}
          </CommandGroup>
        </CommandList>
      </Command>
    )
  }

  return (
    // The highlight starts on the current status, so an Enter straight away changes nothing.
    <Command
      label="Status"
      defaultValue={statusLabel(idea.status)}
      className="border-t border-subtle"
    >
      <CommandInput
        value={search}
        onValueChange={setSearch}
        placeholder="Move to…"
        aria-label="Status"
        // The picker's only field: typing filters right away.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
      />
      <CommandList>
        <CommandGroup>
          {IDEA_STATUSES.map((status) => {
            const current = idea.status === status
            const closed = status === 'closed'
            return (
              <CommandItem
                key={status}
                value={statusLabel(status)}
                keywords={[status]}
                onSelect={() => {
                  if (closed) {
                    setSearch('')
                    setStep('resolution')
                  } else choose(status)
                }}
              >
                <StatusDot
                  tone={closed ? statusTone('closed', idea.resolution ?? 'parked') : status}
                />
                {statusLabel(status)}
                {closed ? (
                  <>
                    <span className="text-sm text-muted">
                      {current ? `· ${statusLabel('closed', idea.resolution)}` : ''}
                    </span>
                    <ChevronRight aria-hidden="true" className="ml-auto" />
                  </>
                ) : (
                  <Check
                    aria-hidden="true"
                    className={cn('ml-auto text-accent!', current ? 'opacity-100' : 'opacity-0')}
                  />
                )}
                {current && <span className="sr-only">(current)</span>}
              </CommandItem>
            )
          })}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}
