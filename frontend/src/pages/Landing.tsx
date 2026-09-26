import { useNavigate } from 'react-router-dom'
import { Upload, Cpu, BarChart2, ShieldCheck, Download, ArrowRight, Activity, FlaskConical } from 'lucide-react'
import { useStore } from '../store'

const steps = [
  { icon: Upload,      color: 'bg-brand-100 text-brand-600',       title: 'Upload',         desc: 'De-identified CSV or Excel dataset.' },
  { icon: Cpu,         color: 'bg-purple-100 text-purple-600',     title: 'Generate',       desc: 'Train CTGAN and synthesise records.' },
  { icon: BarChart2,   color: 'bg-clinical-100 text-clinical-600', title: 'Validate',       desc: 'Compare source and synthetic distributions.' },
  { icon: ShieldCheck, color: 'bg-amber-100 text-amber-600',       title: 'Privacy check',  desc: 'Duplicate and near-duplicate detection.' },
  { icon: Download,    color: 'bg-rose-100 text-rose-600',         title: 'Export',         desc: 'Download as CSV or Excel.' },
]

export default function Landing() {
  const navigate = useNavigate()
  const { dataset, preprocessing, generation, validation, privacy } = useStore()

  // Compact workflow status chips — only shown when there's something to show
  const chips = [
    dataset                          && { label: 'Dataset ready',    color: 'green' },
    preprocessing                    && { label: 'Preprocessed',     color: 'green' },
    generation?.status === 'done'    && { label: 'Generated',        color: 'green' },
    validation                       && { label: 'Validated',        color: 'green' },
    privacy && privacy.risk_level !== 'High' && { label: 'Privacy screened', color: 'green' },
    privacy && privacy.risk_level === 'High' && { label: 'Privacy: review', color: 'amber' },
  ].filter(Boolean) as { label: string; color: string }[]

  return (
    <div className="max-w-4xl mx-auto">
      {/* Hero */}
      <div className="text-center mb-12">
        <div className="inline-flex items-center gap-2 bg-brand-50 text-brand-700 px-4 py-1.5 rounded-full text-xs font-semibold mb-5 uppercase tracking-wide">
          <Activity className="w-3.5 h-3.5" />
          SynthGen Research Prototype
        </div>
        <h1 className="text-4xl font-bold text-slate-900 leading-tight mb-3">
          Privacy-Preserving Synthetic<br />Patient Data Platform
        </h1>
        <p className="text-slate-500 max-w-xl mx-auto mb-8 text-base">
          Generate realistic synthetic healthcare datasets for research and testing
          without exposing source patient records.
        </p>

        {/* CTA buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-6">
          <button onClick={() => navigate('/upload')} className="btn-primary px-7 py-3 text-base">
            <Upload className="w-4 h-4" />
            Upload Dataset
          </button>
          <button onClick={() => navigate('/upload')} className="btn-secondary px-7 py-3 text-base">
            <FlaskConical className="w-4 h-4" />
            Use Demo Dataset
          </button>
        </div>

        {/* Compact workflow status chips — only visible after work has started */}
        {chips.length > 0 && (
          <div className="flex flex-wrap justify-center gap-2">
            {chips.map(c => (
              <span
                key={c.label}
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
                  ${c.color === 'green' ? 'bg-clinical-50 text-clinical-700 border border-clinical-200' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${c.color === 'green' ? 'bg-clinical-500' : 'bg-amber-400'}`} />
                {c.label}
              </span>
            ))}
            {generation?.status === 'done' && (
              <button onClick={() => navigate('/dashboard')} className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-100 transition-colors">
                View dashboard <ArrowRight className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Workflow steps */}
      <div className="mb-12">
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
          {steps.map(({ icon: Icon, color, title, desc }, i) => (
            <div key={title} className="relative">
              {i < steps.length - 1 && (
                <div className="hidden sm:block absolute top-5 left-[calc(100%-6px)] w-3 z-10 text-slate-200">
                  <ArrowRight className="w-3 h-3" />
                </div>
              )}
              <div className="card p-4 text-center h-full">
                <div className={`w-9 h-9 rounded-lg ${color} flex items-center justify-center mx-auto mb-2.5`}>
                  <Icon className="w-4 h-4" />
                </div>
                <p className="text-sm font-semibold text-slate-800 mb-1">{title}</p>
                <p className="text-xs text-slate-400 leading-relaxed">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Compact disclaimer — one line, no large card */}
      <p className="text-center text-xs text-slate-400 max-w-2xl mx-auto">
        <ShieldCheck className="w-3.5 h-3.5 inline mr-1 text-slate-400" />
        Research prototype. Synthetic data is{' '}
        <strong className="text-slate-500">not automatically anonymous</strong>. Consult a qualified privacy
        expert before clinical use. Privacy screening, validation, and risk checks are prototype-level indicators only.
      </p>
    </div>
  )
}
