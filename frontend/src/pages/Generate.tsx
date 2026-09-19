import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Cpu, ArrowRight, CheckCircle, AlertCircle, Activity, ShieldAlert } from 'lucide-react'
import { startGeneration, getGenerationStatus, checkHealth, extractError, type HealthResponse } from '../services/api'
import { useStore } from '../store'
import ProgressBar from '../components/ProgressBar'
import CohortBuilder, { CohortReport } from '../components/CohortBuilder'
import type { CohortRequirement, CohortRequirementResult, ValidationError } from '../types'

const MODELS = [
  { value: 'CTGAN',          label: 'CTGAN',           desc: 'Conditional GAN — best quality.' },
  { value: 'TVAE',           label: 'TVAE',            desc: 'Variational autoencoder.' },
  { value: 'GAUSSIANCOPULA', label: 'Gaussian Copula', desc: 'Fastest, simpler distributions.' },
]

export default function Generate() {
  const navigate = useNavigate()
  const { dataset, preprocessing, generation, setGeneration } = useStore()

  const [numRecords, setNumRecords] = useState(10000)
  const [model, setModel]           = useState<'CTGAN' | 'TVAE' | 'GAUSSIANCOPULA'>('CTGAN')
  const [epochs, setEpochs]         = useState(300)
  const [requirements, setRequirements] = useState<CohortRequirement[]>([])
  const [validationErrors, setValidationErrors] = useState<{ id: string; message: string }[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [sdvMissing, setSdvMissing] = useState(false)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    checkHealth()
      .then((h: HealthResponse) => { if (!h.dependencies.generation_ready) setSdvMissing(true) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (generation && ['pending', 'training', 'generating'].includes(generation.status)) {
      startPolling(generation.id)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, []) // eslint-disable-line

  function startPolling(genId: string) {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const status = await getGenerationStatus(genId)
        setGeneration(status)
        if (status.status === 'done') {
          clearInterval(pollRef.current!)
          toast.success(`Generated ${status.num_generated?.toLocaleString()} records in ${status.generation_time_seconds?.toFixed(1)}s`)
        }
        if (status.status === 'error') {
          clearInterval(pollRef.current!)
          toast.error(`Generation failed: ${status.error_message}`)
        }
      } catch { /* silently retry */ }
    }, 2000)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!dataset || !preprocessing) { toast.error('Upload and preprocess a dataset first.'); return }

    // Validate cohort requirements before submitting
    if (requirements.length > 0) {
      // We need column profiles for validation — fetch them lazily if needed
      // For now do basic structural validation (the CohortBuilder already shows
      // per-field errors; here we just block submission on any errors)
      const errors = validationErrors
      if (errors.length > 0) {
        toast.error('Fix cohort requirement errors before generating.')
        return
      }
    }

    setSubmitting(true)
    try {
      // Strip client-side 'id' field — backend doesn't need it
      const reqs = requirements.length > 0
        ? requirements.map(({ id: _id, ...rest }) => rest)
        : undefined

      const res = await startGeneration({
        dataset_id:  dataset.id,
        num_records: numRecords,
        model,
        epochs,
        requirements: reqs,   // new dynamic path (undefined = no cohort)
      })
      const initial = await getGenerationStatus(res.generation_id)
      setGeneration(initial)
      startPolling(res.generation_id)
      toast.success('Generation started!')
    } catch (err) {
      toast.error(extractError(err))
    } finally {
      setSubmitting(false)
    }
  }

  // Validation errors bubble up directly from CohortBuilder which has the
  // real profile map — never pass an empty map here.
  function handleRequirementsChange(reqs: CohortRequirement[], errs: ValidationError[]) {
    setRequirements(reqs)
    setValidationErrors(errs)
  }

  const isRunning = generation && ['pending', 'training', 'generating'].includes(generation.status)
  const isDone    = generation?.status === 'done'
  const isError   = generation?.status === 'error'

  // Extract dynamic cohort report from generation results
  const cohortReport: CohortRequirementResult[] = (() => {
    if (!generation?.cohort_results) return []
    const cr = generation.cohort_results as Record<string, unknown>
    if (Array.isArray(cr.requirements)) return cr.requirements as CohortRequirementResult[]
    return []
  })()

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="page-title">Generate Synthetic Data</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Configure the synthesis model and cohort requirements, then generate.
        </p>
      </div>

      {/* No dataset prompt */}
      {!preprocessing && (
        <div className="card border-amber-100 bg-amber-50 p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
            <p className="text-sm text-amber-700">No dataset loaded yet.</p>
          </div>
          <button onClick={() => navigate('/upload')} className="btn-secondary text-xs flex-shrink-0">
            Upload dataset <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* SDV missing */}
      {sdvMissing && (
        <div className="card border-red-200 bg-red-50 p-4 flex gap-3">
          <ShieldAlert className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-700">SDV not installed — generation unavailable</p>
            <code className="text-xs text-red-600 mt-1 block">
              pip install sdv ctgan rdt copulas sdmetrics deepecho
            </code>
          </div>
        </div>
      )}

      {/* Generation progress */}
      {(isRunning || isDone || isError) && generation && (
        <div className={`card p-5 space-y-3 ${isError ? 'border-red-200' : isDone ? 'border-clinical-200' : ''}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {isDone
                ? <CheckCircle className="w-4 h-4 text-clinical-600" />
                : isError
                ? <AlertCircle className="w-4 h-4 text-red-500" />
                : <Cpu className="w-4 h-4 text-brand-500 animate-pulse" />
              }
              <span className="text-sm font-semibold text-slate-800">
                {isDone ? 'Generation complete' : isError ? 'Generation failed' : 'Generating…'}
              </span>
            </div>
            {isDone && (
              <span className="text-xs text-slate-400">
                {generation.model_used} · {generation.generation_time_seconds?.toFixed(1)}s
              </span>
            )}
          </div>

          {!isError && (
            <ProgressBar value={generation.progress} animated={isRunning || false} color={isDone ? 'green' : 'blue'} />
          )}
          <p className="text-xs text-slate-500">{generation.progress_message}</p>

          {isError && <p className="text-sm text-red-600">{generation.error_message}</p>}

          {/* Dynamic cohort accuracy report */}
          {isDone && cohortReport.length > 0 && (
            <CohortReport results={cohortReport} />
          )}

          {isDone && (
            <div className="flex flex-wrap gap-2 pt-1">
              <button onClick={() => navigate('/dashboard')} className="btn-primary text-sm">
                Dashboard <ArrowRight className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => navigate('/validation')} className="btn-secondary text-sm">Validate</button>
              <button onClick={() => navigate('/synthetic')}  className="btn-secondary text-sm">Preview data</button>
              <button onClick={() => navigate('/reports')}    className="btn-secondary text-sm">Export</button>
            </div>
          )}
        </div>
      )}

      {/* Config form */}
      {!isRunning && (
        <form onSubmit={handleSubmit} className="space-y-5">

          {/* Dataset context */}
          {preprocessing && (
            <div className="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-lg border border-slate-200">
              <Activity className="w-4 h-4 text-slate-400 flex-shrink-0" />
              <span className="text-sm text-slate-600">
                <strong>{preprocessing.rows_after.toLocaleString()}</strong> source records ·{' '}
                <strong>{preprocessing.columns_included.length}</strong> columns
              </span>
            </div>
          )}

          {/* Generation settings */}
          <div className="card p-5 space-y-4">
            <h2 className="section-title">Generation Settings</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="label">Synthetic records</label>
                <input
                  type="number" min={100} max={500000} required
                  value={numRecords}
                  onChange={e => setNumRecords(Number(e.target.value))}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Training epochs</label>
                <input
                  type="number" min={10} max={2000}
                  value={epochs}
                  onChange={e => setEpochs(Number(e.target.value))}
                  className="input"
                />
                <p className="text-xs text-slate-400 mt-1">Higher = better quality, slower</p>
              </div>
            </div>

            <div>
              <label className="label">Model</label>
              <div className="flex gap-2 flex-wrap">
                {MODELS.map(m => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => setModel(m.value as typeof model)}
                    className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                      model === m.value
                        ? 'border-brand-500 bg-brand-50 text-brand-700 font-semibold'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-slate-400 mt-1.5">
                Auto-fallback: CTGAN → TVAE → Gaussian Copula if training fails.
              </p>
            </div>
          </div>

          {/* Dynamic Cohort Requirements */}
          <div className="card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="section-title">Cohort Requirements</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Features and values come from your uploaded dataset — nothing is hard-coded.
                </p>
              </div>
              <span className="badge-gray text-xs">Optional</span>
            </div>

            {dataset?.id && preprocessing ? (
              <CohortBuilder
                datasetId={dataset.id}
                requirements={requirements}
                onChange={handleRequirementsChange}
                errors={validationErrors}
              />
            ) : (
              <p className="text-xs text-slate-400">
                Upload and preprocess a dataset to configure cohort requirements.
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={submitting || !preprocessing || sdvMissing || validationErrors.length > 0}
            className="btn-primary w-full py-3 text-base justify-center"
          >
            {submitting ? (
              <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />Starting…</>
            ) : (
              <><Cpu className="w-5 h-5" />Generate {numRecords.toLocaleString()} Synthetic Records</>
            )}
          </button>

          {validationErrors.length > 0 && (
            <p className="text-xs text-red-600 text-center">
              Fix {validationErrors.length} cohort error{validationErrors.length > 1 ? 's' : ''} above before generating.
            </p>
          )}
        </form>
      )}
    </div>
  )
}
