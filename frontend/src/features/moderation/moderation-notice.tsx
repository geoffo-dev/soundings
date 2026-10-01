import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowRight, Inbox } from 'lucide-react'

import { useModerationCount } from '@/api/submissions'
import type { Project } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useCommands } from '@/lib/command-registry'

/**
 * "3 ideas waiting for review" above a project's board and list (project
 * admins only; contract-phase4 §3.6): held ideas are on no board or list, so
 * this is how admins find the queue. Nothing shows when the queue is empty.
 */
export function ModerationNotice({ project }: { project: Project }) {
  const admin = project.permissions.can_manage
  const count = useModerationCount(project.slug, { enabled: admin }).data ?? 0
  const navigate = useNavigate()

  useCommands(
    admin && count > 0
      ? {
          id: 'moderation',
          heading: project.name,
          actions: [
            {
              id: 'moderation-review',
              label: `Review new ideas (${count})`,
              icon: <Inbox />,
              keywords: ['moderation', 'approve', 'reject', 'public', 'queue'],
              onSelect: () =>
                void navigate({ to: '/p/$slug/review', params: { slug: project.slug } }),
            },
          ],
        }
      : null,
  )

  if (!admin || count === 0) return null
  return (
    <div className="-mt-1 flex items-center gap-2 rounded-md bg-warning-subtle px-3 py-1.5 text-sm text-primary">
      <Inbox aria-hidden="true" className="size-4 shrink-0 text-warning" />
      <p className="min-w-0 flex-1">
        {count === 1 ? '1 idea from the public form is' : `${count} ideas from the public form are`}{' '}
        waiting for review.
      </p>
      <Button asChild variant="ghost" size="sm">
        <Link to="/p/$slug/review" params={{ slug: project.slug }}>
          Review <ArrowRight aria-hidden="true" />
        </Link>
      </Button>
    </div>
  )
}
