import { useState } from 'react'
import { FileText, ClipboardList, FlaskConical, LayoutDashboard } from 'lucide-react'
import ClaimSubmit from './components/ClaimSubmit.jsx'
import ClaimsList from './components/ClaimsList.jsx'
import EvalRunner from './components/EvalRunner.jsx'
import Dashboard from './components/Dashboard.jsx'

const TABS = [
  { id: 'submit',    label: 'Submit Claim',     icon: FileText },
  { id: 'claims',    label: 'Claims Review',    icon: ClipboardList },
  { id: 'eval',      label: 'Run Eval (12 TCs)', icon: FlaskConical },
  { id: 'dashboard', label: 'Dashboard',        icon: LayoutDashboard },
]

export default function App() {
  const [tab, setTab] = useState('submit')

  const TabIcon = TABS.find(t => t.id === tab)?.icon

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-plum-600 flex items-center justify-center">
                <span className="text-white text-sm font-bold">P</span>
              </div>
              <div>
                <span className="font-bold text-slate-900">Plum</span>
                <span className="text-slate-400 text-sm ml-2">Claims Processing</span>
              </div>
            </div>
            <nav className="flex gap-1">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    tab === id
                      ? 'bg-plum-50 text-plum-700'
                      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                  }`}
                >
                  <Icon size={15} />
                  <span className="hidden sm:inline">{label}</span>
                </button>
              ))}
            </nav>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6">
        {tab === 'submit'    && <ClaimSubmit />}
        {tab === 'claims'    && <ClaimsList />}
        {tab === 'eval'      && <EvalRunner />}
        {tab === 'dashboard' && <Dashboard />}
      </main>

      <footer className="border-t border-slate-200 bg-white py-3 text-center text-xs text-slate-400">
        Plum Health Claims Processing System — Multi-Agent Pipeline v1.0
      </footer>
    </div>
  )
}
