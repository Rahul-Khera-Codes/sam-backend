from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = "v1"
_QUERY_WHITESPACE_PATTERN = re.compile(r"\s+")
_redis_client: redis.Redis | None = None


def normalize_cache_query(question: str) -> str:
    return _QUERY_WHITESPACE_PATTERN.sub(" ", question.strip().lower())


def _get_redis_client() -> redis.Redis | None:
    global _redis_client
    if not settings.hr_onboarding_cache_enabled or not settings.valkey_url:
        return None
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.valkey_url,
            encoding="utf-8",
            decode_responses=True,
            client_name=settings.hr_onboarding_cache_client_name,
        )
    return _redis_client


async def get_hr_policy_document_fingerprint(business_id: str) -> str | None:
    try:
        result = await asyncio.to_thread(
            lambda: supabase_admin.table("business_documents")
            .select("id,name,category,status,embedding_status,embedded_at,created_at")
            .eq("business_id", business_id)
            .eq("document_scope", "hr_onboarding")
            .eq("status", "published")
            .eq("embedding_status", "ready")
            .order("id")
            .execute()
        )
    except Exception as exc:
        logger.warning("Unable to build HR onboarding cache fingerprint: %s", exc)
        return None

    documents = getattr(result, "data", None) or []
    fingerprint_payload = json.dumps(documents, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()


def build_hr_onboarding_cache_key(
    *,
    business_id: str,
    question: str,
    document_id: str | None,
    category: str | None,
    document_fingerprint: str,
    channel: str,
) -> str:
    key_payload = {
        "business_id": business_id,
        "category": category or "",
        "channel": channel,
        "document_fingerprint": document_fingerprint,
        "document_id": document_id or "",
        "question": normalize_cache_query(question),
        "schema": CACHE_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"hr:onboarding:{channel}:{business_id}:{digest}"


def build_hr_onboarding_semantic_cache_key(
    *,
    business_id: str,
    channel: str,
) -> str:
    return f"hr:onboarding:semantic:{channel}:{business_id}:{CACHE_SCHEMA_VERSION}"


def build_hr_onboarding_validation_cache_key(text: str) -> str:
    normalized_text = normalize_cache_query(text)
    digest = hashlib.sha256(
        json.dumps(
            {
                "schema": CACHE_SCHEMA_VERSION,
                "text": normalized_text,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"hr:onboarding:validation:{CACHE_SCHEMA_VERSION}:{digest}"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot_product = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right, strict=True):
        dot_product += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    denominator = math.sqrt(left_norm) * math.sqrt(right_norm)
    if denominator <= 0:
        return 0.0
    return dot_product / denominator


def _semantic_cache_scope_matches(
    entry: dict[str, Any],
    *,
    document_fingerprint: str,
    document_id: str | None,
    category: str | None,
    channel: str,
) -> bool:
    return (
        entry.get("schema") == CACHE_SCHEMA_VERSION
        and entry.get("channel") == channel
        and entry.get("document_fingerprint") == document_fingerprint
        and (entry.get("document_id") or "") == (document_id or "")
        and (entry.get("category") or "") == (category or "")
    )


async def get_cached_hr_onboarding_response(cache_key: str) -> dict[str, Any] | None:
    client = _get_redis_client()
    if client is None:
        return None

    try:
        cached = await client.get(cache_key)
    except Exception as exc:
        logger.warning("Valkey HR onboarding cache read failed: %s", exc)
        return None

    if not cached:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        logger.warning("Valkey HR onboarding cache contained invalid JSON for key %s", cache_key)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


async def get_cached_hr_onboarding_validation_pass(text: str) -> bool:
    client = _get_redis_client()
    if client is None or not settings.hr_onboarding_validation_cache_enabled or not text.strip():
        return False
    cache_key = build_hr_onboarding_validation_cache_key(text)
    try:
        cached = await client.get(cache_key)
    except Exception as exc:
        logger.warning("Valkey HR onboarding validation cache read failed: %s", exc)
        return False
    if not cached:
        return False
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        logger.warning("Valkey HR onboarding validation cache contained invalid JSON for key %s", cache_key)
        return False
    return isinstance(payload, dict) and payload.get("schema") == CACHE_SCHEMA_VERSION and payload.get("status") == "passed"


async def set_cached_hr_onboarding_validation_pass(text: str) -> None:
    client = _get_redis_client()
    if client is None or not settings.hr_onboarding_validation_cache_enabled or not text.strip():
        return
    cache_key = build_hr_onboarding_validation_cache_key(text)
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "status": "passed",
    }
    try:
        await client.setex(
            cache_key,
            settings.hr_onboarding_validation_cache_ttl_seconds,
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("Valkey HR onboarding validation cache write failed: %s", exc)


async def get_semantically_cached_hr_onboarding_response(
    *,
    business_id: str,
    question_embedding: list[float],
    document_fingerprint: str | None,
    document_id: str | None,
    category: str | None,
    channel: str,
) -> dict[str, Any] | None:
    client = _get_redis_client()
    if (
        client is None
        or not settings.hr_onboarding_semantic_cache_enabled
        or not document_fingerprint
        or not question_embedding
    ):
        return None

    semantic_key = build_hr_onboarding_semantic_cache_key(
        business_id=business_id,
        channel=channel,
    )
    try:
        cached = await client.get(semantic_key)
    except Exception as exc:
        logger.warning("Valkey HR onboarding semantic cache read failed: %s", exc)
        return None
    if not cached:
        return None

    try:
        entries = json.loads(cached)
    except json.JSONDecodeError:
        logger.warning("Valkey HR onboarding semantic cache contained invalid JSON for key %s", semantic_key)
        return None
    if not isinstance(entries, list):
        return None

    best_entry: dict[str, Any] | None = None
    best_similarity = 0.0
    for entry in entries:
        if not isinstance(entry, dict) or not _semantic_cache_scope_matches(
            entry,
            document_fingerprint=document_fingerprint,
            document_id=document_id,
            category=category,
            channel=channel,
        ):
            continue
        entry_embedding = entry.get("question_embedding")
        if not isinstance(entry_embedding, list):
            continue
        try:
            entry_embedding_values = [float(value) for value in entry_embedding]
        except (TypeError, ValueError):
            continue
        similarity = _cosine_similarity(
            question_embedding,
            entry_embedding_values,
        )
        if similarity > best_similarity:
            best_similarity = similarity
            best_entry = entry

    if best_entry is None or best_similarity < settings.hr_onboarding_semantic_cache_similarity_threshold:
        return None

    answer = str(best_entry.get("answer") or "").strip()
    if not answer:
        return None
    return {
        "answer": answer,
        "sources": best_entry.get("sources") or [],
        "schema": CACHE_SCHEMA_VERSION,
        "semantic_cache_hit": True,
        "semantic_similarity": best_similarity,
        "cached_question": best_entry.get("question") or "",
    }


async def set_cached_hr_onboarding_response(
    cache_key: str,
    *,
    answer: str,
    sources: list[dict[str, Any]],
) -> None:
    client = _get_redis_client()
    if client is None or not answer.strip():
        return

    payload = {
        "answer": answer,
        "sources": sources,
        "schema": CACHE_SCHEMA_VERSION,
    }
    try:
        await client.setex(
            cache_key,
            settings.hr_onboarding_cache_ttl_seconds,
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("Valkey HR onboarding cache write failed: %s", exc)


async def set_semantically_cached_hr_onboarding_response(
    *,
    business_id: str,
    question: str,
    question_embedding: list[float],
    document_fingerprint: str | None,
    document_id: str | None,
    category: str | None,
    channel: str,
    answer: str,
    sources: list[dict[str, Any]],
) -> None:
    client = _get_redis_client()
    if (
        client is None
        or not settings.hr_onboarding_semantic_cache_enabled
        or not document_fingerprint
        or not question.strip()
        or not question_embedding
        or not answer.strip()
    ):
        return

    semantic_key = build_hr_onboarding_semantic_cache_key(
        business_id=business_id,
        channel=channel,
    )
    try:
        cached = await client.get(semantic_key)
        entries = json.loads(cached) if cached else []
    except Exception as exc:
        logger.warning("Valkey HR onboarding semantic cache read-before-write failed: %s", exc)
        entries = []
    if not isinstance(entries, list):
        entries = []

    normalized_question = normalize_cache_query(question)
    retained_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and not (
            _semantic_cache_scope_matches(
                entry,
                document_fingerprint=document_fingerprint,
                document_id=document_id,
                category=category,
                channel=channel,
            )
            and entry.get("normalized_question") == normalized_question
        )
    ]
    retained_entries.insert(
        0,
        {
            "schema": CACHE_SCHEMA_VERSION,
            "channel": channel,
            "document_fingerprint": document_fingerprint,
            "document_id": document_id or "",
            "category": category or "",
            "question": question,
            "normalized_question": normalized_question,
            "question_embedding": question_embedding,
            "answer": answer,
            "sources": sources,
        },
    )
    max_entries = max(1, settings.hr_onboarding_semantic_cache_max_entries)
    retained_entries = retained_entries[:max_entries]

    try:
        await client.setex(
            semantic_key,
            settings.hr_onboarding_cache_ttl_seconds,
            json.dumps(retained_entries, ensure_ascii=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("Valkey HR onboarding semantic cache write failed: %s", exc)
