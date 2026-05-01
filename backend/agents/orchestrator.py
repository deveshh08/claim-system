"""
Orchestrator — multi-agent pipeline coordinator.

Pipeline stages (in order):
  Stage 1: DocumentVerificationAgent  — gate check, halts on failure
  Stage 2: DocumentExtractionAgent    — LLM extraction, continues degraded on failure
  Stage 3: FraudDetectionAgent        — fraud scoring, continues degraded on failure
  Stage 4: PolicyEngine               — coverage rules, continues degraded on failure
  Stage 5: DecisionMaker              — final decision (always runs)

Failures are:
  - Caught per-agent (never bubble up to API layer)
  - Recorded in component_failures list
  - Reflected in reduced confidence score
  - Visible in the trace

The pipeline halts only after Stage 1 if document verification fails — because
there is nothing to process without valid documents.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from agents.decision_maker import DecisionMaker
from agents.document_extractor import DocumentExtractionAgent
from agents.document_verifier import DocumentVerificationAgent
from agents.fraud_detector import FraudDetectionAgent
from agents.policy_engine import PolicyEngine
from models.schemas import (
    AgentResult,
    AgentStatus,
    ClaimInput,
    DecisionResult,
    DocumentExtractionResult,
    DocumentVerificationResult,
    FraudCheckResult,
    PolicyCheckResult,
)

logger = logging.getLogger(__name__)


# ── Sentinel results used when an agent fails entirely ───────────────────────

def _empty_extraction() -> DocumentExtractionResult:
    return DocumentExtractionResult(
        agent_name="DocumentExtractionAgent",
        status=AgentStatus.FAILED,
        error="Agent did not run",
        overall_extraction_confidence=0.5,
    )


def _empty_fraud() -> FraudCheckResult:
    return FraudCheckResult(
        agent_name="FraudDetectionAgent",
        status=AgentStatus.FAILED,
        error="Agent did not run",
        fraud_score=0.0,
    )


def _empty_policy() -> PolicyCheckResult:
    return PolicyCheckResult(
        agent_name="PolicyEngine",
        status=AgentStatus.FAILED,
        error="Agent did not run",
        eligible=False,
        rejection_reasons=["POLICY_ENGINE_UNAVAILABLE"],
    )


class ClaimOrchestrator:
    """
    Accepts a ClaimInput and returns a DecisionResult.
    The DecisionResult always contains a full trace of every agent that ran.
    """

    def __init__(self):
        self._verifier = DocumentVerificationAgent()
        self._extractor = DocumentExtractionAgent()
        self._fraud = FraudDetectionAgent()
        self._policy = PolicyEngine()
        self._decider = DecisionMaker()

    def process(self, claim: ClaimInput) -> DecisionResult:
        t0 = time.time()
        trace: List[AgentResult] = []
        component_failures: List[str] = []

        # ─────────────────────────────────────────────────────────────────
        # Stage 1: Document Verification (blocking gate)
        # ─────────────────────────────────────────────────────────────────
        logger.info("[%s] Stage 1: DocumentVerification", claim.member_id)
        try:
            verification: DocumentVerificationResult = self._verifier.run(claim)
        except Exception as exc:
            logger.exception("DocumentVerificationAgent crashed")
            verification = DocumentVerificationResult(
                agent_name="DocumentVerificationAgent",
                status=AgentStatus.FAILED,
                error=str(exc),
                passed=False,
                issues=[f"Document verification crashed: {exc}"],
            )

        trace.append(verification)

        # If Stage 1 fails → return immediately (no decision yet)
        if not verification.passed:
            return DecisionResult(
                claim_id=f"DOCFAIL-{claim.member_id}",
                member_id=claim.member_id,
                claim_category=claim.claim_category.value,
                claimed_amount=claim.claimed_amount,
                decision=None,       # type: ignore[arg-type]
                approved_amount=0.0,
                confidence_score=0.0,
                rejection_reasons=verification.issues,
                explanation="\n".join(verification.issues),
                component_failures=[],
                degraded_pipeline=False,
                trace=trace,
            )

        # ─────────────────────────────────────────────────────────────────
        # Stage 2: Document Extraction
        # ─────────────────────────────────────────────────────────────────
        logger.info("[%s] Stage 2: DocumentExtraction", claim.member_id)
        extraction: DocumentExtractionResult
        if claim.simulate_component_failure:
            # Inject a simulated failure for TC011
            extraction = DocumentExtractionResult(
                agent_name="DocumentExtractionAgent",
                status=AgentStatus.FAILED,
                error="Simulated component failure (simulate_component_failure=true)",
                overall_extraction_confidence=0.5,
                documents=[],
            )
            component_failures.append("DocumentExtractionAgent: simulated failure")
            # Re-use raw content so pipeline can still partially decide
            extraction = self._extract_with_fallback(claim, extraction, component_failures)
        else:
            try:
                extraction = self._extractor.run(claim)
                if extraction.status == AgentStatus.FAILED:
                    component_failures.append(f"DocumentExtractionAgent: {extraction.error}")
            except Exception as exc:
                logger.exception("DocumentExtractionAgent crashed")
                extraction = _empty_extraction()
                extraction.error = str(exc)
                component_failures.append(f"DocumentExtractionAgent: {exc}")

        trace.append(extraction)

        # ─────────────────────────────────────────────────────────────────
        # Stage 3: Fraud Detection
        # ─────────────────────────────────────────────────────────────────
        logger.info("[%s] Stage 3: FraudDetection", claim.member_id)
        try:
            fraud: FraudCheckResult = self._fraud.run(claim, extraction)
        except Exception as exc:
            logger.exception("FraudDetectionAgent crashed")
            fraud = _empty_fraud()
            fraud.error = str(exc)
            component_failures.append(f"FraudDetectionAgent: {exc}")

        trace.append(fraud)

        # ─────────────────────────────────────────────────────────────────
        # Stage 4: Policy Engine
        # ─────────────────────────────────────────────────────────────────
        logger.info("[%s] Stage 4: PolicyEngine", claim.member_id)
        try:
            policy: PolicyCheckResult = self._policy.run(claim, extraction)
        except Exception as exc:
            logger.exception("PolicyEngine crashed")
            policy = _empty_policy()
            policy.error = str(exc)
            component_failures.append(f"PolicyEngine: {exc}")

        trace.append(policy)

        # ─────────────────────────────────────────────────────────────────
        # Stage 5: Decision
        # ─────────────────────────────────────────────────────────────────
        logger.info("[%s] Stage 5: DecisionMaker", claim.member_id)
        decision_result = self._decider.run(
            claim, policy, fraud, extraction, component_failures
        )
        decision_result.trace = trace

        logger.info(
            "[%s] Decision: %s | ₹%s | confidence %.2f",
            claim.member_id,
            decision_result.decision,
            decision_result.approved_amount,
            decision_result.confidence_score,
        )

        return decision_result

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _extract_with_fallback(
        self,
        claim: ClaimInput,
        failed_extraction: DocumentExtractionResult,
        component_failures: List[str],
    ) -> DocumentExtractionResult:
        """On extraction failure, still try to get doc content from pre-filled data."""
        try:
            partial = self._extractor.run(claim)
            partial.status = AgentStatus.PARTIAL
            partial.error = "Ran with degraded confidence due to simulated failure"
            partial.overall_extraction_confidence *= 0.6
            return partial
        except Exception:
            return failed_extraction
