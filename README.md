# Plum Claims Processing System

Multi-agent health insurance claims processing pipeline. Automates claim adjudication with full explainability, graceful failure handling, and a React UI.

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+

### Backend

```bash
cd backend
pip install -r requirements.txt
python main.py
# API running at http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# UI at http://localhost:5173
```

### Run Tests

```bash
cd backend
pytest tests/test_agents.py -v          # 30 unit tests
python -m tests.run_eval                # 12 integration test cases
```

---

## Architecture

Five-agent sequential pipeline:

```
ClaimInput
    │
    ▼
[1] DocumentVerificationAgent   ← Gate: halts on bad docs, specific error messages
    │
    ▼
[2] DocumentExtractionAgent     ← Extracts structured fields (test: content dict / prod: Claude vision)
    │
    ▼
[3] FraudDetectionAgent         ← Scores fraud signals; ≥0.80 → MANUAL_REVIEW
    │
[4] PolicyEngine                ← Applies all rules from policy_terms.json
    │
    ▼
[5] DecisionMaker               ← APPROVED | PARTIAL | REJECTED | MANUAL_REVIEW
    │
    ▼
DecisionResult (with full trace)
```

See `docs/ARCHITECTURE.md` for full design decisions, trade-offs, and scaling plan.  
See `docs/COMPONENT_CONTRACTS.md` for per-agent input/output contracts.  
See `docs/EVAL_REPORT.md` for 12/12 test case results.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/claims` | Submit claim (JSON/test mode) |
| POST | `/api/claims/upload` | Submit claim (multipart file upload) |
| GET | `/api/claims` | List all claims |
| GET | `/api/claims/{id}` | Get single claim with trace |
| POST | `/api/eval/run` | Run all 12 test cases |
| GET | `/api/policy` | Policy summary |
| GET | `/api/health` | Liveness probe |
| GET | `/docs` | FastAPI auto-docs (Swagger) |

---

## Project Structure

```
claims_system/
├── backend/
│   ├── main.py                     # FastAPI app
│   ├── policy_terms.json           # Policy config (source of truth)
│   ├── requirements.txt
│   ├── agents/
│   │   ├── orchestrator.py         # Pipeline coordinator
│   │   ├── document_verifier.py    # Stage 1: Gate check
│   │   ├── document_extractor.py   # Stage 2: LLM extraction
│   │   ├── fraud_detector.py       # Stage 3: Fraud scoring
│   │   ├── policy_engine.py        # Stage 4: Coverage rules
│   │   └── decision_maker.py       # Stage 5: Final decision
│   ├── config/
│   │   └── policy_loader.py        # JSON policy loader
│   ├── models/
│   │   └── schemas.py              # All Pydantic models
│   └── tests/
│       ├── test_agents.py          # 30 unit tests
│       ├── run_eval.py             # 12 TC eval runner
│       └── test_cases.json         # Test fixtures
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   └── components/
│   │       ├── ClaimSubmit.jsx     # Submit form with document builder
│   │       ├── ClaimsList.jsx      # Review table with traces
│   │       ├── EvalRunner.jsx      # 12-TC eval UI
│   │       ├── Dashboard.jsx       # Policy summary
│   │       ├── DecisionBadge.jsx   # Decision status badge
│   │       └── TraceViewer.jsx     # Pipeline trace accordion
│   └── package.json
└── docs/
    ├── ARCHITECTURE.md
    ├── COMPONENT_CONTRACTS.md
    └── EVAL_REPORT.md
```

---

## Key Design Decisions

**Policy is data, not code.** Every rule — waiting periods, exclusions, sub-limits, co-pay percentages, network hospitals — is read from `policy_terms.json`. Adding a new exclusion requires no code change.

**Failures are per-agent, not per-pipeline.** If document extraction fails for one file, the other files are still processed. If the extraction agent crashes entirely, the pipeline continues with reduced confidence and flags `degraded_pipeline=true`.

**Every decision is explainable.** The `explanation` field on every `DecisionResult` contains a human-readable audit trail listing every check, its result, and the financial breakdown. Operations can reconstruct exactly why any decision was made.

**Fraud never auto-rejects.** Fraud signals route to `MANUAL_REVIEW`. Auto-rejection based on a probabilistic score is legally and operationally risky.

**Check ordering is deliberate:**
1. Exclusions before waiting periods — permanently excluded treatments get a clearer rejection reason
2. Pre-authorization before per-claim limit — planned procedures get the actionable "get pre-auth" message
3. Network discount before co-pay — invariant financial calculation

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key for document extraction (vision model) | Yes |

**Local development:**
1. Copy `.env.example` to `.env`
2. Add your Gemini API key
3. Install dev dependencies: `pip install -r backend/requirements-dev.txt`

**Production (Render):**
Set `GEMINI_API_KEY` in the Render dashboard Environment tab.

---

