import { UserMinus } from 'lucide-react'

import { useSetIdeaOwner } from '@/api/ideas'
import type { UserRef, UserSearchResult } from '@/api/types'
import { CommandGroup, CommandItem } from '@/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

import { useIdeaPage } from './idea-context'
import { PeopleList } from './people-list'

export function toUserRef(person: UserSearchResult): UserRef {
  return {
    id: person.id,
    display_name: person.display_name,
    avatar_url: person.avatar_url,
    initials: person.initials,
  }
}

/**
 * "Assign owner" (A, the sidebar, the palette) for admins: pick one member or
 * admin of the project; the change is instant with an Undo toast.
 */
export function OwnerDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { idea, ideaKey, me } = useIdeaPage()
  const setOwner = useSetIdeaOwner(ideaKey)
  const owner = idea.owner

  const choose = (person: UserRef | null) => {
    onOpenChange(false)
    if ((person?.id ?? null) === (owner?.id ?? null)) return
    setOwner.mutate({ owner: person })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm" position="top" className="overflow-hidden">
        <DialogHeader className="pb-3">
          <DialogTitle>{owner ? 'Change owner' : 'Assign owner'}</DialogTitle>
          <DialogDescription className="truncate">
            {idea.key} · {idea.title}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <div className="border-t border-subtle">
            <PeopleList
              projectSlug={idea.project.slug}
              selected={owner ? [owner.id] : []}
              meId={me.id}
              label="Owner"
              placeholder="Assign to…"
              onSelect={(person) => choose(toUserRef(person))}
              before={
                owner && (
                  <CommandGroup>
                    <CommandItem value="remove-owner" onSelect={() => choose(null)}>
                      <UserMinus aria-hidden="true" />
                      Remove owner
                    </CommandItem>
                  </CommandGroup>
                )
              }
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
