"""
DocumentExtractionAgent — extracts structured fields from uploaded documents.

Two modes:
  TEST MODE  — document has a `content` dict already (pre-extracted in test fixtures).
               The agent normalises and returns it directly with full confidence.
  PROD MODE  — document has raw file bytes (image or PDF).
               The agent calls the Gemini vision API with a structured extraction prompt.

LLM: Google Gemini 2.0 Flash  (configured via GEMINI_API_KEY env var)
Every extracted document gets an `extraction_confidence` (0–1) and a list of
`low_confidence_fields` so downstream agents can adjust their own confidence.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Dict, List, Optional

from models.schemas import (
    AgentStatus,
    ClaimInput,
    DocumentExtractionResult,
    DocumentInput,
    DocumentQuality,
    DocumentType,
    ExtractedDocument,
)

# ── Gemini configuration ──────────────────────────────────────────────────────
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not _GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")
_MODEL = "gemini-2.5-flash"         


_EXTRACTION_PROMPT = """You are a medical document extraction specialist for an Indian health insurance company.
Extract structured information from the provided medical document and return ONLY valid JSON.

Return exactly this structure:
{
  "document_type": "PRESCRIPTION|HOSPITAL_BILL|LAB_REPORT|PHARMACY_BILL|DISCHARGE_SUMMARY|DENTAL_REPORT|DIAGNOSTIC_REPORT|UNKNOWN",
  "patient_name": "string or null",
  "doctor_name": "string or null",
  "doctor_registration": "string or null",
  "hospital_name": "string or null",
  "treatment_date": "YYYY-MM-DD or null",
  "diagnosis": "string or null",
  "medicines": ["list of medicine names"],
  "tests_ordered": ["list of test names"],
  "line_items": [{"description": "...", "amount": 0.0}],
  "total_amount": 0.0 or null,
  "lab_results": [{"test": "...", "result": "...", "unit": "...", "normal_range": "..."}],
  "extraction_confidence": 0.0-1.0,
  "low_confidence_fields": ["list of field names you were unsure about"],
  "flags": ["DOCUMENT_ALTERATION", "RUBBER_STAMP_OVER_TEXT", "HANDWRITTEN", "PARTIAL_DOCUMENT", etc.]
}

Notes:
- Use medical shorthand mappings: HTN→Hypertension, T2DM→Type 2 Diabetes, URI→Upper Respiratory Infection
- If a field is unreadable due to image quality, include it in low_confidence_fields
- If amounts are crossed out/rewritten, add DOCUMENT_ALTERATION to flags
- extraction_confidence reflects your overall confidence in the extraction (blurry=0.3, partial=0.5, clear=0.95)
- Return ONLY the JSON object — no explanation, no markdown fences"""


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text)


def _extract_via_llm(doc: DocumentInput) -> Dict[str, Any]:
    """Call Gemini vision API to extract fields from a raw file."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_GEMINI_API_KEY)

        mime = doc.mime_type or "image/jpeg"

        # Build the multimodal content: inline image bytes + extraction prompt
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                types.Part.from_bytes(data=doc.file_bytes, mime_type=mime),
                _EXTRACTION_PROMPT,
            ],
        )

        raw_text = response.text
        return _parse_llm_json(raw_text)

    except Exception as exc:
        # Return a degraded placeholder so the pipeline can continue
        return {
            "document_type": doc.actual_type.value if doc.actual_type else "UNKNOWN",
            "extraction_confidence": 0.2,
            "low_confidence_fields": ["all"],
            "flags": [f"EXTRACTION_FAILED: {str(exc)[:100]}"],
        }


def _normalise(raw: Dict[str, Any], doc: DocumentInput) -> ExtractedDocument:
    """Map raw dict (from content or LLM) to ExtractedDocument."""
    line_items = raw.get("line_items", [])
    # Normalise line items to float amounts
    normalised_items = []
    for item in line_items:
        try:
            normalised_items.append({
                "description": str(item.get("description", "")),
                "amount": float(item.get("amount", 0)),
            })
        except (TypeError, ValueError):
            normalised_items.append({"description": str(item), "amount": 0.0})

    # Resolve document type
    raw_type = raw.get("document_type") or (doc.actual_type.value if doc.actual_type else "UNKNOWN")
    try:
        doc_type = DocumentType(raw_type)
    except ValueError:
        doc_type = DocumentType.UNKNOWN

    # Resolve quality
    quality = doc.quality or DocumentQuality.GOOD

    # Compute total_amount from line items if not given
    total = raw.get("total_amount") or raw.get("total")
    if total is None and normalised_items:
        total = sum(i["amount"] for i in normalised_items)

    # Merge patient name from different possible keys
    patient_name = (
        raw.get("patient_name")
        or raw.get("patient")
        or doc.patient_name_on_doc
    )

    confidence = float(raw.get("extraction_confidence", 1.0))
    if quality == DocumentQuality.UNREADABLE:
        confidence = min(confidence, 0.1)
    elif quality == DocumentQuality.DEGRADED:
        confidence = min(confidence, 0.6)

    return ExtractedDocument(
        file_id=doc.file_id,
        document_type=doc_type,
        quality=quality,
        patient_name=patient_name,
        doctor_name=raw.get("doctor_name"),
        doctor_registration=raw.get("doctor_registration"),
        hospital_name=raw.get("hospital_name"),
        treatment_date=raw.get("treatment_date") or raw.get("date"),
        diagnosis=raw.get("diagnosis"),
        medicines=raw.get("medicines", []),
        tests_ordered=raw.get("tests_ordered", []) or raw.get("investigations", []),
        line_items=normalised_items,
        total_amount=float(total) if total is not None else None,
        lab_results=raw.get("lab_results", []),
        extraction_confidence=confidence,
        low_confidence_fields=raw.get("low_confidence_fields", []),
        flags=raw.get("flags", []),
        raw_content=raw,
    )


class DocumentExtractionAgent:
    """
    Input:  ClaimInput (list of DocumentInput)
    Output: DocumentExtractionResult

    Raises: Never — partial failures are captured per-document.
    """

    def run(self, claim: ClaimInput) -> DocumentExtractionResult:
        t0 = time.time()
        extracted: List[ExtractedDocument] = []
        failed_ids: List[str] = []

        for doc in claim.documents:
            try:
                if doc.content:
                    # Test mode — content already available
                    raw = dict(doc.content)
                    raw.setdefault("document_type", doc.actual_type.value if doc.actual_type else "UNKNOWN")
                    raw.setdefault("extraction_confidence", 1.0)
                elif doc.file_bytes:
                    # Prod mode — call LLM
                    raw = _extract_via_llm(doc)
                else:
                    # No content and no bytes — degraded
                    raw = {
                        "document_type": doc.actual_type.value if doc.actual_type else "UNKNOWN",
                        "extraction_confidence": 0.3,
                        "flags": ["NO_CONTENT_AVAILABLE"],
                        "low_confidence_fields": ["all"],
                    }
                extracted.append(_normalise(raw, doc))
            except Exception as exc:  # noqa: BLE001
                failed_ids.append(doc.file_id)
                # Still add a placeholder so pipeline can continue
                extracted.append(
                    ExtractedDocument(
                        file_id=doc.file_id,
                        document_type=doc.actual_type or DocumentType.UNKNOWN,
                        quality=doc.quality or DocumentQuality.GOOD,
                        extraction_confidence=0.0,
                        flags=[f"EXTRACTION_ERROR: {str(exc)[:80]}"],
                        low_confidence_fields=["all"],
                    )
                )

        if not extracted:
            return DocumentExtractionResult(
                agent_name="DocumentExtractionAgent",
                status=AgentStatus.FAILED,
                error="No documents could be extracted",
                duration_ms=(time.time() - t0) * 1000,
            )

        overall_confidence = sum(d.extraction_confidence for d in extracted) / len(extracted)
        status = AgentStatus.PARTIAL if failed_ids else AgentStatus.SUCCESS

        return DocumentExtractionResult(
            agent_name="DocumentExtractionAgent",
            status=status,
            error=f"Failed to extract: {failed_ids}" if failed_ids else None,
            documents=extracted,
            overall_extraction_confidence=overall_confidence,
            duration_ms=(time.time() - t0) * 1000,
        )