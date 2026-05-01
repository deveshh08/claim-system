const BASE = '/api'

export async function submitClaim(claimPayload) {
  const res = await fetch(`${BASE}/claims`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(claimPayload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Submission failed')
  }
  return res.json()
}

export async function listClaims() {
  const res = await fetch(`${BASE}/claims`)
  if (!res.ok) throw new Error('Failed to load claims')
  return res.json()
}

export async function getClaim(id) {
  const res = await fetch(`${BASE}/claims/${id}`)
  if (!res.ok) throw new Error('Claim not found')
  return res.json()
}

export async function runEval() {
  const res = await fetch(`${BASE}/eval/run`, { method: 'POST' })
  if (!res.ok) throw new Error('Eval failed')
  return res.json()
}

export async function getPolicy() {
  const res = await fetch(`${BASE}/policy`)
  if (!res.ok) throw new Error('Failed to load policy')
  return res.json()
}
