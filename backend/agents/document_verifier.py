"""
DocumentVerificationAgent — Gate-1 of the pipeline.

Runs synchronously and must complete before any other agent.
Checks:
  1. Required document types present for the claim category.
  2. No required documents missing (swapped for wrong types).
  3. Documents are not unreadable.
  4. Patient names on documents are consistent (cross-patient detection).

On failure, returns a specific, actionable user-facing message. Never generic.
"""

from __future__ import annotations

import time
from typing import List

from config.policy_loader import get_policy
from models.schemas import (
    AgentStatus,
    ClaimCategory,
    ClaimInput,
    DocumentInput,
    DocumentType,
    DocumentVerificationResult,
)

# Human-friendly label for each document type
_DOC_LABELS: dict[str, str] = {
    "PRESCRIPTION": "a valid prescription from a registered doctor",
    "HOSPITAL_BILL": "an official hospital or clinic bill",
    "LAB_REPORT": "a laboratory / diagnostic report",
    "PHARMACY_BILL": "a pharmacy bill",
    "DISCHARGE_SUMMARY": "a hospital discharge summary",
    "DENTAL_REPORT": "a dental treatment report",
    "DIAGNOSTIC_REPORT": "a diagnostic / imaging report",
}


def _label(doc_type: str) -> str:
    return _DOC_LABELS.get(doc_type, doc_type.replace("_", " ").title())


class DocumentVerificationAgent:
    """
    Input:  ClaimInput
    Output: DocumentVerificationResult

    Raises: Never — all errors are captured in result.issues.
    """

    def __init__(self):
        self.policy = get_policy()

    def run(self, claim: ClaimInput) -> DocumentVerificationResult:
        t0 = time.time()
        issues: list[str] = []
        missing: list[DocumentType] = []
        uploaded_instead: list[DocumentType] = []
        unreadable_ids: list[str] = []
        cross_patient: dict[str, str] = {}

        try:
            # ── 1. Unreadable documents ────────────────────────────────────
            for doc in claim.documents:
                if doc.quality and doc.quality.value == "UNREADABLE":
                    unreadable_ids.append(doc.file_id)
                    fname = doc.file_name or doc.file_id
                    issues.append(
                        f"The document '{fname}' (type: {_label(doc.actual_type.value if doc.actual_type else 'unknown')}) "
                        f"could not be read — the image is too blurry or low resolution. "
                        f"Please re-upload a clear, well-lit photo or scan of this document."
                    )

            # ── 2. Document type coverage ──────────────────────────────────
            required_types = set(self.policy.get_required_documents(claim.claim_category.value))
            uploaded_types = {
                doc.actual_type.value
                for doc in claim.documents
                if doc.actual_type is not None
            }

            for req in required_types:
                if req not in uploaded_types:
                    missing.append(DocumentType(req))

            # Build set of extra/wrong types uploaded
            wrong_types = uploaded_types - required_types - set(
                self.policy.get_optional_documents(claim.claim_category.value)
            )

            if missing:
                # Craft specific message
                for m in missing:
                    # Was a wrong type uploaded in place of this one?
                    wrong_matches = list(wrong_types)
                    if wrong_matches:
                        wrong_label = ", ".join(_label(w) for w in wrong_matches)
                        issues.append(
                            f"Your claim for {claim.claim_category.value} requires {_label(m.value)}, "
                            f"but we received {wrong_label} instead. "
                            f"Please upload {_label(m.value)} to proceed."
                        )
                        uploaded_instead.extend(DocumentType(w) for w in wrong_matches)
                    else:
                        issues.append(
                            f"Your claim for {claim.claim_category.value} requires {_label(m.value)}, "
                            f"which is missing from your submission. "
                            f"Please upload {_label(m.value)} to proceed."
                        )

            # ── 3. Cross-patient detection ─────────────────────────────────
            patient_names: dict[str, str] = {}  # file_id → patient name
            for doc in claim.documents:
                name = doc.patient_name_on_doc
                if name:
                    patient_names[doc.file_id] = name.strip().lower()
                elif doc.content and doc.content.get("patient_name"):
                    patient_names[doc.file_id] = doc.content["patient_name"].strip().lower()

            if len(set(patient_names.values())) > 1:
                # Multiple distinct patient names found
                cross_patient = {fid: n for fid, n in patient_names.items()}
                names_list = ", ".join(
                    f"'{v.title()}' (on {k})" for k, v in patient_names.items()
                )
                issues.append(
                    f"The documents appear to belong to different patients: {names_list}. "
                    f"All documents in a single claim must be for the same patient. "
                    f"Please verify and re-upload the correct documents."
                )

            # ── 4. Evaluate overall result ─────────────────────────────────
            passed = len(issues) == 0

        except Exception as exc:  # noqa: BLE001
            return DocumentVerificationResult(
                agent_name="DocumentVerificationAgent",
                status=AgentStatus.FAILED,
                error=str(exc),
                passed=False,
                issues=[f"Document verification failed due to an internal error: {exc}"],
                duration_ms=(time.time() - t0) * 1000,
            )

        return DocumentVerificationResult(
            agent_name="DocumentVerificationAgent",
            status=AgentStatus.SUCCESS,
            passed=passed,
            issues=issues,
            missing_document_types=missing,
            uploaded_instead=uploaded_instead,
            cross_patient_names=cross_patient if cross_patient else None,
            unreadable_file_ids=unreadable_ids,
            duration_ms=(time.time() - t0) * 1000,
        )
