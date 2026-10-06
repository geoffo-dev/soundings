import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'

import { AdminKeyProjects, KeyProjects } from './key-parts'

const cust = { id: 'p1', slug: 'customer-innovation', key: 'CUST', name: 'Customer Innovation' }
const tools = { id: 'p2', slug: 'internal-tools', key: 'TOOLS', name: 'Internal Tools' }

describe('KeyProjects (Settings → API keys)', () => {
  it('names the projects and counts the ones you can no longer open', () => {
    render(
      <KeyProjects
        apiKey={{ restricted: true, projects: [tools], unavailable_project_count: 1 }}
      />,
    )
    expect(screen.getByText('Internal Tools')).toBeInTheDocument()
    expect(screen.getByText('+1 project you can no longer open')).toBeInTheDocument()
  })

  it('warns when nothing is left and still counts what was lost', () => {
    render(
      <KeyProjects apiKey={{ restricted: true, projects: [], unavailable_project_count: 2 }} />,
    )
    expect(screen.getByText('No projects left: it reaches nothing')).toBeInTheDocument()
    expect(screen.getByText('+2 projects you can no longer open')).toBeInTheDocument()
  })

  it('says nothing extra for an unrestricted key or when every project is reachable', () => {
    const { container, rerender } = render(
      <KeyProjects apiKey={{ restricted: false, projects: [], unavailable_project_count: 0 }} />,
    )
    expect(container).toHaveTextContent(/^All projects$/)
    rerender(
      <KeyProjects apiKey={{ restricted: true, projects: [cust], unavailable_project_count: 0 }} />,
    )
    expect(container).toHaveTextContent(/^Customer Innovation$/)
  })
})

describe('AdminKeyProjects (Admin settings → API keys)', () => {
  it('marks the projects the owner can no longer open', () => {
    render(
      <TooltipProvider>
        <AdminKeyProjects
          apiKey={{
            restricted: true,
            projects: [
              { ...cust, owner_can_view: false },
              { ...tools, owner_can_view: true },
            ],
            unavailable_project_count: 1,
          }}
        />
      </TooltipProvider>,
    )
    const struck = screen.getByText('Customer Innovation')
    expect(struck).toHaveClass('line-through')
    expect(struck).toHaveTextContent('Customer Innovation (the owner can no longer open it)')
    expect(screen.getByText('Internal Tools')).not.toHaveClass('line-through')
    expect(screen.getByText('Owner can’t open 1')).toBeInTheDocument()
  })

  it('says the key reaches nothing when the owner can open none of them', () => {
    render(
      <TooltipProvider>
        <AdminKeyProjects
          apiKey={{
            restricted: true,
            projects: [{ ...cust, owner_can_view: false }],
            unavailable_project_count: 1,
          }}
        />
      </TooltipProvider>,
    )
    expect(screen.getByText('Reaches nothing')).toBeInTheDocument()
  })
})
