from __future__ import annotations

from typing import Any

HR_ONBOARDING_TRACE_METADATA = {
    "component": "hr_employee_chatbot",
    "feature": "hr_onboarding",
}
HR_ONBOARDING_TRACE_TAGS = ["hr-employee-chatbot", "hr-onboarding"]


def compact_text(value: str | None, *, limit: int = 280) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def summarize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    allowed_keys = {
        "category",
        "document_scope",
        "status",
        "storage_bucket",
        "document_created_at",
        "embedded_at",
    }
    return {
        key: value
        for key, value in metadata.items()
        if key in allowed_keys and value is not None
    }


def summarize_chunks(chunks: list[str], *, sample_limit: int = 3) -> dict[str, Any]:
    sizes = [len(chunk) for chunk in chunks]
    return {
        "chunk_count": len(chunks),
        "total_chars": sum(sizes),
        "min_chunk_chars": min(sizes) if sizes else 0,
        "max_chunk_chars": max(sizes) if sizes else 0,
        "sample_chunks": [
            {
                "index": index,
                "chars": len(chunk),
                "preview": compact_text(chunk),
            }
            for index, chunk in enumerate(chunks[:sample_limit])
        ],
    }


def summarize_matches(matches: list[dict[str, Any]], *, sample_limit: int = 5) -> dict[str, Any]:
    return {
        "match_count": len(matches),
        "matches": [
            {
                "chunk_id": str(match.get("chunk_id") or ""),
                "document_id": str(match.get("document_id") or ""),
                "document_name": str(match.get("document_name") or "HR policy document"),
                "category": match.get("category") or None,
                "similarity": match.get("similarity"),
                "reranker_score": match.get("reranker_score"),
                "content_preview": compact_text(str(match.get("content") or "")),
            }
            for match in matches[:sample_limit]
        ],
    }


def summarize_source_payload(source_payload: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "source_count": len(source_payload),
        "sources": [
            {
                "document_id": item.get("document_id") or "",
                "document_name": item.get("document_name") or "HR policy document",
                "category": item.get("category") or "",
                "excerpt_chars": len(item.get("content") or ""),
                "excerpt_preview": compact_text(item.get("content") or ""),
            }
            for item in source_payload[:5]
        ],
    }
