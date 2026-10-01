import type { ReactNode } from 'react'

import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'

import { MappingTestPanel, type MappingTestDraft } from './mapping-test-panel'

/**
 * "Test mapping" (contract-phase2 §3.12) in a sheet, opened from the groups
 * list and from a group's page (which highlights that group in the result).
 * The page keeps the draft, so the claims are still there when it reopens.
 */
export function MappingTestSheet({
  open,
  onOpenChange,
  draft,
  onDraftChange,
  highlightGroupId,
  notice,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  draft: MappingTestDraft
  onDraftChange: (draft: MappingTestDraft) => void
  highlightGroupId?: string
  /** Shown above the box, e.g. "Save the mapping to test it". */
  notice?: ReactNode
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent size="lg">
        <SheetHeader>
          <SheetTitle>Test mapping</SheetTitle>
          <SheetDescription>
            What signing in with these claims would do to group memberships and project roles.
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="flex flex-col gap-4">
          {notice}
          <MappingTestPanel
            draft={draft}
            onDraftChange={onDraftChange}
            highlightGroupId={highlightGroupId}
          />
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}
