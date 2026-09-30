import { CircleDashed, Tag, TriangleAlert, UserRound, Users } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Avatar, AvatarGroup } from '@/components/ui/avatar'
import { Badge, CountBadge } from '@/components/ui/badge'
import { AddFilterChip, FilterChip, FilterValueChip } from '@/components/ui/filter-chip'
import { Kbd, KbdShortcut } from '@/components/ui/kbd'
import { Markdown } from '@/components/ui/markdown'
import { ProgressTicks } from '@/components/ui/progress-ticks'
import { DueDateLabel } from '@/components/ui/due-date'
import { RelativeTime } from '@/components/ui/relative-time'
import { ScoreBadge } from '@/components/ui/score-badge'
import { ScoreBar } from '@/components/ui/score-bar'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { StatusBadge } from '@/components/ui/status-badge'
import {
  SortableTableHead,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type SortDirection,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CLOSED_RESOLUTIONS, IDEA_STATUSES } from '@/lib/status'

import { IDEAS, inDays, PEOPLE, person, SAMPLE_MARKDOWN, type SampleIdea } from './sample-data'

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString()
import { Code, DesignSection, Example, Specimen } from './specimen'

export function BadgesSection() {
  return (
    <DesignSection
      id="badges"
      title="Badges, status & avatars"
      description={
        <>
          Status is always a coloured dot <em>and</em> a label. Admins can rename labels, so pass{' '}
          <Code>label</Code> from project settings. Avatars get a stable colour from the name.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="StatusBadge" className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            {IDEA_STATUSES.filter((s) => s !== 'closed').map((status) => (
              <StatusBadge key={status} status={status} />
            ))}
            {CLOSED_RESOLUTIONS.map((resolution) => (
              <StatusBadge key={resolution} status="closed" resolution={resolution} />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-5">
            <Example label='label="Triage" (renamed)'>
              <StatusBadge status="new" label="Triage" />
            </Example>
            <Example label='variant="plain"'>
              <StatusBadge status="evaluating" variant="plain" />
            </Example>
          </div>
        </Specimen>
        <Specimen title="Badge" className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Badge>Support</Badge>
            <Badge variant="outline">B2B</Badge>
            <Badge variant="accent">Owner</Badge>
            <Badge variant="success">Submitted</Badge>
            <Badge variant="warning">Due tomorrow</Badge>
            <Badge variant="danger">Overdue</Badge>
            <Badge variant="info">Public</Badge>
            <Badge variant="solid">AI</Badge>
          </div>
          <div className="flex items-center gap-3 text-sm text-secondary">
            My work <CountBadge>4</CountBadge>
          </div>
        </Specimen>
        <Specimen title="Avatar" className="flex flex-col gap-5 lg:col-span-2">
          <div className="flex flex-wrap items-end gap-6">
            {(['xs', 'sm', 'md', 'lg', 'xl'] as const).map((size) => (
              <Example key={size} label={size}>
                <Avatar name="Tom Okafor" size={size} />
              </Example>
            ))}
            <Example label="image">
              <Avatar name="Priya Natarajan" src={PEOPLE[0]?.src} size="lg" />
            </Example>
            <Example label="isAgent (AI badge)">
              <Avatar name="Research agent" isAgent size="lg" />
            </Example>
            <Example label="deterministic colours">
              <div className="flex gap-1.5">
                {['Lena Fischer', 'Marcus Webb', 'Sam Rivera', 'Grace Hopper', 'Ada Lovelace'].map(
                  (name) => (
                    <Avatar key={name} name={name} size="md" tooltip />
                  ),
                )}
              </div>
            </Example>
            <Example label="AvatarGroup · max 4 · +N">
              <AvatarGroup people={PEOPLE} max={4} size="md" />
            </Example>
            <Example label='on="background" (ring matches the canvas)'>
              <div className="rounded-md bg-background p-2">
                <AvatarGroup people={PEOPLE} max={3} size="sm" on="background" />
              </div>
            </Example>
          </div>
        </Specimen>
      </div>
    </DesignSection>
  )
}

export function ScoresSection() {
  return (
    <DesignSection
      id="scores"
      title="Scores & progress"
      description="Aggregates are weighted means on a 1–5 scale. Before an evaluator submits, scores stay hidden (blind evaluation)."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="ScoreBadge" className="flex flex-col gap-5">
          <div className="flex flex-wrap items-end gap-4">
            {[1.2, 2.4, 3.1, 3.8, 4.6].map((score) => (
              <Example key={score} label={`band ${Math.round(score)}`}>
                <ScoreBadge score={score} />
              </Example>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-5">
            <Example label="with count">
              <ScoreBadge score={3.8} count={4} />
            </Example>
            <Example label="none yet">
              <ScoreBadge score={null} />
            </Example>
            <Example label="hidden (blind)">
              <ScoreBadge score={4.2} hidden />
            </Example>
            <Example label="size sm">
              <ScoreBadge score={4.1} size="sm" />
            </Example>
          </div>
        </Specimen>
        <Specimen title="ProgressTicks" className="flex flex-wrap items-end gap-6">
          <Example label="none">
            <ProgressTicks done={0} total={3} />
          </Example>
          <Example label="in progress">
            <ProgressTicks done={3} total={4} />
          </Example>
          <Example label="complete">
            <ProgressTicks done={4} total={4} />
          </Example>
          <Example label="many (> 8)">
            <ProgressTicks done={7} total={12} />
          </Example>
        </Specimen>
        <Specimen
          title="ScoreBar"
          description="The whisker under each bar spans the lowest–highest individual score. ⚠ = high disagreement (spread ≥ 2)."
          className="flex flex-col gap-4 lg:col-span-2 lg:grid lg:grid-cols-2 lg:gap-x-10"
        >
          <ScoreBar label="Value" value={4.3} min={4} max={5} />
          <ScoreBar label="Feasibility" value={3.7} min={3} max={4} />
          <ScoreBar label="Effort" value={2.7} min={1} max={4} disagreement />
          <ScoreBar label="Strategic fit" value={4} min={4} max={4} />
          <ScoreBar label="Risk" value={null} />
        </Specimen>
      </div>
    </DesignSection>
  )
}

type SortKey = 'title' | 'score' | 'updated'

export function TableSection() {
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({
    key: 'score',
    direction: 'desc',
  })
  const [needsEvaluators, setNeedsEvaluators] = useState(false)
  const [disagreement, setDisagreement] = useState(true)
  const [statusFilter, setStatusFilter] = useState(true)

  const rows = useMemo(() => {
    const filtered = IDEAS.filter((idea) => !needsEvaluators || idea.evaluatorIds.length < 3)
    const value = (idea: SampleIdea) =>
      sort.key === 'title'
        ? idea.title
        : sort.key === 'score'
          ? (idea.score ?? -1)
          : Date.parse(idea.updatedAt)
    return [...filtered].sort((a, b) => {
      const av = value(a)
      const bv = value(b)
      const cmp =
        typeof av === 'string' && typeof bv === 'string'
          ? av.localeCompare(bv)
          : Number(av) - Number(bv)
      return sort.direction === 'asc' ? cmp : -cmp
    })
  }, [sort, needsEvaluators])

  const toggleSort = (key: SortKey) =>
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  const sortedBy = (key: SortKey) => (sort.key === key ? sort.direction : false)

  return (
    <DesignSection
      id="table"
      title="Table & filters"
      description="The project List view: sortable headers (aria-sort), filter chips above. Rows are 44px; numbers are tabular."
    >
      <Specimen title="Filter chips" className="flex flex-wrap items-center gap-2">
        <FilterValueChip
          field="Status"
          icon={<CircleDashed />}
          value="Evaluating, Shortlisted"
          onEdit={() => undefined}
          onRemove={() => setStatusFilter(false)}
          className={statusFilter ? undefined : 'hidden'}
        />
        <FilterValueChip
          field="Owner"
          icon={<UserRound />}
          value="Priya Natarajan"
          onEdit={() => undefined}
          onRemove={() => undefined}
        />
        <FilterChip pressed={needsEvaluators} onPressedChange={setNeedsEvaluators} icon={<Users />}>
          Needs evaluators
        </FilterChip>
        <FilterChip
          pressed={disagreement}
          onPressedChange={setDisagreement}
          icon={<TriangleAlert />}
          count={1}
        >
          High disagreement
        </FilterChip>
        <FilterChip pressed={false} onPressedChange={() => undefined} icon={<Tag />}>
          Tag
        </FilterChip>
        <AddFilterChip />
      </Specimen>
      <Specimen
        title="Table (List view)"
        description={
          <>
            <Code>mobile=&quot;cards&quot;</Code>: below 768px the header hides and rows become
            stacked cards; give cells a <Code>label</Code> and mark the title <Code>primary</Code>.
          </>
        }
        flush
      >
        <Table mobile="cards">
          <TableHeader>
            <TableRow>
              <SortableTableHead sorted={sortedBy('title')} onSort={() => toggleSort('title')}>
                Title
              </SortableTableHead>
              <TableHead>Owner</TableHead>
              <TableHead>Evaluations</TableHead>
              <SortableTableHead sorted={sortedBy('score')} onSort={() => toggleSort('score')}>
                Score
              </SortableTableHead>
              <TableHead>Status</TableHead>
              <SortableTableHead
                sorted={sortedBy('updated')}
                onSort={() => toggleSort('updated')}
                align="right"
                className="text-right"
              >
                Updated
              </SortableTableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((idea) => (
              <TableRow key={idea.id}>
                <TableCell primary className="max-w-80">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="shrink-0 text-xs text-muted tabular-nums">{idea.key}</span>
                    <span className="font-medium md:truncate">{idea.title}</span>
                  </div>
                </TableCell>
                <TableCell label="Owner">
                  {idea.ownerId ? (
                    <Avatar
                      name={person(idea.ownerId).name}
                      src={person(idea.ownerId).src}
                      size="sm"
                      tooltip
                    />
                  ) : (
                    <span className="text-sm text-muted">Unassigned</span>
                  )}
                </TableCell>
                <TableCell label="Evaluations">
                  {idea.evaluatorIds.length > 0 ? (
                    <ProgressTicks done={idea.submitted} total={idea.evaluatorIds.length} />
                  ) : (
                    <span className="text-sm text-muted">—</span>
                  )}
                </TableCell>
                <TableCell label="Score">
                  <ScoreBadge score={idea.score} size="sm" hidden={idea.hidden} />
                </TableCell>
                <TableCell label="Status">
                  <StatusBadge status={idea.status} resolution={idea.resolution} variant="plain" />
                </TableCell>
                <TableCell
                  label="Updated"
                  className="text-right text-sm whitespace-nowrap text-muted max-md:text-left"
                >
                  <RelativeTime date={idea.updatedAt} style="narrow" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Specimen>
    </DesignSection>
  )
}

export function ContentSection() {
  return (
    <DesignSection
      id="content"
      title="Content & navigation"
      description="Markdown for descriptions and comments (safe: no raw HTML, no remote images), tabs for the idea page, keyboard hints."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="Markdown">
          <Markdown>{SAMPLE_MARKDOWN}</Markdown>
        </Specimen>
        <div className="flex flex-col gap-4">
          <Specimen title="Tabs">
            <Tabs defaultValue="overview">
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="evaluations">
                  Evaluations <CountBadge>3</CountBadge>
                </TabsTrigger>
                <TabsTrigger value="proposal">Proposal</TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="text-sm text-secondary">
                Title, summary, description, then the activity feed.
              </TabsContent>
              <TabsContent value="evaluations" className="text-sm text-secondary">
                Each evaluator’s scores, revealed after you submit your own.
              </TabsContent>
              <TabsContent value="proposal" className="text-sm text-secondary">
                The proposal editor, once the idea is shortlisted.
              </TabsContent>
            </Tabs>
          </Specimen>
          <Specimen title="Dates (lib/dates.ts)" className="flex flex-col gap-3">
            <p className="text-sm text-muted">
              One date util, locale-aware. <Code>RelativeTime</Code> shows the full date on hover;{' '}
              <Code>DueDateLabel</Code> adds an icon so state is never colour alone.
            </p>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
              <RelativeTime date={hoursAgo(0.1)} />
              <RelativeTime date={hoursAgo(3)} />
              <RelativeTime date={hoursAgo(30)} style="narrow" />
              <RelativeTime date={hoursAgo(24 * 20)} />
            </div>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <DueDateLabel value={hoursAgo(50)} />
              <DueDateLabel value={inDays(1)} />
              <DueDateLabel value={inDays(4)} />
              <DueDateLabel value={null} />
            </div>
          </Specimen>
          <Specimen title="Kbd" className="flex flex-wrap items-center gap-5">
            <Example label="Kbd">
              <Kbd>Esc</Kbd>
            </Example>
            <Example label='keys="mod+k"'>
              <KbdShortcut keys="mod+k" />
            </Example>
            <Example label='keys="g m"'>
              <KbdShortcut keys="g m" />
            </Example>
            <Example label='keys="shift+enter"'>
              <KbdShortcut keys="shift+enter" />
            </Example>
            <Example label='tone="accent" (in a primary button)'>
              <span className="inline-flex h-8 items-center gap-2 rounded-md bg-accent px-3 text-sm font-medium text-accent-foreground">
                New idea
                <KbdShortcut keys="n" tone="accent" />
              </span>
            </Example>
          </Specimen>
          <Specimen title="Separator & ScrollArea">
            <ScrollArea focusable aria-label="Idea titles" className="h-32 rounded-md border">
              <div className="p-3">
                {IDEAS.concat(IDEAS).map((idea, i) => (
                  <div key={`${idea.id}-${i}`}>
                    <div className="py-1.5 text-sm text-primary">{idea.title}</div>
                    <Separator />
                  </div>
                ))}
              </div>
            </ScrollArea>
          </Specimen>
        </div>
      </div>
    </DesignSection>
  )
}
