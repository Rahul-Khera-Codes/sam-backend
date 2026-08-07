from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

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
