"""
test_agents.py — pytest unit tests for individual pipeline components.

Run with:
    cd backend
    pytest tests/test_agents.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.decision_maker import DecisionMaker
from agents.document_extractor import DocumentExtractionAgent
from agents.document_verifier import DocumentVerificationAgent
from agents.fraud_detector import FraudDetectionAgent
from agents.policy_engine import PolicyEngine
from agents.orchestrator import ClaimOrchestrator
from config.policy_loader import PolicyLoader, get_policy
from models.schemas import (
    AgentStatus,
    ClaimCategory,
    ClaimHistoryEntry,
    ClaimInput,
    ClaimDecision,
    DocumentExtractionResult,
    DocumentInput,
    DocumentQuality,
    DocumentType,
    FraudCheckResult,
    PolicyCheckResult,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def policy():
    return get_policy()


def _make_claim(**kwargs):
    defaults = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category=ClaimCategory.CONSULTATION,
        treatment_date="2024-11-01",
        claimed_amount=1500.0,
        documents=[
            DocumentInput(
                file_id="F001",
                actual_type=DocumentType.PRESCRIPTION,
                content={"doctor_name": "Dr. A", "diagnosis": "Viral Fever", "patient_name": "Rajesh Kumar"},
            ),
            DocumentInput(
                file_id="F002",
                actual_type=DocumentType.HOSPITAL_BILL,
                content={"patient_name": "Rajesh Kumar", "total": 1500,
                         "line_items": [{"description": "Consultation", "amount": 1500}]},
            ),
        ],
    )
    defaults.update(kwargs)
    return ClaimInput(**defaults)


def _empty_extraction() -> DocumentExtractionResult:
    return DocumentExtractionResult(
        agent_name="DocumentExtractionAgent",
        status=AgentStatus.SUCCESS,
        documents=[],
        overall_extraction_confidence=1.0,
    )


def _empty_fraud() -> FraudCheckResult:
    return FraudCheckResult(
        agent_name="FraudDetectionAgent",
        status=AgentStatus.SUCCESS,
        fraud_score=0.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PolicyLoader tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyLoader:
    def test_loads_policy(self, policy):
        assert policy.policy_id == "PLUM_GHI_2024"

    def test_per_claim_limit(self, policy):
        assert policy.per_claim_limit == 5000.0

    def test_network_hospital_match(self, policy):
        assert policy.is_network_hospital("Apollo Hospitals") is True
        assert policy.is_network_hospital("Random Clinic") is False

    def test_member_found(self, policy):
        m = policy.get_member("EMP001")
        assert m is not None
        assert m["name"] == "Rajesh Kumar"

    def test_member_not_found(self, policy):
        assert policy.get_member("GHOST999") is None

    def test_waiting_period_diabetes(self, policy):
        result = policy.get_waiting_period_for_diagnosis("Type 2 Diabetes Mellitus")
        assert result is not None
        key, days = result
        assert key == "diabetes"
        assert days == 90

    def test_waiting_period_not_matched(self, policy):
        result = policy.get_waiting_period_for_diagnosis("Viral Fever")
        assert result is None

    def test_excluded_bariatric(self, policy):
        excl = policy.is_excluded_condition("Morbid Obesity", "Bariatric Consultation")
        assert excl is not None

    def test_excluded_dental_whitening(self, policy):
        assert policy.is_excluded_dental_procedure("Teeth Whitening") is True
        assert policy.is_excluded_dental_procedure("Root Canal Treatment") is False

    def test_pre_auth_mri_over_threshold(self, policy):
        docs = [{"content": {"tests_ordered": ["MRI Lumbar Spine"]}}]
        assert policy.requires_pre_auth("DIAGNOSTIC", 15000, docs) is True

    def test_pre_auth_mri_under_threshold(self, policy):
        docs = [{"content": {"tests_ordered": ["MRI Lumbar Spine"]}}]
        assert policy.requires_pre_auth("DIAGNOSTIC", 8000, docs) is False


# ─────────────────────────────────────────────────────────────────────────────
# DocumentVerificationAgent tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDocumentVerification:
    def setup_method(self):
        self.agent = DocumentVerificationAgent()

    def test_valid_documents_pass(self):
        claim = _make_claim()
        result = self.agent.run(claim)
        assert result.passed is True
        assert result.issues == []

    def test_missing_hospital_bill(self):
        claim = _make_claim(documents=[
            DocumentInput(file_id="F001", actual_type=DocumentType.PRESCRIPTION,
                          content={"patient_name": "Rajesh Kumar"}),
            DocumentInput(file_id="F002", actual_type=DocumentType.PRESCRIPTION,
                          content={"patient_name": "Rajesh Kumar"}),
        ])
        result = self.agent.run(claim)
        assert result.passed is False
        assert any("HOSPITAL_BILL" in str(i) or "hospital" in i.lower() for i in result.issues)

    def test_unreadable_document_detected(self):
        claim = _make_claim(documents=[
            DocumentInput(file_id="F001", actual_type=DocumentType.PRESCRIPTION,
                          quality=DocumentQuality.GOOD, content={}),
            DocumentInput(file_id="F002", actual_type=DocumentType.HOSPITAL_BILL,
                          quality=DocumentQuality.UNREADABLE, content={}),
        ])
        result = self.agent.run(claim)
        assert result.passed is False
        assert "F002" in result.unreadable_file_ids

    def test_cross_patient_detection(self):
        claim = _make_claim(documents=[
            DocumentInput(file_id="F005", actual_type=DocumentType.PRESCRIPTION,
                          patient_name_on_doc="Rajesh Kumar", content={}),
            DocumentInput(file_id="F006", actual_type=DocumentType.HOSPITAL_BILL,
                          patient_name_on_doc="Arjun Mehta", content={}),
        ])
        result = self.agent.run(claim)
        assert result.passed is False
        assert result.cross_patient_names is not None
        issue_text = " ".join(result.issues)
        assert "Rajesh" in issue_text or "rajesh" in issue_text
        assert "Arjun" in issue_text or "arjun" in issue_text


# ─────────────────────────────────────────────────────────────────────────────
# PolicyEngine tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyEngine:
    def setup_method(self):
        self.engine = PolicyEngine()

    def _run(self, claim):
        ext = DocumentExtractionAgent().run(claim)
        return self.engine.run(claim, ext)

    def test_clean_consultation_approved(self):
        claim = _make_claim()
        result = self._run(claim)
        assert result.eligible is True
        # 10% copay applied
        assert abs(result.approved_amount - 1350.0) < 1.0

    def test_waiting_period_diabetes(self):
        claim = _make_claim(
            member_id="EMP005",
            treatment_date="2024-10-15",
            claimed_amount=3000.0,
            documents=[
                DocumentInput(file_id="F009", actual_type=DocumentType.PRESCRIPTION,
                              content={"diagnosis": "Type 2 Diabetes Mellitus", "patient_name": "Vikram Joshi"}),
                DocumentInput(file_id="F010", actual_type=DocumentType.HOSPITAL_BILL,
                              content={"patient_name": "Vikram Joshi", "total": 3000}),
            ],
        )
        result = self._run(claim)
        assert result.eligible is False
        assert any("WAITING_PERIOD" in r for r in result.rejection_reasons)
        assert result.waiting_period_end_date is not None

    def test_per_claim_limit_exceeded(self):
        claim = _make_claim(claimed_amount=7500.0)
        result = self._run(claim)
        assert result.eligible is False
        assert any("PER_CLAIM" in r for r in result.rejection_reasons)

    def test_network_discount_applied_before_copay(self):
        claim = _make_claim(
            claimed_amount=4500.0,
            hospital_name="Apollo Hospitals",
            documents=[
                DocumentInput(file_id="F019", actual_type=DocumentType.PRESCRIPTION,
                              content={"diagnosis": "Acute Bronchitis", "patient_name": "Deepak Shah"}),
                DocumentInput(file_id="F020", actual_type=DocumentType.HOSPITAL_BILL,
                              content={"hospital_name": "Apollo Hospitals", "patient_name": "Deepak Shah",
                                       "total": 4500,
                                       "line_items": [{"description": "Consultation", "amount": 4500}]}),
            ],
            member_id="EMP010",
        )
        result = self._run(claim)
        assert result.eligible is True
        assert result.is_network_hospital is True
        # 4500 * 0.80 = 3600; 3600 * 0.90 = 3240
        assert abs(result.approved_amount - 3240.0) < 1.0

    def test_exclusion_bariatric(self):
        claim = _make_claim(
            member_id="EMP009",
            treatment_date="2024-10-18",
            claimed_amount=8000.0,
            documents=[
                DocumentInput(file_id="F023", actual_type=DocumentType.PRESCRIPTION,
                              content={"diagnosis": "Morbid Obesity", "treatment": "Bariatric Consultation",
                                       "patient_name": "Anita Desai"}),
                DocumentInput(file_id="F024", actual_type=DocumentType.HOSPITAL_BILL,
                              content={"total": 8000, "patient_name": "Anita Desai",
                                       "line_items": [{"description": "Bariatric Consultation", "amount": 8000}]}),
            ],
        )
        result = self._run(claim)
        assert result.eligible is False
        assert any("EXCLUDED_CONDITION" in r for r in result.rejection_reasons)

    def test_dental_partial_cosmetic(self):
        claim = _make_claim(
            member_id="EMP002",
            claim_category=ClaimCategory.DENTAL,
            treatment_date="2024-10-15",
            claimed_amount=12000.0,
            documents=[
                DocumentInput(file_id="F011", actual_type=DocumentType.HOSPITAL_BILL,
                              content={"patient_name": "Priya Singh",
                                       "line_items": [
                                           {"description": "Root Canal Treatment", "amount": 8000},
                                           {"description": "Teeth Whitening", "amount": 4000},
                                       ], "total": 12000}),
            ],
        )
        ext = DocumentExtractionAgent().run(claim)
        result = self.engine.run(claim, ext)
        assert result.eligible is True
        assert any(li.decision == "REJECTED" for li in result.line_item_decisions)
        approved = sum(li.approved_amount for li in result.line_item_decisions if li.decision == "APPROVED")
        assert abs(approved - 8000.0) < 1.0

    def test_mri_pre_auth_required(self):
        claim = _make_claim(
            member_id="EMP007",
            claim_category=ClaimCategory.DIAGNOSTIC,
            treatment_date="2024-11-02",
            claimed_amount=15000.0,
            documents=[
                DocumentInput(file_id="F012", actual_type=DocumentType.PRESCRIPTION,
                              content={"diagnosis": "Lumbar Disc Herniation",
                                       "tests_ordered": ["MRI Lumbar Spine"]}),
                DocumentInput(file_id="F013", actual_type=DocumentType.LAB_REPORT,
                              content={"test_name": "MRI Lumbar Spine"}),
                DocumentInput(file_id="F014", actual_type=DocumentType.HOSPITAL_BILL,
                              content={"total": 15000,
                                       "line_items": [{"description": "MRI Lumbar Spine", "amount": 15000}]}),
            ],
        )
        ext = DocumentExtractionAgent().run(claim)
        result = self.engine.run(claim, ext)
        assert result.eligible is False
        assert any("PRE_AUTH" in r for r in result.rejection_reasons)


# ─────────────────────────────────────────────────────────────────────────────
# FraudDetectionAgent tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFraudDetection:
    def setup_method(self):
        self.agent = FraudDetectionAgent()

    def test_clean_claim_no_fraud(self):
        claim = _make_claim()
        result = self.agent.run(claim, _empty_extraction())
        assert result.fraud_score < 0.5
        assert result.requires_manual_review is False

    def test_same_day_claims_flag(self):
        claim = _make_claim(
            member_id="EMP008",
            treatment_date="2024-10-30",
            claimed_amount=4800.0,
            claims_history=[
                ClaimHistoryEntry(claim_id="C1", date="2024-10-30", amount=1200),
                ClaimHistoryEntry(claim_id="C2", date="2024-10-30", amount=1800),
                ClaimHistoryEntry(claim_id="C3", date="2024-10-30", amount=2100),
            ],
        )
        result = self.agent.run(claim, _empty_extraction())
        assert result.requires_manual_review is True
        assert any("SAME_DAY" in s for s in result.fraud_signals)

    def test_high_value_claim(self):
        claim = _make_claim(claimed_amount=30000.0)
        result = self.agent.run(claim, _empty_extraction())
        assert any("HIGH_VALUE" in s for s in result.fraud_signals)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator / End-to-End tests
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestrator:
    def setup_method(self):
        self.orch = ClaimOrchestrator()

    def test_tc004_full_approval(self):
        """TC004: Clean consultation → APPROVED at ₹1350."""
        claim = _make_claim()
        result = self.orch.process(claim)
        assert result.decision == ClaimDecision.APPROVED
        assert abs(result.approved_amount - 1350.0) < 1.0
        assert result.confidence_score > 0.85

    def test_tc001_wrong_document(self):
        """TC004: Two prescriptions → no decision, specific error."""
        claim = _make_claim(documents=[
            DocumentInput(file_id="F001", actual_type=DocumentType.PRESCRIPTION,
                          content={"patient_name": "Rajesh Kumar"}),
            DocumentInput(file_id="F002", actual_type=DocumentType.PRESCRIPTION,
                          content={"patient_name": "Rajesh Kumar"}),
        ])
        result = self.orch.process(claim)
        assert result.decision is None
        assert any("hospital" in e.lower() or "HOSPITAL_BILL" in e for e in result.rejection_reasons)

    def test_tc009_fraud_manual_review(self):
        """TC009: 4 same-day claims → MANUAL_REVIEW."""
        claim = _make_claim(
            member_id="EMP008",
            treatment_date="2024-10-30",
            claimed_amount=4800.0,
            claims_history=[
                ClaimHistoryEntry(claim_id="C1", date="2024-10-30", amount=1200),
                ClaimHistoryEntry(claim_id="C2", date="2024-10-30", amount=1800),
                ClaimHistoryEntry(claim_id="C3", date="2024-10-30", amount=2100),
            ],
        )
        result = self.orch.process(claim)
        assert result.decision == ClaimDecision.MANUAL_REVIEW

    def test_tc011_component_failure_graceful(self):
        """TC011: Simulated failure → still produces decision, degraded=True, lower confidence."""
        claim = _make_claim(
            member_id="EMP006",
            claim_category=ClaimCategory.ALTERNATIVE_MEDICINE,
            treatment_date="2024-10-28",
            claimed_amount=4000.0,
            simulate_component_failure=True,
            documents=[
                DocumentInput(file_id="F021", actual_type=DocumentType.PRESCRIPTION,
                              content={"doctor_name": "Vaidya T. Krishnan",
                                       "doctor_registration": "AYUR/KL/2345/2019",
                                       "diagnosis": "Chronic Joint Pain",
                                       "treatment": "Panchakarma Therapy",
                                       "patient_name": "Kavita Nair"}),
                DocumentInput(file_id="F022", actual_type=DocumentType.HOSPITAL_BILL,
                              content={"hospital_name": "Ayur Wellness Centre", "total": 4000,
                                       "line_items": [{"description": "Panchakarma Therapy", "amount": 4000}],
                                       "patient_name": "Kavita Nair"}),
            ],
        )
        result = self.orch.process(claim)
        # Must not crash
        assert result.decision is not None
        # Must flag degraded state
        assert result.degraded_pipeline is True
        # Confidence should be reduced
        normal_claim = _make_claim(member_id="EMP006",
                                   claim_category=ClaimCategory.ALTERNATIVE_MEDICINE,
                                   treatment_date="2024-10-28", claimed_amount=4000.0,
                                   documents=claim.documents)
        normal_result = self.orch.process(normal_claim)
        assert result.confidence_score < normal_result.confidence_score

    def test_pipeline_never_crashes_on_bad_input(self):
        """Pipeline must not raise even on malformed input."""
        claim = ClaimInput(
            member_id="GHOST999",
            policy_id="PLUM_GHI_2024",
            claim_category=ClaimCategory.CONSULTATION,
            treatment_date="2024-11-01",
            claimed_amount=1000.0,
            documents=[],
        )
        result = self.orch.process(claim)
        # May be a rejection but must not raise
        assert result is not None
