import { useState, useEffect } from 'react'
import { RefreshCw, ChevronDown, ChevronRight, Search } from 'lucide-react'
import { listClaims } from '../api.js'
import DecisionBadge from './DecisionBadge.jsx'
import TraceViewer from './TraceViewer.jsx'

export default function ClaimsList() {
  const [claims, setClaims] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(null)
  const [search, setSearch] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const data = await listClaims()
      setClaims(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const filtered = claims.filter(c =>
    c.claim_id?.toLowerCase().includes(search.toLowerCase()) ||
    c.member_id?.toLowerCase().includes(search.toLowerCase()) ||
    c.claim_category?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            className="input pl-8"
            placeholder="Search by claim ID, member, category…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <button onClick={load} className="btn-secondary flex items-center gap-1.5">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="card p-12 text-center text-slate-400">
          <p className="text-sm">No claims found. Submit a claim from the Submit tab.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Claim ID</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Member</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Category</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Claimed</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Approved</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Decision</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Conf.</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map(c => (
                <>
                  <tr
                    key={c.claim_id}
                    className="hover:bg-slate-50 cursor-pointer transition-colors"
                    onClick={() => setExpanded(expanded === c.claim_id ? null : c.claim_id)}
                  >
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">{c.claim_id}</td>
                    <td className="px-4 py-3 font-medium">{c.member_id}</td>
                    <td className="px-4 py-3 text-slate-600">{c.claim_category}</td>
                    <td className="px-4 py-3 text-right text-slate-600">₹{c.claimed_amount?.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-semibold">
                      {c.approved_amount > 0 ? `₹${c.approved_amount?.toLocaleString()}` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <DecisionBadge decision={c.decision} />
                    </td>
                    <td className="px-4 py-3 text-right text-xs">
                      <span className={`font-semibold ${
                        c.confidence_score > 0.8 ? 'text-emerald-600' :
                        c.confidence_score > 0.5 ? 'text-amber-600' : 'text-red-600'
                      }`}>
                        {c.confidence_score ? `${(c.confidence_score * 100).toFixed(0)}%` : '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {expanded === c.claim_id
                        ? <ChevronDown size={15} />
                        : <ChevronRight size={15} />}
                    </td>
                  </tr>
                  {expanded === c.claim_id && (
                    <tr key={`${c.claim_id}-exp`}>
                      <td colSpan={8} className="px-4 py-4 bg-slate-50 border-b border-slate-200">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {/* Explanation */}
                          <div>
                            <h4 className="text-xs font-semibold text-slate-600 mb-2">Decision Explanation</h4>
                            <pre className="text-xs text-slate-600 whitespace-pre-wrap font-mono bg-white rounded-lg border border-slate-200 p-3 overflow-auto max-h-56">
                              {c.explanation || 'No explanation available.'}
                            </pre>

                            {c.rejection_reasons?.length > 0 && (
                              <div className="mt-2 space-y-1">
                                {c.rejection_reasons.map((r, i) => (
                                  <div key={i} className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">{r}</div>
                                ))}
                              </div>
                            )}

                            {c.line_item_decisions?.length > 0 && (
                              <div className="mt-2">
                                <h4 className="text-xs font-semibold text-slate-600 mb-1">Line Items</h4>
                                <div className="rounded border border-slate-200 overflow-hidden">
                                  <table className="w-full text-xs">
                                    <thead className="bg-slate-100">
                                      <tr>
                                        <th className="text-left px-2 py-1.5 text-slate-600">Item</th>
                                        <th className="text-right px-2 py-1.5 text-slate-600">Claimed</th>
                                        <th className="text-right px-2 py-1.5 text-slate-600">Approved</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {c.line_item_decisions.map((li, i) => (
                                        <tr key={i} className={`border-t border-slate-100 ${li.decision === 'REJECTED' ? 'bg-red-50' : ''}`}>
                                          <td className="px-2 py-1.5">{li.description}</td>
                                          <td className="px-2 py-1.5 text-right">₹{li.claimed_amount?.toLocaleString()}</td>
                                          <td className="px-2 py-1.5 text-right font-medium">
                                            {li.decision === 'APPROVED' ? `₹${li.approved_amount?.toLocaleString()}` : <span className="text-red-600">Excluded</span>}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Trace */}
                          <div>
                            <TraceViewer
                              trace={c.trace || []}
                              componentFailures={c.component_failures}
                              degraded={c.degraded_pipeline}
                            />
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
