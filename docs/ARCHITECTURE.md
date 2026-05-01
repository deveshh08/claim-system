# Architecture Document — Plum Claims Processing System

## System Overview

A multi-agent pipeline that automates health insurance claim adjudication. The system accepts a claim submission (member details, documents, treatment metadata), routes it through specialized agents, and produces a deterministic, fully-explainable decision — APPROVED, PARTIAL, REJECTED, or MANUAL_REVIEW — with a full audit trace.

---

## Architecture Diagram

```
                        ┌─────────────────────────────────────────────────┐
                        │              ClaimOrchestrator                  │
                        │                                                 │
  ClaimInput ──────────►│  Stage 1: DocumentVerificationAgent  (Gate)     │
                        │         ↓ (halt if failed)                      │
                        │  Stage 2: DocumentExtractionAgent               │
                        │         ↓                                       │
                        │  Stage 3: FraudDetectionAgent   ─── parallel ──►│
                        │  Stage 4: PolicyEngine          ─── (future)    │
                        │         ↓                                       │
                        │  Stage 5: DecisionMaker                        │
                        │                                                 │
  DecisionResult ◄──────│          (trace attached to output)             │
                        └─────────────────────────────────────────────────┘
```

---

## Components

### 1. DocumentVerificationAgent
**Responsibility:** Gate check before any LLM call or policy evaluation. Fast, deterministic, no external dependencies.

**What it checks:**
- Required document types are present for the claim category (from `policy_terms.json`)
- No unreadable documents (quality = UNREADABLE)
- All documents belong to the same patient (cross-patient name detection)

**Why it's first:** Failing fast saves LLM tokens and avoids producing a claim decision based on fundamentally invalid inputs. Error messages must be specific and actionable — not generic.

**Design decision:** Sync-only, no I/O. Runs in < 5ms. Could be a pure function but structured as an agent for uniform tracing.

---

### 2. DocumentExtractionAgent
**Responsibility:** Extract structured fields from uploaded documents.

**Two modes:**
- **Test mode:** Documents carry a pre-filled `content` dict — agent normalises and returns it directly at full confidence.
- **Production mode:** Documents carry raw bytes — agent calls Claude vision API with a structured extraction prompt, parses the JSON response, handles extraction failures per-document without failing the pipeline.

**Confidence scoring:** Each extracted document gets a `extraction_confidence` (0–1). Quality degradations (DEGRADED → 0.6 cap, UNREADABLE → 0.1 cap), LLM failures (0.0), and partial content reduce this. The average propagates to the final confidence score.

**Design decision:** Failures are per-document, not per-pipeline. If document F002 fails extraction, F001's data is still used. The agent never raises — it returns a placeholder ExtractedDocument with confidence=0.0 and an error flag.

---

### 3. PolicyEngine
**Responsibility:** Apply all coverage rules from `policy_terms.json` against the claim and extracted data.

**Checks (in order):**
1. Member eligibility
2. Submission deadline (30 days from treatment)
3. Minimum claim amount (₹500)
4. Initial 30-day waiting period
5. Condition-specific waiting periods (diabetes 90d, mental health 180d, etc.)
6. Exclusions (bariatric, cosmetic, LASIK, etc.)
7. Pre-authorization requirements (MRI/CT > ₹10,000)
8. Per-claim limit (₹5,000)
9. Category sub-limits
10. Dental/Vision line-item include/exclude (procedure-level)
11. Network discount (applied first)
12. Co-pay (applied after network discount)

**Design decision:** Every check appends to a `checks_performed` list — this is the audit trail. Early returns are used for hard failures; the trace always shows exactly which check failed and why.

**Policy data:** Zero hardcoded rules. All thresholds, lists, and flags read from `policy_terms.json` via `PolicyLoader`. Adding a new exclusion requires only editing the JSON.

---

### 4. FraudDetectionAgent
**Responsibility:** Score the claim for fraud signals.

**Signals:**
- Same-day claim count ≥ threshold (adds 0.45 to score)
- Monthly claim count ≥ threshold (adds 0.25)
- High-value claim above ₹25,000 (adds 0.15)
- Auto-review threshold exceeded (adds 0.10)
- Document alteration flags from extraction (adds 0.20 each)

**Decision:** Score ≥ 0.80 → MANUAL_REVIEW (never auto-reject). Human judgment is required for fraud.

**Design decision:** Fraud never causes a hard REJECTED. Auto-rejection for fraud would be legally and operationally risky.

---

### 5. DecisionMaker
**Responsibility:** Aggregate PolicyEngine + FraudDetectionAgent outputs into a final decision.

**Logic:**
```
fraud.requires_manual_review  → MANUAL_REVIEW
not policy.eligible           → REJECTED
some line items excluded      → PARTIAL (if approved_amount > 0) else REJECTED
approved_amount < claimed * 0.99 → PARTIAL
otherwise                     → APPROVED
```

**Confidence formula:**
```
confidence = base_confidence × extraction_confidence - fraud_penalty - degradation_penalty
           = 0.95 × avg_doc_conf - (fraud_score × 0.3) - (num_failures × 0.20)
```

**Explanation:** Every decision includes a human-readable explanation string with all checks, financial breakdown, fraud signals, and component failures. Operations team can reconstruct exactly why any decision was made from this string alone.

---

### 6. ClaimOrchestrator
**Responsibility:** Pipeline coordinator. Owns the execution order, handles per-stage failures, assembles the trace.

**Failure handling:**
- Stage 1 failure → halt, return immediately (no decision)
- Stage 2–4 failure → continue with empty/sentinel result, add to `component_failures`
- Stage 5 always runs — DecisionMaker never fails
- No exception propagates to the API layer

---

## API Layer (FastAPI)

```
POST /api/claims              — JSON submission (test mode)
POST /api/claims/upload       — Multipart file upload (production mode)
GET  /api/claims/{id}         — Retrieve processed claim
GET  /api/claims              — List all claims
POST /api/eval/run            — Run all 12 test cases
GET  /api/policy              — Policy summary
GET  /api/health              — Liveness probe
```

In-memory claim store (dict). Replace with PostgreSQL at scale.

---

## Frontend (React + Vite + Tailwind)

Four views:
1. **Submit Claim** — full form with document builder, content JSON editor, real-time validation
2. **Claims Review** — searchable table with expandable trace per claim
3. **Eval Runner** — runs all 12 TCs and shows pass/fail with per-case trace
4. **Dashboard** — policy summary, member roster, coverage categories, waiting periods, exclusions

---

## Design Decisions and Trade-offs

### What was chosen and why

**Multi-agent over monolith:** Each agent has a single responsibility, a typed interface, and can fail independently. This makes testing trivial — you can unit-test PolicyEngine by passing a synthetic ExtractedDocument without touching the LLM.

**Pydantic schemas for all inter-agent data:** Every agent input/output is a typed Pydantic model. This catches integration bugs at runtime rather than silently passing dicts. It also makes the component contracts self-documenting.

**JSON-driven policy, zero hardcoded rules:** The `PolicyLoader` reads `policy_terms.json` at startup and caches it. Changing a waiting period or adding a new exclusion requires no code change.

**Test mode vs. production mode in extraction:** Documents can carry pre-extracted `content` dicts for testing without touching the Anthropic API. This lets you run all 12 test cases in CI with no API key.

**Fraud → MANUAL_REVIEW, never REJECTED:** Fraud signals are probabilistic. Auto-rejection based on a score would generate false positives and create legal liability. The threshold routes to a human.

**Confidence score as a first-class output:** Confidence degrades with extraction quality, fraud signals, and component failures. This gives the ops team a triage signal — low-confidence approvals get reviewed first.

### What was cut and why

**Async agent execution (Stages 3 + 4 in parallel):** FraudDetectionAgent and PolicyEngine are independent — they could run concurrently. This was skipped in v1 to keep the code simple and because both are fast (< 50ms each). At scale, `asyncio.gather` would be the obvious next step.

**Persistent database:** Claims are stored in-memory. At production scale, replace with PostgreSQL + SQLAlchemy. The DecisionResult model is ready to be persisted as-is.

**OCR pre-processing:** Real documents need image pre-processing (deskew, contrast normalisation) before Claude vision. Skipped to stay within scope — would add OpenCV or Tesseract as a pre-processing step before `_extract_via_llm`.

**Pre-authorization approval lookup:** The policy checks whether pre-auth is required but assumes no pre-auth has been obtained (no `pre_auth_id` on the ClaimInput). A real system would query the insurer's pre-auth API.

**Member's YTD spend tracking:** The policy has an annual OPD limit (₹50,000), but tracking cumulative spend requires a persistent claims history per member. Skipped — the model accepts `ytd_claims_amount` as an input but the check is not enforced.

---

## Scaling to 10x Load

| Current | At 10x |
|---------|--------|
| In-memory claim store | PostgreSQL with claim_id as PK, indexed by member_id + date |
| Sync pipeline per request | Async FastAPI + background task queue (Celery/RQ) |
| Single process | Horizontal scaling behind a load balancer |
| No caching | Redis cache for PolicyLoader (policy rarely changes) |
| Stages 3+4 sequential | `asyncio.gather` for parallel execution |
| LLM call per document | Batch API for bulk re-processing; rate limit handling |
| No observability | OpenTelemetry traces per claim_id, exported to Datadog/Jaeger |

The architecture is already prepared for this: the orchestrator can be made async with minimal changes, and the claim store is the only stateful component that needs replacing.

---

## Limitations of Current Design

1. **No YTD spend enforcement** — annual OPD limit not enforced because member history isn't persisted.
2. **Pre-auth is always assumed missing** — works correctly for TC007 but would reject legitimate pre-authed claims.
3. **Cross-patient detection is name-string matching** — normalisation (lowercase, strip) but no fuzzy matching. "Rajesh Kumar" vs "R. Kumar" would not be flagged.
4. **LLM extraction confidence is self-reported** — the model reports its own confidence. A calibration layer (comparing reported vs. actual accuracy) would make this more reliable at scale.
5. **Single-tenant** — policy_terms.json is a single file. Multi-tenant would require a policy registry keyed by company/policy_id.
