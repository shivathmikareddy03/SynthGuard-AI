import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  Upload as UploadIcon, CheckCircle, ArrowRight, X,
  Eye, EyeOff, FlaskConical, ShieldAlert, ShieldCheck,
  ChevronDown, ChevronUp, AlertTriangle, HeartPulse,
  Link, Calendar, Users,
} from 'lucide-react'
import clsx from 'clsx'
import { uploadDataset, uploadDemoDataset, preprocessDataset, extractError } from '../services/api'
import { useStore } from '../store'
import type { ColumnInfo, DatasetProfile } from '../types'

type ColCategory = 'direct' | 'linkage' | 'temporal' | 'quasi' | 'health' | 'clinical'

export default function Upload() {
  const navigate = useNavigate()
  const { setDataset, setPreprocessing } = useStore()

  const [profile, setProfile]               = useState<DatasetProfile | null>(null)
  const [uploading, setUploading]           = useState(false)
  const [preprocessing, setPreprocessingState] = useState(false)
  const [excludedCols, setExcludedCols]     = useState<Set<string>>(new Set())
  const [privacyOpen, setPrivacyOpen]       = useState(false)

  function applyProfile(data: DatasetProfile) {
    setProfile(data)
    setDataset(data)
    // Pre-exclude ONLY direct personal identifiers and longitudinal linkage keys.
    // Linkage keys are excluded because they must never be modeled — but they are
    // NOT direct personal identifiers.
    const pc = data.privacy_classification
    const toExclude = new Set([
      ...data.sensitive_columns,                    // direct identifiers
      ...(pc?.longitudinal_linkage_keys ?? []),     // linkage keys
    ])
    setExcludedCols(toExclude)
  }

  const onDrop = useCallback(async (files: File[]) => {
    const file = files[0]
    if (!file) return
    setUploading(true)
    try {
      const data = await uploadDataset(file)
      applyProfile(data)
      toast.success(`Uploaded: ${data.num_rows.toLocaleString()} rows × ${data.num_columns} columns`)
    } catch (e) { toast.error(extractError(e)) }
    finally { setUploading(false) }
  }, [setDataset]) // eslint-disable-line

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    },
    maxFiles: 1,
    disabled: uploading,
  })

  async function loadDemo() {
    setUploading(true)
    try {
      const data = await uploadDemoDataset()
      applyProfile(data)
      toast.success('Demo dataset loaded — 2,000 de-identified records')
    } catch (e) { toast.error(extractError(e)) }
    finally { setUploading(false) }
  }

  function toggleExclude(col: string) {
    setExcludedCols(prev => {
      const next = new Set(prev)
      next.has(col) ? next.delete(col) : next.add(col)
      return next
    })
  }

  async function handlePreprocess() {
    if (!profile) return
    const approved = profile.columns.map(c => c.name).filter(n => !excludedCols.has(n))
    if (approved.length < 2) { toast.error('Select at least 2 columns for modeling.'); return }
    setPreprocessingState(true)
    try {
      const result = await preprocessDataset(profile.id, approved, {})
      setPreprocessing(result)
      toast.success(`Preprocessing complete — ${result.rows_after.toLocaleString()} rows ready`)
      navigate('/generate')
    } catch (e) { toast.error(extractError(e)) }
    finally { setPreprocessingState(false) }
  }

  const approvedCount = profile ? profile.columns.length - excludedCols.size : 0
  const pc  = profile?.privacy_classification
  const lon = profile?.longitudinal_info

  function colCategory(name: string): ColCategory {
    if (!pc) return 'clinical'
    if (pc.direct_identifiers.includes(name))          return 'direct'
    if (pc.longitudinal_linkage_keys.includes(name))   return 'linkage'
    if (pc.temporal_columns.includes(name))            return 'temporal'
    if (pc.quasi_identifiers.includes(name))           return 'quasi'
    if (pc.sensitive_health_attributes.includes(name)) return 'health'
    return 'clinical'
  }

  // Privacy pill: what to show in the compact badge
  const hasDirectIds    = (pc?.direct_identifiers.length ?? 0) > 0
  const hasLinkageKeys  = (pc?.longitudinal_linkage_keys.length ?? 0) > 0
  const isLongitudinal  = lon?.is_longitudinal === true

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="page-title">Upload Dataset</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Upload a de-identified healthcare dataset in CSV or Excel format.
        </p>
      </div>

      {/* ── Upload zone ── */}
      {!profile && (
        <div className="space-y-4">
          <div
            {...getRootProps()}
            className={clsx(
              'card border-2 border-dashed p-12 text-center cursor-pointer transition-colors',
              isDragActive ? 'border-brand-400 bg-brand-50' : 'border-slate-300 hover:border-brand-300 hover:bg-slate-50',
              uploading && 'opacity-50 cursor-not-allowed',
            )}
          >
            <input {...getInputProps()} />
            <div className="flex flex-col items-center gap-3">
              <div className="w-14 h-14 rounded-2xl bg-brand-50 flex items-center justify-center">
                <UploadIcon className="w-7 h-7 text-brand-600" />
              </div>
              <div>
                <p className="text-base font-semibold text-slate-700">
                  {isDragActive ? 'Drop the file here' : 'Drag & drop or click to upload'}
                </p>
                <p className="text-sm text-slate-400 mt-1">Supports .csv and .xlsx — max 50 MB</p>
              </div>
              {uploading && <p className="text-sm text-brand-600 font-medium">Uploading…</p>}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <hr className="flex-1 border-slate-200" />
            <span className="text-xs text-slate-400">or</span>
            <hr className="flex-1 border-slate-200" />
          </div>

          <button onClick={loadDemo} disabled={uploading} className="btn-secondary w-full py-3 justify-center">
            <FlaskConical className="w-4 h-4" />
            Use Demo Dataset (2,000 de-identified synthetic patients)
          </button>
        </div>
      )}

      {/* ── Profile view ── */}
      {profile && pc && (
        <div className="space-y-5">

          {/* ── Compact dataset overview card ── */}
          <div className="card p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] text-slate-400 uppercase tracking-wide mb-1">Dataset</p>
                <p className="font-semibold text-slate-800 truncate max-w-xs">{profile.filename}</p>
              </div>
              <button
                onClick={() => { setProfile(null); setDataset(null) }}
                className="btn-secondary text-xs flex-shrink-0"
              >
                <X className="w-3.5 h-3.5" /> Change
              </button>
            </div>

            {/* Stats + privacy badge row */}
            <div className="mt-4 flex flex-wrap gap-6 items-end">
              <Stat label="Records"  value={profile.num_rows.toLocaleString()} />
              <Stat label="Columns"  value={profile.num_columns} />
              <Stat label="For modeling" value={approvedCount} />
              {isLongitudinal && lon && (
                <Stat label="Unique patients" value={lon.unique_subjects.toLocaleString()} />
              )}

              {/* Compact privacy status pill */}
              <div>
                <p className="text-[11px] text-slate-400 uppercase tracking-wide mb-1">Privacy</p>
                <button
                  onClick={() => setPrivacyOpen(v => !v)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 border transition-colors',
                    hasDirectIds
                      ? 'text-blue-700 bg-blue-50 border-blue-200 hover:bg-blue-100'
                      : 'text-clinical-700 bg-clinical-50 border-clinical-200 hover:bg-clinical-100',
                  )}
                >
                  {hasDirectIds
                    ? <><ShieldCheck className="w-3 h-3" />{pc.direct_identifiers.length} removed before modeling</>
                    : <><ShieldCheck className="w-3 h-3" />Screened ✓</>
                  }
                </button>
              </div>

              {/* Longitudinal badge (separate from privacy) */}
              {lon && (
                <div>
                  <p className="text-[11px] text-slate-400 uppercase tracking-wide mb-1">Structure</p>
                  <span className={clsx(
                    'inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 border',
                    isLongitudinal
                      ? 'text-purple-700 bg-purple-50 border-purple-200'
                      : 'text-slate-600 bg-slate-50 border-slate-200',
                  )}>
                    {isLongitudinal
                      ? <><Users className="w-3 h-3" />Longitudinal</>
                      : <><Users className="w-3 h-3" />Cross-sectional</>
                    }
                  </span>
                </div>
              )}
            </div>

            {/* ── Collapsible privacy + longitudinal details ── */}
            {privacyOpen && (
              <div className="mt-4 pt-4 border-t border-slate-100 space-y-4">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                    Data Classification
                  </p>
                  <button onClick={() => setPrivacyOpen(false)} className="text-slate-400 hover:text-slate-600">
                    <ChevronUp className="w-4 h-4" />
                  </button>
                </div>

                {/* ── Longitudinal linkage section (separate from identifiers) ── */}
                {hasLinkageKeys && (
                  <div className="rounded-lg bg-purple-50 border border-purple-100 p-3 space-y-2">
                    <div className="flex items-center gap-1.5">
                      <Link className="w-3.5 h-3.5 text-purple-500" />
                      <p className="text-xs font-semibold text-purple-700">Longitudinal linkage key</p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {pc.longitudinal_linkage_keys.map(k => (
                        <span key={k} className="text-xs px-2 py-0.5 rounded-full font-medium text-purple-700 bg-purple-100">
                          {k}
                        </span>
                      ))}
                    </div>
                    {isLongitudinal && lon ? (
                      <p className="text-[11px] text-purple-600">
                        Used to group {lon.unique_subjects.toLocaleString()} patients across{' '}
                        {lon.total_observations.toLocaleString()} observations
                        (avg {lon.avg_obs_per_subject} obs/patient).
                        Excluded from modeling. Original IDs never appear in synthetic output.
                      </p>
                    ) : (
                      <p className="text-[11px] text-purple-600">
                        Used only for grouping. Excluded from synthetic-data modeling.
                        Original IDs never appear in synthetic output.
                      </p>
                    )}
                  </div>
                )}

                {/* Temporal columns */}
                {pc.temporal_columns.length > 0 && (
                  <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-2">
                    <div className="flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5 text-slate-500" />
                      <p className="text-xs font-semibold text-slate-600">Date / time columns</p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {pc.temporal_columns.map(k => (
                        <span key={k} className="text-xs px-2 py-0.5 rounded-full font-medium text-slate-600 bg-slate-200">
                          {k}
                        </span>
                      ))}
                    </div>
                    <p className="text-[11px] text-slate-400">
                      Converted to ordinal integers before training.
                    </p>
                  </div>
                )}

                {/* 3-column privacy grid */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <PrivacyDetailBlock
                    label="Direct personal identifiers"
                    items={pc.direct_identifiers}
                    emptyText="None detected"
                    icon={<ShieldAlert className="w-3.5 h-3.5 text-red-500" />}
                    itemClass="text-red-700 bg-red-50"
                    note="Excluded from modeling."
                  />
                  <PrivacyDetailBlock
                    label="Quasi-identifiers"
                    items={pc.quasi_identifiers}
                    emptyText="None detected"
                    icon={<AlertTriangle className="w-3.5 h-3.5 text-amber-500" />}
                    itemClass="text-amber-700 bg-amber-50"
                    note="May contribute to re-identification when combined."
                  />
                  <PrivacyDetailBlock
                    label="Clinical attributes"
                    items={pc.sensitive_health_attributes}
                    emptyText="None"
                    icon={<HeartPulse className="w-3.5 h-3.5 text-blue-500" />}
                    itemClass="text-blue-700 bg-blue-50"
                    note="Medical variables included in modeling."
                  />
                </div>

                <p className="text-[11px] text-slate-400">
                  Basic screening only — not a formal privacy audit.
                </p>
              </div>
            )}

            {!privacyOpen && (
              <button
                onClick={() => setPrivacyOpen(true)}
                className="mt-3 flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors"
              >
                <ChevronDown className="w-3.5 h-3.5" /> View data classification
              </button>
            )}
          </div>

          {/* ── Direct identifiers: acceptance notice (not rejection) ── */}
          {hasDirectIds && (
            <div className="card border-blue-200 bg-blue-50 p-4 flex gap-3">
              <ShieldCheck className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-blue-800">
                  Potentially identifying columns detected — automatically removed before modeling
                </p>
                <p className="text-sm text-blue-700 mt-1">
                  The uploaded dataset contains personal identifiers:{' '}
                  <span className="font-mono">{pc.direct_identifiers.join(', ')}</span>.{' '}
                  These columns are <strong>automatically removed from the modeling dataset</strong>{' '}
                  before synthetic-data generation. They are never passed to CTGAN and never appear
                  in the synthetic output. Identifiers are removed or pseudonymized before modeling —
                  this does not guarantee complete anonymization.
                </p>
              </div>
            </div>
          )}

          {/* ── Longitudinal linkage notice ── */}
          {hasLinkageKeys && (
            <div className="card border-purple-200 bg-purple-50 p-4 flex gap-3">
              <Link className="w-4 h-4 text-purple-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-purple-800">
                  {isLongitudinal ? 'Longitudinal linkage detected' : 'Patient linkage key detected'}
                </p>
                <p className="text-sm text-purple-700 mt-0.5">
                  Linkage key: <span className="font-mono">{pc.longitudinal_linkage_keys.join(', ')}</span>.{' '}
                  {isLongitudinal && lon
                    ? `${lon.unique_subjects.toLocaleString()} patients · ${lon.avg_obs_per_subject} observations/patient average. `
                    : ''}
                  Patient-level identifiers are pseudonymized internally to preserve longitudinal
                  timeline grouping. Original identifiers are not used by the synthetic-data model
                  and will never appear in the synthetic output.
                </p>
              </div>
            </div>
          )}

          {/* ── Column table ── */}
          <div className="card">
            <div className="card-header">
              <h2 className="section-title">Column Selection</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {approvedCount} of {profile.num_columns} columns selected for modeling
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                    <th className="px-4 py-2.5 text-left">Include</th>
                    <th className="px-4 py-2.5 text-left">Column</th>
                    <th className="px-4 py-2.5 text-left">Type</th>
                    <th className="px-4 py-2.5 text-right">Missing</th>
                    <th className="px-4 py-2.5 text-right">Unique</th>
                    <th className="px-4 py-2.5 text-left">Sample</th>
                    <th className="px-4 py-2.5 text-left">Category</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {profile.columns.map((col: ColumnInfo) => {
                    const excluded = excludedCols.has(col.name)
                    const cat      = colCategory(col.name)
                    // Linkage keys and direct identifiers are locked out
                    const locked   = cat === 'direct' || cat === 'linkage'
                    return (
                      <tr key={col.name} className={clsx(excluded && 'opacity-40 bg-slate-50/50')}>
                        <td className="px-4 py-2.5">
                          <input
                            type="checkbox"
                            checked={!excluded}
                            onChange={() => !locked && toggleExclude(col.name)}
                            disabled={locked}
                            title={locked ? 'This column is excluded from modeling' : undefined}
                            className="w-4 h-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500 disabled:opacity-40 disabled:cursor-not-allowed"
                          />
                        </td>
                        <td className="px-4 py-2.5 font-medium text-slate-800">{col.name}</td>
                        <td className="px-4 py-2.5">
                          <span className="badge-gray">{col.dtype}</span>
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          {col.missing_count > 0
                            ? <span className="text-amber-600 text-xs">{col.missing_pct.toFixed(1)}%</span>
                            : <span className="text-clinical-600 text-xs">—</span>
                          }
                        </td>
                        <td className="px-4 py-2.5 text-right text-slate-400 text-xs">
                          {col.unique_count}
                        </td>
                        <td className="px-4 py-2.5 text-slate-400 text-xs max-w-[160px] truncate">
                          {col.sample_values.slice(0, 3).join(', ')}
                        </td>
                        <td className="px-4 py-2.5">
                          <ColCategoryBadge category={cat} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Actions ── */}
          <div className="flex items-center justify-between pt-1">
            <p className="text-sm text-slate-400">{approvedCount} columns selected for modeling</p>
            <button
              onClick={handlePreprocess}
              disabled={preprocessing || approvedCount < 2}
              className="btn-primary px-6 py-2.5"
            >
              {preprocessing ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Preprocessing…
                </>
              ) : (
                <>
                  <CheckCircle className="w-4 h-4" />
                  Confirm & Continue
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-[11px] text-slate-400 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-lg font-bold text-slate-800">{value}</p>
    </div>
  )
}

function PrivacyDetailBlock({
  label, items, emptyText, icon, itemClass, note,
}: {
  label: string
  items: string[]
  emptyText: string
  icon: React.ReactNode
  itemClass: string
  note?: string
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        {icon}
        <p className="text-xs font-semibold text-slate-600">{label}</p>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-slate-400 italic">{emptyText}</p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.map(item => (
            <span key={item} className={`text-xs px-2 py-0.5 rounded-full font-medium ${itemClass}`}>
              {item}
            </span>
          ))}
        </div>
      )}
      {note && <p className="text-[11px] text-slate-400 mt-1.5">{note}</p>}
    </div>
  )
}

function ColCategoryBadge({ category }: { category: ColCategory }) {
  switch (category) {
    case 'direct':
      return (
        <span className="badge-red flex items-center gap-1 w-fit">
          <EyeOff className="w-3 h-3" />Identifier
        </span>
      )
    case 'linkage':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 w-fit">
          <Link className="w-3 h-3" />Linkage key
        </span>
      )
    case 'temporal':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 w-fit">
          <Calendar className="w-3 h-3" />Date / time
        </span>
      )
    case 'quasi':
      return (
        <span className="badge-yellow flex items-center gap-1 w-fit">
          <AlertTriangle className="w-3 h-3" />Quasi
        </span>
      )
    case 'health':
      return (
        <span className="badge-blue flex items-center gap-1 w-fit">
          <HeartPulse className="w-3 h-3" />Clinical
        </span>
      )
    default:
      return (
        <span className="badge-green flex items-center gap-1 w-fit">
          <Eye className="w-3 h-3" />OK
        </span>
      )
  }
}
