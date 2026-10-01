import { Check, CloudOff, MailX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import {
  allTypes,
  useNotificationPreferences,
  useUpdateNotificationPreferences,
} from '@/api/notifications'
import type {
  NotificationMode,
  NotificationPreference,
  NotificationPreferences,
  NotificationPreferencesUpdate,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { toastUndo } from '@/components/ui/toaster'
import { AdminPageHeader, SettingsFrame } from '@/features/admin/settings-frame'
import { SM_UP, useMediaQuery } from '@/lib/media'

import { describeMode, MODE_OPTIONS, modeLabel, previousModes } from './preferences'
import { digestTime, TYPE_COPY } from './notification-text'

/**
 * Settings → Notifications (contract-phase3 §3.4, `self.manage_profile`): per
 * notification type, whether it is emailed immediately, in the daily digest, or
 * not at all. The inbox always gets everything. Saves as you choose
 * (optimistic; a failed save rolls back with a toast).
 */
export function NotificationPreferencesPage() {
  const query = useNotificationPreferences()
  return (
    <SettingsFrame>
      <AdminPageHeader
        title="Email notifications"
        description="Everything shows up in your inbox (the bell). Choose what is also emailed to you, and when."
      />
      {query.data ? (
        <PreferencesForm preferences={query.data} />
      ) : query.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<CloudOff />}
          title="Couldn’t load your email preferences"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <SkeletonGroup label="Loading your email preferences" className="flex flex-col gap-3">
          <Skeleton className="h-4 w-40" />
          <div className="flex flex-col divide-y divide-subtle rounded-lg border">
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center">
                <div className="flex flex-1 flex-col gap-2">
                  <Skeleton className="h-3.5 w-40" />
                  <Skeleton className="h-3 w-64 max-w-full" />
                </div>
                <Skeleton className="h-7 w-64 max-w-full" />
              </div>
            ))}
          </div>
        </SkeletonGroup>
      )}
    </SettingsFrame>
  )
}

function PreferencesForm({ preferences }: { preferences: NotificationPreferences }) {
  const update = useUpdateNotificationPreferences()
  const [saved, setSaved] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const save = (change: NotificationPreferencesUpdate, message: string) => {
    update.mutate(change, {
      onSuccess: () => {
        setSaved(message)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => setSaved(null), 3000)
      },
    })
  }

  const allOff = preferences.items.every((item) => item.mode === 'off')
  const turnAllOff = () => {
    const before = previousModes(preferences)
    update.mutate(allTypes(preferences, 'off'), {
      onSuccess: () =>
        toastUndo('All email turned off', {
          description: 'You’ll still see everything in your inbox.',
          onUndo: () => update.mutate(before),
        }),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      {!preferences.email_available && (
        <Callout tone="neutral" icon={<MailX />} title="Email isn’t set up on this server yet">
          Nothing is emailed for now, so you’ll only see notifications in Soundings. Your choices
          here apply as soon as an administrator turns email on.
        </Callout>
      )}

      {/* One heading per page (the h2 above): the list needs no section title of its own. */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
          <p className="max-w-2xl text-sm text-muted">
            {preferences.email_available ? 'The' : 'Once email is on, the'} daily digest arrives at{' '}
            {digestTime(preferences.digest_hour)} ({preferences.timezone}) with everything set to
            “Daily digest”.
          </p>
          <p
            role="status"
            className="flex h-7 items-center gap-1 text-sm text-muted"
            aria-live="polite"
          >
            {saved && (
              <>
                <Check aria-hidden="true" className="size-3.5 text-success" />
                <span>Saved</span>
                <span className="sr-only">: {saved}</span>
              </>
            )}
          </p>
        </div>
        <ul
          aria-label="Email for each kind of notification"
          className="flex flex-col divide-y divide-subtle rounded-lg border"
        >
          {preferences.items.map((item) => (
            <PreferenceRow
              key={item.type}
              item={item}
              onChange={(mode) =>
                save(
                  { [item.type]: mode },
                  `${TYPE_COPY[item.type].label}: ${describeMode(mode).toLowerCase()}`,
                )
              }
            />
          ))}
        </ul>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">
            Every email has an unsubscribe link that turns off just that kind of email.
          </p>
          <Button variant="ghost" size="sm" disabled={allOff} onClick={turnAllOff}>
            Turn off all email
          </Button>
        </div>
      </div>
    </div>
  )
}

function PreferenceRow({
  item,
  onChange,
}: {
  item: NotificationPreference
  onChange: (mode: NotificationMode) => void
}) {
  const wide = useMediaQuery(SM_UP)
  const copy = TYPE_COPY[item.type]
  const labelId = `pref-${item.type}-label`
  const descriptionId = `pref-${item.type}-description`
  const changed = item.mode !== item.default_mode
  return (
    <li className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-6">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span id={labelId} className="text-sm font-medium text-primary">
          {copy.label}
        </span>
        <span id={descriptionId} className="text-sm text-muted">
          {copy.description}
        </span>
        {changed && (
          <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted">
            Default: {modeLabel(item.default_mode)}
            <span aria-hidden="true">·</span>
            <button
              type="button"
              className="rounded-sm font-medium text-accent underline-offset-4 hover:underline"
              onClick={() => onChange(item.default_mode)}
            >
              Reset<span className="sr-only"> {copy.label} to the default</span>
            </button>
          </span>
        )}
      </div>
      <SegmentedControl
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
        value={item.mode}
        onValueChange={onChange}
        options={MODE_OPTIONS}
        fullWidth={!wide}
        className="sm:shrink-0"
      />
    </li>
  )
}
