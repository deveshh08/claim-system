"""
PolicyLoader — reads policy_terms.json and exposes typed accessors.
All policy logic is data-driven from the JSON file; nothing is hardcoded here.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional


# ── locate the file relative to this module ──────────────────────────────────
_POLICY_FILE = os.path.join(os.path.dirname(__file__), "..", "policy_terms.json")


class PolicyLoader:
    def __init__(self, path: str = _POLICY_FILE):
        with open(path, "r") as f:
            self._raw: Dict[str, Any] = json.load(f)

    # ── raw access ──────────────────────────────────────────────────────────

    @property
    def policy_id(self) -> str:
        return self._raw["policy_id"]

    @property
    def sum_insured(self) -> float:
        return float(self._raw["coverage"]["sum_insured_per_employee"])

    @property
    def per_claim_limit(self) -> float:
        return float(self._raw["coverage"]["per_claim_limit"])

    @property
    def annual_opd_limit(self) -> float:
        return float(self._raw["coverage"]["annual_opd_limit"])

    @property
    def network_hospitals(self) -> List[str]:
        return [h.lower() for h in self._raw["network_hospitals"]]

    # ── member roster ────────────────────────────────────────────────────────

    def get_member(self, member_id: str) -> Optional[Dict[str, Any]]:
        for m in self._raw["members"]:
            if m["member_id"] == member_id:
                return m
        return None

    def is_member_covered(self, member_id: str) -> bool:
        return self.get_member(member_id) is not None

    # ── network hospital ─────────────────────────────────────────────────────

    def is_network_hospital(self, hospital_name: Optional[str]) -> bool:
        if not hospital_name:
            return False
        name_lower = hospital_name.lower()
        return any(nh in name_lower or name_lower in nh for nh in self.network_hospitals)

    # ── opd category rules ───────────────────────────────────────────────────

    def get_category_rules(self, category: str) -> Optional[Dict[str, Any]]:
        """Return the opd_categories entry for a given claim category."""
        cat_map = {
            "CONSULTATION": "consultation",
            "DIAGNOSTIC": "diagnostic",
            "PHARMACY": "pharmacy",
            "DENTAL": "dental",
            "VISION": "vision",
            "ALTERNATIVE_MEDICINE": "alternative_medicine",
        }
        key = cat_map.get(category)
        if not key:
            return None
        return self._raw["opd_categories"].get(key)

    # ── document requirements ────────────────────────────────────────────────

    def get_required_documents(self, category: str) -> List[str]:
        req = self._raw["document_requirements"].get(category, {})
        return req.get("required", [])

    def get_optional_documents(self, category: str) -> List[str]:
        req = self._raw["document_requirements"].get(category, {})
        return req.get("optional", [])

    # ── waiting periods ───────────────────────────────────────────────────────

    @property
    def initial_waiting_days(self) -> int:
        return self._raw["waiting_periods"]["initial_waiting_period_days"]

    @property
    def pre_existing_waiting_days(self) -> int:
        return self._raw["waiting_periods"]["pre_existing_conditions_days"]

    def specific_waiting_days(self, condition_key: str) -> Optional[int]:
        return self._raw["waiting_periods"]["specific_conditions"].get(condition_key)

    def get_waiting_period_for_diagnosis(self, diagnosis: str) -> Optional[tuple[str, int]]:
        """
        Map a diagnosis string to a (condition_key, days) tuple.
        Returns None if no specific waiting period applies.
        """
        diagnosis_lower = diagnosis.lower()
        condition_keywords: Dict[str, List[str]] = {
            "diabetes": ["diabetes", "t2dm", "type 2 diabetes", "type2 diabetes", "dm2"],
            "hypertension": ["hypertension", "htn", "blood pressure"],
            "thyroid_disorders": ["thyroid", "hypothyroid", "hyperthyroid"],
            "joint_replacement": ["joint replacement", "knee replacement", "hip replacement"],
            "maternity": ["maternity", "pregnancy", "obstetric", "antenatal"],
            "mental_health": ["mental health", "depression", "anxiety", "psychiatric", "bipolar"],
            "obesity_treatment": ["obesity", "bariatric", "weight loss", "bmi"],
            "hernia": ["hernia repair", "inguinal hernia", "umbilical hernia", "abdominal hernia"],
            "cataract": ["cataract"],
        }
        for condition_key, keywords in condition_keywords.items():
            if any(kw in diagnosis_lower for kw in keywords):
                days = self.specific_waiting_days(condition_key)
                if days is not None:
                    return (condition_key, days)
        return None

    def member_join_date(self, member_id: str) -> Optional[date]:
        m = self.get_member(member_id)
        if not m:
            return None
        return date.fromisoformat(m["join_date"])

    def initial_waiting_end_date(self, member_id: str) -> Optional[date]:
        join = self.member_join_date(member_id)
        if not join:
            return None
        return join + timedelta(days=self.initial_waiting_days)

    # ── exclusions ────────────────────────────────────────────────────────────

    def is_excluded_condition(self, diagnosis: str, treatment: str = "") -> Optional[str]:
        """Return the exclusion clause if matched, else None."""
        text = f"{diagnosis} {treatment}".lower()
        exclusion_keywords: Dict[str, List[str]] = {
            "Obesity and weight loss programs": ["obesity", "weight loss", "bariatric", "bmi"],
            "Bariatric surgery": ["bariatric"],
            "Cosmetic or aesthetic procedures": ["cosmetic", "aesthetic", "whitening", "bleaching", "veneers"],
            "Self-inflicted injuries": ["self-inflicted", "self inflicted"],
            "Substance abuse treatment": ["substance abuse", "alcohol", "drug abuse"],
            "Experimental treatments": ["experimental"],
            "Infertility and assisted reproduction": ["infertility", "ivf", "iui", "reproduction"],
            "Vaccination (non-medically necessary)": ["vaccination", "vaccine"],
            "Health supplements and tonics": ["supplement", "tonic", "vitamin"],
        }
        for exclusion, keywords in exclusion_keywords.items():
            if any(kw in text for kw in keywords):
                return exclusion
        return None

    def is_excluded_dental_procedure(self, procedure: str) -> bool:
        procedure_lower = procedure.lower()
        excluded = [p.lower() for p in self._raw["exclusions"].get("dental_exclusions", [])]
        # Also check covered_procedures list
        dental_excluded = [
            p.lower() for p in self._raw["opd_categories"]["dental"].get("excluded_procedures", [])
        ]
        all_excluded = set(excluded + dental_excluded)
        return any(ex in procedure_lower or procedure_lower in ex for ex in all_excluded)

    def is_excluded_vision_item(self, item: str) -> bool:
        item_lower = item.lower()
        excluded = [i.lower() for i in self._raw["exclusions"].get("vision_exclusions", [])]
        return any(ex in item_lower for ex in excluded)

    # ── pre-authorization ─────────────────────────────────────────────────────

    def requires_pre_auth(self, category: str, amount: float, documents: List[Dict[str, Any]] = None) -> bool:
        """Return True if this claim requires pre-authorization."""
        rules = self.get_category_rules(category)
        if rules and rules.get("requires_pre_auth"):
            return True
        # High-value MRI/CT/PET
        if category == "DIAGNOSTIC":
            high_value_tests = self._raw["opd_categories"]["diagnostic"].get("high_value_tests_requiring_pre_auth", [])
            pre_auth_threshold = float(self._raw["opd_categories"]["diagnostic"].get("pre_auth_threshold", 10000))
            if amount > pre_auth_threshold and documents:
                for doc in documents:
                    if doc.get("content"):
                        tests = doc["content"].get("tests_ordered", [])
                        test_name = doc["content"].get("test_name", "")
                        all_tests = tests + [test_name]
                        for t in all_tests:
                            for hvt in high_value_tests:
                                if hvt.lower() in t.lower():
                                    return True
        return False

    # ── fraud thresholds ──────────────────────────────────────────────────────

    @property
    def fraud_thresholds(self) -> Dict[str, Any]:
        return self._raw["fraud_thresholds"]

    # ── submission rules ──────────────────────────────────────────────────────

    @property
    def submission_deadline_days(self) -> int:
        return self._raw["submission_rules"]["deadline_days_from_treatment"]

    @property
    def minimum_claim_amount(self) -> float:
        return float(self._raw["submission_rules"]["minimum_claim_amount"])


@lru_cache(maxsize=1)
def get_policy() -> PolicyLoader:
    """Singleton accessor — re-read from disk once per process."""
    return PolicyLoader()
