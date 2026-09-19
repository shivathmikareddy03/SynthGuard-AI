import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, Legend,
  ScatterChart, Scatter, PieChart, Pie, Cell
} from 'recharts'
import { Database, Cpu, Clock, BarChart2, Users, AlertTriangle } from 'lucide-react'
import { runValidation, runPrivacyCheck, getPreview, extractError } from '../services/api'
import { useStore } from '../store'
import StatCard from '../components/StatCard'
import ScoreGauge from '../components/ScoreGauge'
import RiskBadge from '../components/RiskBadge'
import toast from 'react-hot-toast'

const COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

export default function Dashboard() {
  const navigate = useNavigate()
  const { dataset, preprocessing, generation, validation, privacy, setValidation, setPrivacy } = useStore()
  const [loading, setLoading] = useState(false)
  const [sourcePreview, setSourcePreview] = useState<Record<string, unknown>[]>([])
  const [synthPreview, setSynthPreview] = useState<Record<string, unknown>[]>([])

  useEffect(() => {
    if (!generation || generation.status !== 'done') return
    // Auto-run validation and privacy if not done
    async function autoRun() {
      if (!generation) return
      setLoading(true)
      try {
        if (!validation) {
          const v = await runValidation(generation.id)
          setValidation(v)
        }
        if (!privacy) {
          const p = await runPrivacyCheck(generation.id)
          setPrivacy(p)
        }
        // Load preview for charts
        const preview = await getPreview(generation.id, 1, 500)
        setSynthPreview(preview.rows)
      } catch (e) {
        toast.error(extractError(e))
      } finally {
        setLoading(false)
      }
    }
    autoRun()
  }, [generation?.id]) // eslint-disable-line

  if (!generation || generation.status !== 'done') {
    return (
      <div className="max-w-2xl mx-auto text-center py-24">
        <BarChart2 className="w-12 h-12 text-slate-300 mx-auto mb-4" />
        <h2 className="text-lg font-semibold text-slate-600 mb-2">No data yet</h2>
        <p className="text-slate-400 text-sm mb-6">Generate a synthetic dataset to see the dashboard.</p>
        <button onClick={() => navigate('/generate')} className="btn-primary">Go to Generate</button>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 gap-4">
        <div className="w-10 h-10 border-4 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
        <p className="text-slate-500 text-sm">Running validation and privacy checks…</p>
      </div>
    )
  }

  const numStats = validation?.numerical_stats ?? []
  const catStats = validation?.categorical_stats ?? []
  const scores = validation?.overall_scores

  // Build distribution data for charts
  function buildHistData(col: string, data: Record<string, unknown>[]) {
    const vals = data.map(r => Number(r[col])).filter(v => !isNaN(v))
    if (vals.length === 0) return []
    const min = Math.min(...vals), max = Math.max(...vals)
    const bins = 10
    const step = (max - min) / bins || 1
    const buckets = Array.from({ length: bins }, (_, i) => ({
      bin: `${(min + i * step).toFixed(0)}–${(min + (i + 1) * step).toFixed(0)}`,
      count: 0,
    }))
    vals.forEach(v => {
      const idx = Math.min(Math.floor((v - min) / step), bins - 1)
      buckets[idx].count++
    })
    return buckets
  }

  function buildCatData(col: string, data: Record<string, unknown>[]) {
    const counts: Record<string, number> = {}
    data.forEach(r => {
      const v = String(r[col] ?? 'Unknown')
      counts[v] = (counts[v] ?? 0) + 1
    })
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }

  const ageCol = numStats.find(s => s.column.toLowerCase().includes('age'))
  const bpCol = numStats.find(s => s.column.toLowerCase().includes('systolic') || s.column.toLowerCase().includes('bloodpressure'))
  const painCol = numStats.find(s => s.column.toLowerCase().includes('pain'))
  const medCol = numStats.find(s => s.column.toLowerCase().includes('medication') || s.column.toLowerCase().includes('adherence'))

  const diabeticCat = catStats.find(s => s.column.toLowerCase().includes('diabetes'))
  const activityCat = catStats.find(s => s.column.toLowerCase().includes('activity'))

  // Comparison bar data helper
  function comparisonData(stat: typeof ageCol) {
    if (!stat) return []
    return [
      { metric: 'Mean', Source: stat.source_mean, Synthetic: stat.synth_mean },
      { metric: 'Median', Source: stat.source_median, Synthetic: stat.synth_median },
      { metric: 'Std Dev', Source: stat.source_std, Synthetic: stat.synth_std },
    ]
  }

  function catComparisonData(cat: typeof diabeticCat) {
    if (!cat) return []
    const keys = Object.keys(cat.source_distribution)
    return keys.map(k => ({
      name: k,
      Source: cat.source_distribution[k] ?? 0,
      Synthetic: cat.synth_distribution[k] ?? 0,
    }))
  }

  const corrStats = (validation?.correlation_stats ?? []).slice(0, 8)

  return (
    <div className="space-y-8">
      <div>
        <h1 className="page-title">Dashboard</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Overview of source data, synthetic data, and quality metrics.
        </p>
      </div>

      {/* Overview stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Source records" value={preprocessing?.rows_after.toLocaleString() ?? '—'} icon={Database} color="slate" />
        <StatCard label="Synthetic records" value={generation.num_generated?.toLocaleString() ?? '—'} icon={Users} color="blue" />
        <StatCard label="Model used" value={generation.model_used ?? '—'} icon={Cpu} color="purple" />
        <StatCard label="Generation time" value={generation.generation_time_seconds ? `${generation.generation_time_seconds.toFixed(1)}s` : '—'} icon={Clock} color="green" />
      </div>

      {/* Quality scores */}
      {scores && (
        <div>
          <h2 className="section-title mb-1">Synthetic Data Quality</h2>
          <p className="text-xs text-slate-400 mb-4">
            Prototype metrics only — not a formal clinical or privacy certification.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <ScoreGauge score={scores.distribution_similarity} label="Distribution Similarity" />
            <ScoreGauge score={scores.correlation_preservation} label="Correlation Preservation" />
            <ScoreGauge score={scores.ks_pass_rate} label="KS Test Pass Rate"
              note={`p > 0.05 · ${scores.ks_passed_columns ?? '?'}/${scores.ks_tested_columns ?? '?'} cols`} />
            <ScoreGauge score={scores.overall_quality} label="Overall Quality" size="lg" />
          </div>
        </div>
      )}

      {/* Privacy summary */}
      {privacy && (
        <div className="card p-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-700">Privacy Risk Assessment</p>
            <p className="text-xs text-slate-400 mt-0.5">Prototype-level check · not a formal privacy audit</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-center">
              <p className="text-lg font-bold text-slate-800">{privacy.exact_duplicates}</p>
              <p className="text-xs text-slate-400">Exact duplicates</p>
            </div>
            <div className="text-center">
              <p className="text-lg font-bold text-slate-800">{privacy.near_duplicates}</p>
              <p className="text-xs text-slate-400">Near duplicates</p>
            </div>
            <RiskBadge level={privacy.risk_level} large />
          </div>
        </div>
      )}

      {/* Source vs Synthetic charts */}
      <div>
        <h2 className="section-title mb-4">Source vs Synthetic — Distributions</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          {/* Age */}
          {ageCol && (
            <div className="card p-5">
              <p className="text-sm font-semibold text-slate-700 mb-1">{ageCol.column}</p>
              <p className="text-xs text-slate-400 mb-3">Distribution similarity: {ageCol.distribution_similarity.toFixed(1)}%</p>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={comparisonData(ageCol)} barSize={20}>
                  <XAxis dataKey="metric" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Source" fill="#94a3b8" />
                  <Bar dataKey="Synthetic" fill="#3b82f6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Blood pressure */}
          {bpCol && (
            <div className="card p-5">
              <p className="text-sm font-semibold text-slate-700 mb-1">{bpCol.column}</p>
              <p className="text-xs text-slate-400 mb-3">Distribution similarity: {bpCol.distribution_similarity.toFixed(1)}%</p>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={comparisonData(bpCol)} barSize={20}>
                  <XAxis dataKey="metric" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Source" fill="#94a3b8" />
                  <Bar dataKey="Synthetic" fill="#3b82f6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Diabetes */}
          {diabeticCat && (
            <div className="card p-5">
              <p className="text-sm font-semibold text-slate-700 mb-3">{diabeticCat.column} — Category Distribution</p>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={catComparisonData(diabeticCat)} barSize={24}>
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" />
                  <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Source" fill="#94a3b8" />
                  <Bar dataKey="Synthetic" fill="#22c55e" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Activity */}
          {activityCat && (
            <div className="card p-5">
              <p className="text-sm font-semibold text-slate-700 mb-3">{activityCat.column} — Category Distribution</p>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={catComparisonData(activityCat)} barSize={24}>
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" />
                  <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Source" fill="#94a3b8" />
                  <Bar dataKey="Synthetic" fill="#f59e0b" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* Correlation comparison */}
      {corrStats.length > 0 && (
        <div className="card p-6">
          <h2 className="section-title mb-1">Relationship Preservation</h2>
          <p className="text-xs text-slate-400 mb-4">Pearson correlation — Source vs Synthetic</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
                  <th className="px-4 py-2 text-left">Column A</th>
                  <th className="px-4 py-2 text-left">Column B</th>
                  <th className="px-4 py-2 text-right">Source r</th>
                  <th className="px-4 py-2 text-right">Synthetic r</th>
                  <th className="px-4 py-2 text-right">|Difference|</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {corrStats.map(c => (
                  <tr key={`${c.col_a}-${c.col_b}`}>
                    <td className="px-4 py-2 font-medium text-slate-700">{c.col_a}</td>
                    <td className="px-4 py-2 text-slate-600">{c.col_b}</td>
                    <td className="px-4 py-2 text-right">{c.source_correlation.toFixed(3)}</td>
                    <td className="px-4 py-2 text-right">{c.synth_correlation.toFixed(3)}</td>
                    <td className={`px-4 py-2 text-right font-semibold ${c.difference > 0.15 ? 'text-red-600' : c.difference > 0.05 ? 'text-amber-600' : 'text-clinical-600'}`}>
                      {c.difference.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cohort results */}
      {generation.cohort_results && Object.keys(generation.cohort_results).length > 0 && (
        <div className="card p-6">
          <h2 className="section-title mb-4">Cohort Accuracy</h2>
          <CohortAccuracyTable results={generation.cohort_results as Record<string, unknown>} />
        </div>
      )}

      {/* Disclaimer */}
      <div className="card border-slate-200 bg-slate-50 p-4 flex gap-3">
        <AlertTriangle className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-slate-500 leading-relaxed">
          All scores shown are <strong>prototype-level indicators</strong>, not formal clinical validations.
          Synthetic data should be reviewed by a qualified researcher and privacy expert before use in any clinical context.
        </p>
      </div>
    </div>
  )
}

function CohortAccuracyTable({ results }: { results: Record<string, unknown> }) {
  // ── New dynamic path: results.requirements is an array ────────────────────
  if (Array.isArray(results.requirements) && results.requirements.length > 0) {
    const reqs = results.requirements as Array<{
      label: string
      requested_pct: number
      generated_pct: number | null
      diff_pct: number | null
      status: string
    }>
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
              <th className="px-4 py-2 text-left">Requirement</th>
              <th className="px-4 py-2 text-right">Requested</th>
              <th className="px-4 py-2 text-right">Achieved</th>
              <th className="px-4 py-2 text-right">Difference</th>
              <th className="px-4 py-2 text-right">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {reqs.map((r, i) => {
              const diff = r.diff_pct ?? 0
              return (
                <tr key={i}>
                  <td className="px-4 py-2 font-medium">{r.label}</td>
                  <td className="px-4 py-2 text-right">{r.requested_pct?.toFixed(1)}%</td>
                  <td className="px-4 py-2 text-right">{r.generated_pct != null ? `${r.generated_pct.toFixed(1)}%` : '—'}</td>
                  <td className="px-4 py-2 text-right">{r.diff_pct != null ? `${r.diff_pct.toFixed(1)}pp` : '—'}</td>
                  <td className="px-4 py-2 text-right">
                    {r.status === 'column_missing'
                      ? <span className="badge-red">Missing</span>
                      : diff <= 2
                      ? <span className="badge-green">Excellent</span>
                      : diff <= 5
                      ? <span className="badge-blue">Good</span>
                      : <span className="badge-yellow">Review</span>
                    }
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  // ── Legacy path: flat keys older_pct_requested / diabetic_pct_requested ───
  const rows: { label: string; requested: number; actual: number; diff: number }[] = []
  if (results.older_pct_requested !== undefined) {
    rows.push({ label: 'Older patients (age ≥ 60)', requested: Number(results.older_pct_requested), actual: Number(results.older_pct_actual), diff: Number(results.older_pct_diff) })
  }
  if (results.diabetic_pct_requested !== undefined) {
    rows.push({ label: 'Diabetic patients', requested: Number(results.diabetic_pct_requested), actual: Number(results.diabetic_pct_actual), diff: Number(results.diabetic_pct_diff) })
  }
  if (!rows.length) return <p className="text-sm text-slate-400">No cohort constraints were applied.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
            <th className="px-4 py-2 text-left">Cohort</th>
            <th className="px-4 py-2 text-right">Requested</th>
            <th className="px-4 py-2 text-right">Achieved</th>
            <th className="px-4 py-2 text-right">Difference</th>
            <th className="px-4 py-2 text-right">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(r => (
            <tr key={r.label}>
              <td className="px-4 py-2 font-medium">{r.label}</td>
              <td className="px-4 py-2 text-right">{r.requested}%</td>
              <td className="px-4 py-2 text-right">{r.actual}%</td>
              <td className="px-4 py-2 text-right">{r.diff.toFixed(1)}%</td>
              <td className="px-4 py-2 text-right">
                {r.diff <= 2
                  ? <span className="badge-green">Excellent</span>
                  : r.diff <= 5
                  ? <span className="badge-blue">Good</span>
                  : <span className="badge-yellow">Review</span>
                }
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
