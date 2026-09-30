import { ArrowRight, Columns3, List, Plus, Search, Sparkles, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Combobox } from '@/components/ui/combobox'
import { DatePicker } from '@/components/ui/date-picker'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { SegmentedControl, scoreOptions } from '@/components/ui/segmented-control'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tag-input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'

import { PEOPLE } from './sample-data'
import { Code, DesignSection, Example, Specimen } from './specimen'

const personOptions = PEOPLE.map((p) => ({
  value: p.id,
  label: p.name,
  description: p.isAgent ? 'AI agent · kagent' : p.email,
  avatar: { name: p.name, src: p.src, isAgent: p.isAgent },
}))

export function ButtonsSection() {
  return (
    <DesignSection
      id="buttons"
      title="Buttons"
      description={
        <>
          One <Code>primary</Code> per view. <Code>secondary</Code> and <Code>outline</Code> for the
          rest, <Code>ghost</Code> for toolbars and icon buttons. Use <Code>asChild</Code> to style
          a router link.
        </>
      }
    >
      <Specimen title="Variants" className="flex flex-wrap items-end gap-6">
        <Example label="primary">
          <Button variant="primary">Submit evaluation</Button>
        </Example>
        <Example label="secondary">
          <Button variant="secondary">Save draft</Button>
        </Example>
        <Example label="outline">
          <Button variant="outline">Invite evaluators</Button>
        </Example>
        <Example label="ghost">
          <Button variant="ghost">Cancel</Button>
        </Example>
        <Example label="destructive">
          <Button variant="destructive">
            <Trash2 /> Delete idea
          </Button>
        </Example>
        <Example label="link">
          <Button variant="link">View proposal</Button>
        </Example>
      </Specimen>
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="Sizes" className="flex flex-wrap items-end gap-5">
          <Example label="sm · 28px">
            <Button variant="outline" size="sm">
              <Plus /> Add
            </Button>
          </Example>
          <Example label="md · 32px">
            <Button variant="outline">
              <Plus /> Add
            </Button>
          </Example>
          <Example label="lg · 40px">
            <Button variant="outline" size="lg">
              <Plus /> Add
            </Button>
          </Example>
          <Example label="icon">
            <Button variant="outline" size="icon" aria-label="Search">
              <Search />
            </Button>
          </Example>
          <Example label="icon-sm">
            <Button variant="ghost" size="icon-sm" aria-label="Add">
              <Plus />
            </Button>
          </Example>
        </Specimen>
        <Specimen title="States" className="flex flex-wrap items-end gap-5">
          <Example label="default">
            <Button variant="primary">Continue</Button>
          </Example>
          <Example label="hover">
            <Button variant="primary" className="bg-accent-hover">
              Continue
            </Button>
          </Example>
          <Example label="focus-visible">
            <Button variant="primary" className="outline-2 outline-offset-2 outline-focus">
              Continue
            </Button>
          </Example>
          <Example label="loading">
            <Button variant="primary" loading>
              Saving
            </Button>
          </Example>
          <Example label="disabled">
            <Button variant="primary" disabled>
              Continue
            </Button>
          </Example>
          <Example label="with icon">
            <Button variant="secondary">
              <Sparkles /> Ask AI <ArrowRight />
            </Button>
          </Example>
        </Specimen>
      </div>
    </DesignSection>
  )
}

export function FormsSection() {
  const [title, setTitle] = useState('Self-serve returns portal')
  const [summary, setSummary] = useState(
    'Let account admins start and track returns without calling support. Grows as you type — try adding a few lines.',
  )
  const [owner, setOwner] = useState<string | null>('u1')
  const [evaluators, setEvaluators] = useState<string[]>(['u2', 'u3', 'ai'])
  const [due, setDue] = useState('2026-10-07')
  const [status, setStatus] = useState('evaluating')
  const [notify, setNotify] = useState(true)
  const [digest, setDigest] = useState('immediate')
  const [checked, setChecked] = useState<boolean | 'indeterminate'>(true)
  const [tags, setTags] = useState(['returns', 'b2b'])

  return (
    <DesignSection
      id="forms"
      title="Form controls"
      description={
        <>
          Wrap every control in <Code>&lt;Field&gt;</Code>: it wires the label, help text and error
          (<Code>aria-describedby</Code>, <Code>aria-invalid</Code>) automatically. Inputs are 16px
          on phones so iOS doesn’t zoom.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="Input & Field" className="flex flex-col gap-5">
          <Field
            label="Title"
            required
            description="A short, specific name. You can change it later."
          >
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Title" required error="Give your idea a title so others can find it.">
            <Input placeholder="e.g. Offline mode for field engineers" />
          </Field>
          <div className="grid gap-5 sm:grid-cols-3">
            <Example label="startIcon">
              <Field label="Search" hideLabel className="w-full">
                <Input type="search" placeholder="Search ideas…" startIcon={<Search />} />
              </Field>
            </Example>
            <Example label="focus-visible">
              <Field label="Focused example" hideLabel className="w-full">
                <Input
                  defaultValue="Focused"
                  className="border-focus ring-3 ring-focus/20"
                  tabIndex={-1}
                />
              </Field>
            </Example>
            <Example label="disabled">
              <Field label="Disabled example" hideLabel disabled className="w-full">
                <Input value="Viewers can’t edit" readOnly />
              </Field>
            </Example>
          </div>
        </Specimen>
        <Specimen title="Textarea (auto-grow) & date" className="flex flex-col gap-5">
          <Field
            label="Summary"
            description="One or two sentences. Markdown works in the description."
          >
            <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} minRows={2} />
          </Field>
          <Field
            label="Evaluation due"
            description="Evaluators get a reminder 2 days before and on the day."
          >
            <DatePicker value={due} onValueChange={setDue} />
          </Field>
          <Field
            label="Tags"
            description="TagInput: Enter or comma adds, Backspace removes, ↑/↓ pick a suggestion. Pasting “a, b” adds both."
          >
            <TagInput
              value={tags}
              onValueChange={setTags}
              suggestions={['returns', 'logistics', 'b2b', 'checkout', 'support']}
            />
          </Field>
        </Specimen>
        <Specimen title="Select & Combobox (user picker)" className="flex flex-col gap-5">
          <Field label="Status">
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="sm:w-60">
                <SelectValue placeholder="Choose a status" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>Open</SelectLabel>
                  <SelectItem value="new">New</SelectItem>
                  <SelectItem value="evaluating">Evaluating</SelectItem>
                  <SelectItem value="shortlisted">Shortlisted</SelectItem>
                  <SelectItem value="proposal">Proposal</SelectItem>
                </SelectGroup>
                <SelectGroup>
                  <SelectLabel>Closed</SelectLabel>
                  <SelectItem value="accepted">Accepted</SelectItem>
                  <SelectItem value="rejected">Rejected</SelectItem>
                  <SelectItem value="parked">Parked</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Owner" description="Accountable for moving the idea forward.">
            <Combobox
              options={personOptions.filter((o) => !o.avatar.isAgent)}
              value={owner}
              onValueChange={setOwner}
              placeholder="Assign an owner"
              searchPlaceholder="Search people…"
            />
          </Field>
          <Field label="Evaluators">
            <Combobox
              multiple
              options={personOptions}
              value={evaluators}
              onValueChange={setEvaluators}
              placeholder="Invite evaluators"
              searchPlaceholder="Search project members…"
            />
          </Field>
        </Specimen>
        <Specimen title="Checkbox, switch & radio" className="flex flex-col gap-5">
          <div className="flex flex-col gap-3">
            <Field label="Include AI evaluation in the aggregate" inline>
              <Checkbox checked={checked} onCheckedChange={setChecked} />
            </Field>
            <Field label="Select all (indeterminate)" inline>
              <Checkbox checked="indeterminate" />
            </Field>
            <Field label="Disabled option" inline disabled>
              <Checkbox />
            </Field>
          </div>
          <Field
            label="Email me when evaluations are in"
            inline
            description="You can change this per notification in Settings."
          >
            <Switch checked={notify} onCheckedChange={setNotify} />
          </Field>
          <Field label="Comment notifications">
            <RadioGroup value={digest} onValueChange={setDigest}>
              {(
                [
                  ['immediate', 'Immediately'],
                  ['digest', 'Daily digest'],
                  ['off', 'Off'],
                ] as const
              ).map(([value, label]) => (
                <div key={value} className="flex items-center gap-2.5">
                  <RadioGroupItem value={value} id={`digest-${value}`} />
                  <Label htmlFor={`digest-${value}`} className="font-normal">
                    {label}
                  </Label>
                </div>
              ))}
            </RadioGroup>
          </Field>
        </Specimen>
      </div>
    </DesignSection>
  )
}

export function SegmentedSection() {
  const [view, setView] = useState<'board' | 'list'>('board')
  const [score, setScore] = useState<string | null>('4')
  const [small, setSmall] = useState<string | null>(null)
  const [large, setLarge] = useState<string | null>('3')
  const [recommendation, setRecommendation] = useState<string | null>(null)

  return (
    <DesignSection
      id="segmented"
      title="Segmented control"
      description={
        <>
          Radio semantics with roving focus: <Code>←</Code>/<Code>→</Code> move and select,{' '}
          <Code>Home</Code>/<Code>End</Code> jump, and typing <Code>1</Code>–<Code>5</Code> picks a
          score directly. Hover or focus an option to preview its guidance (the placeholder says
          “Tap” on touch screens, via <Code>SCORE_GUIDANCE_PLACEHOLDER</Code>). 44px tall on touch
          screens.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Specimen title="Scoring (accent)" className="flex flex-col gap-6">
          <Field label="Value">
            <SegmentedControl
              variant="accent"
              options={scoreOptions()}
              value={score}
              onValueChange={setScore}
            />
          </Field>
          <Field label="Recommendation">
            <SegmentedControl
              variant="accent"
              options={[
                { value: 'go', label: 'Go', description: 'Take it forward to a proposal' },
                { value: 'maybe', label: 'Maybe', description: 'Promising, but needs more work' },
                { value: 'no', label: 'No', description: 'Don’t pursue this now' },
              ]}
              value={recommendation}
              onValueChange={setRecommendation}
              guidancePlaceholder="Pick an overall recommendation"
            />
          </Field>
        </Specimen>
        <Specimen title="Sizes & view toggle (neutral)" className="flex flex-col gap-6">
          <Example label="neutral · icons">
            <SegmentedControl
              aria-label="View"
              options={[
                {
                  value: 'board',
                  label: (
                    <>
                      <Columns3 /> Board
                    </>
                  ),
                  ariaLabel: 'Board',
                },
                {
                  value: 'list',
                  label: (
                    <>
                      <List /> List
                    </>
                  ),
                  ariaLabel: 'List',
                },
              ]}
              value={view}
              onValueChange={setView}
            />
          </Example>
          <Example label="size sm">
            <SegmentedControl
              size="sm"
              variant="accent"
              aria-label="Score (small)"
              options={scoreOptions().map(({ value, label }) => ({ value, label }))}
              value={small}
              onValueChange={setSmall}
            />
          </Example>
          <Example label="size lg · fullWidth (phones)" className="w-full">
            <SegmentedControl
              size="lg"
              variant="accent"
              fullWidth
              aria-label="Score (large)"
              options={scoreOptions()}
              value={large}
              onValueChange={setLarge}
            />
          </Example>
        </Specimen>
      </div>
    </DesignSection>
  )
}
