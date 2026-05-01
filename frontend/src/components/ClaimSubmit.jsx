import { useState } from 'react'
import { Upload, Plus, Trash2, Send, AlertCircle, ChevronDown } from 'lucide-react'
import { submitClaim } from '../api.js'
import DecisionBadge from './DecisionBadge.jsx'
import TraceViewer from './TraceViewer.jsx'

const CATEGORIES = ['CONSULTATION', 'DIAGNOSTIC', 'PHARMACY', 'DENTAL', 'VISION', 'ALTERNATIVE_MEDICINE']
const DOC_TYPES = ['PRESCRIPTION', 'HOSPITAL_BILL', 'LAB_REPORT', 'PHARMACY_BILL', 'DISCHARGE_SUMMARY', 'DENTAL_REPORT', 'DIAGNOSTIC_REPORT']
const MEMBERS = [
  { id: 'EMP001', name: 'Rajesh Kumar' },
  { id: 'EMP002', name: 'Priya Singh' },
  { id: 'EMP003', name: 'Amit Verma' },
  { id: 'EMP004', name: 'Sneha Reddy' },
  { id: 'EMP005', name: 'Vikram Joshi (joined Sep 2024)' },
  { id: 'EMP006', name: 'Kavita Nair' },
  { id: 'EMP007', name: 'Suresh Patil' },
  { id: 'EMP008', name: 'Ravi Menon' },
  { id: 'EMP009', name: 'Anita Desai' },
  { id: 'EMP010', name: 'Deepak Shah' },
]

const DOC_QUALITIES = ['GOOD', 'DEGRADED', 'UNREADABLE']

function emptyDoc(idx) {
  return { file_id: `F${String(idx).padStart(3, '0')}`, actual_type: 'PRESCRIPTION', quality: 'GOOD', content: {}, patient_name_on_doc: '' }
}

export default function ClaimSubmit() {
  const [form, setForm] = useState({
    member_id: 'EMP001',
    policy_id: 'PLUM_GHI_2024',
    claim_category: 'CONSULTATION',
    treatment_date: '2024-11-01',
    claimed_amount: 1500,
    hospital_name: '',
    ytd_claims_amount: 0,
    simulate_component_failure: false,
  })
  const [documents, setDocuments] = useState([
    { ...emptyDoc(1), actual_type: 'PRESCRIPTION', content: { doctor_name: 'Dr. Arun Sharma', doctor_registration: 'KA/45678/2015', patient_name: 'Rajesh Kumar', diagnosis: 'Viral Fever', medicines: ['Paracetamol 650mg', 'Vitamin C 500mg'] } },
    { ...emptyDoc(2), actual_type: 'HOSPITAL_BILL', content: { hospital_name: 'City Clinic, Bengaluru', patient_name: 'Rajesh Kumar', line_items: [{ description: 'Consultation Fee', amount: 1000 }, { description: 'CBC Test', amount: 300 }, { description: 'Dengue NS1 Test', amount: 200 }], total: 1500 } },
  ])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [docJsonErrors, setDocJsonErrors] = useState({})

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const addDoc = () => setDocuments(d => [...d, emptyDoc(d.length + 1)])
  const removeDoc = (i) => setDocuments(d => d.filter((_, idx) => idx !== i))
  const updateDoc = (i, k, v) => setDocuments(d => d.map((doc, idx) => idx === i ? { ...doc, [k]: v } : doc))

  const updateDocContent = (i, text) => {
    try {
      const parsed = JSON.parse(text)
      updateDoc(i, 'content', parsed)
      setDocJsonErrors(e => ({ ...e, [i]: null }))
    } catch {
      setDocJsonErrors(e => ({ ...e, [i]: 'Invalid JSON' }))
    }
  }

  const handleSubmit = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const payload = {
        ...form,
        claimed_amount: parseFloat(form.claimed_amount),
        ytd_claims_amount: parseFloat(form.ytd_claims_amount) || 0,
        documents: documents.map(d => ({
          ...d,
          patient_name_on_doc: d.patient_name_on_doc || undefined,
        })),
      }
      const res = await submitClaim(payload)
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left — form */}
      <div className="space-y-5">
        <div className="card p-5">
          <h2 className="font-semibold text-slate-900 mb-4">Claim Details</h2>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Member</label>
              <select className="input" value={form.member_id} onChange={e => setField('member_id', e.target.value)}>
                {MEMBERS.map(m => <option key={m.id} value={m.id}>{m.id} — {m.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Category</label>
              <select className="input" value={form.claim_category} onChange={e => setField('claim_category', e.target.value)}>
                {CATEGORIES.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Treatment Date</label>
              <input type="date" className="input" value={form.treatment_date} onChange={e => setField('treatment_date', e.target.value)} />
            </div>
            <div>
              <label className="label">Claimed Amount (₹)</label>
              <input type="number" className="input" value={form.claimed_amount} onChange={e => setField('claimed_amount', e.target.value)} />
            </div>
            <div>
              <label className="label">Hospital Name (optional)</label>
              <input className="input" placeholder="e.g. Apollo Hospitals" value={form.hospital_name} onChange={e => setField('hospital_name', e.target.value)} />
            </div>
            <div>
              <label className="label">YTD Claims (₹)</label>
              <input type="number" className="input" value={form.ytd_claims_amount} onChange={e => setField('ytd_claims_amount', e.target.value)} />
            </div>
          </div>

          <label className="flex items-center gap-2 mt-3 cursor-pointer text-sm text-slate-600">
            <input type="checkbox" checked={form.simulate_component_failure} onChange={e => setField('simulate_component_failure', e.target.checked)} className="rounded" />
            Simulate component failure (TC011)
          </label>
        </div>

        {/* Documents */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-slate-900">Documents ({documents.length})</h2>
            <button onClick={addDoc} className="btn-secondary flex items-center gap-1.5 text-sm">
              <Plus size={14} /> Add Doc
            </button>
          </div>
          <div className="space-y-4">
            {documents.map((doc, i) => (
              <div key={i} className="border border-slate-200 rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-500">Document {i + 1}</span>
                  <button onClick={() => removeDoc(i)} className="text-slate-400 hover:text-red-500 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="label text-xs">File ID</label>
                    <input className="input text-xs" value={doc.file_id} onChange={e => updateDoc(i, 'file_id', e.target.value)} />
                  </div>
                  <div>
                    <label className="label text-xs">Document Type</label>
                    <select className="input text-xs" value={doc.actual_type} onChange={e => updateDoc(i, 'actual_type', e.target.value)}>
                      {DOC_TYPES.map(t => <option key={t}>{t}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label text-xs">Quality</label>
                    <select className="input text-xs" value={doc.quality} onChange={e => updateDoc(i, 'quality', e.target.value)}>
                      {DOC_QUALITIES.map(q => <option key={q}>{q}</option>)}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="label text-xs">Patient Name on Doc</label>
                  <input className="input text-xs" placeholder="Leave blank to skip cross-patient check" value={doc.patient_name_on_doc} onChange={e => updateDoc(i, 'patient_name_on_doc', e.target.value)} />
                </div>
                <div>
                  <label className="label text-xs">
                    Content JSON
                    {docJsonErrors[i] && <span className="ml-2 text-red-500 font-normal">{docJsonErrors[i]}</span>}
                  </label>
                  <textarea
                    className={`input text-xs font-mono h-24 resize-none ${docJsonErrors[i] ? 'border-red-400' : ''}`}
                    defaultValue={JSON.stringify(doc.content, null, 2)}
                    onChange={e => updateDocContent(i, e.target.value)}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading || Object.values(docJsonErrors).some(Boolean)}
          className="btn-primary w-full flex items-center justify-center gap-2"
        >
          {loading ? (
            <><span className="animate-spin">⟳</span> Processing...</>
          ) : (
            <><Send size={16} /> Submit Claim</>
          )}
        </button>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-start gap-2 text-red-700 text-sm">
            <AlertCircle size={16} className="shrink-0 mt-0.5" />
            {error}
          </div>
        )}
      </div>

      {/* Right — result */}
      <div>
        {result ? (
          <ResultPanel result={result} />
        ) : (
          <div className="card p-8 flex flex-col items-center justify-center text-slate-400 h-64">
            <Upload size={36} className="mb-3 opacity-40" />
            <p className="text-sm">Submit a claim to see the decision and full pipeline trace</p>
          </div>
        )}
      </div>
    </div>
  )
}

function ResultPanel({ result }) {
  const [showTrace, setShowTrace] = useState(false)

  return (
    <div className="space-y-4">
      {/* Decision card */}
      <div className="card p-5">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <DecisionBadge decision={result.decision} size="lg" />
              {result.degraded_pipeline && (
                <span className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full">⚡ Degraded</span>
              )}
            </div>
            <p className="text-xs text-slate-500">{result.claim_id}</p>
          </div>
          <div className="text-right">
            {result.approved_amount > 0 && (
              <p className="text-2xl font-bold text-slate-900">₹{result.approved_amount.toLocaleString()}</p>
            )}
            <p className="text-xs text-slate-500">
              Confidence: <span className={`font-semibold ${result.confidence_score > 0.8 ? 'text-emerald-600' : result.confidence_score > 0.5 ? 'text-amber-600' : 'text-red-600'}`}>
                {(result.confidence_score * 100).toFixed(0)}%
              </span>
            </p>
          </div>
        </div>

        {/* Rejection/halt messages */}
        {result.rejection_reasons?.length > 0 && (
          <div className="space-y-2 mb-3">
            {result.rejection_reasons.map((r, i) => (
              <div key={i} className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">{r}</div>
            ))}
          </div>
        )}

        {/* Line items */}
        {result.line_item_decisions?.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-semibold text-slate-600 mb-2">Line Items</p>
            <div className="rounded-lg overflow-hidden border border-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left px-3 py-2 text-slate-600">Description</th>
                    <th className="text-right px-3 py-2 text-slate-600">Claimed</th>
                    <th className="text-right px-3 py-2 text-slate-600">Approved</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {result.line_item_decisions.map((li, i) => (
                    <tr key={i} className={`border-t border-slate-100 ${li.decision === 'REJECTED' ? 'bg-red-50' : ''}`}>
                      <td className="px-3 py-2">{li.description}</td>
                      <td className="px-3 py-2 text-right text-slate-600">₹{li.claimed_amount.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right font-medium">
                        {li.decision === 'APPROVED' ? `₹${li.approved_amount.toLocaleString()}` : '—'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${li.decision === 'APPROVED' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                          {li.decision}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Claimed vs approved summary */}
        <div className="mt-3 pt-3 border-t border-slate-100 grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-slate-500">Claimed</span>
            <p className="font-semibold">₹{result.claimed_amount?.toLocaleString()}</p>
          </div>
          <div>
            <span className="text-slate-500">Approved</span>
            <p className={`font-semibold ${result.approved_amount > 0 ? 'text-emerald-600' : 'text-slate-500'}`}>
              ₹{result.approved_amount?.toLocaleString() || '0'}
            </p>
          </div>
        </div>
      </div>

      {/* Explanation */}
      {result.explanation && (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-2">Decision Explanation</h3>
          <pre className="text-xs text-slate-600 whitespace-pre-wrap font-mono bg-slate-50 rounded-lg p-3 overflow-auto max-h-48">{result.explanation}</pre>
        </div>
      )}

      {/* Trace */}
      {result.trace?.length > 0 && (
        <div className="card p-5">
          <button
            onClick={() => setShowTrace(t => !t)}
            className="w-full flex items-center justify-between text-sm font-semibold text-slate-700"
          >
            Pipeline Trace
            <ChevronDown size={16} className={`text-slate-400 transition-transform ${showTrace ? 'rotate-180' : ''}`} />
          </button>
          {showTrace && (
            <div className="mt-3">
              <TraceViewer
                trace={result.trace}
                componentFailures={result.component_failures}
                degraded={result.degraded_pipeline}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
