import { createFileRoute } from '@tanstack/react-router'

import { PageNotFound } from '@/components/not-found'

/** Any other path, for signed-in people: the not-found page inside the app shell. */
export const Route = createFileRoute('/_app/$')({
  head: () => ({ meta: [{ title: 'Page not found · Soundings' }] }),
  component: PageNotFound,
})
