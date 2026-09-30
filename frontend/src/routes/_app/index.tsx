import { createFileRoute } from '@tanstack/react-router'

import { myWorkQueryOptions } from '@/api/work'
import { MyWorkPage } from '@/features/work/my-work-page'

export const Route = createFileRoute('/_app/')({
  staticData: { crumb: 'My work' },
  head: () => ({ meta: [{ title: 'My work · Soundings' }] }),
  // Start the request early (hover/preload); the page shows skeletons meanwhile.
  loader: ({ context }) => {
    const { refetchInterval: _interval, ...options } = myWorkQueryOptions()
    void context.queryClient.query(options).catch(() => undefined)
  },
  component: MyWorkPage,
})
