import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'

/**
 * Copies text. The Clipboard API needs a secure context (https or localhost);
 * on plain http (a lab install) fall back to a hidden textarea and execCommand.
 */
export async function copyText(value: string): Promise<boolean> {
  try {
    if (window.isSecureContext && 'clipboard' in navigator) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {
    // Permission denied or unavailable: try the fallback.
  }
  try {
    const area = document.createElement('textarea')
    area.value = value
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- the only option outside secure contexts
    const ok = document.execCommand('copy')
    area.remove()
    return ok
  } catch {
    return false
  }
}

/** An icon button that copies `value` ("Copy redirect URI"), with a short "Copied" check. */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  return (
    <WithTooltip content={copied ? 'Copied' : `Copy ${label}`}>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={`Copy ${label}`}
        onClick={() => {
          void copyText(value).then((ok) => {
            if (!ok) {
              toast.error('Couldn’t copy', { description: 'Select the text and copy it instead.' })
              return
            }
            setCopied(true)
            window.clearTimeout(timer.current)
            timer.current = window.setTimeout(() => setCopied(false), 1500)
          })
        }}
      >
        {copied ? <Check className="text-success" /> : <Copy />}
      </Button>
    </WithTooltip>
  )
}
