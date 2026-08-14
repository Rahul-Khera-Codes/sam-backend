from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langsmith import traceable

from app.services.hr_onboarding_langsmith_service import (
    HR_ONBOARDING_TRACE_METADATA,
    HR_ONBOARDING_TRACE_TAGS,
    compact_text,
    summarize_matches,
)

logger = logging.getLogger(__name__)

RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_MAX_CANDIDATES = 12
RERANKER_TEXT_LIMIT_CHARS = 1_200


@lru_cache(maxsize=1)
def _get_cross_encoder() -> Any:
    from sentence_transformers import CrossEncoder

    logger.info("Loading HR onboarding reranker model: %s", RERANKER_MODEL_NAME)
    return CrossEncoder(RERANKER_MODEL_NAME)


def _reranker_text(match: dict[str, Any]) -> str:
    document_name = str(match.get("document_name") or "")
    category = str(match.get("category") or "")
    content = " ".join(str(match.get("content") or "").split())
    text = f"Document: {document_name}\nCategory: {category}\nContent: {content}"
    return text[:RERANKER_TEXT_LIMIT_CHARS]


def _process_reranker_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    query = str(inputs.get("query") or "")
    matches = inputs.get("matches") or []
    return {
        "query_chars": len(query),
        "query_preview": compact_text(query),
        "candidate_count": len(matches),
        "max_candidates": inputs.get("max_candidates"),
        "candidates": summarize_matches(matches),
        "reranker_model": RERANKER_MODEL_NAME,
    }


def _process_reranker_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **summarize_matches(outputs),
        "reranker_model": RERANKER_MODEL_NAME,
    }


@traceable(
    name="hr_onboarding.chat.rerank_policy_chunks",
    run_type="tool",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_reranker_inputs,
    process_outputs=_process_reranker_outputs,
)
def rerank_hr_policy_chunks(
    *,
    query: str,
    matches: list[dict[str, Any]],
    max_candidates: int = RERANKER_MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    if len(matches) <= 1 or not query.strip():
        return matches

    candidate_count = min(max(max_candidates, 1), len(matches))
    candidates = matches[:candidate_count]
    tail = matches[candidate_count:]
    model = _get_cross_encoder()
    scores = model.predict([(query, _reranker_text(match)) for match in candidates])

    scored_candidates = [
        (float(score), index, match)
        for index, (score, match) in enumerate(zip(scores, candidates))
    ]
    scored_candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)

    reranked = []
    for score, _index, match in scored_candidates:
        reranked.append({**match, "reranker_score": score})
    return [*reranked, *tail]
