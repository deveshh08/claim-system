import { useState } from 'react'
import { Play, ChevronDown, ChevronRight, CheckCircle2, XCircle } from 'lucide-react'
import { runEval } from '../api.js'
import DecisionBadge from './DecisionBadge.jsx'
import TraceViewer from './TraceViewer.jsx'

export default function EvalRunner() {
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [error, setError] = useState(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const data = await runEval()
      setReport(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="font-semibold text-slate-900">Eval Runner — 12 Test Cases</h2>
            <p className="text-sm text-slate-500 mt-1">
              Runs all test cases from <code className="bg-slate-100 px-1 rounded text-xs">test_cases.json</code> through the live pipeline and compares against expected outcomes.
            </p>
          </div>
          <button
            onClick={run}
            disabled={loading}
            className="btn-primary flex items-center gap-2 shrink-0"
          >
            {loading
              ? <><span className="animate-spin text-lg">⟳</span> Running…</>
              : <><Play size={15} /> Run All Tests</>}
          </button>
        </div>

        {error && (
          <div className="mt-3 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>
        )}
      </div>

      {report && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-3 gap-4">
            <div className="card p-4 text-center">
              <p className="text-3xl font-bold text-slate-900">{report.total}</p>
              <p className="text-xs text-slate-500 mt-1">Total Cases</p>
            </div>
            <div className="card p-4 text-center">
              <p className="text-3xl font-bold text-emerald-600">{report.passed}</p>
              <p className="text-xs text-slate-500 mt-1">Passed</p>
            </div>
            <div className="card p-4 text-center">
              <p className={`text-3xl font-bold ${report.failed > 0 ? 'text-red-600' : 'text-slate-300'}`}>{report.failed}</p>
              <p className="text-xs text-slate-500 mt-1">Failed</p>
            </div>
          </div>

          {/* Progress bar */}
          <div className="card p-4">
            <div className="flex justify-between text-xs text-slate-500 mb-1.5">
              <span>Pass rate</span>
              <span className="font-semibold">{Math.round((report.passed / report.total) * 100)}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all duration-700"
                style={{ width: `${(report.passed / report.total) * 100}%` }}
              />
            </div>
          </div>

          {/* Results table */}
          <div className="card overflow-hidden">
            <div className="bg-slate-50 border-b border-slate-200 px-4 py-3">
              <h3 className="font-semibold text-sm text-slate-700">Test Case Results</h3>
            </div>
            <div className="divide-y divide-slate-100">
              {report.results.map(r => (
                <div key={r.case_id}>
                  <div
                    className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 cursor-pointer transition-colors"
                    onClick={() => setExpanded(expanded === r.case_id ? null : r.case_id)}
                  >
                    {r.matched
                      ? <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
                      : <XCircle size={16} className="text-red-500 shrink-0" />}

                    <span className="font-mono text-xs text-slate-500 w-14 shrink-0">{r.case_id}</span>
                    <span className="text-sm text-slate-700 flex-1">{r.case_name}</span>

                    <div className="flex items-center gap-2">
                      <div className="text-right">
                        <div className="text-xs text-slate-400 mb-0.5">Expected</div>
                        <DecisionBadge decision={r.expected?.decision ?? null} />
                      </div>
                      <span className="text-slate-300 text-xs">→</span>
                      <div className="text-right">
                        <div className="text-xs text-slate-400 mb-0.5">Actual</div>
                        <DecisionBadge decision={r.actual?.decision ?? null} />
                      </div>
                    </div>

                    {r.actual?.approved_amount > 0 && (
                      <span className="text-xs font-semibold text-slate-600 w-20 text-right">
                        ₹{r.actual.approved_amount.toLocaleString()}
                      </span>
                    )}

                    {expanded === r.case_id
                      ? <ChevronDown size={14} className="text-slate-400 shrink-0" />
                      : <ChevronRight size={14} className="text-slate-400 shrink-0" />}
                  </div>

                  {expanded === r.case_id && (
                    <div className="bg-slate-50 border-t border-slate-100 px-4 py-4 space-y-3">
                      {/* Match note */}
                      <div className={`rounded-lg p-3 text-sm ${r.matched ? 'bg-emerald-50 border border-emerald-200 text-emerald-800' : 'bg-red-50 border border-red-200 text-red-800'}`}>
                        {r.match_note}
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Expected vs Actual */}
                        <div className="space-y-2">
                          <h4 className="text-xs font-semibold text-slate-600">Expected</h4>
                          <pre className="text-xs bg-white rounded border border-slate-200 p-3 overflow-auto max-h-40">
                            {JSON.stringify(r.expected, null, 2)}
                          </pre>

                          <h4 className="text-xs font-semibold text-slate-600 mt-3">Actual Result</h4>
                          <pre className="text-xs bg-white rounded border border-slate-200 p-3 overflow-auto max-h-40">
                            {JSON.stringify({
                              decision: r.actual?.decision,
                              approved_amount: r.actual?.approved_amount,
                              confidence_score: r.actual?.confidence_score,
                              rejection_reasons: r.actual?.rejection_reasons,
                            }, null, 2)}
                          </pre>

                          {r.actual?.rejection_reasons?.length > 0 && (
                            <div className="space-y-1">
                              {r.actual.rejection_reasons.map((reason, i) => (
                                <div key={i} className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
                                  {reason}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Trace */}
                        <div>
                          <h4 className="text-xs font-semibold text-slate-600 mb-2">Pipeline Trace</h4>
                          {r.trace?.length > 0 ? (
                            <div className="space-y-1">
                              {r.trace.map((t, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs">
                                  <span className={`w-2 h-2 rounded-full shrink-0 ${
                                    t.status === 'SUCCESS' ? 'bg-emerald-500' :
                                    t.status === 'PARTIAL' ? 'bg-amber-500' :
                                    t.status === 'FAILED' ? 'bg-red-500' : 'bg-slate-300'
                                  }`} />
                                  <span className="font-medium text-slate-700">{t.agent}</span>
                                  <span className={`px-1.5 py-0.5 rounded text-xs ${
                                    t.status === 'SUCCESS' ? 'bg-emerald-100 text-emerald-700' :
                                    t.status === 'PARTIAL' ? 'bg-amber-100 text-amber-700' :
                                    'bg-red-100 text-red-700'
                                  }`}>{t.status}</span>
                                  {t.error && <span className="text-red-600 truncate">{t.error.slice(0, 50)}</span>}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="space-y-1">
                              {r.actual?.rejection_reasons?.map((reason, i) => (
                                <div key={i} className="text-xs bg-red-50 rounded border border-red-100 p-2 text-red-700">{reason}</div>
                              ))}
                              {!r.actual?.rejection_reasons?.length && (
                                <p className="text-xs text-slate-400">Pipeline halted at document verification</p>
                              )}
                            </div>
                          )}

                          {r.actual?.explanation && (
                            <div className="mt-3">
                              <h4 className="text-xs font-semibold text-slate-600 mb-1">Explanation</h4>
                              <pre className="text-xs bg-white rounded border border-slate-200 p-3 overflow-auto max-h-40 whitespace-pre-wrap">
                                {r.actual.explanation}
                              </pre>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
