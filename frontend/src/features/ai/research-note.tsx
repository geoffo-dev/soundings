import { MoreHorizontal, Trash2 } from 'lucide-react'
import { useId, useState } from 'react'

import { useDeleteResearchNote } from '@/api/ai'
import type { AiResearchNoteActivity } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Markdown } from '@/components/ui/markdown'
import { RelativeTime } from '@/components/ui/relative-time'
import { toast } from '@/components/ui/toaster'

import { researchNoteDomId } from './dom-ids'
import { SourceList } from './sources'

/**
 * An AI research note in the activity feed (contract-phase6 §3.8): who wrote it
 * with the AI label, its Markdown rendered as untrusted text (http/https links
 * with their hosts, no mentions, no raw HTML), its numbered sources under "Cited
 * by AI, not checked", and Delete for the idea's owner and admins
 * (`ai.delete_note`, confirmed: no undo).
 */
export function ResearchNoteItem({
  item,
  ideaKey,
}: {
  item: AiResearchNoteActivity
  ideaKey: string
}) {
  const { note } = item
  const author = note.agent?.display_name ?? item.actor?.display_name ?? 'An AI agent'
  const headingId = useId()
  const [confirming, setConfirming] = useState(false)
  const remove = useDeleteResearchNote(ideaKey)

  const confirm = () => {
    remove.mutate(note.id, {
      onSuccess: () => {
        setConfirming(false)
        toast.success('Research note deleted', {
          description: 'Its text and sources are gone for everyone.',
        })
      },
    })
  }

  return (
    <li className="relative py-2">
      <article
        id={researchNoteDomId(note.id)}
        aria-labelledby={headingId}
        tabIndex={-1}
        className="scroll-mt-20 rounded-lg border bg-surface outline-offset-2"
      >
        <header className="flex min-h-10 flex-wrap items-center gap-x-2 gap-y-1 pt-1.5 pr-1.5 pl-3 text-sm">
          <Avatar name={author} isAgent size="sm" decorative className="mr-1" />
          <h3 id={headingId} className="min-w-0 truncate text-primary">
            <span className="font-medium">Research note</span>{' '}
            <span className="text-muted">by {author}</span>
          </h3>
          <AiBadge />
          <RelativeTime date={item.created_at} className="text-muted" />
          {note.can_delete && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="ml-auto"
                  aria-label={`Research note actions (${author})`}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onSelect={() => setConfirming(true)}>
                  <Trash2 /> Delete note…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </header>
        <div className="flex flex-col gap-4 px-3 pt-1 pb-3">
          <Markdown untrusted nested>
            {note.body_md}
          </Markdown>
          <SourceList sources={note.sources} numbered />
          <p className="text-xs text-muted">
            Written by an AI agent from what it could find. Check the facts before you rely on them.
          </p>
        </div>
      </article>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader>
            <DialogTitle>Delete this research note?</DialogTitle>
            <DialogDescription>
              Its text and sources are removed for everyone; the feed keeps a line saying a note was
              deleted. This can’t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-5">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="destructive" loading={remove.isPending} onClick={confirm}>
              Delete note
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  )
}
