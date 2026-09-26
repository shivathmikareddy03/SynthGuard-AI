import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Upload, Cpu, BarChart2,
  ShieldCheck, Table2, FileText, Activity
} from 'lucide-react'
import { useStore } from '../store'
import clsx from 'clsx'

const navItems = [
  { to: '/',           label: 'Home',          icon: Activity },
  { to: '/upload',     label: 'Upload Dataset', icon: Upload },
  { to: '/generate',   label: 'Generate Data',  icon: Cpu },
  { to: '/dashboard',  label: 'Dashboard',      icon: LayoutDashboard },
  { to: '/validation', label: 'Validation',     icon: BarChart2 },
  { to: '/privacy',    label: 'Privacy',        icon: ShieldCheck },
  { to: '/synthetic',  label: 'Synthetic Data', icon: Table2 },
  { to: '/reports',    label: 'Reports',        icon: FileText },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { dataset, preprocessing, generation, validation, privacy } = useStore()

  function stepBadge(to: string) {
    if (to === '/upload' && dataset) return 'done'
    if (to === '/generate' && generation?.status === 'done') return 'done'
    if (to === '/generate' && generation?.status === 'error') return 'error'
    if (to === '/dashboard' && generation?.status === 'done') return 'done'
    if (to === '/validation' && validation) return 'done'
    if (to === '/privacy' && privacy) {
      return privacy.risk_level === 'High' ? 'warn' : 'done'
    }
    if (to === '/synthetic' && generation?.status === 'done') return 'done'
    return null
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Sidebar */}
      <aside className="w-60 flex-shrink-0 bg-white border-r border-slate-200 flex flex-col">
        {/* Logo */}
        <div className="px-5 py-5 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <Activity className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-sm font-bold text-slate-900 leading-none">SynthGen</p>
              <p className="text-[10px] text-slate-500 mt-0.5">Synthetic Patient Data</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {navItems.map(({ to, label, icon: Icon }) => {
            const badge = stepBadge(to)
            return (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-brand-50 text-brand-700'
                      : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                  )
                }
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                <span className="flex-1">{label}</span>
                {badge === 'done' && (
                  <span className="w-2 h-2 rounded-full bg-clinical-500" />
                )}
                {badge === 'warn' && (
                  <span className="w-2 h-2 rounded-full bg-amber-400" />
                )}
                {badge === 'error' && (
                  <span className="w-2 h-2 rounded-full bg-red-500" />
                )}
              </NavLink>
            )
          })}
        </nav>

        {/* Workflow status */}
        <div className="px-4 py-4 border-t border-slate-100 space-y-1.5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Workflow</p>
          <StatusRow label="Dataset uploaded"   done={!!dataset} />
          <StatusRow label="Preprocessed"       done={!!preprocessing} />
          <StatusRow label="Synthetic generated" done={generation?.status === 'done'} />
          <StatusRow label="Validated"           done={!!validation} />
          <StatusRow
            label="Privacy checked"
            done={!!privacy}
            warn={privacy?.risk_level === 'High'}
          />
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <div className="min-h-full p-8">
          {children}
        </div>
      </main>
    </div>
  )
}

function StatusRow({
  label, done, warn = false,
}: { label: string; done: boolean; warn?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500">
      <span className={clsx(
        'w-3.5 h-3.5 rounded-full flex items-center justify-center text-[8px] font-bold flex-shrink-0',
        done && !warn ? 'bg-clinical-500 text-white' :
        done && warn  ? 'bg-amber-400 text-white' :
                        'bg-slate-200 text-slate-400'
      )}>
        {done ? (warn ? '!' : '✓') : '·'}
      </span>
      <span className={done ? 'text-slate-700' : ''}>{label}</span>
    </div>
  )
}
