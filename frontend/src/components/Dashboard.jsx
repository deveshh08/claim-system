import { useState, useEffect } from 'react'
import { getPolicy } from '../api.js'
import { Building2, Users, Shield, Clock, Ban } from 'lucide-react'

function StatCard({ icon: Icon, label, value, sub, color = 'plum' }) {
  const colors = {
    plum:    'bg-plum-50 text-plum-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    amber:   'bg-amber-50 text-amber-600',
    red:     'bg-red-50 text-red-600',
  }
  return (
    <div className="card p-5 flex items-start gap-4">
      <div className={`rounded-lg p-2.5 ${colors[color]}`}>
        <Icon size={20} />
      </div>
      <div>
        <p className="text-2xl font-bold text-slate-900">{value}</p>
        <p className="text-sm font-medium text-slate-700">{label}</p>
        {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [policy, setPolicy] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getPolicy().then(setPolicy).finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-48 text-slate-400 text-sm">Loading policy…</div>
  )
  if (!policy) return (
    <div className="card p-8 text-center text-red-600">Failed to load policy. Is the backend running?</div>
  )

  const employees = policy.members?.filter(m => m.relationship === 'SELF') || []
  const dependents = policy.members?.filter(m => m.relationship !== 'SELF') || []

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">{policy.policy_id}</h2>
        <p className="text-sm text-slate-500">Group Health Insurance — Standard Plan · ICICI Lombard</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Shield} label="Sum Insured / Employee" value={`₹${(policy.sum_insured / 100000).toFixed(1)}L`} color="plum" />
        <StatCard icon={Clock} label="Per-Claim Limit" value={`₹${policy.per_claim_limit?.toLocaleString()}`} color="amber" />
        <StatCard icon={Shield} label="Annual OPD Limit" value={`₹${(policy.annual_opd_limit / 1000).toFixed(0)}K`} color="emerald" />
        <StatCard icon={Users} label="Members" value={policy.members?.length} sub={`${employees.length} employees, ${dependents.length} dependents`} color="plum" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Network Hospitals */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Building2 size={16} className="text-plum-600" />
            <h3 className="font-semibold text-slate-800">Network Hospitals ({policy.network_hospitals?.length})</h3>
          </div>
          <div className="space-y-1.5">
            {policy.network_hospitals?.map(h => (
              <div key={h} className="flex items-center gap-2 text-sm text-slate-700">
                <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                {h}
              </div>
            ))}
          </div>
        </div>

        {/* Member Roster */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Users size={16} className="text-plum-600" />
            <h3 className="font-semibold text-slate-800">Member Roster</h3>
          </div>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {policy.members?.map(m => (
              <div key={m.member_id} className="flex items-center justify-between text-sm py-1 border-b border-slate-50 last:border-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-400 w-16">{m.member_id}</span>
                  <span className="text-slate-700">{m.name}</span>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  m.relationship === 'SELF' ? 'bg-plum-100 text-plum-700' : 'bg-slate-100 text-slate-600'
                }`}>{m.relationship}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Coverage Categories */}
      <div className="card p-5">
        <h3 className="font-semibold text-slate-800 mb-4">Coverage Categories</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {[
            { name: 'Consultation', sub: '₹2,000 sub-limit', copay: '10% co-pay', badge: 'bg-blue-100 text-blue-700' },
            { name: 'Diagnostic', sub: '₹10,000 sub-limit', copay: 'Requires Rx', badge: 'bg-purple-100 text-purple-700' },
            { name: 'Pharmacy', sub: '₹15,000 sub-limit', copay: 'Generic mandatory', badge: 'bg-green-100 text-green-700' },
            { name: 'Dental', sub: '₹10,000 sub-limit', copay: 'No co-pay', badge: 'bg-yellow-100 text-yellow-700' },
            { name: 'Vision', sub: '₹5,000 sub-limit', copay: 'No co-pay', badge: 'bg-pink-100 text-pink-700' },
            { name: 'Alternative Medicine', sub: '₹8,000 sub-limit', copay: '20 sessions/yr', badge: 'bg-teal-100 text-teal-700' },
          ].map(cat => (
            <div key={cat.name} className="border border-slate-200 rounded-lg p-3">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cat.badge}`}>{cat.name}</span>
              <p className="text-xs text-slate-600 mt-2">{cat.sub}</p>
              <p className="text-xs text-slate-400">{cat.copay}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Waiting Periods */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Clock size={16} className="text-amber-500" />
          <h3 className="font-semibold text-slate-800">Key Waiting Periods</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Initial Waiting', days: 30 },
            { label: 'Pre-existing', days: 365 },
            { label: 'Diabetes/HTN', days: 90 },
            { label: 'Mental Health', days: 180 },
            { label: 'Maternity', days: 270 },
            { label: 'Joint Replacement', days: 730 },
            { label: 'Hernia / Cataract', days: 365 },
            { label: 'Obesity', days: 365 },
          ].map(w => (
            <div key={w.label} className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-center">
              <p className="text-xl font-bold text-amber-700">{w.days}</p>
              <p className="text-xs text-amber-600">days</p>
              <p className="text-xs text-slate-600 mt-1">{w.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Key Exclusions */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Ban size={16} className="text-red-500" />
          <h3 className="font-semibold text-slate-800">Key Exclusions</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          {[
            'Cosmetic procedures', 'Bariatric surgery', 'LASIK', 'Teeth whitening',
            'Orthodontic braces', 'Infertility / IVF', 'Substance abuse',
            'Self-inflicted injuries', 'Experimental treatments', 'Supplements & tonics',
            'Non-medically necessary vaccinations', 'Veneers / implants (cosmetic)',
          ].map(e => (
            <span key={e} className="text-xs bg-red-50 border border-red-200 text-red-700 px-2.5 py-1 rounded-full">{e}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
