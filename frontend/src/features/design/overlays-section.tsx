import {
  Archive,
  CircleDashed,
  Copy,
  FileText,
  Inbox,
  Link2,
  MoreHorizontal,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  UserPlus,
} from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { CommandPalette } from '@/components/ui/command-palette'
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { StatusDot } from '@/components/ui/status-badge'
import { toast, toastUndo } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import { useAppCommands } from '@/components/layout/app-commands'
import { defaultStatusLabel, statusTone, IDEA_STATUSES } from '@/lib/status'

import { EvaluateSheet } from './patterns'
import { Code, DesignSection, Example, Specimen } from './specimen'

export function OverlaysSection() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const { openCommandPalette, openShortcutSheet } = useAppCommands()

  return (
    <DesignSection
      id="overlays"
      title="Overlays"
      description={
        <>
          Overlays are the only things with shadows. All are Radix-based: focus is trapped and
          restored,
          <Code>Esc</Code> closes, and they animate in 160–200ms.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <Specimen title="Tooltip" className="flex flex-wrap items-center gap-3">
          <WithTooltip content="New idea" shortcut="n">
            <Button variant="outline" size="icon" aria-label="New idea">
              <Plus />
            </Button>
          </WithTooltip>
          <WithTooltip content="Copy link">
            <Button variant="ghost" size="icon" aria-label="Copy link">
              <Link2 />
            </Button>
          </WithTooltip>
          <span className="text-sm text-muted">Hover or focus</span>
        </Specimen>
        <Specimen title="Popover" className="flex items-center">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">
                <UserPlus /> Invite evaluator
              </Button>
            </PopoverTrigger>
            <PopoverContent className="flex flex-col gap-3">
              <Field label="Email or name">
                <Input placeholder="name@example.com" />
              </Field>
              <Button variant="primary" size="sm" className="self-end">
                Send invite
              </Button>
            </PopoverContent>
          </Popover>
        </Specimen>
        <Specimen title="Dropdown menu" className="flex items-center">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Idea actions">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuLabel>CI-42</DropdownMenuLabel>
              <DropdownMenuItem>
                <Pencil /> Edit
                <DropdownMenuShortcut keys="e" />
              </DropdownMenuItem>
              <DropdownMenuItem>
                <Copy /> Copy link
                <DropdownMenuShortcut keys="mod+shift+c" />
              </DropdownMenuItem>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <CircleDashed /> Move to
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {IDEA_STATUSES.map((status) => (
                    <DropdownMenuItem key={status}>
                      <StatusDot tone={statusTone(status)} className="mx-1" />{' '}
                      {defaultStatusLabel(status)}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
              <DropdownMenuCheckboxItem checked={showArchived} onCheckedChange={setShowArchived}>
                Show archived
              </DropdownMenuCheckboxItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive">
                <Trash2 /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </Specimen>
        <Specimen title="Dialog" className="flex items-center">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">Close evaluation…</Button>
            </DialogTrigger>
            <DialogContent size="sm">
              <DialogHeader>
                <DialogTitle>Close evaluation?</DialogTitle>
                <DialogDescription>
                  Evaluators can no longer change their scores. One evaluation is still missing.
                </DialogDescription>
              </DialogHeader>
              <DialogBody />
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="ghost">Cancel</Button>
                </DialogClose>
                <DialogClose asChild>
                  <Button variant="primary">Close evaluation</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </Specimen>
        <Specimen
          title="Sheet"
          description="Right on desktop, bottom sheet on phones."
          className="flex items-center"
        >
          <EvaluateSheet />
        </Specimen>
        <Specimen title="Command palette" className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => setPaletteOpen(true)}>
            Open demo palette
          </Button>
          <Button variant="ghost" onClick={openCommandPalette}>
            App palette (⌘K)
          </Button>
          <Button variant="ghost" onClick={openShortcutSheet}>
            Shortcuts (?)
          </Button>
          <CommandPalette
            open={paletteOpen}
            onOpenChange={setPaletteOpen}
            groups={[
              {
                heading: 'Ideas',
                actions: [
                  {
                    id: 'i1',
                    label: 'Self-serve returns portal',
                    hint: 'CI-42',
                    icon: <FileText />,
                    onSelect: () => toast.message('Opened CI-42'),
                  },
                  {
                    id: 'i2',
                    label: 'Carbon footprint estimate',
                    hint: 'CI-38',
                    icon: <FileText />,
                    onSelect: () => toast.message('Opened CI-38'),
                  },
                ],
              },
              {
                heading: 'Actions',
                actions: [
                  {
                    id: 'new',
                    label: 'New idea',
                    icon: <Plus />,
                    shortcut: 'n',
                    onSelect: () => toast.message('New idea'),
                  },
                  {
                    id: 'assign',
                    label: 'Assign owner…',
                    icon: <UserPlus />,
                    onSelect: () => toast.message('Assign owner'),
                  },
                  {
                    id: 'ai',
                    label: 'Ask AI to evaluate',
                    icon: <Sparkles />,
                    keywords: ['kagent', 'agent'],
                    onSelect: () => toast.message('AI evaluation queued'),
                  },
                  {
                    id: 'inbox',
                    label: 'Go to My work',
                    icon: <Inbox />,
                    shortcut: 'g m',
                    onSelect: () => toast.message('My work'),
                  },
                ],
              },
            ]}
          />
        </Specimen>
      </div>
      <Specimen
        title="Toasts"
        description="Bottom-right, brief, never blocking. Destructive-ish actions apply immediately and offer Undo."
        className="flex flex-wrap items-end gap-5"
      >
        <Example label="toast.success">
          <Button
            variant="outline"
            onClick={() =>
              toast.success('Evaluation submitted', {
                description: 'Other scores are now visible.',
              })
            }
          >
            Success
          </Button>
        </Example>
        <Example label="toast.error">
          <Button
            variant="outline"
            onClick={() =>
              toast.error('Couldn’t save', { description: 'Check your connection and try again.' })
            }
          >
            Error
          </Button>
        </Example>
        <Example label="toast.info">
          <Button variant="outline" onClick={() => toast.info('Reminder sent to 2 evaluators')}>
            Info
          </Button>
        </Example>
        <Example label="toastUndo">
          <Button
            variant="outline"
            onClick={() =>
              toastUndo('Idea archived', {
                description: 'CI-17 · Gamified onboarding checklist',
                onUndo: () => toast.success('Idea restored'),
              })
            }
          >
            <Archive /> Archive with Undo
          </Button>
        </Example>
      </Specimen>
    </DesignSection>
  )
}
