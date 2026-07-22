from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.supabase import supabase_admin


POLICY_VERSION = "2026-07-22"
COMPLIANCE_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class ComplianceResult:
    allowed: bool
    categories: list[str]
    reason: str = ""


class InterviewComplianceError(ValueError):
    def __init__(self, message: str, *, categories: list[str] | None = None):
        super().__init__(message)
        self.categories = categories or []


class InterviewComplianceUnavailable(RuntimeError):
    pass


_PROHIBITED_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "age": (
        re.compile(r"\bhow old\b", re.I),
        re.compile(r"\b(date|year) of birth\b", re.I),
        re.compile(r"\bwhat year did you graduate\b", re.I),
    ),
    "race_ethnicity": (
        re.compile(r"\b(race|ethnicity|ethnic background)\b", re.I),
    ),
    "religion": (
        re.compile(r"\b(religion|religious beliefs?|place of worship)\b", re.I),
    ),
    "disability": (
        re.compile(r"\b(disability|disabled|medical history|medical condition)\b", re.I),
    ),
    "pregnancy_family": (
        re.compile(r"\b(pregnant|pregnancy|family plans?|plan to have children|childcare)\b", re.I),
    ),
    "marital_status": (
        re.compile(r"\b(married|marital status|spouse|relationship status)\b", re.I),
    ),
    "sexual_orientation": (
        re.compile(r"\b(sexual orientation|gay|lesbian|bisexual|transgender)\b", re.I),
    ),
    "citizenship_national_origin": (
        re.compile(r"\b(citizen|citizenship|national origin|where were you born|country are you from)\b", re.I),
    ),
    "union_membership": (
        re.compile(r"\b(union member|union membership|labor union|trade union)\b", re.I),
    ),
    "salary_history": (
        re.compile(r"\b(previous|current|last|prior)\s+(salary|pay|compensation)\b", re.I),
        re.compile(r"\bhow much (did|do) you (make|earn)\b", re.I),
        re.compile(r"\bsalary history\b", re.I),
    ),
}

_CATEGORY_REASONS = {
    "age": "Age and birth-date information are protected characteristics and are not job-performance evidence.",
    "race_ethnicity": "Race and ethnicity are protected characteristics and cannot be used in hiring evaluation.",
    "religion": "Religious beliefs and practices are protected and are unrelated to role capability.",
    "disability": "Disability and medical-history questions are prohibited; ask only about performing essential job duties.",
    "pregnancy_family": "Pregnancy, childcare, and family-planning information cannot be considered in hiring.",
    "marital_status": "Marital and relationship status are protected personal information.",
    "sexual_orientation": "Sexual orientation and gender identity are protected characteristics.",
    "citizenship_national_origin": "Citizenship and national origin are protected; only neutral legal work-authorization questions are allowed.",
    "union_membership": "Union membership and organizing activity cannot be used in hiring decisions.",
    "salary_history": "Prior compensation history is restricted in many jurisdictions and is not allowed in AI Employees interviews.",
}


def deterministic_check(text: str) -> ComplianceResult:
    categories = [
        category
        for category, patterns in _PROHIBITED_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    ]
    return ComplianceResult(
        allowed=not categories,
        categories=categories,
        reason=" ".join(_CATEGORY_REASONS[category] for category in categories),
    )


async def classify_questions(texts: list[str]) -> list[ComplianceResult]:
    if not texts:
        return []

    deterministic_results = [deterministic_check(text) for text in texts]
    if any(not result.allowed for result in deterministic_results):
        return deterministic_results

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=15.0,
        max_retries=1,
    )
    prompt = {
        "policy_version": POLICY_VERSION,
        "prohibited_categories": [
            "age",
            "race or ethnicity",
            "religion",
            "disability or medical history",
            "pregnancy, children, childcare, or family plans",
            "marital or relationship status",
            "sexual orientation or gender identity",
            "citizenship or national origin",
            "union membership or organizing",
            "salary or compensation history",
        ],
        "allowed_exception": (
            "A neutral question asking whether the candidate is legally authorized "
            "to work in the job's country is allowed."
        ),
        "questions": [{"index": index, "text": text} for index, text in enumerate(texts)],
        "response_schema": {
            "results": [
                {
                    "index": 0,
                    "allowed": True,
                    "categories": [],
                    "reason": "",
                }
            ]
        },
    }
    try:
        response = await client.chat.completions.create(
            model=COMPLIANCE_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a fail-closed employment interview compliance classifier. "
                        "Classify meaning, euphemisms, and indirect proxy questions. Return JSON only."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        rows = payload.get("results")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ValueError("Classifier returned an incomplete result.")
        indexed = {int(row["index"]): row for row in rows}
        return [
            ComplianceResult(
                allowed=bool(indexed[index].get("allowed")),
                categories=[str(item) for item in indexed[index].get("categories") or []],
                reason=str(indexed[index].get("reason") or ""),
            )
            for index in range(len(texts))
        ]
    except Exception as exc:
        raise InterviewComplianceUnavailable(
            "Interview safety validation is temporarily unavailable. No changes were saved."
        ) from exc


async def enforce_questions(texts: list[str]) -> list[ComplianceResult]:
    results = await classify_questions(texts)
    blocked = [
        result
        for result in results
        if not result.allowed
    ]
    if blocked:
        categories = sorted({category for result in blocked for category in result.categories})
        reason = next((result.reason for result in blocked if result.reason), "")
        raise InterviewComplianceError(
            reason or "One or more questions use a prohibited hiring topic.",
            categories=categories,
        )
    return results


def record_compliance_checks(
    *,
    business_id: str,
    bank_id: str | None,
    question_rows: list[dict[str, Any]],
    results: list[ComplianceResult],
    source: str,
) -> None:
    if not question_rows:
        return
    rows = []
    for index, question in enumerate(question_rows):
        text = str(question.get("question_text") or question.get("text") or "")
        result = results[index] if index < len(results) else ComplianceResult(False, [], "Missing result")
        rows.append(
            {
                "business_id": business_id,
                "bank_id": bank_id,
                "question_id": question.get("id"),
                "input_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "policy_version": POLICY_VERSION,
                "outcome": "approved" if result.allowed else "blocked",
                "detected_categories": result.categories,
                "source": source,
            }
        )
    supabase_admin.table("hr_interview_compliance_checks").insert(rows).execute()
