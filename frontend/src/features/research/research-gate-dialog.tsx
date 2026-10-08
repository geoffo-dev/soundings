import { useNavigate } from '@tanstack/react-router'
import { CircleDashed, ShieldAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { closeResearchGate, useResearchGate, type ResearchGate } from '@/api/research'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

import { gateDescription, OVERRIDE_LABELS } from './research-copy'
import { requestResearchFocus } from './research-focus'

const REASON_MAX = 200

/**
 * The research gate (contract-phase8 §3.5, §3.13): a move, the first invite, "Ask AI
 * to evaluate" or "Start proposal" was refused with 409 `research_incomplete`. Lists
 * the open required items with **Open research**; project and platform admins (the
 * 409's `can_override`) may go on anyway with an optional reason, which is audited.
 * Mounted once in the signed-in layout; focus returns where it came from.
 */
export function ResearchGateDialog() {
  const gate = useResearchGate()
  // The last gate stays rendered while the dialog animates closed.
  const [shown, setShown] = useState(gate)
  if (gate && gate !== shown) setShown(gate)
  return (
    <Dialog open={gate !== null} onOpenChange={(open) => !open && closeResearchGate()}>
      {shown && <GateContent key={`${shown.ideaKey}:${shown.action}`} gate={shown} />}
    </Dialog>
  )
}

function GateContent({ gate }: { gate: ResearchGate }) {
  const navigate = useNavigate()
  const leaving = useRef(false)
  // The safe way on starts focused: Open research (not the override).
  const openRef = useRef<HTMLButtonElement>(null)
  const [overriding, setOverriding] = useState(false)
  const [reason, setReason] = useState('')
  // "Move anyway…" swaps the buttons for the reason field: focus goes there.
  const reasonRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (overriding) reasonRef.current?.focus()
  }, [overriding])
  const count = gate.openItems.length
  const tooLong = reason.trim().length > REASON_MAX
  const overrideLabel = OVERRIDE_LABELS[gate.action]

  const openResearch = () => {
    leaving.current = true
    closeResearchGate()
    requestResearchFocus(gate.ideaKey)
    void navigate({
      to: '/ideas/$ideaKey',
      params: { ideaKey: gate.ideaKey },
      search: {},
      hash: 'research',
    })
  }
  const goAnyway = () => {
    if (tooLong) return
    const trimmed = reason.trim()
    closeResearchGate()
    gate.retry({ override_research: true, override_reason: trimmed || null })
  }

  return (
    <DialogContent
      size="sm"
      onOpenAutoFocus={(event) => {
        event.preventDefault()
        openRef.current?.focus()
      }}
      onCloseAutoFocus={(event) => {
        // A card that snapped back is a new element: focus it there (not when leaving).
        if (leaving.current) return
        const target = gate.returnFocus?.()
        if (!target?.isConnected) return
        event.preventDefault()
        target.focus()
      }}
    >
      <DialogHeader>
        <DialogTitle>Finish the research first</DialogTitle>
        <DialogDescription>
          {gateDescription(gate.action, gate.ideaKey, gate.targetLabel)}
        </DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-4 px-5 pt-4">
        {count > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium text-primary">
              Still open: {count} required {count === 1 ? 'item' : 'items'}
            </p>
            <ul className="flex flex-col gap-1.5" aria-label="Open research items">
              {gate.openItems.map((item) => (
                <li key={item.item_id} className="flex items-start gap-2 text-sm text-secondary">
                  <CircleDashed aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
                  <span className="min-w-0 break-words">{item.title}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {overriding && (
          <form
            id="research-override"
            className="flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              goAnyway()
            }}
          >
            <Field
              label="Reason (optional)"
              description="Recorded in the audit log with your name."
              error={tooLong ? `Keep it to ${REASON_MAX} characters.` : undefined}
            >
              <Input
                ref={reasonRef}
                value={reason}
                autoComplete="off"
                maxLength={REASON_MAX + 20}
                placeholder="e.g. Legal agreed on a call; notes to follow"
                onChange={(event) => setReason(event.target.value)}
              />
            </Field>
          </form>
        )}
        {gate.canOverride && !overriding && (
          <p className="flex items-start gap-2 text-sm text-muted">
            <ShieldAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            As an admin you can go ahead anyway. That’s recorded in the audit log.
          </p>
        )}
      </div>
      <DialogFooter className="pt-5">
        {overriding ? (
          <>
            <Button variant="ghost" onClick={() => setOverriding(false)}>
              Back
            </Button>
            <Button type="submit" form="research-override" variant="primary">
              {overrideLabel}
            </Button>
          </>
        ) : (
          <>
            {gate.canOverride ? (
              <Button variant="ghost" onClick={() => setOverriding(true)}>
                {overrideLabel}…
              </Button>
            ) : (
              <Button variant="ghost" onClick={closeResearchGate}>
                Close
              </Button>
            )}
            <Button ref={openRef} variant="primary" onClick={openResearch}>
              Open research
            </Button>
          </>
        )}
      </DialogFooter>
    </DialogContent>
  )
}
