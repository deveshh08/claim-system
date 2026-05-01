import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, AlertTriangle, Zap } from 'lucide-react'

const STATUS_ICONS = {
  SUCCESS: <CheckCircle2 size={14} className="text-emerald-500" />,
  PARTIAL: <AlertTriangle size={14} className="text-amber-500" />,
  FAILED:  <XCircle size={14} className="text-red-500" />,
  SKIPPED: <Zap size={14} className="text-slate-400" />,
}

function AgentRow({ result }) {
  const [open, setOpen] = useState(false)
  const icon = STATUS_ICONS[result.status] ?? STATUS_ICONS.SKIPPED

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-2.5">
          {icon}
          <span className="font-medium text-sm text-slate-800">{result.agent_name}</span>
          {result.duration_ms && (
            <span className="text-xs text-slate-400">{Math.round(result.duration_ms)}ms</span>
          )}
          {result.error && (
            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
              {result.error.slice(0, 60)}
            </span>
          )}
        </div>
        {open ? <ChevronDown size={15} className="text-slate-400" /> : <ChevronRight size={15} className="text-slate-400" />}
      </button>

      {open && (
        <div className="border-t border-slate-100 px-4 py-3 bg-slate-50 text-xs space-y-2">
          {/* Document verification specifics */}
          {result.agent_name === 'DocumentVerificationAgent' && (
            <>
              <p className={`font-semibold ${result.passed ? 'text-emerald-700' : 'text-red-700'}`}>
                {result.passed ? '✓ All checks passed' : '✗ Verification failed'}
              </p>
              {result.issues?.map((issue, i) => (
                <div key={i} className="bg-red-50 border border-red-200 rounded p-2 text-red-800">{issue}</div>
              ))}
              {result.unreadable_file_ids?.length > 0 && (
                <p className="text-amber-700">Unreadable files: {result.unreadable_file_ids.join(', ')}</p>
              )}
            </>
          )}

          {/* Extraction specifics */}
          {result.agent_name === 'DocumentExtractionAgent' && (
            <>
              <p className="text-slate-600">
                Overall extraction confidence: <strong>{(result.overall_extraction_confidence * 100).toFixed(0)}%</strong>
              </p>
              {result.documents?.map(doc => (
                <div key={doc.file_id} className="bg-white border border-slate-200 rounded p-2">
                  <span className="font-medium">{doc.document_type}</span>
                  <span className="text-slate-500 ml-2">[{doc.file_id}]</span>
                  <span className={`ml-2 ${doc.extraction_confidence < 0.5 ? 'text-red-600' : 'text-slate-600'}`}>
                    conf: {(doc.extraction_confidence * 100).toFixed(0)}%
                  </span>
                  {doc.flags?.length > 0 && (
                    <span className="ml-2 text-amber-700">flags: {doc.flags.join(', ')}</span>
                  )}
                  {doc.diagnosis && <div className="mt-1 text-slate-600">Diagnosis: {doc.diagnosis}</div>}
                  {doc.total_amount && <div className="text-slate-600">Total: ₹{doc.total_amount?.toLocaleString()}</div>}
                </div>
              ))}
            </>
          )}

          {/* Policy engine checks */}
          {result.agent_name === 'PolicyEngine' && (
            <>
              {result.checks_performed?.map((c, i) => (
                <div key={i} className="flex items-start gap-2">
                  {c.passed
                    ? <CheckCircle2 size={12} className="text-emerald-500 mt-0.5 shrink-0" />
                    : <XCircle size={12} className="text-red-500 mt-0.5 shrink-0" />
                  }
                  <div>
                    <span className="font-medium text-slate-700">{c.check}: </span>
                    <span className="text-slate-500">{c.detail}</span>
                  </div>
                </div>
              ))}
              {result.line_item_decisions?.length > 0 && (
                <div className="mt-2">
                  <p className="font-semibold text-slate-700 mb-1">Line items:</p>
                  {result.line_item_decisions.map((li, i) => (
                    <div key={i} className={`flex justify-between rounded px-2 py-1 mb-1 ${
                      li.decision === 'APPROVED' ? 'bg-emerald-50' : 'bg-red-50'
                    }`}>
                      <span>{li.description}</span>
                      <span className="font-medium">
                        {li.decision === 'APPROVED' ? `₹${li.approved_amount?.toLocaleString()}` : '✗ Excluded'}
                        {li.reason && <span className="text-xs ml-2 text-slate-500">({li.reason})</span>}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* Fraud signals */}
          {result.agent_name === 'FraudDetectionAgent' && (
            <>
              <p>Fraud score: <strong>{(result.fraud_score * 100).toFixed(0)}%</strong>
                {result.requires_manual_review && (
                  <span className="ml-2 text-blue-700 font-semibold">→ Routed to Manual Review</span>
                )}
              </p>
              {result.fraud_signals?.map((s, i) => (
                <div key={i} className="bg-amber-50 border border-amber-200 rounded p-2 text-amber-800">⚠ {s}</div>
              ))}
              {result.fraud_signals?.length === 0 && (
                <p className="text-emerald-700">✓ No fraud signals detected</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function TraceViewer({ trace = [], componentFailures = [], degraded = false }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-700">Pipeline Trace ({trace.length} agents)</h3>
        {degraded && (
          <span className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full font-medium">
            ⚡ Degraded pipeline
          </span>
        )}
      </div>

      {trace.map((r, i) => <AgentRow key={i} result={r} />)}

      {componentFailures?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
          <p className="font-semibold mb-1">Component failures (pipeline continued):</p>
          {componentFailures.map((f, i) => <p key={i}>⚡ {f}</p>)}
          <p className="mt-1 italic">Manual review recommended due to incomplete processing.</p>
        </div>
      )}
    </div>
  )
}
