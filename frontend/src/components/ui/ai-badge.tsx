import { Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/**
 * Marks work an AI agent did (contract-phase6 §3.7): its evaluator row and
 * evaluation, research notes, suggestions and runs. Read as "AI agent".
 * Agent text next to it is untrusted data: render it with `Markdown untrusted`.
 */
export function AiBadge({ className }: { className?: string }) {
  return (
    <Badge variant="accent" className={cn('shrink-0', className)}>
      <Sparkles aria-hidden="true" />
      AI
      <span className="sr-only"> agent</span>
    </Badge>
  )
}
