/**
 * CohortBuilder — fully dataset-driven cohort requirement builder.
 *
 * The dataset defines the UI:
 *   - Feature list comes from the uploaded dataset's cohort-profile endpoint.
 *   - Available operators are determined by column kind (numerical / binary /
 *     categorical / ordinal).
 *   - Value controls (number input, dropdown, range) are generated from the
 *     column's actual data.
 *   - No healthcare column names are hard-coded anywhere in this file.
 */
import { useEffect, useState, useId } from 'react'
import { Plus, Trash2, Search, AlertCircle, CheckCircle, ChevronDown } from 'lucide-react'
import { getCohortProfile, extractError } from '../services/api'
import type {
  CohortColumnProfile,
  CohortOperator,
  CohortRequirement,
  CohortRequirementResult,
  ColumnKind,
} from '../types'
import clsx from 'clsx'

// ── Operator definitions per column kind ─────────────────────────────────────

interface OperatorDef {
  value: CohortOperator
  label: string
  needsTwoValues?: boolean  // true for "between"
}

const NUMERICAL_OPS: OperatorDef[] = [
  { value: 'greater_than',          label: '>' },
  { value: 'gte',                   label: '≥' },
  { value: 'less_than',             label: '<' },
  { value: 'lte',                   label: '≤' },
  { value: 'equal',                 label: '=' },
  { value: 'between',               label: 'between', needsTwoValues: true },
]

const CATEGORICAL_OPS: OperatorDef[] = [
  { value: 'equal',    label: '=' },
  { value: 'not_equal', label: '≠' },
]

const MULTI_CAT_OPS: OperatorDef[] = [
  { value: 'equal',      label: '=' },
  { value: 'not_equal',  label: '≠' },
  { value: 'in_values',  label: 'is one of' },
]

function opsForKind(kind: ColumnKind, uniqueCount: number): OperatorDef[] {
  if (kind === 'numerical') return NUMERICAL_OPS
  if (kind === 'binary')    return CATEGORICAL_OPS
  if (kind === 'ordinal')   return [...NUMERICAL_OPS.slice(0, 5), ...CATEGORICAL_OPS]
  // categorical
  return uniqueCount > 2 ? MULTI_CAT_OPS : CATEGORICAL_OPS
}

function defaultOperator(kind: ColumnKind): CohortOperator {
  if (kind === 'numerical') return 'greater_than'
  return 'equal'
}

// ── Tiny UUID helper (no dependency needed) ───────────────────────────────────
function uid() { return Math.random().toString(36).slice(2, 10) }

// ── Validation ────────────────────────────────────────────────────────────────

interface ValidationError { id: string; message: string }

function validateRequirements(
  reqs: CohortRequirement[],
  profileMap: Map<string, CohortColumnProfile>,
): ValidationError[] {
  const errors: ValidationError[] = []

  reqs.forEach(r => {
    const col = profileMap.get(r.feature)
    if (!col) {
      errors.push({ id: r.id, message: `Column "${r.feature}" not found in dataset.` })
      return
    }

    // Target proportion
    const pct = r.target_proportion * 100
    if (pct < 0 || pct > 100 || isNaN(pct)) {
      errors.push({ id: r.id, message: 'Target % must be between 0 and 100.' })
    }

    // Numerical value validation
    if (col.kind === 'numerical') {
      if (r.operator === 'between') {
        const arr = r.value as [number, number]
        if (!Array.isArray(arr) || arr.length !== 2 || isNaN(arr[0]) || isNaN(arr[1])) {
          errors.push({ id: r.id, message: 'Between requires two valid numbers.' })
        } else if (arr[0] >= arr[1]) {
          errors.push({ id: r.id, message: 'Between: lower bound must be less than upper bound.' })
        }
      } else {
        const v = Number(r.value)
        if (isNaN(v)) {
          errors.push({ id: r.id, message: 'Value must be a number for this column.' })
        }
      }
    }

    // Categorical value must exist in dataset
    if ((col.kind === 'binary' || col.kind === 'categorical' || col.kind === 'ordinal')
        && col.unique_values && r.operator !== 'in_values') {
      const v = String(r.value)
      if (!col.unique_values.includes(v)) {
        errors.push({ id: r.id, message: `"${v}" is not a valid value. Choose from: ${col.unique_values.slice(0, 5).join(', ')}…` })
      }
    }
  })

  // Check for contradictory requirements on the same column
  const byFeature = new Map<string, CohortRequirement[]>()
  reqs.forEach(r => {
    const existing = byFeature.get(r.feature) ?? []
    existing.push(r)
    byFeature.set(r.feature, existing)
  })
  byFeature.forEach((group, feature) => {
    if (group.length < 2) return
    const totalPct = group.reduce((s, r) => s + r.target_proportion * 100, 0)
    if (totalPct > 150) {
      group.forEach(r => errors.push({
        id: r.id,
        message: `Multiple requirements for "${feature}" total ${totalPct.toFixed(0)}% — check for contradictions.`,
      }))
    }
  })

  return errors
}

// ── Sub-components ────────────────────────────────────────────────────────────

function FeatureSearch({
  profile,
  selected,
  onSelect,
}: {
  profile: CohortColumnProfile[]
  selected: string
  onSelect: (col: CohortColumnProfile) => void
}) {
  const [open, setOpen]   = useState(false)
  const [query, setQuery] = useState('')

  const kinds: ColumnKind[] = ['numerical', 'binary', 'ordinal', 'categorical']
  const kindLabel: Record<ColumnKind, string> = {
    numerical:   'Numerical',
    binary:      'Binary',
    ordinal:     'Ordinal',
    categorical: 'Categorical',
  }
  const kindColor: Record<ColumnKind, string> = {
    numerical:   'bg-brand-100 text-brand-700',
    binary:      'bg-clinical-100 text-clinical-700',
    ordinal:     'bg-purple-100 text-purple-700',
    categorical: 'bg-amber-100 text-amber-700',
  }

  const filtered = profile.filter(c =>
    c.name.toLowerCase().includes(query.toLowerCase())
  )
  const grouped = kinds.map(k => ({
    kind: k,
    label: kindLabel[k],
    cols: filtered.filter(c => c.kind === k),
  })).filter(g => g.cols.length > 0)

  const selectedCol = profile.find(c => c.name === selected)

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="input flex items-center justify-between gap-2 text-left"
      >
        {selectedCol ? (
          <span className="flex items-center gap-2 min-w-0">
            <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded flex-shrink-0', kindColor[selectedCol.kind])}>
              {kindLabel[selectedCol.kind].slice(0, 3).toUpperCase()}
            </span>
            <span className="truncate text-slate-800">{selectedCol.name}</span>
          </span>
        ) : (
          <span className="text-slate-400">Select a feature…</span>
        )}
        <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-64 flex flex-col">
          <div className="p-2 border-b border-slate-100">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                autoFocus
                type="text"
                placeholder="Search features…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                className="input pl-8 py-1.5 text-xs"
              />
            </div>
          </div>
          <div className="overflow-y-auto flex-1">
            {grouped.length === 0 && (
              <p className="text-xs text-slate-400 p-3 text-center">No matching columns</p>
            )}
            {grouped.map(g => (
              <div key={g.kind}>
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest px-3 pt-2 pb-1">
                  {g.label}
                </p>
                {g.cols.map(col => (
                  <button
                    key={col.name}
                    type="button"
                    onClick={() => { onSelect(col); setOpen(false); setQuery('') }}
                    className={clsx(
                      'w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center gap-2',
                      col.name === selected && 'bg-brand-50 text-brand-700',
                    )}
                  >
                    <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded flex-shrink-0', kindColor[col.kind])}>
                      {g.label.slice(0, 3).toUpperCase()}
                    </span>
                    <span className="truncate">{col.name}</span>
                    {col.kind === 'numerical' && col.min != null && col.max != null && (
                      <span className="text-[11px] text-slate-400 ml-auto flex-shrink-0">
                        {col.min}–{col.max}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ValueControl({
  col,
  operator,
  value,
  onChange,
}: {
  col: CohortColumnProfile
  operator: CohortOperator
  value: CohortRequirement['value']
  onChange: (v: CohortRequirement['value']) => void
}) {
  if (col.kind === 'numerical') {
    if (operator === 'between') {
      const arr = (Array.isArray(value) ? value : [col.min ?? 0, col.max ?? 100]) as [number, number]
      return (
        <div className="flex items-center gap-1.5">
          <input
            type="number" className="input w-24"
            placeholder="min"
            value={arr[0]}
            onChange={e => onChange([Number(e.target.value), arr[1]])}
          />
          <span className="text-xs text-slate-400">and</span>
          <input
            type="number" className="input w-24"
            placeholder="max"
            value={arr[1]}
            onChange={e => onChange([arr[0], Number(e.target.value)])}
          />
        </div>
      )
    }
    return (
      <input
        type="number" className="input"
        placeholder={col.min != null ? `${col.min}–${col.max}` : 'value'}
        value={value as number ?? ''}
        onChange={e => onChange(e.target.value === '' ? '' as unknown as number : Number(e.target.value))}
      />
    )
  }

  // Ordinal with numeric operators → numeric input
  if (col.kind === 'ordinal' && ['greater_than','gt','less_than','lt','gte','lte','equal','eq'].includes(operator)) {
    // If all unique values are numeric-like, show a number input
    const allNumeric = col.unique_values?.every(v => !isNaN(Number(v)))
    if (allNumeric) {
      return (
        <input
          type="number" className="input"
          value={value as number ?? ''}
          onChange={e => onChange(Number(e.target.value))}
        />
      )
    }
  }

  if (operator === 'in_values') {
    // Multi-select for categorical
    const selected = Array.isArray(value) ? (value as string[]) : []
    const opts = col.unique_values ?? []
    return (
      <div className="flex flex-wrap gap-1">
        {opts.map(opt => (
          <button
            key={opt}
            type="button"
            onClick={() => {
              const next = selected.includes(opt)
                ? selected.filter(v => v !== opt)
                : [...selected, opt]
              onChange(next)
            }}
            className={clsx(
              'px-2 py-0.5 rounded-full text-xs border transition-colors',
              selected.includes(opt)
                ? 'bg-brand-600 text-white border-brand-600'
                : 'border-slate-300 text-slate-600 hover:border-brand-400',
            )}
          >
            {opt}
          </button>
        ))}
      </div>
    )
  }

  // Single-value dropdown from actual unique values
  const opts = col.ordinal_order ?? col.unique_values ?? []
  return (
    <select
      className="input"
      value={value as string ?? ''}
      onChange={e => onChange(e.target.value)}
    >
      <option value="">Select value…</option>
      {opts.map(opt => (
        <option key={opt} value={opt}>{opt}</option>
      ))}
    </select>
  )
}

function RequirementCard({
  req,
  profile,
  error,
  onChange,
  onRemove,
}: {
  req: CohortRequirement
  profile: CohortColumnProfile[]
  error?: string
  onChange: (updated: CohortRequirement) => void
  onRemove: () => void
}) {
  const profileMap = new Map(profile.map(c => [c.name, c]))
  const col = profileMap.get(req.feature)
  const ops = col ? opsForKind(col.kind, col.unique_values?.length ?? col.unique_count ?? 0) : NUMERICAL_OPS

  function update(patch: Partial<CohortRequirement>) {
    onChange({ ...req, ...patch })
  }

  function onFeatureSelect(newCol: CohortColumnProfile) {
    const op = defaultOperator(newCol.kind)
    const val = newCol.kind === 'numerical'
      ? (newCol.min ?? 0)
      : (newCol.ordinal_order?.[0] ?? newCol.unique_values?.[0] ?? '')
    update({ feature: newCol.name, operator: op, value: val })
  }

  return (
    <div className={clsx(
      'card p-4 space-y-3',
      error ? 'border-red-200 bg-red-50/30' : '',
    )}>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1fr_auto] gap-2 items-start">
        {/* Feature selector */}
        <FeatureSearch profile={profile} selected={req.feature} onSelect={onFeatureSelect} />

        {/* Operator */}
        <select
          className="input sm:w-28"
          value={req.operator}
          onChange={e => update({ operator: e.target.value as CohortOperator, value: col?.kind === 'numerical' ? (col.min ?? 0) : (col?.unique_values?.[0] ?? '') })}
        >
          {ops.map(op => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </select>

        {/* Value control */}
        {col ? (
          <ValueControl
            col={col}
            operator={req.operator}
            value={req.value}
            onChange={val => update({ value: val })}
          />
        ) : (
          <input className="input" placeholder="Select a feature first" disabled />
        )}

        {/* Remove */}
        <button
          type="button"
          onClick={onRemove}
          className="p-2 text-slate-400 hover:text-red-500 transition-colors rounded-lg hover:bg-red-50 mt-0.5 flex-shrink-0"
          title="Remove requirement"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Target proportion */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-500 whitespace-nowrap">Target proportion</label>
        <input
          type="number" min={0} max={100} step={1}
          className="input w-24"
          placeholder="e.g. 40"
          value={req.target_proportion * 100 || ''}
          onChange={e => {
            const v = e.target.value === '' ? 0 : Number(e.target.value)
            update({ target_proportion: v / 100 })
          }}
        />
        <span className="text-xs text-slate-400">%</span>
        <span className="text-xs text-slate-400">
          ≈ {Math.round(req.target_proportion * 100)}% of generated records will satisfy this condition
        </span>
      </div>

      {error && (
        <div className="flex items-center gap-1.5 text-xs text-red-600">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          {error}
        </div>
      )}
    </div>
  )
}

// ── Post-generation report ────────────────────────────────────────────────────

export function CohortReport({ results }: { results: CohortRequirementResult[] }) {
  if (!results || results.length === 0) return null
  return (
    <div>
      <p className="text-xs font-semibold text-slate-500 mb-2">Cohort accuracy</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 text-slate-500 uppercase tracking-wide">
              <th className="px-3 py-2 text-left">Requirement</th>
              <th className="px-3 py-2 text-right">Requested</th>
              <th className="px-3 py-2 text-right">Generated</th>
              <th className="px-3 py-2 text-right">Diff</th>
              <th className="px-3 py-2 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {results.map((r, i) => (
              <tr key={i}>
                <td className="px-3 py-2 text-slate-700 font-medium max-w-[180px] truncate" title={r.label}>{r.label}</td>
                <td className="px-3 py-2 text-right">{r.requested_pct?.toFixed(1)}%</td>
                <td className="px-3 py-2 text-right">{r.generated_pct?.toFixed(1) ?? '—'}%</td>
                <td className={`px-3 py-2 text-right font-semibold ${(r.diff_pct ?? 0) > 5 ? 'text-amber-600' : 'text-clinical-600'}`}>
                  {r.diff_pct != null ? `${r.diff_pct.toFixed(1)}pp` : '—'}
                </td>
                <td className="px-3 py-2 text-center">
                  {r.status === 'pass'
                    ? <CheckCircle className="w-3.5 h-3.5 text-clinical-500 inline" />
                    : r.status === 'warn'
                    ? <AlertCircle className="w-3.5 h-3.5 text-amber-500 inline" />
                    : <span className="text-slate-400">—</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main CohortBuilder export ─────────────────────────────────────────────────

interface Props {
  datasetId: string
  requirements: CohortRequirement[]
  onChange: (reqs: CohortRequirement[]) => void
  errors: ValidationError[]
}

export default function CohortBuilder({ datasetId, requirements, onChange, errors }: Props) {
  const [profile, setProfile]   = useState<CohortColumnProfile[]>([])
  const [loading, setLoading]   = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!datasetId) return
    setLoading(true)
    setLoadError(null)
    getCohortProfile(datasetId)
      .then(resp => setProfile(resp.columns))
      .catch(e => setLoadError(extractError(e)))
      .finally(() => setLoading(false))
  }, [datasetId])

  const errorMap = new Map(errors.map(e => [e.id, e.message]))

  function addRequirement() {
    if (profile.length === 0) return
    const firstNumeric = profile.find(c => c.kind === 'numerical') ?? profile[0]
    const op = defaultOperator(firstNumeric.kind)
    const val = firstNumeric.kind === 'numerical'
      ? (firstNumeric.min ?? 0)
      : (firstNumeric.ordinal_order?.[0] ?? firstNumeric.unique_values?.[0] ?? '')
    onChange([...requirements, {
      id:                uid(),
      feature:           firstNumeric.name,
      operator:          op,
      value:             val,
      target_proportion: 0.3,
    }])
  }

  function updateRequirement(id: string, updated: CohortRequirement) {
    onChange(requirements.map(r => r.id === id ? updated : r))
  }

  function removeRequirement(id: string) {
    onChange(requirements.filter(r => r.id !== id))
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 py-3">
        <span className="w-4 h-4 border-2 border-slate-200 border-t-brand-500 rounded-full animate-spin" />
        Analysing dataset columns…
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="text-xs text-red-600 flex items-center gap-1.5">
        <AlertCircle className="w-3.5 h-3.5" /> {loadError}
      </div>
    )
  }

  if (profile.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        Preprocess the dataset first to enable cohort customisation.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {requirements.length === 0 && (
        <p className="text-xs text-slate-400 italic">
          No requirements added. Click "+ Add Requirement" to define cohort constraints.
        </p>
      )}

      {requirements.map(req => (
        <RequirementCard
          key={req.id}
          req={req}
          profile={profile}
          error={errorMap.get(req.id)}
          onChange={updated => updateRequirement(req.id, updated)}
          onRemove={() => removeRequirement(req.id)}
        />
      ))}

      <button
        type="button"
        onClick={addRequirement}
        className="btn-secondary text-sm"
      >
        <Plus className="w-4 h-4" /> Add Requirement
      </button>

      {/* Column legend */}
      <div className="flex flex-wrap gap-3 pt-1">
        {[
          { kind: 'numerical',   label: 'Numerical',   cls: 'bg-brand-100 text-brand-700' },
          { kind: 'binary',      label: 'Binary',      cls: 'bg-clinical-100 text-clinical-700' },
          { kind: 'ordinal',     label: 'Ordinal',     cls: 'bg-purple-100 text-purple-700' },
          { kind: 'categorical', label: 'Categorical', cls: 'bg-amber-100 text-amber-700' },
        ].map(({ kind, label, cls }) => {
          const count = profile.filter(c => c.kind === kind).length
          if (count === 0) return null
          return (
            <span key={kind} className={`text-[10px] font-bold px-2 py-0.5 rounded ${cls}`}>
              {label} ({count})
            </span>
          )
        })}
      </div>
    </div>
  )
}

export { validateRequirements }
export type { ValidationError }
