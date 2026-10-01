import { Link } from '@tanstack/react-router'
import { Compass } from 'lucide-react'

import { Logo } from '@/components/layout/logo'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'

/** "We couldn't find that page", as the page's h1. Inside the app shell for signed-in routes. */
export function PageNotFound() {
  return (
    <EmptyState
      headingLevel={1}
      icon={<Compass />}
      title="We couldn’t find that page"
      description="The link may be out of date, or the page may have moved. Head back to your work and carry on from there."
      action={
        <Button asChild variant="primary">
          <Link to="/">Go to My work</Link>
        </Button>
      }
    />
  )
}

/**
 * The router's last resort (no app shell: it may show before anyone signs in).
 * Unknown paths inside the app are caught by routes/_app/$.tsx, in the shell.
 */
export function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="flex h-14 items-center px-5">
        <Link to="/" className="rounded-md">
          <Logo />
        </Link>
      </header>
      <main id="main" className="flex flex-1 items-center justify-center px-4 pb-24">
        <PageNotFound />
      </main>
    </div>
  )
}
