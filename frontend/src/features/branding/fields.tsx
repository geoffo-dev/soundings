import { CircleAlert, ImagePlus, TriangleAlert, Upload } from 'lucide-react'
import { useEffect, useId, useRef, useState, type DragEvent, type ReactNode } from 'react'

import { imageContentType, useUploadBrandAsset, type BrandingScope } from '@/api/branding'
import type { BrandAsset, BrandAssetKind, BrandFont } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { BRAND_FONT_KEYS, BRAND_FONTS, loadBrandFont, setElementProperties } from '@/lib/branding'
import { cn } from '@/lib/utils'

import { HEX_COLOUR_ERROR, normaliseHex, uploadErrorMessage } from './branding-form'
import type { ColourAdvice } from './contrast'

/** A colour chip painted from a validated hex value (set as a style property, never as CSS text). */
export function Swatch({ hex, className }: { hex: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const element = ref.current
    const color = normaliseHex(hex)
    if (!element || !color) return
    return setElementProperties(element, { 'background-color': color })
  }, [hex])
  return (
    <span
      ref={ref}
      aria-hidden="true"
      className={cn('inline-block size-5 shrink-0 rounded-sm border border-strong', className)}
    />
  )
}

/** Curated starting points; any hex works. */
const PRESETS: { hex: string; name: string }[] = [
  { hex: '#1d5fa8', name: 'Ocean' },
  { hex: '#0f766e', name: 'Teal' },
  { hex: '#2e7d4f', name: 'Forest' },
  { hex: '#4338ca', name: 'Indigo' },
  { hex: '#7e22ce', name: 'Plum' },
  { hex: '#b42318', name: 'Brick' },
  { hex: '#b45309', name: 'Amber' },
  { hex: '#3f3f46', name: 'Graphite' },
]

/**
 * A brand colour: the system picker, a hex field and preset swatches, with
 * contrast advice. Empty = inherit (shown as "Default" with the inherited value).
 */
export function ColorField({
  id,
  label,
  description,
  value,
  inherited,
  inheritedLabel,
  resetLabel,
  onChange,
  error,
  advice,
}: {
  id: string
  label: string
  description: ReactNode
  value: string
  inherited: string
  /** Next to an empty field: where the value comes from ("Default"). */
  inheritedLabel: string
  /** The button that empties the field ("Use the default"). */
  resetLabel: string
  onChange: (value: string) => void
  error?: string
  advice: (hex: string) => ColourAdvice
}) {
  const effective = normaliseHex(value) ?? inherited
  const inheriting = !value.trim()
  const tip = advice(effective)
  // Checked when you leave the field (not while typing "#1d5f…"): until then the
  // preview shows the inherited colour, and this says why.
  const [checked, setChecked] = useState(false)
  const invalid = checked && !inheriting && !normaliseHex(value)
  const change = (next: string) => {
    setChecked(false)
    onChange(next)
  }
  return (
    <Field
      label={label}
      error={error ?? (invalid ? HEX_COLOUR_ERROR : undefined)}
      id={id}
      description={
        <span className="flex flex-col gap-1">
          <span>{description}</span>
          <span
            data-testid={`${id}-advice`}
            className={cn('flex items-start gap-1.5', tip.tone === 'warning' && 'text-warning')}
          >
            {tip.tone === 'warning' && (
              <TriangleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            )}
            <span>{tip.message}</span>
          </span>
        </span>
      }
    >
      <div className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="color"
            aria-label={`${label}: open the colour picker`}
            value={effective}
            onChange={(event) => change(event.target.value)}
            className="size-9 shrink-0 cursor-pointer rounded-md border border-input bg-surface p-0.5 sm:size-8"
          />
          <Input
            value={value}
            placeholder={inherited}
            maxLength={7}
            autoComplete="off"
            spellCheck={false}
            className="w-32 font-mono"
            onChange={(event) => change(event.target.value)}
            onBlur={() => {
              const hex = normaliseHex(value)
              if (hex && hex !== value) onChange(hex)
              setChecked(true)
            }}
          />
          {inheriting ? (
            <span className="text-sm text-muted">{inheritedLabel}</span>
          ) : (
            <Button type="button" variant="ghost" size="sm" onClick={() => change('')}>
              {resetLabel}
            </Button>
          )}
        </div>
        <div role="group" aria-label={`${label} presets`} className="flex flex-wrap gap-1.5">
          {PRESETS.map((preset) => {
            const selected = effective === preset.hex
            return (
              <button
                key={preset.hex}
                type="button"
                aria-label={`${preset.name} (${preset.hex})`}
                aria-pressed={selected}
                title={preset.name}
                onClick={() => change(preset.hex)}
                className={cn(
                  'flex size-8 items-center justify-center rounded-md border border-transparent transition-colors hover:border-strong pointer-coarse:size-10',
                  selected && 'border-control bg-subtle',
                )}
              >
                <Swatch hex={preset.hex} className="size-5 border-transparent" />
              </button>
            )
          })}
        </div>
      </div>
    </Field>
  )
}

/** The largest upload the API can be configured to take (900 KiB); its own limit decides. */
const HARD_MAX_KB = 900
const DEFAULT_MAX_KB = 512

/**
 * A logo or favicon: drop a file or choose one (PNG or SVG). It uploads at
 * once (the API checks and re-encodes it) and becomes part of the form; Save
 * makes it live. Shown only through `<img>`, never inline.
 */
export function ImageField({
  kind,
  label,
  description,
  value,
  inheritedUrl,
  emptyText,
  inheritedText,
  resetLabel,
  scope,
  onChange,
  error,
  disabled = false,
}: {
  kind: BrandAssetKind
  label: string
  description: string
  value: BrandAsset | null
  inheritedUrl: string | null
  emptyText: string
  /** Shown while the inherited image is in use ("Using the default"). */
  inheritedText: string
  /** Drops this profile's image for the inherited one ("Use the default"). */
  resetLabel: string
  scope: BrandingScope
  onChange: (asset: BrandAsset | null) => void
  error?: string
  disabled?: boolean
}) {
  const upload = useUploadBrandAsset(scope)
  const [problem, setProblem] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const labelId = useId()
  const shown = value?.url ?? inheritedUrl
  const message = problem ?? error

  const accept = (file: File | undefined) => {
    if (!file || disabled) return
    setProblem(null)
    if (!imageContentType(file)) {
      setProblem('Choose a PNG or SVG file.')
      return
    }
    if (file.size > HARD_MAX_KB * 1024) {
      setProblem(`That file is larger than ${DEFAULT_MAX_KB} KB.`)
      return
    }
    upload.mutate(
      { kind, file },
      {
        onSuccess: (asset) => onChange(asset),
        onError: (failure) => setProblem(uploadErrorMessage(failure, DEFAULT_MAX_KB)),
      },
    )
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    accept(event.dataTransfer.files[0])
  }

  return (
    <div role="group" aria-labelledby={labelId} className="flex flex-col gap-1.5">
      <span id={labelId} className="text-sm font-medium text-primary">
        {label}
      </span>
      <div
        data-dragging={dragging || undefined}
        onDragOver={(event) => {
          event.preventDefault()
          if (!disabled) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'flex items-center gap-3 rounded-lg border border-dashed border-input p-3 transition-colors',
          'data-dragging:border-accent data-dragging:bg-accent-subtle',
          message && 'border-danger',
        )}
      >
        <span
          className={cn(
            'flex h-14 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-background',
            kind === 'logo' ? 'w-24' : 'w-14',
          )}
        >
          {shown ? (
            <img
              src={shown}
              alt={value ? `The ${kind} you chose` : `The current ${kind}`}
              className={cn(
                'object-contain',
                kind === 'favicon' ? 'size-8' : 'logo-plate max-h-10 max-w-20',
              )}
            />
          ) : (
            <ImagePlus aria-hidden="true" className="size-5 text-muted" />
          )}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <p className="text-sm text-secondary">
            {value ? assetSummary(value) : inheritedUrl ? inheritedText : emptyText}
          </p>
          <div className="flex flex-wrap items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              loading={upload.isPending}
              disabled={disabled}
              onClick={() => input.current?.click()}
            >
              <Upload aria-hidden="true" />
              {value || inheritedUrl ? 'Replace…' : 'Choose a file…'}
            </Button>
            {value && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={disabled}
                onClick={() => {
                  setProblem(null)
                  onChange(null)
                }}
              >
                {inheritedUrl ? resetLabel : 'Remove'}
              </Button>
            )}
          </div>
          <span className="text-xs text-muted pointer-coarse:hidden">or drop a file here</span>
        </div>
        <input
          ref={input}
          type="file"
          accept="image/png,image/svg+xml,.png,.svg"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => {
            accept(event.target.files?.[0])
            event.target.value = ''
          }}
        />
      </div>
      <p className="text-sm text-muted">{description}</p>
      {message && (
        <p role="alert" className="flex items-start gap-1.5 text-sm text-danger">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>{message}</span>
        </p>
      )}
    </div>
  )
}

function assetSummary(asset: BrandAsset): string {
  const type = asset.content_type === 'image/svg+xml' ? 'SVG' : 'PNG'
  const size = asset.width && asset.height ? ` · ${asset.width} × ${asset.height}` : ''
  const kb = Math.max(1, Math.round(asset.byte_size / 1024))
  return `${type}${size} · ${kb} KB`
}

/** A sample of a bundled font, painted in it (the family comes from the fixed map). */
function FontSample({ font }: { font: BrandFont }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    void loadBrandFont(font)
    if (!ref.current) return
    return setElementProperties(ref.current, {
      'font-family': `"${BRAND_FONTS[font].family}", ui-sans-serif, system-ui, sans-serif`,
    })
  }, [font])
  return (
    <span ref={ref} aria-hidden="true" className="text-lg text-primary">
      Share an idea
    </span>
  )
}

/** The bundled fonts as cards, each shown in itself. */
export function FontField({
  value,
  inherited,
  inheritedName,
  onChange,
  description,
}: {
  value: BrandFont | null
  inherited: BrandFont
  /** What the inherited value is called: "default", or "global" for a project. */
  inheritedName: string
  onChange: (font: BrandFont | null) => void
  description: string
}) {
  const current = value ?? inherited
  const labelId = useId()
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span id={labelId} className="text-sm font-medium text-primary">
          Font
        </span>
        {value && value !== inherited && (
          <Button type="button" variant="link" size="sm" onClick={() => onChange(null)}>
            Use the {inheritedName} font ({BRAND_FONTS[inherited].label})
          </Button>
        )}
      </div>
      <RadioGroup
        aria-labelledby={labelId}
        value={current}
        onValueChange={(next) => onChange(next as BrandFont)}
        className="grid gap-2 sm:grid-cols-2"
      >
        {BRAND_FONT_KEYS.map((font) => (
          <label
            key={font}
            htmlFor={`font-${font}`}
            className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent"
          >
            <RadioGroupItem
              id={`font-${font}`}
              value={font}
              className="mt-1"
              aria-describedby={`font-${font}-note`}
            />
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-medium text-primary">
                {BRAND_FONTS[font].label}
                {font === inherited && !value && (
                  <span className="font-normal text-muted"> · {inheritedName}</span>
                )}
              </span>
              <FontSample font={font} />
              <span id={`font-${font}-note`} className="text-xs text-muted">
                {BRAND_FONTS[font].note}
              </span>
            </span>
          </label>
        ))}
      </RadioGroup>
      <p className="text-sm text-muted">{description}</p>
    </div>
  )
}
