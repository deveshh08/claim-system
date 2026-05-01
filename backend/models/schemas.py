"""
Schemas — all Pydantic models used across the pipeline.
Every agent consumes and produces typed objects defined here.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class ClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    UNKNOWN = "UNKNOWN"


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    UNREADABLE = "UNREADABLE"


class ClaimCategory(str, Enum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class AgentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# ─────────────────────────────────────────────────────────────────────────────
# Document models
# ─────────────────────────────────────────────────────────────────────────────

class DocumentInput(BaseModel):
    """A single document as submitted in a claim."""
    file_id: str
    file_name: Optional[str] = None
    actual_type: Optional[DocumentType] = None          # known in tests; inferred in prod
    quality: Optional[DocumentQuality] = DocumentQuality.GOOD
    content: Optional[Dict[str, Any]] = None            # pre-extracted content (test mode)
    patient_name_on_doc: Optional[str] = None           # if known, used for cross-patient check
    file_bytes: Optional[bytes] = None                  # raw bytes for LLM extraction (prod)
    mime_type: Optional[str] = None                     # e.g. image/jpeg, application/pdf


class ExtractedDocument(BaseModel):
    """Structured information extracted from a single document."""
    file_id: str
    document_type: DocumentType
    quality: DocumentQuality = DocumentQuality.GOOD
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    hospital_name: Optional[str] = None
    treatment_date: Optional[str] = None
    diagnosis: Optional[str] = None
    medicines: List[str] = Field(default_factory=list)
    tests_ordered: List[str] = Field(default_factory=list)
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    total_amount: Optional[float] = None
    lab_results: List[Dict[str, Any]] = Field(default_factory=list)
    extraction_confidence: float = 1.0
    low_confidence_fields: List[str] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)      # DOCUMENT_ALTERATION, etc.
    raw_content: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Claim input/output
# ─────────────────────────────────────────────────────────────────────────────

class ClaimHistoryEntry(BaseModel):
    claim_id: str
    date: str
    amount: float
    provider: Optional[str] = None


class ClaimInput(BaseModel):
    """Everything submitted by the member when filing a claim."""
    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: str                                 # ISO date string
    claimed_amount: float
    hospital_name: Optional[str] = None
    ytd_claims_amount: Optional[float] = 0.0           # year-to-date approved claims
    submission_date: Optional[str] = None               # ISO date; defaults to treatment_date if not set
    claims_history: Optional[List[ClaimHistoryEntry]] = Field(default_factory=list)
    documents: List[DocumentInput]
    simulate_component_failure: Optional[bool] = False  # test hook


class LineItemDecision(BaseModel):
    """Per-line-item outcome (used in PARTIAL decisions)."""
    description: str
    claimed_amount: float
    approved_amount: float
    decision: str       # APPROVED / REJECTED
    reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Agent result envelopes
# ─────────────────────────────────────────────────────────────────────────────

class AgentResult(BaseModel):
    """Base envelope every agent returns."""
    agent_name: str
    status: AgentStatus
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class DocumentVerificationResult(AgentResult):
    passed: bool
    issues: List[str] = Field(default_factory=list)     # human-readable issues
    missing_document_types: List[DocumentType] = Field(default_factory=list)
    uploaded_instead: List[DocumentType] = Field(default_factory=list)
    cross_patient_names: Optional[Dict[str, str]] = None  # file_id → patient name
    unreadable_file_ids: List[str] = Field(default_factory=list)


class DocumentExtractionResult(AgentResult):
    documents: List[ExtractedDocument] = Field(default_factory=list)
    overall_extraction_confidence: float = 1.0


class PolicyCheckResult(AgentResult):
    eligible: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    approved_amount: float = 0.0
    line_item_decisions: List[LineItemDecision] = Field(default_factory=list)
    copay_amount: float = 0.0
    network_discount_amount: float = 0.0
    is_network_hospital: bool = False
    waiting_period_end_date: Optional[str] = None
    checks_performed: List[Dict[str, Any]] = Field(default_factory=list)


class FraudCheckResult(AgentResult):
    fraud_score: float = 0.0
    fraud_signals: List[str] = Field(default_factory=list)
    requires_manual_review: bool = False
    same_day_claim_count: int = 0


class DecisionResult(BaseModel):
    """Final output of the entire pipeline."""
    claim_id: str
    member_id: str
    claim_category: str
    claimed_amount: float
    decision: Optional[ClaimDecision]
    approved_amount: float = 0.0
    confidence_score: float = 0.0
    rejection_reasons: List[str] = Field(default_factory=list)
    line_item_decisions: List[LineItemDecision] = Field(default_factory=list)
    explanation: str = ""
    component_failures: List[str] = Field(default_factory=list)
    degraded_pipeline: bool = False
    trace: List[AgentResult] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    model_config = {"arbitrary_types_allowed": True}
