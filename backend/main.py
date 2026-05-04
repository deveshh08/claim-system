"""
main.py — FastAPI application entry point.

Routes:
  POST /api/claims              — submit a claim (JSON body)
  POST /api/claims/upload       — submit a claim with file uploads (multipart)
  GET  /api/claims/{claim_id}   — retrieve a previously processed claim
  GET  /api/health              — liveness probe
  GET  /api/policy              — return loaded policy summary
  POST /api/eval/run            — run all test cases and return report
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env file if present (for local development)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed (production doesn't need it)

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add backend root to path so relative imports work
sys.path.insert(0, str(Path(__file__).parent))

from agents.orchestrator import ClaimOrchestrator
from config.policy_loader import get_policy
from models.schemas import (
    ClaimCategory,
    ClaimHistoryEntry,
    ClaimInput,
    DecisionResult,
    DocumentInput,
    DocumentQuality,
    DocumentType,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Plum Claims Processing API",
    description="Multi-agent health insurance claims processing system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Local dev
        "https://claim-system-11.onrender.com",  # Production frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory claim store (replace with DB at scale)
_claim_store: Dict[str, DecisionResult] = {}
_orchestrator = ClaimOrchestrator()


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/policy")
def get_policy_summary():
    p = get_policy()
    return {
        "policy_id": p.policy_id,
        "sum_insured": p.sum_insured,
        "per_claim_limit": p.per_claim_limit,
        "annual_opd_limit": p.annual_opd_limit,
        "network_hospitals": p._raw["network_hospitals"],
        "members": [
            {"member_id": m["member_id"], "name": m["name"], "relationship": m["relationship"]}
            for m in p._raw["members"]
        ],
    }


@app.post("/api/claims", response_model=Dict[str, Any])
def submit_claim_json(claim: ClaimInput):
    """Submit a claim via JSON (test mode — documents have pre-filled content)."""
    try:
        result = _orchestrator.process(claim)
        _claim_store[result.claim_id] = result
        return _serialise(result)
    except Exception as exc:
        logger.exception("Unhandled error in claim processing")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/claims/upload", response_model=Dict[str, Any])
async def submit_claim_upload(
    member_id: str = Form(...),
    policy_id: str = Form(...),
    claim_category: str = Form(...),
    treatment_date: str = Form(...),
    claimed_amount: float = Form(...),
    hospital_name: Optional[str] = Form(None),
    ytd_claims_amount: float = Form(0.0),
    files: List[UploadFile] = File(default=[]),
):
    """Submit a claim with real file uploads (production mode)."""
    docs = []
    for i, upload in enumerate(files):
        content = await upload.read()
        mime = upload.content_type or "image/jpeg"
        docs.append(DocumentInput(
            file_id=f"F{i+1:03d}-{uuid.uuid4().hex[:6]}",
            file_name=upload.filename,
            mime_type=mime,
            file_bytes=content,
        ))

    try:
        cat = ClaimCategory(claim_category.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid claim_category: {claim_category}")

    claim = ClaimInput(
        member_id=member_id,
        policy_id=policy_id,
        claim_category=cat,
        treatment_date=treatment_date,
        claimed_amount=claimed_amount,
        hospital_name=hospital_name,
        ytd_claims_amount=ytd_claims_amount,
        documents=docs,
    )

    try:
        result = _orchestrator.process(claim)
        _claim_store[result.claim_id] = result
        return _serialise(result)
    except Exception as exc:
        logger.exception("Unhandled error in claim processing")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/claims/{claim_id}", response_model=Dict[str, Any])
def get_claim(claim_id: str):
    result = _claim_store.get(claim_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return _serialise(result)


@app.get("/api/claims", response_model=List[Dict[str, Any]])
def list_claims():
    return [_serialise(r) for r in _claim_store.values()]


@app.post("/api/eval/run")
def run_eval():
    """Run all 12 test cases and return the eval report."""
    test_file = Path(__file__).parent / "tests" / "test_cases.json"
    if not test_file.exists():
        raise HTTPException(status_code=404, detail="test_cases.json not found")

    with open(test_file) as f:
        test_data = json.load(f)

    results = []
    for tc in test_data["test_cases"]:
        try:
            claim = _build_claim_from_tc(tc)
            result = _orchestrator.process(claim)
            results.append({
                "case_id": tc["case_id"],
                "case_name": tc["case_name"],
                "expected": tc["expected"],
                "actual": _serialise(result),
                "matched": _eval_match(tc["expected"], result),
            })
        except Exception as exc:
            results.append({
                "case_id": tc["case_id"],
                "case_name": tc["case_name"],
                "expected": tc["expected"],
                "actual": {"error": str(exc)},
                "matched": False,
            })

    passed = sum(1 for r in results if r["matched"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialise(result: DecisionResult) -> Dict[str, Any]:
    return result.model_dump(mode="json")


def _build_claim_from_tc(tc: Dict[str, Any]) -> ClaimInput:
    inp = tc["input"]
    docs = []
    for d in inp.get("documents", []):
        docs.append(DocumentInput(
            file_id=d.get("file_id", f"F{len(docs)+1:03d}"),
            file_name=d.get("file_name"),
            actual_type=DocumentType(d["actual_type"]) if d.get("actual_type") else None,
            quality=DocumentQuality(d["quality"]) if d.get("quality") else DocumentQuality.GOOD,
            content=d.get("content"),
            patient_name_on_doc=d.get("patient_name_on_doc"),
        ))

    history = []
    for h in inp.get("claims_history", []):
        history.append(ClaimHistoryEntry(
            claim_id=h["claim_id"],
            date=h["date"],
            amount=h["amount"],
            provider=h.get("provider"),
        ))

    return ClaimInput(
        member_id=inp["member_id"],
        policy_id=inp["policy_id"],
        claim_category=ClaimCategory(inp["claim_category"]),
        treatment_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        hospital_name=inp.get("hospital_name"),
        ytd_claims_amount=inp.get("ytd_claims_amount", 0.0),
        claims_history=history,
        documents=docs,
        simulate_component_failure=inp.get("simulate_component_failure", False),
    )


def _eval_match(expected: Dict[str, Any], result: DecisionResult) -> bool:
    """Lightweight match — checks decision and, where given, approved_amount."""
    exp_decision = expected.get("decision")

    # Cases where no decision is expected (doc failure cases TC001-TC003)
    if exp_decision is None:
        return result.decision is None

    if result.decision is None:
        return False

    if result.decision.value != exp_decision:
        return False

    # Check approved amount if given (allow 1% tolerance)
    exp_amount = expected.get("approved_amount")
    if exp_amount is not None:
        tol = max(1.0, abs(exp_amount) * 0.02)
        if abs(result.approved_amount - float(exp_amount)) > tol:
            return False

    return True


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
