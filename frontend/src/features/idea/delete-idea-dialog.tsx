import { useNavigate } from '@tanstack/react-router'

import { useDeleteIdea } from '@/api/ideas'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from '@/components/ui/toaster'

import { useIdeaPage } from './idea-context'

/** Admins only. Deleting has no undo (contract §3.14), so it asks first. */
export function DeleteIdeaDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { idea, ideaKey } = useIdeaPage()
  const remove = useDeleteIdea(ideaKey)
  const navigate = useNavigate()

  const confirm = () => {
    remove.mutate(undefined, {
      onSuccess: () => {
        onOpenChange(false)
        toast.success(`${idea.key} deleted`, { description: idea.title })
        void navigate({ to: '/p/$slug', params: { slug: idea.project.slug } })
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm" role="alertdialog">
        <DialogHeader>
          <DialogTitle>Delete {idea.key}?</DialogTitle>
          <DialogDescription>
            “{idea.title}” and its evaluations, comments and activity will be deleted for everyone.
            This can’t be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="pt-5">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" loading={remove.isPending} onClick={confirm}>
            Delete idea
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
