# Component Contracts

Every significant component in the pipeline. Each section is precise enough that another engineer could reimplement the component from this document alone without reading the code.

---

## 1. DocumentVerificationAgent

### Input
```python
ClaimInput:
  member_id:        str                    # e.g. "EMP001"
  policy_id:        str                    # e.g. "PLUM_GHI_2024"
  claim_category:   ClaimCategory          # CONSULTATION | DIAGNOSTIC | PHARMACY | DENTAL | VISION | ALTERNATIVE_MEDICINE
  treatment_date:   str                    # ISO date "YYYY-MM-DD"
  claimed_amount:   float                  # in INR
  documents:        List[DocumentInput]
    file_id:          str
    actual_type:      Optional[DocumentType]   # PRESCRIPTION | HOSPITAL_BILL | LAB_REPORT | ...
    quality:          Optional[DocumentQuality] # GOOD | DEGRADED | UNREADABLE
    content:          Optional[Dict]
    patient_name_on_doc: Optional[str]
```

### Output
```python
DocumentVerificationResult:
  agent_name:              str = "DocumentVerificationAgent"
  status:                  AgentStatus   # SUCCESS | FAILED
  passed:                  bool
  issues:                  List[str]     # human-readable, actionable — empty if passed=True
  missing_document_types:  List[DocumentType]
  uploaded_instead:        List[DocumentType]
  cross_patient_names:     Optional[Dict[str, str]]   # file_id → patient_name
  unreadable_file_ids:     List[str]
  duration_ms:             float
  error:                   Optional[str]   # set only if agent itself crashed
```

### Behaviour contract
- `passed=True` iff `issues` is empty
- If `passed=False`, the pipeline MUST halt — no downstream agent runs
- Each entry in `issues` MUST name the specific document type(s) involved — never a generic message
- If two documents have different patient names, `cross_patient_names` is populated and `passed=False`
- If any document has `quality=UNREADABLE`, its `file_id` appears in `unreadable_file_ids` and `passed=False`
- Never raises — all failures captured in `status=FAILED` + `error`

### Errors raised
None. All errors are captured in the result.

---

## 2. DocumentExtractionAgent

### Input
```python
ClaimInput  # same as above; uses documents[].content (test mode) or documents[].file_bytes (prod)
```

### Output
```python
DocumentExtractionResult:
  agent_name:                    str = "DocumentExtractionAgent"
  status:                        AgentStatus   # SUCCESS | PARTIAL | FAILED
  documents:                     List[ExtractedDocument]
  overall_extraction_confidence: float         # 0–1; avg of per-document confidences
  error:                         Optional[str]
  duration_ms:                   float

ExtractedDocument:
  file_id:               str
  document_type:         DocumentType
  quality:               DocumentQuality
  patient_name:          Optional[str]
  doctor_name:           Optional[str]
  doctor_registration:   Optional[str]
  hospital_name:         Optional[str]
  treatment_date:        Optional[str]
  diagnosis:             Optional[str]
  medicines:             List[str]
  tests_ordered:         List[str]
  line_items:            List[{"description": str, "amount": float}]
  total_amount:          Optional[float]
  lab_results:           List[{"test": str, "result": str, "unit": str, "normal_range": str}]
  extraction_confidence: float   # 0–1
  low_confidence_fields: List[str]
  flags:                 List[str]   # DOCUMENT_ALTERATION | RUBBER_STAMP_OVER_TEXT | HANDWRITTEN | ...
  raw_content:           Optional[Dict]
```

### Behaviour contract
- If a single document fails extraction, a placeholder ExtractedDocument (confidence=0.0, flags=["EXTRACTION_ERROR:..."]) is appended; other documents are unaffected
- `status=PARTIAL` if any document failed; `status=FAILED` only if ALL documents failed
- `overall_extraction_confidence` = mean of per-document `extraction_confidence` values
- UNREADABLE quality caps confidence at 0.1; DEGRADED caps at 0.6
- Never raises

---

## 3. PolicyEngine

### Input
```python
claim:     ClaimInput
extraction: DocumentExtractionResult
```

### Output
```python
PolicyCheckResult:
  agent_name:              str = "PolicyEngine"
  status:                  AgentStatus
  eligible:                bool
  rejection_reasons:       List[str]        # machine-readable codes + human detail
  approved_amount:         float            # 0.0 if not eligible
  line_item_decisions:     List[LineItemDecision]
  copay_amount:            float
  network_discount_amount: float
  is_network_hospital:     bool
  waiting_period_end_date: Optional[str]   # ISO date; set when rejected for waiting period
  checks_performed:        List[{"check": str, "passed": bool, "detail": str}]
  duration_ms:             float
  error:                   Optional[str]

LineItemDecision:
  description:     str
  claimed_amount:  float
  approved_amount: float
  decision:        str    # "APPROVED" | "REJECTED"
  reason:          Optional[str]
```

### Check order (invariant — must be preserved by any reimplementation)
1. `member_eligibility` — member exists in policy roster
2. `submission_deadline` — treatment_date within 30 days of today
3. `minimum_claim_amount` — claimed_amount ≥ ₹500
4. `initial_waiting_period` — treatment_date ≥ join_date + 30 days
5. `waiting_period_{condition}` — condition-specific waiting period (if diagnosis matches)
6. `exclusion_check` — diagnosis/treatment not in exclusions list
7. `pre_authorization` — pre-auth obtained if required
8. `per_claim_limit` — claimed_amount ≤ ₹5,000
9. `dental_line_item:{desc}` / `vision_line_item:{desc}` — procedure-level include/exclude
10. `network_hospital` — informational (no rejection)
11. `network_discount` — informational (shows calculation)
12. `copay` — informational (shows calculation)

### Financial calculation (invariant)
```
base_amount = claimed_amount (or sum of approved line items for DENTAL/VISION)
after_network = base_amount - (base_amount × network_discount_pct / 100)   [only if network hospital]
approved_amount = after_network - (after_network × copay_pct / 100)
```
Network discount is ALWAYS applied before co-pay.

### Behaviour contract
- Returns after first hard failure (checks 1–8) — subsequent checks not run
- Checks 9–12 are always run if check 8 passes
- `checks_performed` contains every check that ran, regardless of pass/fail
- `eligible=False` iff `rejection_reasons` is non-empty
- Never raises

---

## 4. FraudDetectionAgent

### Input
```python
claim:     ClaimInput   # uses claims_history and claimed_amount
extraction: DocumentExtractionResult   # uses document flags
```

### Output
```python
FraudCheckResult:
  agent_name:            str = "FraudDetectionAgent"
  status:                AgentStatus
  fraud_score:           float       # 0–1; capped at 1.0
  fraud_signals:         List[str]   # human-readable descriptions of each signal
  requires_manual_review: bool       # True iff fraud_score ≥ 0.80
  same_day_claim_count:  int
  duration_ms:           float
  error:                 Optional[str]
```

### Scoring weights (from policy_terms.json fraud_thresholds)
| Signal | Weight |
|--------|--------|
| same_day_claims ≥ limit | +0.45 |
| monthly_claims ≥ limit | +0.25 |
| claimed_amount ≥ high_value_threshold | +0.15 |
| claimed_amount > auto_review_threshold | +0.10 |
| DOCUMENT_ALTERATION flag (per doc) | +0.20 |

### Behaviour contract
- `requires_manual_review=True` routes to MANUAL_REVIEW in DecisionMaker; never causes REJECTED
- `fraud_score` is capped at 1.0
- If no signals triggered, `fraud_signals=[]` and `fraud_score=0.0`
- Never raises

---

## 5. DecisionMaker

### Input
```python
claim:             ClaimInput
policy:            PolicyCheckResult
fraud:             FraudCheckResult
extraction:        DocumentExtractionResult
component_failures: List[str]   # names of agents that failed
```

### Output
```python
DecisionResult:
  claim_id:             str      # "CLM-{8 hex chars}"
  member_id:            str
  claim_category:       str
  claimed_amount:       float
  decision:             ClaimDecision   # APPROVED | PARTIAL | REJECTED | MANUAL_REVIEW | None
  approved_amount:      float
  confidence_score:     float   # 0–1
  rejection_reasons:    List[str]
  line_item_decisions:  List[LineItemDecision]
  explanation:          str     # full human-readable audit trail
  component_failures:   List[str]
  degraded_pipeline:    bool
  trace:                List[AgentResult]
  created_at:           str   # ISO datetime UTC
```

### Decision logic (invariant)
```
if fraud.requires_manual_review         → MANUAL_REVIEW
elif not policy.eligible                → REJECTED
elif any line_item.decision == REJECTED:
  if sum(approved line items) == 0      → REJECTED
  else                                  → PARTIAL
elif approved_amount < claimed * 0.99   → PARTIAL (if > 0) else REJECTED
else                                    → APPROVED
```

### Confidence formula (invariant)
```
base      = 0.95 if APPROVED/PARTIAL else 0.92
ext_conf  = extraction.overall_extraction_confidence
fraud_pen = fraud.fraud_score × 0.3
deg_pen   = len(component_failures) × 0.20
confidence = max(0.05, base × ext_conf − fraud_pen − deg_pen)
```

### Explanation contract
The `explanation` string MUST contain:
- Claim summary (member, category, amount)
- All policy checks with pass/fail and detail
- Rejection reasons (if any)
- Financial breakdown (base → discount → copay → approved)
- Fraud signals (if any)
- Document extraction confidence per document
- Component failures (if any)

### Behaviour contract
- Always produces a result — never raises
- `decision=None` only when called after DocumentVerificationAgent failure (orchestrator sets this directly)
- `degraded_pipeline=True` iff `component_failures` is non-empty

---

## 6. ClaimOrchestrator

### Input
```python
ClaimInput
```

### Output
```python
DecisionResult   # trace field populated with all AgentResult objects from the run
```

### Stage contract
```
Stage 1: DocumentVerificationAgent
  → if not passed: return DecisionResult(decision=None, rejection_reasons=issues, trace=[verification_result])
  → else: continue

Stage 2: DocumentExtractionAgent
  → on agent exception: use empty extraction + append to component_failures; continue

Stage 3: FraudDetectionAgent
  → on agent exception: use empty fraud result + append to component_failures; continue

Stage 4: PolicyEngine
  → on agent exception: use sentinel rejection result + append to component_failures; continue

Stage 5: DecisionMaker
  → always runs; output.trace = [s1_result, s2_result, s3_result, s4_result]
```

### Behaviour contract
- Only halts at Stage 1
- Component failures reduce confidence score but do not prevent a decision
- Every AgentResult is included in the trace regardless of status
- Never raises — the API layer never receives a 500 from a pipeline bug

---

## 7. PolicyLoader

### Input
```python
path: str   # path to policy_terms.json; defaults to ../policy_terms.json
```

### Key methods
```python
get_member(member_id: str) → Optional[Dict]
is_network_hospital(hospital_name: Optional[str]) → bool
get_category_rules(category: str) → Optional[Dict]
get_required_documents(category: str) → List[str]
get_waiting_period_for_diagnosis(diagnosis: str) → Optional[Tuple[str, int]]
is_excluded_condition(diagnosis: str, treatment: str) → Optional[str]
is_excluded_dental_procedure(procedure: str) → bool
is_excluded_vision_item(item: str) → bool
requires_pre_auth(category: str, amount: float, documents: List[Dict]) → bool
```

### Behaviour contract
- Singleton via `@lru_cache` — loaded once per process
- All lookups are case-insensitive substring matches (not exact equality)
- `get_waiting_period_for_diagnosis` returns `(condition_key, days)` for the first matched keyword
- Never raises after successful load
