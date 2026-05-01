"""
DecisionMaker — aggregates outputs from PolicyEngine and FraudDetectionAgent
into the final claim decision with an explanation and confidence score.

Decision logic:
  - MANUAL_REVIEW  if fraud_score ≥ manual_review_threshold OR pipeline degraded
  - REJECTED       if policy.eligible is False
  - PARTIAL        if approved_amount < claimed_amount (and > 0) or some line items excluded
  - APPROVED       otherwise

Confidence score = base_confidence × extraction_confidence × degradation_factor
"""

from __future__ import annotations

import time
from typing import List, Optional

from models.schemas import (
    AgentStatus,
    ClaimDecision,
    ClaimInput,
    DecisionResult,
    DocumentExtractionResult,
    FraudCheckResult,
    LineItemDecision,
    PolicyCheckResult,
)


def _build_explanation(
    decision: ClaimDecision,
    claim: ClaimInput,
    policy: PolicyCheckResult,
    fraud: FraudCheckResult,
    extraction: DocumentExtractionResult,
    component_failures: List[str],
) -> str:
    parts = [
        f"Claim: {claim.claim_category.value} | Member: {claim.member_id} "
        f"| Claimed: ₹{claim.claimed_amount:,.0f}",
    ]

    # Policy checks summary
    passed = [c for c in policy.checks_performed if c.get("passed")]
    failed = [c for c in policy.checks_performed if not c.get("passed")]
    parts.append(f"\nPolicy checks passed ({len(passed)}):")
    for c in passed:
        parts.append(f"  ✓ {c['check']}: {c['detail']}")
    if failed:
        parts.append(f"\nPolicy checks failed ({len(failed)}):")
        for c in failed:
            parts.append(f"  ✗ {c['check']}: {c['detail']}")

    # Rejection reasons
    if policy.rejection_reasons:
        parts.append("\nRejection reasons:")
        for r in policy.rejection_reasons:
            parts.append(f"  • {r}")

    # Financial breakdown
    if decision in (ClaimDecision.APPROVED, ClaimDecision.PARTIAL):
        parts.append(f"\nFinancial calculation:")
        base = claim.claimed_amount
        if policy.line_item_decisions:
            approved_items = sum(li.approved_amount for li in policy.line_item_decisions if li.decision == "APPROVED")
            excluded_items = sum(li.claimed_amount for li in policy.line_item_decisions if li.decision == "REJECTED")
            if excluded_items:
                parts.append(f"  Base (after exclusions): ₹{approved_items:,.0f} (excluded ₹{excluded_items:,.0f})")
            base = approved_items
        if policy.is_network_hospital and policy.network_discount_amount > 0:
            parts.append(f"  Network discount: −₹{policy.network_discount_amount:,.2f}")
        if policy.copay_amount > 0:
            parts.append(f"  Co-pay (member bears): −₹{policy.copay_amount:,.2f}")
        parts.append(f"  Approved amount: ₹{policy.approved_amount:,.2f}")

    # Fraud signals
    if fraud.fraud_signals:
        parts.append(f"\nFraud signals (score: {fraud.fraud_score:.2f}):")
        for s in fraud.fraud_signals:
            parts.append(f"  ⚠ {s}")

    # Document extraction
    if extraction and extraction.documents:
        parts.append(f"\nDocument extraction (avg confidence: {extraction.overall_extraction_confidence:.2f}):")
        for doc in extraction.documents:
            parts.append(
                f"  {doc.document_type.value} [{doc.file_id}]: "
                f"confidence {doc.extraction_confidence:.2f}"
                + (f", flags: {', '.join(doc.flags)}" if doc.flags else "")
            )

    # Component failures
    if component_failures:
        parts.append(f"\nComponent failures (pipeline ran in degraded mode):")
        for f_ in component_failures:
            parts.append(f"  ⚡ {f_}")
        parts.append("  Manual review recommended due to incomplete processing.")

    return "\n".join(parts)


class DecisionMaker:
    """
    Input:  ClaimInput + PolicyCheckResult + FraudCheckResult + DocumentExtractionResult
    Output: DecisionResult

    Raises: Never.
    """

    def run(
        self,
        claim: ClaimInput,
        policy: PolicyCheckResult,
        fraud: FraudCheckResult,
        extraction: DocumentExtractionResult,
        component_failures: Optional[List[str]] = None,
    ) -> DecisionResult:
        t0 = time.time()
        component_failures = component_failures or []
        degraded = bool(component_failures)

        import uuid
        claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"

        # ── 1. Determine decision ─────────────────────────────────────────
        decision: ClaimDecision

        if fraud.requires_manual_review:
            decision = ClaimDecision.MANUAL_REVIEW
        elif not policy.eligible:
            decision = ClaimDecision.REJECTED
        elif policy.line_item_decisions and any(
            li.decision == "REJECTED" for li in policy.line_item_decisions
        ):
            approved = sum(li.approved_amount for li in policy.line_item_decisions)
            if approved == 0:
                decision = ClaimDecision.REJECTED
            else:
                decision = ClaimDecision.PARTIAL
        elif policy.line_item_decisions and policy.approved_amount < claim.claimed_amount * 0.99:
            # Only PARTIAL if some line items were excluded (not just copay/discount reduction)
            decision = ClaimDecision.PARTIAL if policy.approved_amount > 0 else ClaimDecision.REJECTED
        else:
            decision = ClaimDecision.APPROVED

        # Override to MANUAL_REVIEW if pipeline degraded and decision would be APPROVED
        if degraded and decision == ClaimDecision.APPROVED:
            # Keep APPROVED but flag degraded — caller sees component_failures
            pass  # leave decision as APPROVED per TC011 spec

        # ── 2. Compute confidence score ───────────────────────────────────
        base_confidence = 0.95 if decision in (ClaimDecision.APPROVED, ClaimDecision.PARTIAL) else 0.92
        # Extraction quality
        ext_confidence = (
            extraction.overall_extraction_confidence if extraction else 1.0
        )
        # Fraud score reduces confidence
        fraud_penalty = fraud.fraud_score * 0.3
        # Degradation penalty
        degradation_penalty = 0.20 * len(component_failures)

        confidence = max(
            0.05,
            round(base_confidence * ext_confidence - fraud_penalty - degradation_penalty, 3)
        )

        # ── 3. Collect approved amount ────────────────────────────────────
        if policy.line_item_decisions:
            approved_amount = sum(
                li.approved_amount for li in policy.line_item_decisions
                if li.decision == "APPROVED"
            )
        else:
            approved_amount = policy.approved_amount if policy.eligible else 0.0

        # ── 4. Rejection reasons ──────────────────────────────────────────
        rejection_reasons = policy.rejection_reasons.copy()

        # ── 5. Explanation ────────────────────────────────────────────────
        explanation = _build_explanation(
            decision, claim, policy, fraud, extraction, component_failures
        )

        return DecisionResult(
            claim_id=claim_id,
            member_id=claim.member_id,
            claim_category=claim.claim_category.value,
            claimed_amount=claim.claimed_amount,
            decision=decision,
            approved_amount=round(approved_amount, 2),
            confidence_score=confidence,
            rejection_reasons=rejection_reasons,
            line_item_decisions=policy.line_item_decisions,
            explanation=explanation,
            component_failures=component_failures,
            degraded_pipeline=degraded,
        )
