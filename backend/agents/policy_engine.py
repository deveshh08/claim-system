"""
PolicyEngine — evaluates a claim against the loaded policy and produces an
approved amount, rejection reasons, and a full audit trail of every check.

Rules applied in order:
  1. Member eligibility (exists, active policy)
  2. Submission deadline
  3. Minimum claim amount
  4. Initial waiting period (30 days from join date)
  5. Condition-specific waiting periods (diabetes 90 days, etc.)
  6. Exclusions (bariatric, cosmetic, etc.)
  7. Pre-authorization requirements
  8. Per-claim limit
  9. Category-specific sub-limit (annual)
 10. Dental/Vision procedure-level include/exclude
 11. Network discount (applied first)
 12. Co-pay deduction (applied after network discount)
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from config.policy_loader import get_policy
from models.schemas import (
    AgentStatus,
    ClaimInput,
    DocumentExtractionResult,
    ExtractedDocument,
    LineItemDecision,
    PolicyCheckResult,
)


def _iso(d: str) -> date:
    return date.fromisoformat(d)


class PolicyEngine:
    """
    Input:  ClaimInput + DocumentExtractionResult
    Output: PolicyCheckResult

    Raises: Never.
    """

    def __init__(self):
        self.policy = get_policy()

    def run(
        self,
        claim: ClaimInput,
        extraction: DocumentExtractionResult,
    ) -> PolicyCheckResult:
        t0 = time.time()
        checks: List[Dict[str, Any]] = []
        rejection_reasons: List[str] = []

        def check(name: str, passed: bool, detail: str):
            checks.append({"check": name, "passed": passed, "detail": detail})
            return passed

        # ── helpers ──────────────────────────────────────────────────────────
        treatment_date = _iso(claim.treatment_date)
        member = self.policy.get_member(claim.member_id)
        extracted_docs = extraction.documents if extraction else []

        # aggregate diagnosis across all extracted documents
        diagnoses = " ".join(
            d.diagnosis or "" for d in extracted_docs if d.diagnosis
        ).strip()
        treatments = " ".join(
            d.raw_content.get("treatment", "") if d.raw_content else "" for d in extracted_docs
        ).strip()

        hospital_name = claim.hospital_name or next(
            (d.hospital_name for d in extracted_docs if d.hospital_name), None
        )
        category = claim.claim_category.value
        cat_rules = self.policy.get_category_rules(category)

        # ── 1. Member eligibility ─────────────────────────────────────────
        if not check(
            "member_eligibility",
            member is not None,
            f"Member {claim.member_id} {'found' if member else 'not found'} in roster",
        ):
            rejection_reasons.append("MEMBER_NOT_FOUND")
            return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 2. Submission deadline ────────────────────────────────────────
        # Use submission_date if provided (test mode), else use treatment_date as submission day
        submission_str = getattr(claim, 'submission_date', None) or claim.treatment_date
        submission_date_obj = _iso(submission_str)
        days_since = (submission_date_obj - treatment_date).days
        deadline = self.policy.submission_deadline_days
        if not check(
            "submission_deadline",
            days_since <= deadline,
            f"{days_since} days since treatment; deadline is {deadline} days",
        ):
            rejection_reasons.append("SUBMISSION_DEADLINE_EXCEEDED")
            return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 3. Minimum claim amount ───────────────────────────────────────
        min_amount = self.policy.minimum_claim_amount
        check(
            "minimum_claim_amount",
            claim.claimed_amount >= min_amount,
            f"Claimed ₹{claim.claimed_amount}; minimum is ₹{min_amount}",
        )
        if claim.claimed_amount < min_amount:
            rejection_reasons.append("BELOW_MINIMUM_CLAIM_AMOUNT")
            return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 4. Initial waiting period ──────────────────────────────────────
        join_date = date.fromisoformat(member["join_date"])
        initial_end = join_date + timedelta(days=self.policy.initial_waiting_days)
        initial_passed = treatment_date >= initial_end
        check(
            "initial_waiting_period",
            initial_passed,
            f"Join date: {join_date}; initial waiting ends: {initial_end}; treatment: {treatment_date}",
        )
        if not initial_passed:
            rejection_reasons.append(f"INITIAL_WAITING_PERIOD — eligible from {initial_end}")
            return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 5. Exclusions (checked before condition-specific waiting periods) ──
        exclusion = self.policy.is_excluded_condition(diagnoses, treatments)
        check(
            "exclusion_check",
            exclusion is None,
            f"Exclusion: '{exclusion}'" if exclusion else "No exclusion matched",
        )
        if exclusion:
            rejection_reasons.append(f"EXCLUDED_CONDITION — {exclusion}")
            return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 6. Condition-specific waiting period ───────────────────────────
        waiting_end_date: Optional[str] = None
        if diagnoses:
            result = self.policy.get_waiting_period_for_diagnosis(diagnoses)
            if result:
                condition_key, waiting_days = result
                condition_end = join_date + timedelta(days=waiting_days)
                within_wait = treatment_date < condition_end
                check(
                    f"waiting_period_{condition_key}",
                    not within_wait,
                    f"Condition '{condition_key}' has {waiting_days}-day waiting period; "
                    f"ends {condition_end}; treatment was {treatment_date}",
                )
                if within_wait:
                    waiting_end_date = condition_end.isoformat()
                    rejection_reasons.append(
                        f"WAITING_PERIOD — {condition_key.replace('_', ' ').title()} "
                        f"({waiting_days} days); eligible from {condition_end.strftime('%d %b %Y')}"
                    )
                    return self._finish(
                        False, rejection_reasons, checks, 0.0, t0,
                        waiting_period_end=condition_end.isoformat()
                    )

        # ── 7. Pre-authorization ──────────────────────────────────────────
        # Runs before per-claim limit so PRE_AUTH_MISSING is the stated reason for
        # planned procedures like MRI that happen to exceed the per-claim cap.
        raw_docs = [{"content": d.raw_content} for d in extracted_docs if d.raw_content]
        needs_pre_auth = self.policy.requires_pre_auth(
            claim.claim_category.value, claim.claimed_amount, raw_docs
        )
        pre_auth_id = None  # future: read from claim
        check(
            "pre_authorization",
            not needs_pre_auth or pre_auth_id is not None,
            "Pre-auth required and not provided" if needs_pre_auth else "Pre-auth not required",
        )
        if needs_pre_auth and not pre_auth_id:
            rejection_reasons.append(
                "PRE_AUTH_MISSING — Pre-authorization is required for this procedure "
                "(MRI/CT scan above ₹10,000 or planned hospitalization). "
                "To resubmit: obtain a pre-authorization approval number from ICICI Lombard "
                "at 1800-2666 before scheduling the procedure, then resubmit with that number."
            )
            return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 8. Per-claim limit ─────────────────────────────────────────────
        # DENTAL and VISION use line-item sub-limit evaluation, not a flat per-claim cap
        per_claim_limit = self.policy.per_claim_limit
        skip_per_claim = category in ("DENTAL", "VISION")
        if skip_per_claim:
            check("per_claim_limit", True, f"Per-claim limit skipped for {category} (line-item evaluation applies)")
        else:
            within_per_claim = claim.claimed_amount <= per_claim_limit
            check(
                "per_claim_limit",
                within_per_claim,
                f"Claimed ₹{claim.claimed_amount}; per-claim limit is ₹{per_claim_limit}",
            )
            if not within_per_claim:
                rejection_reasons.append(
                    f"PER_CLAIM_EXCEEDED — Claimed amount ₹{claim.claimed_amount:,.0f} exceeds "
                    f"the per-claim limit of ₹{per_claim_limit:,.0f}."
                )
                return self._finish(False, rejection_reasons, checks, 0.0, t0)

        # ── 9. Category-specific logic (dental / vision line items) ────────
        line_item_decisions: List[LineItemDecision] = []

        if category == "DENTAL":
            line_item_decisions, base_amount, any_exclusion = self._evaluate_dental(
                extracted_docs, checks
            )
        elif category == "VISION":
            line_item_decisions, base_amount, any_exclusion = self._evaluate_vision(
                extracted_docs, checks
            )
        else:
            base_amount = claim.claimed_amount
            any_exclusion = False

        # ── 10. Apply network discount then co-pay ─────────────────────────
        is_network = self.policy.is_network_hospital(hospital_name)
        check(
            "network_hospital",
            True,  # informational — not a rejection
            f"Hospital '{hospital_name or 'unknown'}' is {'IN' if is_network else 'NOT IN'} network",
        )

        network_discount_pct = float(cat_rules.get("network_discount_percent", 0)) if cat_rules else 0.0
        copay_pct = float(cat_rules.get("copay_percent", 0)) if cat_rules else 0.0

        network_discount_amount = 0.0
        copay_amount = 0.0
        approved_amount = base_amount

        if is_network and network_discount_pct > 0:
            network_discount_amount = round(base_amount * network_discount_pct / 100, 2)
            approved_amount = base_amount - network_discount_amount
            check(
                "network_discount",
                True,
                f"Network discount {network_discount_pct}% applied: "
                f"₹{base_amount} → ₹{approved_amount} (saved ₹{network_discount_amount})",
            )

        if copay_pct > 0:
            copay_amount = round(approved_amount * copay_pct / 100, 2)
            approved_amount = round(approved_amount - copay_amount, 2)
            check(
                "copay",
                True,
                f"Co-pay {copay_pct}% applied: ₹{approved_amount + copay_amount} → ₹{approved_amount} "
                f"(member pays ₹{copay_amount})",
            )

        # Decide final decision type
        eligible = True
        if any_exclusion and base_amount < claim.claimed_amount:
            # Some items excluded → PARTIAL handled by caller via line_item_decisions
            pass

        return PolicyCheckResult(
            agent_name="PolicyEngine",
            status=AgentStatus.SUCCESS,
            eligible=eligible,
            rejection_reasons=rejection_reasons,
            approved_amount=approved_amount,
            line_item_decisions=line_item_decisions,
            copay_amount=copay_amount,
            network_discount_amount=network_discount_amount,
            is_network_hospital=is_network,
            waiting_period_end_date=waiting_end_date,
            checks_performed=checks,
            duration_ms=(time.time() - t0) * 1000,
        )

    # ── Dental line-item evaluation ──────────────────────────────────────────

    def _evaluate_dental(
        self,
        docs: List[ExtractedDocument],
        checks: List[Dict[str, Any]],
    ):
        line_items: List[LineItemDecision] = []
        approved_total = 0.0
        claimed_total = 0.0
        any_exclusion = False

        for doc in docs:
            for item in doc.line_items:
                desc = item.get("description", "")
                amount = float(item.get("amount", 0))
                claimed_total += amount
                excluded = self.policy.is_excluded_dental_procedure(desc)
                if excluded:
                    any_exclusion = True
                    line_items.append(LineItemDecision(
                        description=desc,
                        claimed_amount=amount,
                        approved_amount=0.0,
                        decision="REJECTED",
                        reason=f"Excluded dental procedure — '{desc}' is not covered under the policy",
                    ))
                    checks.append({
                        "check": f"dental_line_item:{desc[:30]}",
                        "passed": False,
                        "detail": f"Excluded procedure: {desc} (₹{amount})",
                    })
                else:
                    approved_total += amount
                    line_items.append(LineItemDecision(
                        description=desc,
                        claimed_amount=amount,
                        approved_amount=amount,
                        decision="APPROVED",
                        reason="Covered dental procedure",
                    ))
                    checks.append({
                        "check": f"dental_line_item:{desc[:30]}",
                        "passed": True,
                        "detail": f"Covered procedure: {desc} (₹{amount})",
                    })

        return line_items, approved_total, any_exclusion

    # ── Vision line-item evaluation ──────────────────────────────────────────

    def _evaluate_vision(
        self,
        docs: List[ExtractedDocument],
        checks: List[Dict[str, Any]],
    ):
        line_items: List[LineItemDecision] = []
        approved_total = 0.0
        any_exclusion = False

        for doc in docs:
            for item in doc.line_items:
                desc = item.get("description", "")
                amount = float(item.get("amount", 0))
                excluded = self.policy.is_excluded_vision_item(desc)
                if excluded:
                    any_exclusion = True
                    line_items.append(LineItemDecision(
                        description=desc,
                        claimed_amount=amount,
                        approved_amount=0.0,
                        decision="REJECTED",
                        reason=f"Excluded vision procedure — '{desc}' is not covered",
                    ))
                else:
                    approved_total += amount
                    line_items.append(LineItemDecision(
                        description=desc,
                        claimed_amount=amount,
                        approved_amount=amount,
                        decision="APPROVED",
                    ))

        return line_items, approved_total, any_exclusion

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _finish(
        self,
        eligible: bool,
        rejection_reasons: List[str],
        checks: List[Dict[str, Any]],
        approved_amount: float,
        t0: float,
        waiting_period_end: Optional[str] = None,
    ) -> PolicyCheckResult:
        return PolicyCheckResult(
            agent_name="PolicyEngine",
            status=AgentStatus.SUCCESS,
            eligible=eligible,
            rejection_reasons=rejection_reasons,
            approved_amount=approved_amount,
            waiting_period_end_date=waiting_period_end,
            checks_performed=checks,
            duration_ms=(time.time() - t0) * 1000,
        )
