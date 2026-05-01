"""
FraudDetectionAgent — scores a claim for fraud signals.

Signals evaluated:
  - Same-day claims: more than policy threshold from same member on same day
  - Monthly claims: more than policy threshold in current calendar month
  - High-value claim: amount above high_value_claim_threshold
  - Document alteration flags from extraction

A fraud_score ≥ fraud_score_manual_review_threshold routes the claim to MANUAL_REVIEW.
The agent never auto-rejects on fraud — it always escalates to human review.
"""

from __future__ import annotations

import time
from datetime import date
from typing import List

from config.policy_loader import get_policy
from models.schemas import (
    AgentStatus,
    ClaimInput,
    DocumentExtractionResult,
    FraudCheckResult,
)


class FraudDetectionAgent:
    """
    Input:  ClaimInput + DocumentExtractionResult
    Output: FraudCheckResult

    Raises: Never.
    """

    def __init__(self):
        self.policy = get_policy()

    def run(
        self,
        claim: ClaimInput,
        extraction: DocumentExtractionResult,
    ) -> FraudCheckResult:
        t0 = time.time()
        signals: List[str] = []
        fraud_score = 0.0
        thresholds = self.policy.fraud_thresholds

        try:
            treatment_date = date.fromisoformat(claim.treatment_date)

            # ── 1. Same-day claims ─────────────────────────────────────────
            history = claim.claims_history or []
            same_day = [
                c for c in history
                if c.date == claim.treatment_date
            ]
            same_day_count = len(same_day)
            limit_same_day = thresholds.get("same_day_claims_limit", 2)

            if same_day_count >= limit_same_day:
                fraud_score += 0.85
                signals.append(
                    f"SAME_DAY_CLAIMS — {same_day_count} previous claims on {claim.treatment_date} "
                    f"(limit: {limit_same_day}). Providers: "
                    + ", ".join(c.provider or "unknown" for c in same_day)
                )

            # ── 2. Monthly claims ──────────────────────────────────────────
            month_str = claim.treatment_date[:7]  # YYYY-MM
            monthly = [c for c in history if c.date.startswith(month_str)]
            monthly_count = len(monthly)
            limit_monthly = thresholds.get("monthly_claims_limit", 6)

            if monthly_count >= limit_monthly:
                fraud_score += 0.25
                signals.append(
                    f"HIGH_MONTHLY_CLAIMS — {monthly_count} claims in {month_str} (limit: {limit_monthly})"
                )

            # ── 3. High-value claim ────────────────────────────────────────
            hv_threshold = thresholds.get("high_value_claim_threshold", 25000)
            if claim.claimed_amount >= hv_threshold:
                fraud_score += 0.15
                signals.append(
                    f"HIGH_VALUE_CLAIM — ₹{claim.claimed_amount:,.0f} "
                    f"(threshold: ₹{hv_threshold:,.0f})"
                )

            # ── 4. Auto-manual-review threshold ───────────────────────────
            auto_threshold = thresholds.get("auto_manual_review_above", 25000)
            if claim.claimed_amount > auto_threshold:
                fraud_score += 0.10
                signals.append(
                    f"AUTO_REVIEW_THRESHOLD — Amount ₹{claim.claimed_amount:,.0f} "
                    f"exceeds auto-review threshold ₹{auto_threshold:,.0f}"
                )

            # ── 5. Document alteration flags ───────────────────────────────
            if extraction:
                for doc in extraction.documents:
                    alteration_flags = [f for f in doc.flags if "ALTERATION" in f or "DUPLICATE" in f]
                    if alteration_flags:
                        fraud_score += 0.20
                        signals.append(
                            f"DOCUMENT_FLAG on {doc.file_id}: {', '.join(alteration_flags)}"
                        )

            # Cap score at 1.0
            fraud_score = min(round(fraud_score, 3), 1.0)

            manual_threshold = thresholds.get("fraud_score_manual_review_threshold", 0.80)
            requires_manual = fraud_score >= manual_threshold

        except Exception as exc:  # noqa: BLE001
            return FraudCheckResult(
                agent_name="FraudDetectionAgent",
                status=AgentStatus.FAILED,
                error=str(exc),
                fraud_score=0.0,
                duration_ms=(time.time() - t0) * 1000,
            )

        return FraudCheckResult(
            agent_name="FraudDetectionAgent",
            status=AgentStatus.SUCCESS,
            fraud_score=fraud_score,
            fraud_signals=signals,
            requires_manual_review=requires_manual,
            same_day_claim_count=same_day_count,
            duration_ms=(time.time() - t0) * 1000,
        )
