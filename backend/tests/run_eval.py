"""
run_eval.py — runs all 12 test cases through the pipeline and prints a report.

Usage:
    cd backend
    python -m tests.run_eval

Output: console table + eval_report.json written to tests/
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from typing import Any, Dict, List

# Add backend root so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.orchestrator import ClaimOrchestrator
from models.schemas import (
    ClaimCategory,
    ClaimHistoryEntry,
    ClaimInput,
    DocumentInput,
    DocumentQuality,
    DocumentType,
)


def build_claim(tc_input: Dict[str, Any]) -> ClaimInput:
    docs = []
    for d in tc_input.get("documents", []):
        docs.append(DocumentInput(
            file_id=d.get("file_id", "F001"),
            file_name=d.get("file_name"),
            actual_type=DocumentType(d["actual_type"]) if d.get("actual_type") else None,
            quality=DocumentQuality(d["quality"]) if d.get("quality") else DocumentQuality.GOOD,
            content=d.get("content"),
            patient_name_on_doc=d.get("patient_name_on_doc"),
        ))

    history = []
    for h in tc_input.get("claims_history", []):
        history.append(ClaimHistoryEntry(
            claim_id=h["claim_id"],
            date=h["date"],
            amount=h["amount"],
            provider=h.get("provider"),
        ))

    return ClaimInput(
        member_id=tc_input["member_id"],
        policy_id=tc_input["policy_id"],
        claim_category=ClaimCategory(tc_input["claim_category"]),
        treatment_date=tc_input["treatment_date"],
        claimed_amount=tc_input["claimed_amount"],
        hospital_name=tc_input.get("hospital_name"),
        ytd_claims_amount=tc_input.get("ytd_claims_amount", 0.0),
        claims_history=history,
        documents=docs,
        simulate_component_failure=tc_input.get("simulate_component_failure", False),
    )


def evaluate_match(expected: Dict[str, Any], result) -> tuple[bool, str]:
    exp_decision = expected.get("decision")

    # TC001-TC003: no decision expected
    if exp_decision is None:
        if result.decision is None:
            return True, "Correctly stopped before decision"
        return False, f"Expected no decision but got {result.decision}"

    if result.decision is None:
        return False, f"Expected {exp_decision} but got no decision (document failure)"

    if result.decision.value != exp_decision:
        return False, f"Expected {exp_decision}, got {result.decision.value}"

    exp_amount = expected.get("approved_amount")
    if exp_amount is not None:
        tol = max(1.0, abs(float(exp_amount)) * 0.02)
        diff = abs(result.approved_amount - float(exp_amount))
        if diff > tol:
            return False, (
                f"Decision matches ({exp_decision}) but amount wrong: "
                f"expected ₹{exp_amount}, got ₹{result.approved_amount:.2f}"
            )

    return True, f"Decision: {result.decision.value}" + (
        f" | Amount: ₹{result.approved_amount:.2f}" if result.approved_amount else ""
    )


def run():
    test_file = Path(__file__).parent / "test_cases.json"
    with open(test_file) as f:
        data = json.load(f)

    orchestrator = ClaimOrchestrator()
    report = []

    print("\n" + "═" * 90)
    print(f"{'PLUM CLAIMS PROCESSING — EVAL REPORT':^90}")
    print("═" * 90)
    print(f"{'ID':<8} {'Name':<42} {'Expected':<14} {'Actual':<14} {'Match':<6} {'Amount'}")
    print("─" * 90)

    for tc in data["test_cases"]:
        claim = build_claim(tc["input"])
        result = orchestrator.process(claim)

        matched, note = evaluate_match(tc["expected"], result)
        status = "✅ PASS" if matched else "❌ FAIL"

        exp_d = tc["expected"].get("decision") or "HALT"
        act_d = result.decision.value if result.decision else "HALT"
        amt = f"₹{result.approved_amount:,.0f}" if result.approved_amount > 0 else "—"

        print(f"{tc['case_id']:<8} {tc['case_name'][:41]:<42} {exp_d:<14} {act_d:<14} {status:<8} {amt}")

        # Capture detail
        trace_summary = []
        for agent_result in result.trace:
            trace_summary.append({
                "agent": agent_result.agent_name,
                "status": agent_result.status.value,
                "error": agent_result.error,
            })

        report.append({
            "case_id": tc["case_id"],
            "case_name": tc["case_name"],
            "matched": matched,
            "match_note": note,
            "expected": tc["expected"],
            "actual": {
                "decision": result.decision.value if result.decision else None,
                "approved_amount": result.approved_amount,
                "confidence_score": result.confidence_score,
                "rejection_reasons": result.rejection_reasons,
                "line_item_decisions": [li.model_dump() for li in result.line_item_decisions],
                "degraded_pipeline": result.degraded_pipeline,
                "component_failures": result.component_failures,
                "explanation": result.explanation,
            },
            "trace": trace_summary,
        })

    print("─" * 90)
    passed = sum(1 for r in report if r["matched"])
    print(f"\n{'TOTAL':>55} {passed}/{len(report)} passed")
    print("═" * 90 + "\n")

    # Write JSON report
    out = Path(__file__).parent / "eval_report.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Full report written to: {out}")

    # Print failed cases detail
    failed = [r for r in report if not r["matched"]]
    if failed:
        print(f"\n{'FAILED CASES DETAIL':^90}")
        for r in failed:
            print(f"\n[{r['case_id']}] {r['case_name']}")
            print(f"  Expected: {r['expected']}")
            print(f"  Actual decision: {r['actual']['decision']}")
            print(f"  Actual amount: ₹{r['actual']['approved_amount']:,.2f}")
            print(f"  Rejection reasons: {r['actual']['rejection_reasons']}")
            print(f"  Note: {r['match_note']}")

    return report


if __name__ == "__main__":
    run()
